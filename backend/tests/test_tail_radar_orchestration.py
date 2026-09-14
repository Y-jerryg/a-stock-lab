from datetime import datetime, timedelta
from threading import Barrier
from types import SimpleNamespace
from typing import cast
from uuid import UUID

import pytest

from a_stock_lab.core.time import MARKET_TIME_ZONE
from a_stock_lab.features.tail_radar.application.contracts import TailRadarDataRepository
from a_stock_lab.features.tail_radar.application.models import (
    TailRadarCandidateData,
    TailRadarCandidatePage,
    TailRadarCandidatePayload,
)
from a_stock_lab.features.tail_radar.application.on_demand_research_service import (
    TailRadarOnDemandResearchService,
)
from a_stock_lab.features.tail_radar.application.orchestration_models import (
    TAIL_RADAR_WORKFLOW_VERSION,
    TailRadarCandidateStageStatus,
    TailRadarWorkflowCandidateState,
    TailRadarWorkflowClaim,
    TailRadarWorkflowData,
    TailRadarWorkflowDisposition,
    TailRadarWorkflowLifecycle,
)
from a_stock_lab.features.tail_radar.application.orchestration_service import (
    TailRadarApplicationService,
)
from a_stock_lab.features.tail_radar.application.research_models import TailRadarResearchStatus
from a_stock_lab.features.tail_radar.application.research_service import TailRadarResearchService
from a_stock_lab.features.tail_radar.domain.errors import (
    TailRadarOnDemandResearchRetryRequiredError,
)
from a_stock_lab.features.tail_radar.domain.screening import (
    TAIL_RADAR_SCREENING_RULE_VERSION,
    TailRadarDecisionOutcome,
    TailRadarDecisionReason,
    TailRadarScreeningConfiguration,
    TailRadarScreeningDecision,
    TailRadarSnapshotEvidence,
)
from a_stock_lab.shared.execution.models import RunStatus
from a_stock_lab.shared.market_data.models import MarketSnapshotRecord

INTENDED = datetime(2026, 8, 28, 14, 30, tzinfo=MARKET_TIME_ZONE)
ANALYSIS_AS_OF = datetime(2026, 8, 28, 14, 35, tzinfo=MARKET_TIME_ZONE)
NOW = datetime(2026, 8, 28, 14, 40, tzinfo=MARKET_TIME_ZONE)
WORKFLOW_ID = UUID("10000000-0000-4000-8000-000000000001")
SNAPSHOT_RUN_ID = UUID("20000000-0000-4000-8000-000000000001")
SNAPSHOT_ID = UUID("30000000-0000-4000-8000-000000000001")
SCREENING_RUN_ID = UUID("40000000-0000-4000-8000-000000000001")
CANDIDATE_ONE = UUID("50000000-0000-4000-8000-000000000001")
CANDIDATE_TWO = UUID("50000000-0000-4000-8000-000000000002")


def candidate(candidate_id: UUID, symbol: str) -> TailRadarCandidateData:
    fetched_at = INTENDED + timedelta(seconds=2)
    record = MarketSnapshotRecord(
        symbol=symbol,
        name=f"Fixture {symbol}",
        price=10.25,
        pct_change=2.5,
        amount=10_000_000,
        turnover_rate=1.2,
        provider="fixture",
        fetched_at=fetched_at,
    )
    evidence = TailRadarSnapshotEvidence(
        snapshot_id=SNAPSHOT_ID,
        snapshot_run_id=SNAPSHOT_RUN_ID,
        trade_date=INTENDED.date(),
        intended_snapshot_time=INTENDED,
        actual_fetch_started_at=INTENDED + timedelta(seconds=1),
        actual_fetch_finished_at=fetched_at,
        provider="fixture",
        checksum_sha256="a" * 64,
        snapshot_schema_version=2,
    )
    return TailRadarCandidateData(
        candidate_id=candidate_id,
        run_id=SCREENING_RUN_ID,
        snapshot_id=SNAPSHOT_ID,
        symbol=symbol,
        trade_date=INTENDED.date(),
        as_of=fetched_at,
        payload=TailRadarCandidatePayload(
            screening_rule_version=TAIL_RADAR_SCREENING_RULE_VERSION,
            rule_configuration=TailRadarScreeningConfiguration(),
            snapshot_evidence=evidence,
            snapshot_record=record,
            decision=TailRadarScreeningDecision(
                outcome=TailRadarDecisionOutcome.INCLUDED,
                reason=TailRadarDecisionReason.PCT_CHANGE_IN_RANGE,
                observed_pct_change=2.5,
                observed_price=10.25,
            ),
        ),
        created_at=INTENDED + timedelta(minutes=1),
    )


class FakeWorkflowRepository:
    def __init__(self) -> None:
        self.workflow: TailRadarWorkflowData | None = None
        self.states: dict[UUID, TailRadarWorkflowCandidateState] = {}

    def claim_workflow(
        self,
        *,
        intended_snapshot_time: datetime,
        requested_analysis_as_of: datetime | None,
        workflow_version: str,
        started_at: datetime,
    ) -> TailRadarWorkflowClaim:
        if self.workflow is not None:
            return TailRadarWorkflowClaim(workflow=self.workflow, created=False)
        self.workflow = self._workflow(
            lifecycle=TailRadarWorkflowLifecycle.CLAIMED,
            execution_status=RunStatus.RUNNING,
            intended_snapshot_time=intended_snapshot_time,
            analysis_as_of=requested_analysis_as_of,
            workflow_version=workflow_version,
            actual_started_at=started_at,
        )
        return TailRadarWorkflowClaim(workflow=self.workflow, created=True)

    def get_workflow(self, workflow_run_id: UUID) -> TailRadarWorkflowData | None:
        return self.workflow if workflow_run_id == WORKFLOW_ID else None

    def set_workflow_lifecycle(
        self, *, workflow_run_id: UUID, lifecycle: TailRadarWorkflowLifecycle
    ) -> TailRadarWorkflowData:
        assert self.workflow is not None and workflow_run_id == WORKFLOW_ID
        self.workflow = self.workflow.model_copy(
            update={
                "lifecycle": lifecycle,
                "execution_status": RunStatus.RUNNING,
                "actual_finished_at": None,
                "error_stage": None,
                "error_code": None,
            }
        )
        return self.workflow

    def attach_workflow_snapshot(
        self, *, workflow_run_id: UUID, snapshot_run_id: UUID, snapshot_id: UUID
    ) -> TailRadarWorkflowData:
        assert self.workflow is not None and workflow_run_id == WORKFLOW_ID
        self.workflow = self.workflow.model_copy(
            update={"snapshot_run_id": snapshot_run_id, "snapshot_id": snapshot_id}
        )
        return self.workflow

    def attach_workflow_screening(
        self,
        *,
        workflow_run_id: UUID,
        screening_run_id: UUID,
        analysis_as_of: datetime,
        candidate_ids: tuple[UUID, ...],
    ) -> TailRadarWorkflowData:
        assert self.workflow is not None and workflow_run_id == WORKFLOW_ID
        for candidate_id in candidate_ids:
            self.states.setdefault(candidate_id, self._state(candidate_id))
        count = len(candidate_ids)
        self.workflow = self.workflow.model_copy(
            update={
                "screening_run_id": screening_run_id,
                "analysis_as_of": analysis_as_of,
                "candidate_count": count,
                "technical_pending_count": count,
                "research_pending_count": count,
            }
        )
        return self.workflow

    def list_workflow_candidate_states(
        self, workflow_run_id: UUID
    ) -> tuple[TailRadarWorkflowCandidateState, ...]:
        assert workflow_run_id == WORKFLOW_ID
        return tuple(self.states.values())

    def set_candidate_technical_stage(
        self,
        *,
        workflow_run_id: UUID,
        candidate_id: UUID,
        status: TailRadarCandidateStageStatus,
        analysis_id: UUID | None = None,
        error_code: str | None = None,
    ) -> TailRadarWorkflowCandidateState:
        state = self.states[candidate_id].model_copy(
            update={
                "technical_status": status,
                "intraday_analysis_id": analysis_id,
                "technical_error_code": error_code,
            }
        )
        self.states[candidate_id] = state
        self._refresh_counts()
        return state

    def set_candidate_research_stage(
        self,
        *,
        workflow_run_id: UUID,
        candidate_id: UUID,
        status: TailRadarCandidateStageStatus,
        research_id: UUID | None = None,
        error_code: str | None = None,
    ) -> TailRadarWorkflowCandidateState:
        state = self.states[candidate_id].model_copy(
            update={
                "research_status": status,
                "research_id": research_id,
                "research_error_code": error_code,
            }
        )
        self.states[candidate_id] = state
        self._refresh_counts()
        return state

    def complete_workflow(
        self, *, workflow_run_id: UUID, finished_at: datetime
    ) -> TailRadarWorkflowData:
        assert self.workflow is not None
        self._refresh_counts()
        partial = any(
            state.technical_status is not TailRadarCandidateStageStatus.SUCCEEDED
            for state in self.states.values()
        )
        self.workflow = self.workflow.model_copy(
            update={
                "lifecycle": (
                    TailRadarWorkflowLifecycle.PARTIAL_SUCCESS
                    if partial
                    else TailRadarWorkflowLifecycle.SUCCEEDED
                ),
                "execution_status": RunStatus.SUCCEEDED,
                "actual_finished_at": finished_at,
            }
        )
        return self.workflow

    def fail_workflow(
        self,
        *,
        workflow_run_id: UUID,
        finished_at: datetime,
        error_stage: str,
        error_code: str,
    ) -> TailRadarWorkflowData:
        assert self.workflow is not None
        self.workflow = self.workflow.model_copy(
            update={
                "lifecycle": TailRadarWorkflowLifecycle.FAILED,
                "execution_status": RunStatus.FAILED,
                "actual_finished_at": finished_at,
                "error_stage": error_stage,
                "error_code": error_code,
            }
        )
        return self.workflow

    def _refresh_counts(self) -> None:
        assert self.workflow is not None
        technical = [state.technical_status for state in self.states.values()]
        research = [state.research_status for state in self.states.values()]
        self.workflow = self.workflow.model_copy(
            update={
                "technical_succeeded_count": technical.count(
                    TailRadarCandidateStageStatus.SUCCEEDED
                ),
                "technical_failed_count": technical.count(TailRadarCandidateStageStatus.FAILED),
                "technical_pending_count": sum(
                    status
                    in {
                        TailRadarCandidateStageStatus.PENDING,
                        TailRadarCandidateStageStatus.RUNNING,
                    }
                    for status in technical
                ),
                "research_succeeded_count": research.count(TailRadarCandidateStageStatus.SUCCEEDED),
                "research_no_evidence_count": research.count(
                    TailRadarCandidateStageStatus.NO_EVIDENCE
                ),
                "research_failed_count": research.count(TailRadarCandidateStageStatus.FAILED),
                "research_pending_count": sum(
                    status
                    in {
                        TailRadarCandidateStageStatus.PENDING,
                        TailRadarCandidateStageStatus.RUNNING,
                    }
                    for status in research
                ),
            }
        )

    @staticmethod
    def _workflow(**updates: object) -> TailRadarWorkflowData:
        values: dict[str, object] = {
            "workflow_run_id": WORKFLOW_ID,
            "trade_date": INTENDED.date(),
            "intended_snapshot_time": INTENDED,
            "analysis_as_of": None,
            "workflow_version": TAIL_RADAR_WORKFLOW_VERSION,
            "lifecycle": TailRadarWorkflowLifecycle.CLAIMED,
            "execution_status": RunStatus.RUNNING,
            "snapshot_run_id": None,
            "snapshot_id": None,
            "screening_run_id": None,
            "candidate_count": None,
            "technical_succeeded_count": 0,
            "technical_failed_count": 0,
            "technical_pending_count": 0,
            "research_succeeded_count": 0,
            "research_no_evidence_count": 0,
            "research_failed_count": 0,
            "research_pending_count": 0,
            "error_stage": None,
            "error_code": None,
            "actual_started_at": NOW,
            "actual_finished_at": None,
            "created_at": NOW,
            "updated_at": NOW,
        }
        values.update(updates)
        return TailRadarWorkflowData.model_validate(values)

    @staticmethod
    def _state(candidate_id: UUID) -> TailRadarWorkflowCandidateState:
        return TailRadarWorkflowCandidateState(
            workflow_run_id=WORKFLOW_ID,
            candidate_id=candidate_id,
            technical_status=TailRadarCandidateStageStatus.PENDING,
            research_status=TailRadarCandidateStageStatus.PENDING,
            intraday_analysis_id=None,
            research_id=None,
            technical_error_code=None,
            research_error_code=None,
            created_at=NOW,
            updated_at=NOW,
        )


class FakeTailRadarRepository:
    def __init__(self, candidates: tuple[TailRadarCandidateData, ...]) -> None:
        self.candidates = candidates

    def list_candidates(self, *, run_id: UUID, offset: int, limit: int) -> TailRadarCandidatePage:
        assert run_id == SCREENING_RUN_ID
        return TailRadarCandidatePage(
            items=self.candidates[offset : offset + limit],
            total=len(self.candidates),
            offset=offset,
            limit=limit,
        )


class FakeSnapshotExecution:
    def __init__(self, *, fail: bool = False) -> None:
        self.fail = fail
        self.calls = 0

    def execute(self, *, intended_snapshot_time: datetime, force: bool) -> SimpleNamespace:
        self.calls += 1
        if self.fail:
            raise RuntimeError("snapshot unavailable")
        return SimpleNamespace(
            run=SimpleNamespace(run_id=SNAPSHOT_RUN_ID, status=RunStatus.SUCCEEDED),
            manifest=SimpleNamespace(snapshot_id=SNAPSHOT_ID),
        )


class FakeScreening:
    def __init__(self) -> None:
        self.calls = 0

    def execute(self, *, snapshot_id: UUID) -> SimpleNamespace:
        self.calls += 1
        assert snapshot_id == SNAPSHOT_ID
        return SimpleNamespace(
            run=SimpleNamespace(run_id=SCREENING_RUN_ID, status=RunStatus.SUCCEEDED)
        )


class FakeIntraday:
    def __init__(self) -> None:
        self.failures: set[UUID] = set()
        self.calls: list[UUID] = []

    def execute(self, *, candidate_id: UUID, analysis_as_of: datetime) -> SimpleNamespace:
        self.calls.append(candidate_id)
        if candidate_id in self.failures:
            raise RuntimeError("intraday unavailable")
        return SimpleNamespace(analysis=SimpleNamespace(analysis_id=_derived_id(candidate_id, 1)))


def build_service(
    *, snapshot_fail: bool = False, intraday_workers: int = 1
) -> tuple[
    TailRadarApplicationService,
    FakeWorkflowRepository,
    FakeSnapshotExecution,
    FakeScreening,
    FakeIntraday,
]:
    candidates = (
        candidate(CANDIDATE_ONE, "600000"),
        candidate(CANDIDATE_TWO, "000001"),
    )
    workflow = FakeWorkflowRepository()
    snapshot = FakeSnapshotExecution(fail=snapshot_fail)
    screening = FakeScreening()
    intraday = FakeIntraday()
    service = TailRadarApplicationService(
        snapshot_execution=snapshot,  # type: ignore[arg-type]
        screening=screening,  # type: ignore[arg-type]
        intraday=intraday,  # type: ignore[arg-type]
        tail_radar_repository=FakeTailRadarRepository(candidates),  # type: ignore[arg-type]
        workflow_repository=workflow,  # type: ignore[arg-type]
        intraday_workers=intraday_workers,
        clock=lambda: NOW,
    )
    return service, workflow, snapshot, screening, intraday


def test_complete_workflow_is_idempotent_without_running_paid_research() -> None:
    service, repository, snapshot, screening, intraday = build_service()
    result = service.execute(
        intended_snapshot_time=INTENDED,
        analysis_as_of=ANALYSIS_AS_OF,
    )
    replay = service.execute(
        intended_snapshot_time=INTENDED,
        analysis_as_of=ANALYSIS_AS_OF,
    )

    assert result.workflow.lifecycle is TailRadarWorkflowLifecycle.SUCCEEDED
    assert result.workflow.technical_succeeded_count == 2
    assert result.workflow.research_pending_count == 2
    assert replay.disposition is TailRadarWorkflowDisposition.IDEMPOTENT_REPLAY
    assert snapshot.calls == 1
    assert screening.calls == 1
    assert intraday.calls == [CANDIDATE_ONE, CANDIDATE_TWO]
    assert all(state.intraday_analysis_id is not None for state in repository.states.values())
    assert all(state.research_id is None for state in repository.states.values())


def test_partial_technical_failures_are_isolated_and_resume_safe() -> None:
    service, repository, _, _, intraday = build_service()
    intraday.failures.add(CANDIDATE_TWO)

    first = service.execute(
        intended_snapshot_time=INTENDED,
        analysis_as_of=ANALYSIS_AS_OF,
    )
    assert first.workflow.lifecycle is TailRadarWorkflowLifecycle.PARTIAL_SUCCESS
    assert first.workflow.technical_succeeded_count == 1
    assert first.workflow.technical_failed_count == 1
    assert first.workflow.research_pending_count == 2

    intraday.failures.clear()
    second = service.resume(workflow_run_id=WORKFLOW_ID)
    assert second.workflow.lifecycle is TailRadarWorkflowLifecycle.SUCCEEDED
    assert intraday.calls.count(CANDIDATE_ONE) == 1
    assert intraday.calls.count(CANDIDATE_TWO) == 2
    assert repository.states[CANDIDATE_ONE].research_id is None


def test_snapshot_provider_failure_is_fatal_without_starting_candidate_work() -> None:
    service, repository, _, screening, intraday = build_service(snapshot_fail=True)

    with pytest.raises(RuntimeError, match="snapshot unavailable"):
        service.execute(
            intended_snapshot_time=INTENDED,
            analysis_as_of=ANALYSIS_AS_OF,
        )

    assert repository.workflow is not None
    assert repository.workflow.lifecycle is TailRadarWorkflowLifecycle.FAILED
    assert repository.workflow.error_stage == "snapshot"
    assert screening.calls == 0
    assert intraday.calls == []


class FakeOnDemandRepository(FakeWorkflowRepository):
    def __init__(self) -> None:
        super().__init__()
        self.candidate = candidate(CANDIDATE_ONE, "600000")
        self.workflow = self._workflow(
            lifecycle=TailRadarWorkflowLifecycle.SUCCEEDED,
            execution_status=RunStatus.SUCCEEDED,
            analysis_as_of=ANALYSIS_AS_OF,
            snapshot_run_id=SNAPSHOT_RUN_ID,
            snapshot_id=SNAPSHOT_ID,
            screening_run_id=SCREENING_RUN_ID,
            candidate_count=1,
            technical_succeeded_count=1,
            research_pending_count=1,
            actual_started_at=INTENDED,
            actual_finished_at=NOW,
        )
        self.states[CANDIDATE_ONE] = self._state(CANDIDATE_ONE).model_copy(
            update={
                "technical_status": TailRadarCandidateStageStatus.SUCCEEDED,
                "intraday_analysis_id": _derived_id(CANDIDATE_ONE, 1),
            }
        )

    def get_candidate(self, candidate_id: UUID) -> TailRadarCandidateData | None:
        return self.candidate if candidate_id == CANDIDATE_ONE else None

    def get_workflow_for_screening_run(
        self, screening_run_id: UUID
    ) -> TailRadarWorkflowData | None:
        return self.workflow if screening_run_id == SCREENING_RUN_ID else None

    def get_candidate_workflow_state(
        self, candidate_id: UUID
    ) -> TailRadarWorkflowCandidateState | None:
        return self.states.get(candidate_id)

    def get_latest_research(self, candidate_id: UUID) -> None:
        del candidate_id
        return None


class FakePaidResearch:
    def __init__(self) -> None:
        self.calls: list[tuple[UUID, datetime, bool]] = []

    def execute(
        self, *, candidate_id: UUID, analysis_as_of: datetime, force: bool
    ) -> SimpleNamespace:
        self.calls.append((candidate_id, analysis_as_of, force))
        return SimpleNamespace(
            research=SimpleNamespace(
                research_id=_derived_id(candidate_id, 2),
                status=TailRadarResearchStatus.SUCCEEDED,
                error_code=None,
            )
        )


def test_on_demand_research_calls_exactly_one_selected_candidate() -> None:
    repository = FakeOnDemandRepository()
    research = FakePaidResearch()
    service = TailRadarOnDemandResearchService(
        research=cast(TailRadarResearchService, research),
        repository=cast(TailRadarDataRepository, repository),
    )

    service.execute(candidate_id=CANDIDATE_ONE)

    assert research.calls == [(CANDIDATE_ONE, ANALYSIS_AS_OF, False)]
    assert (
        repository.states[CANDIDATE_ONE].research_status is TailRadarCandidateStageStatus.SUCCEEDED
    )
    assert repository.states[CANDIDATE_ONE].research_id == _derived_id(CANDIDATE_ONE, 2)


def test_failed_on_demand_research_requires_explicit_paid_retry() -> None:
    repository = FakeOnDemandRepository()
    repository.states[CANDIDATE_ONE] = repository.states[CANDIDATE_ONE].model_copy(
        update={
            "research_status": TailRadarCandidateStageStatus.FAILED,
            "research_error_code": "fixture_failure",
        }
    )
    research = FakePaidResearch()
    service = TailRadarOnDemandResearchService(
        research=cast(TailRadarResearchService, research),
        repository=cast(TailRadarDataRepository, repository),
    )

    with pytest.raises(TailRadarOnDemandResearchRetryRequiredError):
        service.execute(candidate_id=CANDIDATE_ONE)

    assert research.calls == []
    service.execute(candidate_id=CANDIDATE_ONE, retry_failed=True)
    assert research.calls == [(CANDIDATE_ONE, ANALYSIS_AS_OF, True)]


def _derived_id(source: UUID, suffix: int) -> UUID:
    return UUID(int=(source.int + suffix) % (1 << 128))


def test_parallel_intraday_preserves_cutoff_isolates_failure_and_resumes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service, repository, snapshot, screening, intraday = build_service(intraday_workers=2)
    barrier = Barrier(2, timeout=3)
    execute = intraday.execute

    def concurrent(*, candidate_id: UUID, analysis_as_of: datetime) -> SimpleNamespace:
        assert analysis_as_of == ANALYSIS_AS_OF
        barrier.wait()  # Cannot complete if candidate requests are accidentally serialized.
        return execute(candidate_id=candidate_id, analysis_as_of=analysis_as_of)

    intraday.failures.add(CANDIDATE_TWO)
    monkeypatch.setattr(intraday, "execute", concurrent)
    result = service.execute(intended_snapshot_time=INTENDED, analysis_as_of=ANALYSIS_AS_OF)
    assert result.workflow.technical_succeeded_count == 1
    assert result.workflow.technical_failed_count == 1
    assert set(intraday.calls) == {CANDIDATE_ONE, CANDIDATE_TWO}
    assert all(state.research_id is None for state in repository.states.values())
    monkeypatch.setattr(intraday, "execute", execute)
    intraday.failures.clear()
    assert service.resume(workflow_run_id=WORKFLOW_ID).workflow.technical_succeeded_count == 2
    assert intraday.calls.count(CANDIDATE_ONE) == 1
    assert snapshot.calls == screening.calls == 1

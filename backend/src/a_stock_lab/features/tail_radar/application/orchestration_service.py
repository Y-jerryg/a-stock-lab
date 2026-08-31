from collections.abc import Callable
from datetime import datetime
from uuid import UUID

from a_stock_lab.core.time import as_market_timezone, now_in_market_timezone
from a_stock_lab.features.tail_radar.application.contracts import (
    TailRadarRepository,
    TailRadarWorkflowRepository,
)
from a_stock_lab.features.tail_radar.application.intraday_service import (
    TailRadarIntradayAnalysisService,
)
from a_stock_lab.features.tail_radar.application.models import TailRadarCandidateData
from a_stock_lab.features.tail_radar.application.orchestration_models import (
    TAIL_RADAR_WORKFLOW_VERSION,
    TailRadarCandidateStageStatus,
    TailRadarWorkflowData,
    TailRadarWorkflowDisposition,
    TailRadarWorkflowLifecycle,
    TailRadarWorkflowResult,
)
from a_stock_lab.features.tail_radar.application.research_models import TailRadarResearchStatus
from a_stock_lab.features.tail_radar.application.research_service import TailRadarResearchService
from a_stock_lab.features.tail_radar.application.service import TailRadarScreeningService
from a_stock_lab.features.tail_radar.domain.errors import (
    TailRadarCommitUncertainError,
    TailRadarPersistenceError,
    TailRadarWorkflowError,
    TailRadarWorkflowNotFoundError,
    TailRadarWorkflowTimeError,
)
from a_stock_lab.shared.execution.models import RunStatus
from a_stock_lab.shared.market_data.execution_service import FullMarketSnapshotExecutionEngine


class TailRadarApplicationService:
    """Resume-safe orchestration over the existing point-in-time application services."""

    def __init__(
        self,
        *,
        snapshot_execution: FullMarketSnapshotExecutionEngine,
        screening: TailRadarScreeningService,
        intraday: TailRadarIntradayAnalysisService,
        research: TailRadarResearchService,
        tail_radar_repository: TailRadarRepository,
        workflow_repository: TailRadarWorkflowRepository,
        clock: Callable[[], datetime] = now_in_market_timezone,
    ) -> None:
        self._snapshot_execution = snapshot_execution
        self._screening = screening
        self._intraday = intraday
        self._research = research
        self._tail_radar_repository = tail_radar_repository
        self._workflow_repository = workflow_repository
        self._clock = clock

    def execute(
        self,
        *,
        intended_snapshot_time: datetime,
        analysis_as_of: datetime | None = None,
    ) -> TailRadarWorkflowResult:
        intended = self._normalize_timestamp(
            intended_snapshot_time,
            field="intended_snapshot_time",
        )
        requested_as_of = (
            None
            if analysis_as_of is None
            else self._normalize_timestamp(analysis_as_of, field="analysis_as_of")
        )
        if requested_as_of is not None and requested_as_of.date() != intended.date():
            raise TailRadarWorkflowTimeError(
                "analysis_as_of must be on the intended A-share trade date"
            )
        started_at = as_market_timezone(self._clock())
        claim = self._workflow_repository.claim_workflow(
            intended_snapshot_time=intended,
            requested_analysis_as_of=requested_as_of,
            workflow_version=TAIL_RADAR_WORKFLOW_VERSION,
            started_at=started_at,
        )
        if not claim.created:
            return TailRadarWorkflowResult(
                disposition=TailRadarWorkflowDisposition.IDEMPOTENT_REPLAY,
                workflow=claim.workflow,
            )
        workflow = self._continue_workflow(
            claim.workflow,
            retry_failed_research=False,
        )
        return TailRadarWorkflowResult(
            disposition=TailRadarWorkflowDisposition.CREATED,
            workflow=workflow,
        )

    def resume(
        self,
        *,
        workflow_run_id: UUID,
        retry_failed_research: bool = False,
    ) -> TailRadarWorkflowResult:
        workflow = self._workflow_repository.get_workflow(workflow_run_id)
        if workflow is None:
            raise TailRadarWorkflowNotFoundError("Tail Radar workflow was not found")
        if workflow.lifecycle is TailRadarWorkflowLifecycle.SUCCEEDED:
            return TailRadarWorkflowResult(
                disposition=TailRadarWorkflowDisposition.IDEMPOTENT_REPLAY,
                workflow=workflow,
            )
        completed = self._continue_workflow(
            workflow,
            retry_failed_research=retry_failed_research,
        )
        return TailRadarWorkflowResult(
            disposition=TailRadarWorkflowDisposition.RESUMED,
            workflow=completed,
        )

    def _continue_workflow(
        self,
        workflow: TailRadarWorkflowData,
        *,
        retry_failed_research: bool,
    ) -> TailRadarWorkflowData:
        stage = "snapshot"
        try:
            if workflow.snapshot_id is None or workflow.snapshot_run_id is None:
                workflow = self._workflow_repository.set_workflow_lifecycle(
                    workflow_run_id=workflow.workflow_run_id,
                    lifecycle=TailRadarWorkflowLifecycle.SNAPSHOT_RUNNING,
                )
                snapshot = self._snapshot_execution.execute(
                    intended_snapshot_time=workflow.intended_snapshot_time,
                    force=False,
                )
                if snapshot.run.status is not RunStatus.SUCCEEDED or snapshot.manifest is None:
                    raise TailRadarWorkflowError(
                        "official full-market snapshot did not complete successfully"
                    )
                workflow = self._workflow_repository.attach_workflow_snapshot(
                    workflow_run_id=workflow.workflow_run_id,
                    snapshot_run_id=snapshot.run.run_id,
                    snapshot_id=snapshot.manifest.snapshot_id,
                )

            stage = "screening"
            if workflow.screening_run_id is None:
                snapshot_id = workflow.snapshot_id
                if snapshot_id is None:
                    raise TailRadarWorkflowError("workflow has no snapshot for screening")
                workflow = self._workflow_repository.set_workflow_lifecycle(
                    workflow_run_id=workflow.workflow_run_id,
                    lifecycle=TailRadarWorkflowLifecycle.SCREENING_RUNNING,
                )
                screening = self._screening.execute(snapshot_id=snapshot_id)
                if screening.run.status is not RunStatus.SUCCEEDED:
                    raise TailRadarWorkflowError(
                        "deterministic Tail Radar screening did not complete successfully"
                    )
                candidates = self._all_candidates(screening.run.run_id)
                analysis_as_of = workflow.analysis_as_of or as_market_timezone(self._clock())
                self._validate_analysis_time(
                    analysis_as_of=analysis_as_of,
                    workflow=workflow,
                    candidates=candidates,
                )
                workflow = self._workflow_repository.attach_workflow_screening(
                    workflow_run_id=workflow.workflow_run_id,
                    screening_run_id=screening.run.run_id,
                    analysis_as_of=analysis_as_of,
                    candidate_ids=tuple(candidate.candidate_id for candidate in candidates),
                )
            else:
                candidates = self._all_candidates(workflow.screening_run_id)

            if workflow.analysis_as_of is None:
                raise TailRadarWorkflowError("workflow has no analysis_as_of boundary")
            self._validate_analysis_time(
                analysis_as_of=workflow.analysis_as_of,
                workflow=workflow,
                candidates=candidates,
            )
            stage = "candidate_analysis"
            workflow = self._workflow_repository.set_workflow_lifecycle(
                workflow_run_id=workflow.workflow_run_id,
                lifecycle=TailRadarWorkflowLifecycle.CANDIDATE_ANALYSIS_RUNNING,
            )
            self._analyze_candidates(
                workflow=workflow,
                candidates=candidates,
                retry_failed_research=retry_failed_research,
            )
            return self._workflow_repository.complete_workflow(
                workflow_run_id=workflow.workflow_run_id,
                finished_at=as_market_timezone(self._clock()),
            )
        except TailRadarCommitUncertainError:
            raise
        except Exception as exc:
            try:
                self._workflow_repository.fail_workflow(
                    workflow_run_id=workflow.workflow_run_id,
                    finished_at=as_market_timezone(self._clock()),
                    error_stage=stage,
                    error_code=_error_code(exc),
                )
            except TailRadarPersistenceError as recording_error:
                raise recording_error from exc
            raise

    def _analyze_candidates(
        self,
        *,
        workflow: TailRadarWorkflowData,
        candidates: tuple[TailRadarCandidateData, ...],
        retry_failed_research: bool,
    ) -> None:
        if workflow.analysis_as_of is None:
            raise TailRadarWorkflowError("candidate analysis requires analysis_as_of")
        states = {
            state.candidate_id: state
            for state in self._workflow_repository.list_workflow_candidate_states(
                workflow.workflow_run_id
            )
        }
        if set(states) != {candidate.candidate_id for candidate in candidates}:
            raise TailRadarWorkflowError("workflow candidate state set is incomplete")

        for candidate in candidates:
            state = states[candidate.candidate_id]
            if state.technical_status is not TailRadarCandidateStageStatus.SUCCEEDED:
                self._workflow_repository.set_candidate_technical_stage(
                    workflow_run_id=workflow.workflow_run_id,
                    candidate_id=candidate.candidate_id,
                    status=TailRadarCandidateStageStatus.RUNNING,
                )
                try:
                    intraday_result = self._intraday.execute(
                        candidate_id=candidate.candidate_id,
                        analysis_as_of=workflow.analysis_as_of,
                    )
                except Exception as exc:
                    if isinstance(exc, TailRadarCommitUncertainError):
                        raise
                    self._workflow_repository.set_candidate_technical_stage(
                        workflow_run_id=workflow.workflow_run_id,
                        candidate_id=candidate.candidate_id,
                        status=TailRadarCandidateStageStatus.FAILED,
                        error_code=_error_code(exc),
                    )
                else:
                    self._workflow_repository.set_candidate_technical_stage(
                        workflow_run_id=workflow.workflow_run_id,
                        candidate_id=candidate.candidate_id,
                        status=TailRadarCandidateStageStatus.SUCCEEDED,
                        analysis_id=intraday_result.analysis.analysis_id,
                    )

        states = {
            state.candidate_id: state
            for state in self._workflow_repository.list_workflow_candidate_states(
                workflow.workflow_run_id
            )
        }
        for candidate in candidates:
            state = states[candidate.candidate_id]
            if state.research_status in {
                TailRadarCandidateStageStatus.SUCCEEDED,
                TailRadarCandidateStageStatus.NO_EVIDENCE,
            }:
                continue
            if (
                state.research_status is TailRadarCandidateStageStatus.FAILED
                and not retry_failed_research
            ):
                continue
            force = (
                retry_failed_research
                and state.research_status is TailRadarCandidateStageStatus.FAILED
            )
            self._workflow_repository.set_candidate_research_stage(
                workflow_run_id=workflow.workflow_run_id,
                candidate_id=candidate.candidate_id,
                status=TailRadarCandidateStageStatus.RUNNING,
            )
            try:
                research_result = self._research.execute(
                    candidate_id=candidate.candidate_id,
                    analysis_as_of=workflow.analysis_as_of,
                    force=force,
                )
            except Exception as exc:
                if isinstance(exc, TailRadarCommitUncertainError):
                    raise
                self._workflow_repository.set_candidate_research_stage(
                    workflow_run_id=workflow.workflow_run_id,
                    candidate_id=candidate.candidate_id,
                    status=TailRadarCandidateStageStatus.FAILED,
                    error_code=_error_code(exc),
                )
                continue
            research = research_result.research
            if research.status is TailRadarResearchStatus.SUCCEEDED:
                status = TailRadarCandidateStageStatus.SUCCEEDED
            elif research.status is TailRadarResearchStatus.NO_EVIDENCE:
                status = TailRadarCandidateStageStatus.NO_EVIDENCE
            elif research.status is TailRadarResearchStatus.FAILED:
                self._workflow_repository.set_candidate_research_stage(
                    workflow_run_id=workflow.workflow_run_id,
                    candidate_id=candidate.candidate_id,
                    status=TailRadarCandidateStageStatus.FAILED,
                    error_code=research.error_code or "research_failed",
                )
                continue
            else:
                continue
            self._workflow_repository.set_candidate_research_stage(
                workflow_run_id=workflow.workflow_run_id,
                candidate_id=candidate.candidate_id,
                status=status,
                research_id=research.research_id,
            )

    def _all_candidates(self, run_id: UUID) -> tuple[TailRadarCandidateData, ...]:
        items: list[TailRadarCandidateData] = []
        offset = 0
        page_size = 100
        while True:
            page = self._tail_radar_repository.list_candidates(
                run_id=run_id,
                offset=offset,
                limit=page_size,
            )
            items.extend(page.items)
            offset += len(page.items)
            if offset >= page.total:
                break
            if not page.items:
                raise TailRadarWorkflowError("candidate pagination ended before its total")
        return tuple(items)

    def _validate_analysis_time(
        self,
        *,
        analysis_as_of: datetime,
        workflow: TailRadarWorkflowData,
        candidates: tuple[TailRadarCandidateData, ...],
    ) -> None:
        as_of = self._normalize_timestamp(analysis_as_of, field="analysis_as_of")
        now = as_market_timezone(self._clock())
        if as_of > now:
            raise TailRadarWorkflowTimeError("analysis_as_of cannot be in the future")
        if as_of.date() != workflow.trade_date:
            raise TailRadarWorkflowTimeError("analysis_as_of must be on the workflow trade date")
        if any(as_of < candidate.as_of for candidate in candidates):
            raise TailRadarWorkflowTimeError(
                "analysis_as_of cannot precede candidate snapshot evidence"
            )

    @staticmethod
    def _normalize_timestamp(value: datetime, *, field: str) -> datetime:
        try:
            return as_market_timezone(value)
        except ValueError as exc:
            raise TailRadarWorkflowTimeError(
                f"{field} must include an explicit UTC offset"
            ) from exc


def _error_code(error: Exception) -> str:
    code = getattr(error, "code", None)
    return code if isinstance(code, str) and code else type(error).__name__

from uuid import UUID

from a_stock_lab.features.tail_radar.application.contracts import TailRadarDataRepository
from a_stock_lab.features.tail_radar.application.intraday_models import (
    TailRadarIntradayAnalysisData,
)
from a_stock_lab.features.tail_radar.application.models import (
    TailRadarCandidateData,
    TailRadarCandidatePage,
    TailRadarRunData,
    TailRadarRunPage,
)
from a_stock_lab.features.tail_radar.application.orchestration_models import (
    TailRadarWorkflowCandidateState,
    TailRadarWorkflowData,
)
from a_stock_lab.features.tail_radar.application.query_models import (
    TailRadarCandidateOverviewData,
    TailRadarCandidateOverviewPage,
)
from a_stock_lab.features.tail_radar.application.research_models import TailRadarResearchData
from a_stock_lab.shared.market_data.persistence_schemas import PersistedSnapshotManifest


class TailRadarQueryService:
    """Read already-persisted Tail Radar results without triggering execution."""

    def __init__(self, repository: TailRadarDataRepository) -> None:
        self._repository = repository

    def latest_run(self) -> TailRadarRunData | None:
        return self._repository.get_latest_run()

    def list_runs(self, *, offset: int, limit: int) -> TailRadarRunPage:
        return self._repository.list_runs(offset=offset, limit=limit)

    def get_run(self, run_id: UUID) -> TailRadarRunData | None:
        return self._repository.get_run(run_id)

    def list_candidates(self, *, run_id: UUID, offset: int, limit: int) -> TailRadarCandidatePage:
        return self._repository.list_candidates(run_id=run_id, offset=offset, limit=limit)

    def list_candidate_overviews(
        self, *, run_id: UUID, offset: int, limit: int
    ) -> TailRadarCandidateOverviewPage:
        page = self._repository.list_candidates(run_id=run_id, offset=offset, limit=limit)
        candidate_ids = tuple(item.candidate_id for item in page.items)
        intraday = self._repository.get_latest_intraday_analyses(candidate_ids)
        workflow = self._repository.get_workflow_for_screening_run(run_id)
        states = (
            {}
            if workflow is None
            else {
                state.candidate_id: state
                for state in self._repository.list_workflow_candidate_states(
                    workflow.workflow_run_id
                )
            }
        )
        return TailRadarCandidateOverviewPage(
            items=tuple(
                TailRadarCandidateOverviewData(
                    candidate=candidate,
                    intraday_analysis=intraday.get(candidate.candidate_id),
                    workflow_state=states.get(candidate.candidate_id),
                )
                for candidate in page.items
            ),
            total=page.total,
            offset=page.offset,
            limit=page.limit,
        )

    def get_candidate(self, candidate_id: UUID) -> TailRadarCandidateData | None:
        return self._repository.get_candidate(candidate_id)

    def get_latest_intraday_analysis(
        self, candidate_id: UUID
    ) -> TailRadarIntradayAnalysisData | None:
        return self._repository.get_latest_intraday_analysis(candidate_id)

    def get_latest_research(self, candidate_id: UUID) -> TailRadarResearchData | None:
        return self._repository.get_latest_research(candidate_id)

    def get_workflow_for_run(self, run_id: UUID) -> TailRadarWorkflowData | None:
        return self._repository.get_workflow_for_screening_run(run_id)

    def get_candidate_workflow_state(
        self, candidate_id: UUID
    ) -> TailRadarWorkflowCandidateState | None:
        return self._repository.get_candidate_workflow_state(candidate_id)

    def get_snapshot(self, snapshot_id: UUID) -> PersistedSnapshotManifest | None:
        return self._repository.get_official_snapshot(snapshot_id)

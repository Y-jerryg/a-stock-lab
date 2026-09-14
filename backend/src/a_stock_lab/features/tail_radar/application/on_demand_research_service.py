from uuid import UUID

from a_stock_lab.features.tail_radar.application.contracts import (
    TailRadarDataRepository,
)
from a_stock_lab.features.tail_radar.application.orchestration_models import (
    TailRadarCandidateStageStatus,
)
from a_stock_lab.features.tail_radar.application.research_models import (
    TailRadarResearchDisposition,
    TailRadarResearchResult,
    TailRadarResearchStatus,
)
from a_stock_lab.features.tail_radar.application.research_service import TailRadarResearchService
from a_stock_lab.features.tail_radar.domain.errors import (
    TailRadarCandidateNotFoundError,
    TailRadarCommitUncertainError,
    TailRadarOnDemandResearchInProgressError,
    TailRadarOnDemandResearchRetryRequiredError,
    TailRadarOnDemandResearchUnavailableError,
)


class TailRadarOnDemandResearchService:
    """Run paid research for exactly one explicitly selected workflow candidate."""

    def __init__(
        self,
        *,
        research: TailRadarResearchService,
        repository: TailRadarDataRepository,
    ) -> None:
        self._research = research
        self._repository = repository

    def execute(
        self,
        *,
        candidate_id: UUID,
        retry_failed: bool = False,
    ) -> TailRadarResearchResult:
        candidate = self._repository.get_candidate(candidate_id)
        if candidate is None:
            raise TailRadarCandidateNotFoundError("Tail Radar candidate was not found")
        workflow = self._repository.get_workflow_for_screening_run(candidate.run_id)
        state = self._repository.get_candidate_workflow_state(candidate_id)
        if workflow is None or workflow.analysis_as_of is None or state is None:
            raise TailRadarOnDemandResearchUnavailableError(
                "candidate is not attached to a point-in-time Tail Radar workflow"
            )
        if state.workflow_run_id != workflow.workflow_run_id:
            raise TailRadarOnDemandResearchUnavailableError(
                "candidate workflow state does not match its screening run"
            )
        if state.research_status is TailRadarCandidateStageStatus.RUNNING:
            raise TailRadarOnDemandResearchInProgressError(
                "research for this candidate is already running"
            )
        if state.research_status in {
            TailRadarCandidateStageStatus.SUCCEEDED,
            TailRadarCandidateStageStatus.NO_EVIDENCE,
        }:
            existing = self._repository.get_latest_research(candidate_id)
            if existing is None or existing.status.value != state.research_status.value:
                raise TailRadarOnDemandResearchUnavailableError(
                    "candidate research state has no matching persisted artifact"
                )
            return TailRadarResearchResult(
                disposition=TailRadarResearchDisposition.CACHED,
                research=existing,
            )
        if state.research_status is TailRadarCandidateStageStatus.FAILED and not retry_failed:
            raise TailRadarOnDemandResearchRetryRequiredError(
                "a failed paid attempt requires explicit retry confirmation"
            )
        if retry_failed and state.research_status is not TailRadarCandidateStageStatus.FAILED:
            raise TailRadarOnDemandResearchRetryRequiredError(
                "forced retry is permitted only for a previously failed candidate"
            )

        self._repository.set_candidate_research_stage(
            workflow_run_id=workflow.workflow_run_id,
            candidate_id=candidate_id,
            status=TailRadarCandidateStageStatus.RUNNING,
        )
        try:
            result = self._research.execute(
                candidate_id=candidate_id,
                analysis_as_of=workflow.analysis_as_of,
                force=retry_failed,
            )
        except TailRadarCommitUncertainError:
            raise
        except Exception as exc:
            self._repository.set_candidate_research_stage(
                workflow_run_id=workflow.workflow_run_id,
                candidate_id=candidate_id,
                status=TailRadarCandidateStageStatus.FAILED,
                error_code=_error_code(exc),
            )
            raise

        research = result.research
        if research.status is TailRadarResearchStatus.SUCCEEDED:
            status = TailRadarCandidateStageStatus.SUCCEEDED
        elif research.status is TailRadarResearchStatus.NO_EVIDENCE:
            status = TailRadarCandidateStageStatus.NO_EVIDENCE
        elif research.status is TailRadarResearchStatus.RUNNING:
            raise TailRadarOnDemandResearchInProgressError(
                "research for this candidate is already running"
            )
        else:
            self._repository.set_candidate_research_stage(
                workflow_run_id=workflow.workflow_run_id,
                candidate_id=candidate_id,
                status=TailRadarCandidateStageStatus.FAILED,
                error_code=research.error_code or "research_failed",
            )
            raise TailRadarOnDemandResearchRetryRequiredError(
                "the previous paid attempt failed; explicit retry confirmation is required"
            )
        self._repository.set_candidate_research_stage(
            workflow_run_id=workflow.workflow_run_id,
            candidate_id=candidate_id,
            status=status,
            research_id=research.research_id,
        )
        return result


def _error_code(error: Exception) -> str:
    code = getattr(error, "code", None)
    return code if isinstance(code, str) and code else type(error).__name__

from uuid import UUID

from a_stock_lab.features.tail_radar.application.contracts import TailRadarRepository
from a_stock_lab.features.tail_radar.application.models import (
    TailRadarCandidateData,
    TailRadarCandidatePage,
    TailRadarRunData,
    TailRadarRunPage,
)


class TailRadarQueryService:
    """Read already-persisted Tail Radar results without triggering execution."""

    def __init__(self, repository: TailRadarRepository) -> None:
        self._repository = repository

    def latest_run(self) -> TailRadarRunData | None:
        return self._repository.get_latest_run()

    def list_runs(self, *, offset: int, limit: int) -> TailRadarRunPage:
        return self._repository.list_runs(offset=offset, limit=limit)

    def get_run(self, run_id: UUID) -> TailRadarRunData | None:
        return self._repository.get_run(run_id)

    def list_candidates(self, *, run_id: UUID, offset: int, limit: int) -> TailRadarCandidatePage:
        return self._repository.list_candidates(run_id=run_id, offset=offset, limit=limit)

    def get_candidate(self, candidate_id: UUID) -> TailRadarCandidateData | None:
        return self._repository.get_candidate(candidate_id)

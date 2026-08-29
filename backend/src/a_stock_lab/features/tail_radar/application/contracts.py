from collections.abc import Sequence
from datetime import datetime
from typing import Protocol
from uuid import UUID

from a_stock_lab.features.tail_radar.application.models import (
    TailRadarCandidateCreate,
    TailRadarCandidateData,
    TailRadarCandidatePage,
    TailRadarRunClaim,
    TailRadarRunData,
    TailRadarRunPage,
)
from a_stock_lab.features.tail_radar.domain.screening import TailRadarScreeningConfiguration
from a_stock_lab.shared.market_data.models import FullMarketSnapshot
from a_stock_lab.shared.market_data.persistence_schemas import PersistedSnapshotManifest


class MarketSnapshotArtifactReader(Protocol):
    def read(self, manifest: PersistedSnapshotManifest) -> FullMarketSnapshot: ...


class TailRadarRepository(Protocol):
    def get_official_snapshot(self, snapshot_id: UUID) -> PersistedSnapshotManifest | None: ...

    def claim_run(
        self,
        *,
        snapshot: PersistedSnapshotManifest,
        screening_rule_version: str,
        rule_configuration: TailRadarScreeningConfiguration,
        started_at: datetime,
    ) -> TailRadarRunClaim: ...

    def complete_run(
        self,
        *,
        run_id: UUID,
        candidates: Sequence[TailRadarCandidateCreate],
        evaluated_record_count: int,
        invalid_record_count: int,
        finished_at: datetime,
    ) -> TailRadarRunData: ...

    def fail_run(
        self,
        *,
        run_id: UUID,
        finished_at: datetime,
        error_code: str,
    ) -> TailRadarRunData: ...

    def get_latest_run(self) -> TailRadarRunData | None: ...

    def list_runs(self, *, offset: int, limit: int) -> TailRadarRunPage: ...

    def get_run(self, run_id: UUID) -> TailRadarRunData | None: ...

    def list_candidates(
        self, *, run_id: UUID, offset: int, limit: int
    ) -> TailRadarCandidatePage: ...

    def get_candidate(self, candidate_id: UUID) -> TailRadarCandidateData | None: ...

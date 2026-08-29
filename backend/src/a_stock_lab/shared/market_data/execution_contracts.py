from datetime import datetime
from typing import Protocol
from uuid import UUID

from a_stock_lab.shared.execution.schemas import ExecutionRunData
from a_stock_lab.shared.market_data.execution_models import (
    SnapshotManifestCreate,
    SnapshotRunClaim,
    SnapshotRunKey,
)
from a_stock_lab.shared.market_data.persistence_schemas import PersistedSnapshotManifest


class SnapshotExecutionRepository(Protocol):
    def claim_run(
        self,
        *,
        key: SnapshotRunKey,
        provider: str,
        started_at: datetime,
        force: bool,
    ) -> SnapshotRunClaim: ...

    def complete_run(
        self,
        *,
        manifest: SnapshotManifestCreate,
        run_metadata: dict[str, object],
        finished_at: datetime,
    ) -> tuple[ExecutionRunData, PersistedSnapshotManifest]: ...

    def fail_run(
        self,
        *,
        run_id: UUID,
        finished_at: datetime,
        error_code: str,
        error_message: str,
        error_details: dict[str, object] | None,
    ) -> ExecutionRunData: ...

    def get_run(self, run_id: UUID) -> ExecutionRunData | None: ...

    def get_manifest(self, snapshot_id: UUID) -> PersistedSnapshotManifest | None: ...

    def get_manifest_for_run(self, run_id: UUID) -> PersistedSnapshotManifest | None: ...

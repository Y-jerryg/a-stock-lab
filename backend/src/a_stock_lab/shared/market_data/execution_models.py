from datetime import date
from enum import StrEnum
from uuid import UUID

from pydantic import (
    AwareDatetime,
    BaseModel,
    ConfigDict,
    Field,
    JsonValue,
    field_validator,
    model_validator,
)

from a_stock_lab.core.time import as_market_timezone
from a_stock_lab.shared.execution.models import RunStatus
from a_stock_lab.shared.execution.schemas import ExecutionRunData
from a_stock_lab.shared.market_data.models import SnapshotManifestStatus, SnapshotQualityReport
from a_stock_lab.shared.market_data.persistence_schemas import (
    PersistedSnapshotManifest,
    normalize_storage_key,
)

FULL_MARKET_SNAPSHOT_JOB_TYPE = "market_data.full_market_snapshot"
SNAPSHOT_EXECUTION_VERSION = "1"


class SnapshotExecutionDisposition(StrEnum):
    CREATED = "created"
    IDEMPOTENT_REPLAY = "idempotent_replay"
    FORCED_RERUN = "forced_rerun"


class SnapshotRunKey(BaseModel):
    model_config = ConfigDict(frozen=True)

    job_type: str = Field(min_length=1, max_length=128)
    trade_date: date
    intended_snapshot_time: AwareDatetime
    execution_version: str = Field(min_length=1, max_length=64)

    @field_validator("intended_snapshot_time")
    @classmethod
    def normalize_intended_time(cls, value: AwareDatetime) -> AwareDatetime:
        return as_market_timezone(value)

    @model_validator(mode="after")
    def trade_date_matches_intended_time(self) -> "SnapshotRunKey":
        if self.trade_date != self.intended_snapshot_time.date():
            raise ValueError("trade date must match intended snapshot time in Asia/Shanghai")
        return self


class SnapshotRunClaim(BaseModel):
    model_config = ConfigDict(frozen=True)

    run: ExecutionRunData
    created: bool


class SnapshotManifestCreate(BaseModel):
    model_config = ConfigDict(frozen=True)

    snapshot_id: UUID
    run_id: UUID
    trade_date: date
    intended_snapshot_time: AwareDatetime
    actual_fetch_started_at: AwareDatetime
    actual_fetch_finished_at: AwareDatetime
    provider: str = Field(min_length=1, max_length=128)
    provider_version: str | None = Field(default=None, max_length=128)
    provider_timestamp: AwareDatetime | None = None
    provider_metadata: dict[str, JsonValue]
    storage_key: str = Field(min_length=1, max_length=1024)
    checksum_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    row_count: int = Field(gt=0)
    latency_ms: float = Field(ge=0)
    quality_report: SnapshotQualityReport
    schema_version: int = Field(gt=0)
    status: SnapshotManifestStatus = SnapshotManifestStatus.AVAILABLE
    persisted_at: AwareDatetime

    @field_validator(
        "intended_snapshot_time",
        "actual_fetch_started_at",
        "actual_fetch_finished_at",
        "provider_timestamp",
        "persisted_at",
    )
    @classmethod
    def normalize_market_timestamps(cls, value: AwareDatetime | None) -> AwareDatetime | None:
        return None if value is None else as_market_timezone(value)

    @field_validator("storage_key")
    @classmethod
    def require_relative_storage_key(cls, value: str) -> str:
        return normalize_storage_key(value)

    @model_validator(mode="after")
    def validate_point_in_time_order(self) -> "SnapshotManifestCreate":
        if self.trade_date != self.intended_snapshot_time.date():
            raise ValueError("trade date must match intended snapshot time in Asia/Shanghai")
        if self.actual_fetch_finished_at < self.actual_fetch_started_at:
            raise ValueError("fetch finish cannot precede fetch start")
        if self.persisted_at < self.actual_fetch_finished_at:
            raise ValueError("persisted time cannot precede fetch finish")
        return self


class SnapshotExecutionResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    disposition: SnapshotExecutionDisposition
    run: ExecutionRunData
    manifest: PersistedSnapshotManifest | None = None

    @model_validator(mode="after")
    def manifest_matches_run_state(self) -> "SnapshotExecutionResult":
        if self.run.status is RunStatus.SUCCEEDED and self.manifest is None:
            raise ValueError("a succeeded snapshot run must have a manifest")
        if self.manifest is not None:
            if self.run.status is not RunStatus.SUCCEEDED:
                raise ValueError("only a succeeded snapshot run may have a manifest")
            if self.manifest.run_id != self.run.run_id:
                raise ValueError("snapshot manifest must reference the returned run")
        return self

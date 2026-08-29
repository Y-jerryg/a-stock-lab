from datetime import date
from uuid import UUID

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, JsonValue, field_validator

from a_stock_lab.core.time import as_market_timezone
from a_stock_lab.shared.market_data.models import SnapshotManifestStatus, SnapshotQualityReport


def normalize_storage_key(value: str) -> str:
    normalized = value.replace("\\", "/")
    segments = normalized.split("/")
    first_segment = segments[0]
    if (
        normalized.startswith("/")
        or any(segment in {"", ".", ".."} for segment in segments)
        or first_segment.endswith(":")
    ):
        raise ValueError("storage key must be a safe relative path")
    return normalized


class SnapshotStorageResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    storage_key: str = Field(min_length=1, max_length=1024)
    checksum_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    size_bytes: int = Field(ge=0)

    @field_validator("storage_key")
    @classmethod
    def require_relative_storage_key(cls, value: str) -> str:
        return normalize_storage_key(value)


class PersistedSnapshotManifest(BaseModel):
    model_config = ConfigDict(from_attributes=True, frozen=True)

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
    status: SnapshotManifestStatus
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

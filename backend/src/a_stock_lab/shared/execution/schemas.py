from datetime import date
from typing import Any
from uuid import UUID

from pydantic import AwareDatetime, BaseModel, ConfigDict, field_validator

from a_stock_lab.core.time import as_market_timezone
from a_stock_lab.shared.execution.models import RunStatus


class ExecutionRunData(BaseModel):
    model_config = ConfigDict(from_attributes=True, frozen=True)

    run_id: UUID
    job_type: str
    trade_date: date | None = None
    intended_execution_time: AwareDatetime
    actual_started_at: AwareDatetime | None = None
    actual_finished_at: AwareDatetime | None = None
    status: RunStatus
    provider: str | None = None
    implementation_version: str
    is_official: bool
    rerun_of_run_id: UUID | None = None
    run_metadata: dict[str, Any]
    error_code: str | None = None
    error_message: str | None = None
    error_details: dict[str, Any] | None = None
    created_at: AwareDatetime
    updated_at: AwareDatetime

    @field_validator(
        "intended_execution_time",
        "actual_started_at",
        "actual_finished_at",
        "created_at",
        "updated_at",
    )
    @classmethod
    def normalize_market_timestamps(cls, value: AwareDatetime | None) -> AwareDatetime | None:
        return None if value is None else as_market_timezone(value)

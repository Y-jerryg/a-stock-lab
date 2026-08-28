from typing import Any
from uuid import UUID

from pydantic import AwareDatetime, BaseModel, ConfigDict

from a_stock_lab.shared.execution.models import RunStatus


class ExecutionRunData(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    run_id: UUID
    job_type: str
    intended_execution_time: AwareDatetime
    actual_started_at: AwareDatetime | None = None
    actual_finished_at: AwareDatetime | None = None
    status: RunStatus
    provider: str | None = None
    implementation_version: str
    run_metadata: dict[str, Any]
    error_code: str | None = None
    error_message: str | None = None
    error_details: dict[str, Any] | None = None
    created_at: AwareDatetime
    updated_at: AwareDatetime

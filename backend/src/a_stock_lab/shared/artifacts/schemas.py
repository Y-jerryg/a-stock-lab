from datetime import date
from typing import Any
from uuid import UUID

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field


class ResearchArtifactData(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    artifact_id: UUID
    module: str
    artifact_type: str
    symbol: str | None = None
    trade_date: date | None = None
    as_of: AwareDatetime
    schema_version: int = Field(ge=1)
    payload: dict[str, Any]
    created_at: AwareDatetime

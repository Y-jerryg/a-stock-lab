from datetime import datetime
from typing import Literal

from pydantic import AwareDatetime, BaseModel


class DependencyHealth(BaseModel):
    status: Literal["available", "unavailable"]


class HealthResponse(BaseModel):
    status: Literal["ok", "degraded"]
    service: str
    version: str
    generated_at: AwareDatetime
    database: DependencyHealth

    @classmethod
    def healthy(cls, *, version: str, generated_at: datetime) -> "HealthResponse":
        return cls(
            status="ok",
            service="a-stock-lab-backend",
            version=version,
            generated_at=generated_at,
            database=DependencyHealth(status="available"),
        )

    @classmethod
    def degraded(cls, *, version: str, generated_at: datetime) -> "HealthResponse":
        return cls(
            status="degraded",
            service="a-stock-lab-backend",
            version=version,
            generated_at=generated_at,
            database=DependencyHealth(status="unavailable"),
        )

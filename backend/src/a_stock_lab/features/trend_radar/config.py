from datetime import time
from typing import Literal, Self

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class TrendSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(".env", "../.env"), extra="ignore", allow_inf_nan=False, env_parse_none_str="null"
    )

    trend_top_n: int = Field(default=300, gt=0, le=10000)
    trend_min_days: int = Field(default=7, ge=7, le=9)
    trend_max_days: int = Field(default=9, ge=7, le=9)
    trend_max_pullback_days: int = Field(default=2, ge=0, le=2)
    trend_max_single_pullback_pct: float | None = Field(default=None, ge=0)
    trend_baseline_volume_days: int = Field(default=20, gt=0, le=120)
    trend_strong_volume_ratio: float = Field(default=0.55, gt=0)
    trend_schedule_time: time = time(15, 45)
    trend_timezone: Literal["Asia/Shanghai"] = "Asia/Shanghai"
    trend_schedule_poll_seconds: float = Field(default=5, gt=0, le=60)
    trend_heartbeat_seconds: float = Field(default=20, gt=0, le=30)
    trend_provider_timeout_seconds: float = Field(default=60, gt=0, le=300)
    trend_provider_attempts: int = Field(default=3, ge=1, le=5)
    trend_provider_pace_seconds: float = Field(default=0.3, ge=0, le=30)
    trend_max_failure_ratio: float = Field(default=0.2, gt=0, le=1)
    trend_max_consecutive_failures: int = Field(default=10, ge=1)

    @model_validator(mode="after")
    def validate_settings(self) -> Self:
        if self.trend_min_days > self.trend_max_days:
            raise ValueError("trend_min_days must not exceed trend_max_days")
        if self.trend_schedule_time.tzinfo or self.trend_schedule_time < time(15, 15):
            raise ValueError("trend_schedule_time must be a local time at or after 15:15")
        return self

    def snapshot(self) -> dict[str, object]:
        return {
            "rule_version": 2,
            "universe_scope": "all_a",
            **{
                key.removeprefix("trend_"): value
                for key, value in self.model_dump(mode="json").items()
                if key.startswith("trend_")
            },
        }

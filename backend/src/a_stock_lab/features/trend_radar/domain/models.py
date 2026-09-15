from datetime import date
from typing import Literal, Self
from uuid import UUID, uuid4

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, model_validator


class Model(BaseModel):
    model_config = ConfigDict(frozen=True, allow_inf_nan=False)


class ListedStock(Model):
    symbol: str = Field(pattern=r"^\d{6}$")
    name: str = Field(min_length=1)
    fetched_at: AwareDatetime


class Heat(ListedStock):
    heat_score: float | None = Field(default=None, ge=0)
    # Zero denotes unavailable attention rank, never an invented ranking position.
    heat_rank: int = Field(default=0, ge=0)
    heat_source: str
    data_date: date | None = None


class Bar(Model):
    symbol: str = Field(pattern=r"^\d{6}$")
    trade_date: date
    open: float = Field(gt=0)
    high: float = Field(gt=0)
    low: float = Field(gt=0)
    close: float = Field(gt=0)
    volume: float = Field(ge=0)
    amount: float = Field(ge=0)
    adjustment_type: Literal["qfq"] = "qfq"
    source: str = "eastmoney_daily_qfq"
    fetched_at: AwareDatetime

    @model_validator(mode="after")
    def prices(self) -> Self:
        if self.low > min(self.open, self.close) or self.high < max(self.open, self.close):
            raise ValueError("invalid OHLC range")
        return self


class Trend(Model):
    trend_days: int
    trend_start_date: date
    trend_end_date: date
    trend_start_close: float
    trend_end_close: float
    trend_return_pct: float
    pullback_days: int
    max_pullback_pct: float
    trend_slope: float


class Contraction(Model):
    trend_volume_avg: float
    baseline_volume_avg: float
    volume_ratio: float
    trend_amount_avg: float
    baseline_amount_avg: float
    amount_ratio: float | None
    is_strong_volume_contraction: bool
    highlight_level: Literal["strong", "normal"]


class Candidate(Heat, Trend, Contraction):
    pass


def candidate_order(row: Candidate, top_n: int) -> tuple[bool, bool, float, int, str]:
    return (
        not 0 < row.heat_rank <= top_n,
        not row.is_strong_volume_contraction,
        row.volume_ratio,
        row.heat_rank or 100000,
        row.symbol,
    )


class StockFailure(Model):
    symbol: str = Field(pattern=r"^\d{6}$")
    name: str
    error_code: str
    provider: str | None = None
    attempt: int | None = None
    exception_type: str


COMPLETED_STATUSES = ("success", "completed_with_warnings")


class ScanRun(Model):
    id: UUID = Field(default_factory=uuid4)
    trade_date: date | None = None
    trigger_type: Literal["scheduled", "manual", "cli"]
    status: Literal["running", "success", "completed_with_warnings", "failed"] = "running"
    requested_at: AwareDatetime | None = None
    started_at: AwareDatetime
    finished_at: AwareDatetime | None = None
    data_as_of: AwareDatetime | None = None
    heat_universe_count: int = 0
    requested_count: int = 0
    successful_count: int = 0
    failed_count: int = 0
    failed_symbols: list[StockFailure] = Field(default_factory=list)
    candidate_count: int = 0
    strong_contraction_count: int = 0
    error_message: str | None = None
    configuration_snapshot: dict[str, object]
    heat_source: str = "eastmoney_attention_index"
    market_data_source: str = "eastmoney_daily_qfq"
    schema_version: int = 1
    exclusions: dict[str, str] = Field(default_factory=dict)


class TrendError(Exception):
    def __init__(self, code: str, *, details: dict[str, object] | None = None) -> None:
        self.code = code
        self.details = details or {}
        super().__init__(code)


class ScanBusyError(TrendError):
    def __init__(self) -> None:
        super().__init__("scan_busy")

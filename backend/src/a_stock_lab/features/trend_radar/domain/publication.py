from datetime import date
from typing import Literal
from uuid import UUID

from pydantic import AwareDatetime, Field, model_validator

from a_stock_lab.features.trend_radar.domain.models import (
    COMPLETED_STATUSES,
    Bar,
    Candidate,
    Model,
    ScanRun,
)


class PublicParameters(Model):
    rule_version: Literal[1, 2] = 1
    universe_scope: Literal["top_heat", "all_a"] = "top_heat"
    top_n: int
    min_days: int
    max_days: int
    max_pullback_days: int
    max_single_pullback_pct: float | None
    baseline_volume_days: int
    strong_volume_ratio: float


class PublicStockFailure(Model):
    symbol: str
    name: str
    error_code: str


class PublicRunPayload(Model):
    data_as_of: AwareDatetime | None
    heat_universe_count: int
    candidate_count: int
    strong_contraction_count: int
    requested_count: int = 0
    successful_count: int = 0
    failed_count: int = 0
    failed_symbols: list[PublicStockFailure] = Field(default_factory=list)
    configuration_snapshot: PublicParameters


class PublicRun(Model):
    id: UUID
    trade_date: date | None
    status: Literal["running", "success", "completed_with_warnings", "failed"]
    started_at: AwareDatetime
    finished_at: AwareDatetime | None
    trigger_type: Literal["scheduled", "manual", "cli"]
    payload: PublicRunPayload

    @classmethod
    def from_run(cls, run: ScanRun) -> "PublicRun":
        return cls(
            id=run.id,
            trade_date=run.trade_date,
            status=run.status,
            started_at=run.started_at,
            finished_at=run.finished_at,
            trigger_type=run.trigger_type,
            payload=PublicRunPayload(
                data_as_of=run.data_as_of,
                heat_universe_count=run.heat_universe_count,
                candidate_count=run.candidate_count,
                strong_contraction_count=run.strong_contraction_count,
                requested_count=run.requested_count,
                successful_count=run.successful_count,
                failed_count=run.failed_count,
                failed_symbols=[
                    PublicStockFailure(symbol=row.symbol, name=row.name, error_code=row.error_code)
                    for row in run.failed_symbols
                ],
                configuration_snapshot=PublicParameters.model_validate(run.configuration_snapshot),
            ),
        )


class PublicIndex(Model):
    schema_version: Literal[2] = 2
    detail_schema_version: Literal[1] = 1
    generated_at: AwareDatetime
    latest: PublicRun | None
    attempts: list[PublicRun]


class PublicResults(Model):
    schema_version: Literal[1] = 1
    run_id: UUID
    results: list[Candidate]


class PublicStockDetail(Model):
    candidate: Candidate
    bars: list[Bar]


class PublicRunDetails(Model):
    schema_version: Literal[1] = 1
    run: PublicRun
    volume_unit: Literal["lot"] = "lot"
    amount_unit: Literal["CNY"] = "CNY"
    details: list[PublicStockDetail]

    @model_validator(mode="after")
    def evidence_identity(self) -> "PublicRunDetails":
        if self.run.status not in COMPLETED_STATUSES:
            raise ValueError("Only completed scan details can be published")
        if len(self.details) != self.run.payload.candidate_count or len(
            {item.candidate.symbol for item in self.details}
        ) != len(self.details):
            raise ValueError("Detail candidates do not match the run")
        for item in self.details:
            dates = [bar.trade_date for bar in item.bars]
            if dates != sorted(set(dates)) or any(
                bar.symbol != item.candidate.symbol
                or self.run.trade_date is None
                or bar.trade_date > self.run.trade_date
                or self.run.payload.data_as_of is None
                or bar.fetched_at > self.run.payload.data_as_of
                for bar in item.bars
            ):
                raise ValueError("Detail bars do not match the saved scan boundary")
            if item.bars and item.bars[-1].trade_date != item.candidate.trend_end_date:
                raise ValueError("Detail bars do not end at the candidate trend")
        return self

import logging
from collections.abc import Callable
from datetime import UTC, date, datetime, time
from typing import Literal
from zoneinfo import ZoneInfo

from a_stock_lab.features.trend_radar.application.contracts import (
    HeatProvider,
    LocalRepository,
    MarketDataProvider,
    ResultPublisher,
    TradingCalendarProvider,
)
from a_stock_lab.features.trend_radar.application.diagnostics import scanning_stock
from a_stock_lab.features.trend_radar.config import TrendSettings
from a_stock_lab.features.trend_radar.domain.detector import analyze_volume, detect_trend
from a_stock_lab.features.trend_radar.domain.models import (
    Bar,
    Candidate,
    Heat,
    ScanRun,
    StockFailure,
    TrendError,
)

logger = logging.getLogger(__name__)
SHANGHAI = ZoneInfo("Asia/Shanghai")


def utc_now() -> datetime:
    return datetime.now(UTC)


def rank_heat(rows: list[Heat], count: int) -> list[Heat]:
    if len({row.symbol for row in rows}) != len(rows):
        raise TrendError("duplicate_heat_symbols")
    if len(rows) < count:
        raise TrendError("insufficient_heat_universe")
    return [
        row.model_copy(update={"heat_rank": index + 1})
        for index, row in enumerate(
            sorted(rows, key=lambda row: (-row.heat_score, row.symbol))[:count]
        )
    ]


class TrendRadarScanService:
    def __init__(
        self,
        *,
        config: TrendSettings,
        heat: HeatProvider,
        market: MarketDataProvider,
        calendar: TradingCalendarProvider,
        local: LocalRepository,
        publisher: ResultPublisher,
        clock: Callable[[], datetime] = utc_now,
    ) -> None:
        self.config, self.heat, self.market = config, heat, market
        self.calendar, self.local, self.publisher, self.clock = calendar, local, publisher, clock

    def scan(self, trigger: Literal["scheduled", "cli"]) -> ScanRun | None:
        with self.local.lock():
            started = self.clock()
            run = ScanRun(
                trigger_type=trigger,
                started_at=started,
                trade_date=started.astimezone(SHANGHAI).date(),
                configuration_snapshot=self.config.snapshot(),
                schema_version=2,
            )
            if not self.local.begin(run):
                self.publisher.publish()
                return None  # This scheduled date already has a durable local claim.

            def remember(progress: ScanRun) -> None:
                nonlocal run
                run = progress

            try:
                # A publication outage must not prevent collection. Final export is retriable
                # from the completed local evidence without another provider call.
                try:
                    self.publisher.publish()
                except Exception:
                    logger.warning("trend_progress_export_failed", extra={"run_id": str(run.id)})
                run, results, inputs = self._evaluate(run, remember)
                self.local.complete(run, results, inputs)
                logger.info(
                    "trend_scan_completed",
                    extra={
                        "run_id": str(run.id),
                        "trigger_type": trigger,
                        "trade_date": run.trade_date,
                        "data_as_of": run.data_as_of,
                        "candidate_count": len(results),
                        "status": run.status,
                        "requested": run.requested_count,
                        "successful": run.successful_count,
                        "failed": run.failed_count,
                        "strong_count": run.strong_contraction_count,
                        "duration": (self.clock() - started).total_seconds(),
                    },
                )
            except Exception as exc:
                code = exc.code if isinstance(exc, TrendError) else "unexpected_error"
                run = run.model_copy(
                    update={"status": "failed", "error_message": code, "finished_at": self.clock()}
                )
                logger.exception(
                    "trend_scan_failed",
                    extra={
                        "run_id": str(run.id),
                        "error_code": code,
                        "trade_date": run.trade_date,
                        "requested": run.requested_count,
                        "successful": run.successful_count,
                        "failed": run.failed_count,
                        "candidate_count": run.candidate_count,
                        "exception_type": type(exc).__name__,
                    },
                )
                self.local.save_run(run)
            # Export failure leaves successful analysis successful in PostgreSQL. `export`
            # repairs the static files later; it must never trigger fresh market collection.
            self.publisher.publish()
            return run

    def _evaluate(
        self, run: ScanRun, remember: Callable[[ScanRun], None]
    ) -> tuple[ScanRun, list[Candidate], dict[str, list[Bar]]]:
        now = self.clock().astimezone(SHANGHAI)
        with scanning_stock(run_id=str(run.id)):
            sessions = self.calendar.sessions(now.date())
        completed = [
            day
            for day in sessions
            if day < now.date() or (day == now.date() and now.time() >= time(15, 15))
        ]
        required = self.config.trend_max_days + self.config.trend_baseline_volume_days
        if len(completed) < required:
            raise TrendError("insufficient_calendar_history")
        trade_date = completed[-1]
        run = run.model_copy(update={"trade_date": trade_date})
        self.local.save_run(run)
        remember(run)
        logger.info(
            "trend_session_resolved",
            extra={
                "run_id": str(run.id),
                "trade_date": trade_date,
                "market_time": now,
            },
        )
        with scanning_stock(run_id=str(run.id)):
            heat = rank_heat(self.heat.fetch_heat(), self.config.trend_top_n)
        if any(row.data_date != trade_date for row in heat):
            raise TrendError("stale_heat_data")
        run = run.model_copy(
            update={
                "trade_date": trade_date,
                "data_as_of": self.clock(),
                "heat_universe_count": len(heat),
                "requested_count": len(heat),
            }
        )
        self.local.save_run(run)
        remember(run)
        self.local.save_heat(run.id, heat)
        results: list[Candidate] = []
        inputs: dict[str, list[Bar]] = {}
        exclusions: dict[str, str] = {}
        failures: list[StockFailure] = []
        sources: set[str] = set()
        successful = consecutive_failures = 0
        for index, stock in enumerate(heat, start=1):
            context = {
                "run_id": str(run.id),
                "stock_number": index,
                "total": len(heat),
                "symbol": stock.symbol,
                "stock_name": stock.name,
            }
            logger.info(
                "trend_scan_progress",
                extra=context,
            )
            candidate = None
            # Database failures are global, not provider failures: keep cache IO outside
            # the stock-error boundary so outages never become 300 skipped stocks.
            bars = self.local.load_bars(stock.symbol, trade_date, self.clock())
            fetched = bars is None
            try:
                with scanning_stock(**context):
                    if bars is None:
                        bars = self.market.fetch_bars(
                            stock.symbol, completed[-min(len(completed), required + 30)], trade_date
                        )
                dates = [bar.trade_date for bar in bars]
                if (
                    dates != sorted(set(dates))
                    or any(
                        bar.symbol != stock.symbol or bar.trade_date > trade_date for bar in bars
                    )
                    or len({bar.source for bar in bars}) > 1
                ):
                    raise TrendError("invalid_market_sequence")
                if not bars or bars[-1].trade_date != trade_date:
                    raise TrendError("missing_latest_session")
            except TrendError as exc:
                details = exc.details
                failure = StockFailure(
                    symbol=stock.symbol,
                    name=stock.name,
                    error_code=exc.code,
                    provider=str(details["provider"]) if details.get("provider") else None,
                    attempt=int(str(details["attempt"])) if details.get("attempt") else None,
                    exception_type=str(details.get("exception_type", type(exc).__name__)),
                )
                failures.append(failure)
                consecutive_failures += 1
                logger.exception(
                    "trend_scan_stock_failed",
                    extra={
                        **context,
                        **details,
                        "error_code": exc.code,
                        "exception_type": failure.exception_type,
                        "exception_message": details.get("exception_message", exc.code),
                    },
                )
            else:
                assert bars
                if fetched:
                    self.local.save_bars(stock.symbol, trade_date, bars)
                sources.update(bar.source for bar in bars)
                successful += 1
                consecutive_failures = 0
                candidate, exclusion = self._candidate(stock, bars, completed, required)
                if exclusion:
                    exclusions[stock.symbol] = exclusion
                if candidate:
                    results.append(candidate)
                    inputs[stock.symbol] = bars
            run = run.model_copy(
                update={
                    "successful_count": successful,
                    "failed_count": len(failures),
                    "failed_symbols": list(failures),
                    "candidate_count": len(results),
                    "strong_contraction_count": sum(
                        row.is_strong_volume_contraction for row in results
                    ),
                    "exclusions": dict(exclusions),
                    "data_as_of": self.clock(),
                    "market_data_source": ",".join(sorted(sources)) or run.market_data_source,
                }
            )
            self.local.checkpoint(run, candidate, bars if candidate and bars else [])
            remember(run)
            if index % 10 == 0:
                try:
                    self.publisher.publish()
                except Exception:
                    logger.warning("trend_progress_export_failed", extra={"run_id": str(run.id)})
            logger.info(
                "trend_scan_stock_completed",
                extra={
                    **context,
                    "successful": successful,
                    "failed": len(failures),
                    "candidate_count": len(results),
                },
            )
            if failures and (
                len(failures) / len(heat) >= self.config.trend_max_failure_ratio
                or consecutive_failures >= self.config.trend_max_consecutive_failures
            ):
                raise TrendError("market_data_failure_threshold")
        results.sort(
            key=lambda row: (not row.is_strong_volume_contraction, row.volume_ratio, row.heat_rank)
        )
        return (
            run.model_copy(
                update={
                    "status": "completed_with_warnings" if failures else "success",
                    "finished_at": self.clock(),
                    "data_as_of": self.clock(),
                }
            ),
            results,
            inputs,
        )

    def _candidate(
        self, stock: Heat, bars: list[Bar], completed: list[date], required: int
    ) -> tuple[Candidate | None, str | None]:
        if len(bars) < self.config.trend_min_days + self.config.trend_baseline_volume_days:
            return None, "insufficient_history"
        if [bar.trade_date for bar in bars[-required:]] != completed[-min(required, len(bars)) :]:
            return None, "nonconsecutive_sessions"
        trend = detect_trend(bars, self.config)
        if trend is None:
            return None, None
        try:
            volume = analyze_volume(bars, trend, self.config)
        except TrendError as exc:
            return None, exc.code
        return (Candidate(**stock.model_dump(), **trend.model_dump(), **volume.model_dump()), None)

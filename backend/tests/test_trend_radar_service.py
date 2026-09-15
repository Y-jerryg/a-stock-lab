from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, date, datetime, timedelta
from uuid import UUID

import pytest

from a_stock_lab.features.trend_radar.application.service import TrendRadarScanService, rank_heat
from a_stock_lab.features.trend_radar.application.worker import TrendWorker
from a_stock_lab.features.trend_radar.config import TrendSettings
from a_stock_lab.features.trend_radar.domain.models import (
    Bar,
    Candidate,
    Heat,
    ListedStock,
    ScanRun,
    TrendError,
)
from test_trend_radar_domain import bars_for

NOW = datetime(2026, 1, 29, 8, 0, tzinfo=UTC)


class Memory:
    def __init__(self) -> None:
        self.runs: list[ScanRun] = []
        self.published: list[Candidate] = []
        self.beats: list[str] = []
        self.results: dict[UUID, list[Candidate]] = {}
        self.inputs: dict[UUID, dict[str, list[Bar]]] = {}
        self.claims: set[date] = set()
        self.heat = [
            Heat(
                symbol="600000",
                name="Test",
                heat_score=100,
                heat_source="test",
                data_date=NOW.date(),
                fetched_at=NOW,
            )
        ]
        self.bars = [
            bar.model_copy(update={"fetched_at": NOW})
            for bar in bars_for([100 - i for i in range(9)])
        ]
        self.busy = False
        self.failure = False
        self.triggers: list[str] = []

    @contextmanager
    def lock(self) -> Iterator[None]:
        yield

    def save_run(self, run: ScanRun) -> None:
        self.runs.append(run)

    def save_heat(self, run_id: UUID, heat: list[Heat]) -> None:
        assert heat[0].heat_rank == 1

    def load_bars(self, symbol: str, vintage: date, now: datetime) -> list[Bar] | None:
        return None

    def save_bars(self, symbol: str, vintage: date, bars: list[Bar]) -> None:
        pass

    def checkpoint(self, run: ScanRun, candidate: Candidate | None, bars: list[Bar]) -> None:
        self.save_run(run)
        if candidate:
            self.results.setdefault(run.id, []).append(candidate)

    def complete(
        self, run: ScanRun, results: list[Candidate], inputs: dict[str, list[Bar]]
    ) -> None:
        self.runs.append(run)
        self.results[run.id] = results
        self.inputs[run.id] = inputs

    def begin(self, run: ScanRun) -> bool:
        self.triggers.append(run.trigger_type)
        if self.busy or (run.trigger_type == "scheduled" and run.trade_date in self.claims):
            return False
        if run.trigger_type == "scheduled" and run.trade_date:
            self.claims.add(run.trade_date)
        self.runs.append(run)
        return True

    def public_runs(self) -> list[ScanRun]:
        return list({run.id: run for run in self.runs}.values())

    def public_results(self, run_id: UUID) -> list[Candidate]:
        return self.results[run_id]

    def candidate_inputs(self, run_id: UUID) -> dict[str, list[Bar]]:
        return self.inputs[run_id]

    def publish(self) -> None:
        runs = [
            run
            for run in self.public_runs()
            if run.status in {"success", "completed_with_warnings"}
        ]
        if runs:
            self.published = self.results[runs[-1].id]

    def write(self, now: datetime, state: str) -> None:
        self.beats.append(state)

    def fetch_heat(self) -> list[Heat]:
        return self.heat

    def fetch_universe(self) -> list[ListedStock]:
        return [ListedStock(symbol=row.symbol, name=row.name, fetched_at=NOW) for row in self.heat]

    def fetch_bars(self, symbol: str, start: date, end: date) -> list[Bar]:
        if self.failure:
            raise TrendError("provider_error")
        return self.bars

    def sessions(self, today: date) -> list[date]:
        # A fixture calendar; no production weekday inference.
        return [date(2025, 12, 1) + timedelta(days=i) for i in range(100)]


def service(memory: Memory, now: datetime = NOW) -> TrendRadarScanService:
    return TrendRadarScanService(
        config=TrendSettings(_env_file=None, trend_top_n=1),
        universe=memory,
        heat=memory,
        market=memory,
        calendar=memory,
        local=memory,
        publisher=memory,
        clock=lambda: now,
    )


@pytest.mark.parametrize("trigger", ["scheduled", "cli"])
def test_shared_pipeline(trigger: str) -> None:
    memory = Memory()
    run = service(memory).scan(trigger)  # type: ignore[arg-type]
    assert run and run.status == "success" and run.candidate_count == 1
    assert memory.published[0].trend_days == 9
    assert "top_n" in run.configuration_snapshot


def test_all_a_stocks_are_scanned_including_outside_top_n_and_without_attention(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    memory = Batch(set())
    listed = memory.fetch_universe()
    memory.heat = memory.heat[:2]  # 298 listed stocks have no attention observation.
    monkeypatch.setattr(memory, "fetch_universe", lambda: listed)
    scanner = service(memory)  # top_n = 1 is a display threshold, not a scan limit.
    run = scanner.scan("cli")
    assert run and run.status == "success"
    assert run.requested_count == run.successful_count == run.candidate_count == 300
    assert run.heat_universe_count == 2
    assert len(memory.called) == 300
    assert memory.published[0].heat_rank == 1
    assert any(row.heat_rank == 2 for row in memory.published)
    missing = next(row for row in memory.published if row.symbol == "600002")
    assert missing.heat_rank == 0 and missing.heat_score is None and missing.data_date is None
    assert run.configuration_snapshot["universe_scope"] == "all_a"
    assert run.configuration_snapshot["rule_version"] == 2


def test_new_rule_records_price_exclusions(monkeypatch: pytest.MonkeyPatch) -> None:
    memory = Memory()
    memory.bars[-1] = memory.bars[-2].model_copy(update={"trade_date": NOW.date()})
    run = service(memory).scan("cli")
    assert run and run.status == "success" and run.candidate_count == 0
    assert run.exclusions == {"600000": "no_matching_downtrend"}


@pytest.mark.parametrize("problem", ["stale", "missing", "duplicate", "provider", "heat_date"])
def test_failure_does_not_replace_publication(problem: str) -> None:
    memory = Memory()
    scanner = service(memory)
    assert scanner.scan("cli")
    previous = memory.published
    if problem in {"stale", "missing"}:
        memory.bars = memory.bars[:-1]
    elif problem == "duplicate":
        memory.bars += memory.bars[-1:]
    elif problem == "heat_date":
        memory.heat = [memory.heat[0].model_copy(update={"data_date": date(2025, 1, 1)})]
    else:
        memory.failure = True
    run = scanner.scan("cli")
    assert run and run.status == "failed"
    assert memory.published is previous


def test_rank_universe_not_provider_order() -> None:
    heat = Memory().heat
    with pytest.raises(TrendError, match="insufficient_heat_universe"):
        rank_heat(heat, 300)
    with pytest.raises(TrendError, match="duplicate_heat_symbols"):
        rank_heat(heat * 300, 300)
    result = rank_heat(
        [*heat, heat[0].model_copy(update={"symbol": "920001", "heat_score": 200})], 1
    )
    assert result[0].symbol == "920001" and result[0].heat_rank == 1


def test_busy_does_not_fetch() -> None:
    memory = Memory()
    memory.busy = True
    memory.failure = True
    assert service(memory).scan("cli") is None
    assert not memory.runs


def test_intraday_uses_previous_completed_session() -> None:
    memory = Memory()
    memory.bars = memory.bars[:-1]
    memory.heat = [memory.heat[0].model_copy(update={"data_date": date(2026, 1, 28)})]
    run = service(memory, datetime(2026, 1, 29, 4, tzinfo=UTC)).scan("cli")
    assert run and run.trade_date == date(2026, 1, 28)


def test_weekend_and_holiday_use_last_exchange_session() -> None:
    class Closed(Memory):
        def sessions(self, today: date) -> list[date]:
            return [
                day
                for day in super().sessions(today)
                if day <= NOW.date() or day >= date(2026, 2, 3)
            ]

    for today in (datetime(2026, 2, 1, 8, tzinfo=UTC), datetime(2026, 2, 2, 8, tzinfo=UTC)):
        run = service(Closed(), today).scan("cli")
        assert run and run.status == "success" and run.trade_date == NOW.date()


class Batch(Memory):
    def __init__(self, failures: set[str]) -> None:
        super().__init__()
        self.heat = [
            self.heat[0].model_copy(update={"symbol": f"600{i:03}", "heat_score": 300 - i})
            for i in range(300)
        ]
        self.failures = failures
        self.called: list[str] = []

    def fetch_bars(self, symbol: str, start: date, end: date) -> list[Bar]:
        self.called.append(symbol)
        if symbol in self.failures:
            raise TrendError(
                "provider_error",
                details={
                    "provider": "test_daily_qfq",
                    "attempt": 3,
                    "exception_type": "ConnectionError",
                    "exception_message": "upstream unavailable",
                },
            )
        return [bar.model_copy(update={"symbol": symbol}) for bar in self.bars]


def test_three_stock_failures_keep_297_results_and_detailed_logs(
    caplog: pytest.LogCaptureFixture,
) -> None:
    memory = Batch({"600000", "600127", "600299"})
    scanner = service(memory)
    scanner.config = TrendSettings(_env_file=None)
    run = scanner.scan("cli")
    assert run and run.status == "completed_with_warnings"
    assert (run.requested_count, run.successful_count, run.failed_count) == (300, 297, 3)
    assert len(memory.called) == 300 and len(memory.published) == 297
    assert {row.symbol for row in run.failed_symbols} == memory.failures
    log = next(row for row in caplog.records if row.message == "trend_scan_stock_failed")
    fields = log.__dict__
    assert fields["symbol"] == "600000" and fields["stock_number"] == 1 and fields["total"] == 300
    assert fields["provider"] == "test_daily_qfq" and fields["attempt"] == 3
    assert fields["exception_type"] == "ConnectionError" and log.exc_info
    assert memory.results[run.id][126].symbol == "600128"


def test_widespread_failure_stops_and_keeps_prior_checkpoints() -> None:
    memory = Batch({f"600{i:03}" for i in range(128, 300)})
    scanner = service(memory)
    scanner.config = TrendSettings(_env_file=None)
    run = scanner.scan("cli")
    assert run and run.status == "failed" and run.error_message == "market_data_failure_threshold"
    assert run.successful_count == 128 and run.failed_count == 10
    assert run.candidate_count == len(memory.results[run.id]) == 128
    assert run.heat_universe_count == run.requested_count == 300
    assert run.trade_date == NOW.date() and run.data_as_of == NOW
    assert len(memory.called) == 138


def test_scattered_failures_use_requested_universe_for_threshold() -> None:
    memory = Batch({f"600{i:03}" for i in range(0, 300, 4)})
    scanner = service(memory)
    scanner.config = TrendSettings(_env_file=None)
    run = scanner.scan("cli")
    assert run and run.status == "failed"
    assert run.failed_count == 60 and run.successful_count == 177
    assert len(memory.called) == 237


def test_cli_partial_completion_is_a_successful_command(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    import json

    from a_stock_lab.features.trend_radar import cli

    memory = Batch({"600002"})
    memory.heat = memory.heat[:6]
    scanner = service(memory)
    scanner.config = scanner.config.model_copy(update={"trend_top_n": 6})
    monkeypatch.setattr(cli, "create_service", lambda: scanner)
    monkeypatch.setattr(cli, "configure_logging", lambda _: None)
    monkeypatch.setattr("sys.argv", ["trend-radar", "scan"])
    cli.main()  # Must not raise SystemExit(1), which the desktop script treats as global failure.
    assert json.loads(capsys.readouterr().out)["status"] == "completed_with_warnings"


def test_database_failure_is_global_not_a_skipped_stock(monkeypatch: pytest.MonkeyPatch) -> None:
    memory = Batch(set())
    scanner = service(memory)
    scanner.config = TrendSettings(_env_file=None)

    def broken_cache(symbol: str, vintage: date, now: datetime) -> None:
        if symbol == "600001":
            raise RuntimeError("database unavailable")

    monkeypatch.setattr(memory, "load_bars", broken_cache)
    run = scanner.scan("cli")
    assert run and run.status == "failed" and run.failed_count == 0
    assert run.successful_count == run.candidate_count == 1
    assert memory.called == ["600000"]


def test_worker_continues_and_schedules_with_same_service() -> None:
    memory = Memory()
    memory.failure = True
    worker = TrendWorker(service(memory), memory, clock=lambda: NOW)
    worker.tick()
    memory.failure = False
    worker.tick()
    assert memory.triggers == ["scheduled", "scheduled"]
    assert not memory.published  # A failed scheduled attempt is not retried every poll.
    assert service(memory).scan("cli")
    assert memory.published


def test_calendar_holiday_prevents_scheduled_scan() -> None:
    class Holiday(Memory):
        def sessions(self, today: date) -> list[date]:
            return [day for day in super().sessions(today) if day != today]

    memory = Holiday()
    TrendWorker(service(memory), memory, clock=lambda: NOW).tick()
    assert memory.triggers == []


def test_worker_loop_recovers_and_stops_cleanly(monkeypatch: pytest.MonkeyPatch) -> None:
    memory = Memory()
    scanner = service(memory)
    scanner.config = scanner.config.model_copy(update={"trend_schedule_poll_seconds": 0.001})
    worker = TrendWorker(scanner, memory)
    calls: list[int] = []

    def tick() -> None:
        calls.append(1)
        if len(calls) == 1:
            raise TrendError("provider_error")
        worker.stop.set()

    monkeypatch.setattr(worker, "tick", tick)
    worker.run()
    assert len(calls) == 2

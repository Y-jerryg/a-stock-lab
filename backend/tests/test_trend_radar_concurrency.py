import os
import subprocess
import time
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from datetime import date
from multiprocessing.connection import Connection
from threading import Barrier, Lock, get_ident
from typing import Any
from unittest.mock import Mock

import pytest

from a_stock_lab.features.trend_radar.adapters.process_pool import (
    ProviderProcessPool,
    ProviderWorker,
)
from a_stock_lab.features.trend_radar.application.collection import collect_bounded
from a_stock_lab.features.trend_radar.application.diagnostics import stock_context
from a_stock_lab.features.trend_radar.domain.models import Bar
from test_trend_radar_service import Batch, service


def protocol_worker(connection: Connection) -> None:
    """Real child process; no network. Exercise kill/restart and message isolation."""
    while True:
        try:
            action, args = connection.recv()
        except EOFError:
            return
        if action == "hang":
            time.sleep(30)
        if action == "crash":
            os._exit(7)
        if action == "wait":
            time.sleep(0.05)
        if action == "error":
            connection.send({"error": {"exception_type": "ConnectionError"}})
        else:
            connection.send({"rows": [{"pid": os.getpid(), "args": args}]})


@pytest.mark.parametrize("failure", ["hang", "crash"])
def test_dead_worker_is_killed_and_next_request_starts_fresh(failure: str) -> None:
    worker = ProviderWorker(protocol_worker)
    try:
        first = worker.request("pid", (), 10)[0]["pid"]
        with pytest.raises(subprocess.SubprocessError):
            worker.request(failure, (), 0.2)
        assert worker.process is None and worker.connection is None
        second = worker.request("pid", (), 10)[0]["pid"]
        assert first != second
    finally:
        worker.close()
    assert worker.process is None


def test_process_reuse_error_isolation_and_periodic_recycle() -> None:
    worker = ProviderWorker(protocol_worker, max_requests=3)
    try:
        first = worker.request("pid", (), 10)[0]["pid"]
        with pytest.raises(subprocess.CalledProcessError):
            worker.request("error", (), 10)
        assert worker.request("pid", (), 10)[0]["pid"] == first
        assert worker.request("pid", (), 10)[0]["pid"] != first
    finally:
        worker.close()


def test_four_processes_are_reused_without_crossed_replies_and_all_close() -> None:
    pool = ProviderProcessPool(4, protocol_worker)
    barrier = Barrier(4)

    def call(index: int) -> dict[str, Any]:
        barrier.wait(timeout=10)
        return pool.request("wait", (str(index),), 10)[0]  # type: ignore[no-any-return]

    try:
        with ThreadPoolExecutor(max_workers=4) as executor:
            results = list(executor.map(call, range(12)))
        assert len({row["pid"] for row in results}) == 4
        assert [row["args"] for row in results] == [(str(i),) for i in range(12)]
    finally:
        pool.close()
    assert all(worker.process is None for worker in pool.workers)


def test_bounded_collection_never_submits_the_whole_universe_on_abort() -> None:
    called: list[int] = []
    lock = Lock()

    def fetch(index: int, item: int) -> int:
        with lock:
            called.append(item)
        return item

    with closing(collect_bounded(list(range(5564)), fetch, 4)) as items:
        _, _, future = next(items)
        assert future.result() == 0
    assert 1 <= len(called) <= 4


def test_parallel_scan_matches_serial_and_writes_only_on_coordinator() -> None:
    class Parallel(Batch):
        def __init__(self) -> None:
            super().__init__({"600002"})
            self.heat = self.heat[:12]
            self.barrier = Barrier(4)
            self.counter_lock = Lock()
            self.active = self.peak = 0
            self.owner = get_ident()

        def fetch_bars(self, symbol: str, start: date, end: date) -> list[Bar]:
            assert stock_context()["symbol"] == symbol
            with self.counter_lock:
                self.active += 1
                self.peak = max(self.peak, self.active)
            try:
                if int(symbol[-3:]) < 4:
                    self.barrier.wait(timeout=5)
                return super().fetch_bars(symbol, start, end)
            finally:
                with self.counter_lock:
                    self.active -= 1

        def save_bars(self, symbol: str, vintage: date, bars: list[Bar]) -> None:
            assert get_ident() == self.owner

    memory = Parallel()
    parallel = service(memory).scan("cli")
    assert parallel and parallel.status == "completed_with_warnings"
    assert memory.peak == 4 and memory.active == 0
    assert (parallel.successful_count, parallel.failed_count) == (11, 1)
    serial_memory = Batch({"600002"})
    serial_memory.heat = serial_memory.heat[:12]
    scanner = service(serial_memory)
    scanner.config = scanner.config.model_copy(update={"trend_fetch_workers": 1})
    serial = scanner.scan("cli")
    assert serial and memory.results[parallel.id] == serial_memory.results[serial.id]


def test_parallel_threshold_retains_processed_work_and_bounds_inflight_calls() -> None:
    memory = Batch({f"600{i:03}" for i in range(128, 300)})
    run = service(memory).scan("cli")
    assert run and run.status == "failed" and run.error_message == "market_data_failure_threshold"
    assert (run.successful_count, run.failed_count, run.candidate_count) == (128, 10, 128)
    assert 138 <= len(memory.called) <= 141
    assert len(memory.results[run.id]) == 128


@pytest.mark.parametrize("failed", [False, True])
def test_scan_always_closes_provider_resources(
    failed: bool,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    memory = Batch({"600000"} if failed else set())
    memory.heat = memory.heat[:1]
    close = Mock()
    monkeypatch.setattr(memory, "close", close)
    run = service(memory).scan("cli")
    assert run and (run.status == "failed") == failed
    close.assert_called_once()

import logging
from datetime import datetime, timedelta
from pathlib import Path
from threading import Event
from typing import Any
from uuid import UUID

import pytest

from a_stock_lab.core.time import MARKET_TIME_ZONE
from a_stock_lab.features.tail_radar.adapters.worker_heartbeat import JsonWorkerHeartbeatStore
from a_stock_lab.features.tail_radar.application.scheduling_models import (
    TailRadarScheduleStatus,
    TailRadarWorkerHeartbeat,
)
from a_stock_lab.features.tail_radar.application.worker import TailRadarWorker

NOW = datetime(2026, 8, 31, 14, 29, tzinfo=MARKET_TIME_ZONE)
WORKER_ID = UUID("40000000-0000-4000-8000-000000000040")


class FakeScheduler:
    def __init__(self) -> None:
        self.calls = 0

    def tick(self) -> Any:
        self.calls += 1
        return type("Schedule", (), {"status": TailRadarScheduleStatus.SCHEDULED})()


class FailingScheduler:
    def tick(self) -> Any:
        raise RuntimeError("provider unavailable")


class MemoryHeartbeatStore:
    def __init__(self) -> None:
        self.writes: list[TailRadarWorkerHeartbeat] = []

    def write(self, heartbeat: TailRadarWorkerHeartbeat) -> None:
        self.writes.append(heartbeat)


def test_worker_honors_an_already_requested_graceful_shutdown() -> None:
    scheduler = FakeScheduler()
    heartbeats = MemoryHeartbeatStore()
    worker = TailRadarWorker(
        scheduler=scheduler,  # type: ignore[arg-type]
        heartbeat_store=heartbeats,
        poll_interval_seconds=5,
        clock=lambda: NOW,
        worker_id=WORKER_ID,
    )
    stopped = Event()
    stopped.set()

    worker.run(stopped)

    assert scheduler.calls == 0
    assert [heartbeat.state for heartbeat in heartbeats.writes] == ["starting", "stopped"]


def test_json_heartbeat_health_detects_live_stale_and_stopped_workers(
    tmp_path: Path,
) -> None:
    store = JsonWorkerHeartbeatStore(tmp_path / "worker" / "heartbeat.json")
    live = TailRadarWorkerHeartbeat(
        worker_id=WORKER_ID,
        state="running",
        updated_at=NOW,
        last_schedule_status=TailRadarScheduleStatus.SCHEDULED,
    )
    store.write(live)

    assert store.read() == live
    assert store.is_live(now=NOW + timedelta(seconds=20), maximum_age=timedelta(seconds=30))
    assert not store.is_live(now=NOW + timedelta(seconds=31), maximum_age=timedelta(seconds=30))

    store.write(live.model_copy(update={"state": "stopped"}))
    assert not store.is_live(now=NOW, maximum_age=timedelta(seconds=30))


def test_worker_logs_failures_and_remains_live_for_a_later_poll(
    caplog: pytest.LogCaptureFixture,
) -> None:
    heartbeats = MemoryHeartbeatStore()
    worker = TailRadarWorker(
        scheduler=FailingScheduler(),  # type: ignore[arg-type]
        heartbeat_store=heartbeats,
        poll_interval_seconds=5,
        clock=lambda: NOW,
        worker_id=WORKER_ID,
    )

    with caplog.at_level(logging.ERROR):
        heartbeat = worker.run_once()

    assert heartbeat.state == "degraded"
    assert heartbeat.last_error_code == "RuntimeError"
    assert "tail_radar_worker_tick_failed" in caplog.messages

from collections.abc import Callable
from datetime import datetime
from threading import Event
from typing import Protocol
from uuid import UUID, uuid4

from a_stock_lab.core.logging import get_logger
from a_stock_lab.core.time import as_market_timezone, now_in_market_timezone
from a_stock_lab.features.tail_radar.application.scheduling_models import (
    TailRadarScheduleStatus,
    TailRadarWorkerHeartbeat,
)
from a_stock_lab.features.tail_radar.application.scheduling_service import (
    TailRadarScheduledExecutionService,
)

logger = get_logger(__name__)


class TailRadarWorker:
    """Interruptible polling process; schedule semantics remain in the application service."""

    def __init__(
        self,
        *,
        scheduler: TailRadarScheduledExecutionService,
        heartbeat_store: "WorkerHeartbeatStore",
        poll_interval_seconds: float,
        clock: Callable[[], datetime] = now_in_market_timezone,
        worker_id: UUID | None = None,
    ) -> None:
        if poll_interval_seconds <= 0:
            raise ValueError("worker poll interval must be positive")
        self._scheduler = scheduler
        self._heartbeat_store = heartbeat_store
        self._poll_interval_seconds = poll_interval_seconds
        self._clock = clock
        self._worker_id = worker_id or uuid4()

    @property
    def worker_id(self) -> UUID:
        return self._worker_id

    def run(self, stop_event: Event) -> None:
        self._write_heartbeat(state="starting")
        try:
            while not stop_event.is_set():
                try:
                    schedule = self._scheduler.tick()
                except Exception as exc:
                    self._log_tick_failure(exc)
                    self._write_heartbeat(
                        state="degraded",
                        error_code=_error_code(exc),
                    )
                else:
                    self._write_heartbeat(
                        state="running",
                        schedule_status=schedule.status,
                    )
                stop_event.wait(self._poll_interval_seconds)
        finally:
            self._write_heartbeat(state="stopped")

    def run_once(self) -> TailRadarWorkerHeartbeat:
        try:
            schedule = self._scheduler.tick()
        except Exception as exc:
            self._log_tick_failure(exc)
            heartbeat = self._heartbeat(
                state="degraded",
                error_code=_error_code(exc),
            )
        else:
            heartbeat = self._heartbeat(
                state="running",
                schedule_status=schedule.status,
            )
        self._heartbeat_store.write(heartbeat)
        return heartbeat

    def _log_tick_failure(self, error: Exception) -> None:
        logger.exception(
            "tail_radar_worker_tick_failed",
            extra={
                "feature": "tail_radar",
                "worker_id": str(self._worker_id),
                "error_code": _error_code(error),
                "error_type": type(error).__name__,
            },
        )

    def _write_heartbeat(
        self,
        *,
        state: str,
        schedule_status: TailRadarScheduleStatus | None = None,
        error_code: str | None = None,
    ) -> None:
        self._heartbeat_store.write(
            self._heartbeat(
                state=state,
                schedule_status=schedule_status,
                error_code=error_code,
            )
        )

    def _heartbeat(
        self,
        *,
        state: str,
        schedule_status: TailRadarScheduleStatus | None = None,
        error_code: str | None = None,
    ) -> TailRadarWorkerHeartbeat:
        return TailRadarWorkerHeartbeat(
            worker_id=self._worker_id,
            state=state,
            updated_at=as_market_timezone(self._clock()),
            last_schedule_status=schedule_status,
            last_error_code=error_code,
        )


def _error_code(error: Exception) -> str:
    code = getattr(error, "code", None)
    return code if isinstance(code, str) and code else type(error).__name__


class WorkerHeartbeatStore(Protocol):
    def write(self, heartbeat: TailRadarWorkerHeartbeat) -> None: ...

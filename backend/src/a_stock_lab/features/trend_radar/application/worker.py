import logging
from collections.abc import Callable
from datetime import datetime
from threading import Event, Thread

from a_stock_lab.features.trend_radar.application.contracts import WorkerHeartbeat
from a_stock_lab.features.trend_radar.application.service import (
    SHANGHAI,
    TrendRadarScanService,
    utc_now,
)
from a_stock_lab.features.trend_radar.domain.models import ScanBusyError

logger = logging.getLogger(__name__)


class TrendWorker:
    def __init__(
        self,
        service: TrendRadarScanService,
        heartbeat: WorkerHeartbeat,
        clock: Callable[[], datetime] = utc_now,
    ) -> None:
        self.service, self.clock = service, clock
        self.heartbeat = heartbeat
        self.stop = Event()

    def tick(self) -> None:
        service = self.service
        now = self.clock().astimezone(SHANGHAI)
        if now.time() >= service.config.trend_schedule_time:
            if now.date() in service.calendar.sessions(now.date()):
                service.scan("scheduled")

    def run(self) -> None:
        logger.info("trend_worker_started")
        pulse = Thread(target=self._heartbeat, daemon=True)
        pulse.start()
        try:
            while not self.stop.is_set():
                try:
                    self.tick()
                except ScanBusyError:
                    pass
                except Exception:
                    logger.error("trend_worker_iteration_failed")
                self.stop.wait(self.service.config.trend_schedule_poll_seconds)
        finally:
            self.service.market.close()
            self.stop.set()
            pulse.join(timeout=5)
            self.heartbeat.write(self.clock(), "stopped")
            logger.info("trend_worker_stopped")

    def _heartbeat(self) -> None:
        while not self.stop.is_set():
            try:
                self.heartbeat.write(self.clock(), "running")
            except Exception:
                logger.warning("trend_worker_heartbeat_failed")
            self.stop.wait(self.service.config.trend_heartbeat_seconds)

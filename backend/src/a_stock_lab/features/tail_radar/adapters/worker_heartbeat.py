import json
import os
from datetime import datetime, timedelta
from pathlib import Path
from uuid import UUID

from a_stock_lab.core.time import as_market_timezone
from a_stock_lab.features.tail_radar.application.scheduling_models import TailRadarWorkerHeartbeat
from a_stock_lab.features.tail_radar.domain.errors import TailRadarSchedulingError


class JsonWorkerHeartbeatStore:
    """Atomic, secret-free liveness state for container health checks."""

    def __init__(self, path: Path) -> None:
        self._path = path

    @property
    def path(self) -> Path:
        return self._path

    def write(self, heartbeat: TailRadarWorkerHeartbeat) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self._path.with_name(f".{self._path.name}.{heartbeat.worker_id}.tmp")
        try:
            temporary.write_text(
                json.dumps(heartbeat.model_dump(mode="json"), ensure_ascii=False),
                encoding="utf-8",
            )
            os.replace(temporary, self._path)
        except OSError as exc:
            try:
                temporary.unlink(missing_ok=True)
            except OSError:
                pass
            raise TailRadarSchedulingError("worker heartbeat could not be written") from exc

    def read(self) -> TailRadarWorkerHeartbeat | None:
        try:
            if not self._path.exists():
                return None
            return TailRadarWorkerHeartbeat.model_validate_json(
                self._path.read_text(encoding="utf-8")
            )
        except (OSError, ValueError) as exc:
            raise TailRadarSchedulingError("worker heartbeat could not be read") from exc

    def is_live(
        self,
        *,
        now: datetime,
        maximum_age: timedelta,
        expected_worker_id: UUID | None = None,
    ) -> bool:
        heartbeat = self.read()
        if heartbeat is None or heartbeat.state == "stopped":
            return False
        if expected_worker_id is not None and heartbeat.worker_id != expected_worker_id:
            return False
        observed = as_market_timezone(now)
        return timedelta(0) <= observed - heartbeat.updated_at <= maximum_age

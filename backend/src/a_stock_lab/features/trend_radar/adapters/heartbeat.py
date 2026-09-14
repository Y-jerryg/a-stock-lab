import json
from datetime import datetime
from pathlib import Path

from a_stock_lab.features.trend_radar.adapters.static_publication import atomic_write


class LocalWorkerHeartbeat:
    def __init__(self, path: Path) -> None:
        self.path = path

    def write(self, now: datetime, state: str) -> None:
        atomic_write(self.path, json.dumps({"updated_at": now.isoformat(), "state": state}))

    def healthy(self, now: datetime) -> bool:
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            updated = datetime.fromisoformat(data["updated_at"])
            return bool(
                updated.tzinfo
                and data["state"] == "running"
                and 0 <= (now - updated).total_seconds() <= 60
            )
        except (OSError, ValueError, TypeError, KeyError):
            return False

from datetime import UTC, date, datetime, timedelta
from pathlib import Path

from pydantic import ValidationError

from a_stock_lab.features.tail_radar.application.daily_chart import DailyChart


class FileChartStore:
    """Bounded, expendable quote cache; not an immutable research artifact."""

    def __init__(self, root: Path) -> None:
        self.root = root / "tail-daily-charts"

    def _path(self, symbol: str, cutoff: date) -> Path:
        if len(symbol) != 6 or not symbol.isascii() or not symbol.isdigit():
            raise ValueError("Invalid symbol")
        return self.root / f"{symbol}-{cutoff.isoformat()}.json"

    def read(self, symbol: str, cutoff: date) -> DailyChart | None:
        try:
            result = DailyChart.model_validate_json(
                self._path(symbol, cutoff).read_text(encoding="utf-8")
            )
        except (OSError, ValidationError):
            return None
        if result.symbol != symbol or result.cutoff != cutoff:
            return None
        age = datetime.now(UTC) - result.fetched_at
        if not timedelta(0) <= age < timedelta(days=1):
            return None
        return result

    def write(self, chart: DailyChart) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        path = self._path(chart.symbol, chart.cutoff)
        temporary = path.with_suffix(".tmp")
        temporary.write_text(chart.model_dump_json(), encoding="utf-8")
        temporary.replace(path)
        # Keep a bounded disk cache even when visitors browse many historical candidates.
        files = sorted(
            self.root.glob("*.json"), key=lambda item: item.stat().st_mtime, reverse=True
        )
        before = (datetime.now(UTC) - timedelta(days=30)).timestamp()
        for index, item in enumerate(files):
            if index >= 6000 or item.stat().st_mtime < before:
                item.unlink(missing_ok=True)

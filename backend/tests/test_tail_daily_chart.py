from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from unittest.mock import Mock

import pytest

from a_stock_lab.features.tail_radar.adapters.daily_chart import FileChartStore
from a_stock_lab.features.tail_radar.application.daily_chart import (
    ChartBusyError,
    DailyChartService,
)
from a_stock_lab.features.trend_radar.domain.models import Bar, TrendError


def bar(day: date) -> Bar:
    return Bar(
        symbol="600000",
        trade_date=day,
        open=10,
        high=11,
        low=9,
        close=10,
        volume=1234,
        amount=1234000,
        fetched_at=datetime.now(UTC),
    )


def test_daily_chart_cutoff_cache_and_limits(tmp_path: Path) -> None:
    # 00:30 UTC is the morning in Shanghai. Never expose the unfinished same-day bar.
    as_of = datetime(2026, 9, 17, 0, 30, tzinfo=UTC)
    provider = Mock()
    provider.fetch_bars.return_value = [
        bar(date(2026, 9, 17) - timedelta(days=i)) for i in range(200)
    ]
    store = FileChartStore(tmp_path)
    service = DailyChartService(provider, store)
    result = service.read("600000", as_of)
    assert result.cutoff == date(2026, 9, 16)
    assert len(result.bars) == 120
    assert result.bars[-1].trade_date == date(2026, 9, 16)
    assert result.bars[0].trade_date < result.bars[-1].trade_date
    assert result.purpose == "reference_only"
    assert service.read("600000", as_of) == result
    provider.fetch_bars.assert_called_once()
    provider.close.assert_called_once()
    # Expired observations are refreshed; an interrupted/corrupt write is a cache miss.
    path = next((tmp_path / "tail-daily-charts").glob("*.json"))
    path.write_text(
        result.model_copy(
            update={"fetched_at": datetime.now(UTC) - timedelta(days=2)}
        ).model_dump_json()
    )
    assert store.read("600000", result.cutoff) is None
    path.write_text("invalid")
    assert store.read("600000", result.cutoff) is None


def test_failure_closes_provider_and_releases_capacity(tmp_path: Path) -> None:
    provider = Mock()
    provider.fetch_bars.side_effect = TrendError("provider_error")
    service = DailyChartService(provider, FileChartStore(tmp_path))
    with pytest.raises(TrendError):
        service.read("600000", datetime.now(UTC))
    provider.close.assert_called_once()
    assert not service.lock.locked()
    with service.lock, pytest.raises(ChartBusyError):
        service.read("600000", datetime.now(UTC))
    provider.fetch_bars.assert_called_once()

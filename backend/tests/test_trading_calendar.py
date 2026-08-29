from datetime import date
from typing import ClassVar, Literal

import pytest

from a_stock_lab.shared.market_data.adapters.akshare_calendar import AkShareTradingCalendar
from a_stock_lab.shared.market_data.errors import (
    TradingCalendarInvalidResponseError,
    TradingCalendarOutOfRangeError,
)


class FakeFrame:
    columns: ClassVar[list[object]] = ["trade_date"]

    def __init__(self, values: list[object]) -> None:
        self._values = values

    def to_dict(self, *, orient: Literal["records"]) -> list[dict[object, object]]:
        assert orient == "records"
        return [{"trade_date": value} for value in self._values]


def test_calendar_uses_provider_dates_and_caches_the_result() -> None:
    calls = 0

    def fetch() -> FakeFrame:
        nonlocal calls
        calls += 1
        return FakeFrame([date(2026, 9, 30), "2026-10-09"])

    calendar = AkShareTradingCalendar(fetcher=fetch)

    assert calendar.resolve(date(2026, 9, 30)).is_trading_day is True
    assert calendar.resolve(date(2026, 10, 1)).is_trading_day is False
    assert calls == 1


def test_calendar_rejects_dates_outside_authoritative_coverage() -> None:
    calendar = AkShareTradingCalendar(
        fetcher=lambda: FakeFrame([date(2026, 8, 28), date(2026, 8, 31)])
    )

    with pytest.raises(TradingCalendarOutOfRangeError):
        calendar.resolve(date(2026, 9, 1))


def test_calendar_rejects_malformed_provider_data() -> None:
    calendar = AkShareTradingCalendar(fetcher=lambda: FakeFrame(["not-a-date"]))

    with pytest.raises(TradingCalendarInvalidResponseError):
        calendar.resolve(date(2026, 8, 28))

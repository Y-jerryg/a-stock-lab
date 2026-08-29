from datetime import UTC, datetime

import pytest

from a_stock_lab.core.time import (
    MARKET_TIME_ZONE,
    as_market_timezone,
    now_in_market_timezone,
    require_aware,
)


def test_market_clock_is_timezone_aware_and_uses_shanghai() -> None:
    timestamp = now_in_market_timezone()

    assert timestamp.tzname() == "CST"
    assert timestamp.utcoffset() is not None


def test_naive_timestamp_is_rejected() -> None:
    with pytest.raises(ValueError, match="timezone-aware"):
        require_aware(datetime(2026, 8, 28, 14, 30))  # noqa: DTZ001


def test_aware_timestamp_is_normalized_to_market_timezone() -> None:
    timestamp = as_market_timezone(datetime(2026, 8, 28, 6, 30, tzinfo=UTC))

    assert timestamp == datetime(2026, 8, 28, 14, 30, tzinfo=MARKET_TIME_ZONE)
    assert timestamp.tzinfo == MARKET_TIME_ZONE

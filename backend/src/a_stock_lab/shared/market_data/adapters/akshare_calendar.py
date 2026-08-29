from collections.abc import Callable, Collection
from datetime import date, datetime
from typing import Literal, Protocol, cast

from requests.exceptions import RequestException, Timeout

from a_stock_lab.shared.market_data.errors import (
    TradingCalendarInvalidResponseError,
    TradingCalendarOutOfRangeError,
    TradingCalendarUnavailableError,
)
from a_stock_lab.shared.market_data.trading_calendar import TradingDay

from .akshare_common import AKSHARE_PROVIDER_ID, installed_akshare_version

_TRADE_DATE_COLUMN = "trade_date"


class _FrameLike(Protocol):
    columns: Collection[object]

    def to_dict(self, *, orient: Literal["records"]) -> list[dict[object, object]]: ...


def _fetch_live_calendar_frame() -> object:
    import akshare  # type: ignore[import-untyped]

    return akshare.tool_trade_date_hist_sina()


def _as_date(value: object) -> date:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        try:
            return date.fromisoformat(value.strip()[:10])
        except ValueError as exc:
            raise ValueError("invalid trade date") from exc
    raise ValueError("invalid trade date")


class AkShareTradingCalendar:
    """AKShare-backed A-share calendar with provider details contained in this adapter."""

    def __init__(
        self,
        *,
        fetcher: Callable[[], object] = _fetch_live_calendar_frame,
    ) -> None:
        self._fetcher = fetcher
        self._trade_dates: frozenset[date] | None = None
        self._coverage_start: date | None = None
        self._coverage_end: date | None = None

    @property
    def provider_id(self) -> str:
        return AKSHARE_PROVIDER_ID

    def resolve(self, trade_date: date) -> TradingDay:
        self._ensure_loaded()
        if self._coverage_start is None or self._coverage_end is None or self._trade_dates is None:
            raise AssertionError("calendar coverage was not initialized")
        if not self._coverage_start <= trade_date <= self._coverage_end:
            raise TradingCalendarOutOfRangeError(
                provider=self.provider_id,
                message="requested date is outside trading-calendar coverage",
            )
        return TradingDay(
            trade_date=trade_date,
            is_trading_day=trade_date in self._trade_dates,
            provider=self.provider_id,
            provider_metadata={
                "adapter": type(self).__name__,
                "akshare_version": installed_akshare_version(),
                "upstream": "Sina Finance",
                "upstream_function": "tool_trade_date_hist_sina",
                "coverage_start": self._coverage_start.isoformat(),
                "coverage_end": self._coverage_end.isoformat(),
            },
        )

    def _ensure_loaded(self) -> None:
        if self._trade_dates is not None:
            return
        try:
            raw_frame = self._fetcher()
        except (Timeout, TimeoutError) as exc:
            raise TradingCalendarUnavailableError(
                provider=self.provider_id,
                message="trading-calendar provider timed out",
            ) from exc
        except (RequestException, OSError) as exc:
            raise TradingCalendarUnavailableError(
                provider=self.provider_id,
                message="trading-calendar provider is unavailable",
            ) from exc
        except Exception as exc:
            raise TradingCalendarInvalidResponseError(
                provider=self.provider_id,
                message="trading-calendar provider returned an unreadable response",
            ) from exc

        if not hasattr(raw_frame, "columns") or not callable(getattr(raw_frame, "to_dict", None)):
            raise TradingCalendarInvalidResponseError(
                provider=self.provider_id,
                message="trading-calendar provider did not return a tabular response",
            )
        frame = cast(_FrameLike, raw_frame)
        if _TRADE_DATE_COLUMN not in {str(column) for column in frame.columns}:
            raise TradingCalendarInvalidResponseError(
                provider=self.provider_id,
                message="trading-calendar response is missing trade_date",
            )
        try:
            rows = frame.to_dict(orient="records")
            dates = frozenset(_as_date(row[_TRADE_DATE_COLUMN]) for row in rows)
        except (KeyError, TypeError, ValueError) as exc:
            raise TradingCalendarInvalidResponseError(
                provider=self.provider_id,
                message="trading-calendar response contains malformed dates",
            ) from exc
        if not dates:
            raise TradingCalendarInvalidResponseError(
                provider=self.provider_id,
                message="trading-calendar provider returned no dates",
            )
        self._trade_dates = dates
        self._coverage_start = min(dates)
        self._coverage_end = max(dates)

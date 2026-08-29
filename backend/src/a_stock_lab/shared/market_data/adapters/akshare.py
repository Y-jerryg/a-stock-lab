import math
import re
import time
from collections.abc import Callable, Collection, Mapping
from datetime import datetime
from typing import Literal, Protocol, cast

from pydantic import ValidationError
from requests.exceptions import JSONDecodeError as RequestsJSONDecodeError
from requests.exceptions import RequestException, Timeout

from a_stock_lab.core.logging import get_logger
from a_stock_lab.core.time import as_market_timezone, now_in_market_timezone
from a_stock_lab.shared.market_data.errors import (
    ProviderError,
    ProviderInvalidResponseError,
    ProviderTimeoutError,
    ProviderUnavailableError,
)
from a_stock_lab.shared.market_data.models import (
    MarketDataCapability,
    MarketSnapshotRecord,
    NormalizationIssue,
    NormalizationIssueCode,
    ProviderRetryPolicy,
    ProviderSnapshotBatch,
)
from a_stock_lab.shared.market_data.symbols import infer_a_share_exchange

from .akshare_common import AKSHARE_PROVIDER_ID, installed_akshare_version

logger = get_logger(__name__)

_SHARES_PER_LOT = 100
_SYMBOL_PATTERN = re.compile(r"^\d{6}$")
_MISSING_TEXT = frozenset({"", "-", "--", "nan", "none", "null", "<na>", "n/a"})

_COLUMNS = {
    "symbol": "代码",
    "name": "名称",
    "price": "最新价",
    "pct_change": "涨跌幅",
    "absolute_change": "涨跌额",
    "volume": "成交量",
    "amount": "成交额",
    "amplitude": "振幅",
    "high": "最高",
    "low": "最低",
    "open": "今开",
    "previous_close": "昨收",
    "volume_ratio": "量比",
    "turnover_rate": "换手率",
    "pe_dynamic": "市盈率-动态",
    "pb": "市净率",
    "total_market_cap": "总市值",
    "float_market_cap": "流通市值",
}
_NUMERIC_FIELDS = tuple(field for field in _COLUMNS if field not in {"symbol", "name"})


class _FrameLike(Protocol):
    columns: Collection[object]

    def to_dict(self, *, orient: Literal["records"]) -> list[dict[object, object]]: ...


def _fetch_live_frame() -> object:
    import akshare  # type: ignore[import-untyped]

    return akshare.stock_zh_a_spot_em()


def _optional_text(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return None if text.casefold() in _MISSING_TEXT else text


def _optional_number(value: object) -> tuple[float | None, bool]:
    if value is None:
        return None, False
    if isinstance(value, bool):
        return None, True
    if isinstance(value, str) and value.strip().casefold() in _MISSING_TEXT:
        return None, False
    try:
        number = float(str(value))
    except (TypeError, ValueError):
        return None, True
    if not math.isfinite(number):
        return None, True
    return number, False


class AkShareMarketDataProvider:
    """AKShare adapter; no SDK schema or exception escapes this module."""

    def __init__(
        self,
        *,
        retry_policy: ProviderRetryPolicy | None = None,
        fetcher: Callable[[], object] = _fetch_live_frame,
        sleeper: Callable[[float], None] = time.sleep,
        clock: Callable[[], datetime] = now_in_market_timezone,
    ) -> None:
        self._retry_policy = retry_policy or ProviderRetryPolicy()
        self._fetcher = fetcher
        self._sleeper = sleeper
        self._clock = clock

    @property
    def provider_id(self) -> str:
        return AKSHARE_PROVIDER_ID

    @property
    def capabilities(self) -> frozenset[MarketDataCapability]:
        return frozenset({MarketDataCapability.FULL_MARKET_SNAPSHOT})

    def fetch_full_market_snapshot(self) -> ProviderSnapshotBatch:
        frame, attempt_count = self._fetch_with_retry()
        rows = self._extract_rows(frame)
        fetched_at = as_market_timezone(self._clock())
        records: list[MarketSnapshotRecord] = []
        issues: list[NormalizationIssue] = []

        for row_number, row in enumerate(rows, start=1):
            record, row_issues = self._normalize_row(
                row=row,
                row_number=row_number,
                fetched_at=fetched_at,
            )
            issues.extend(row_issues)
            if record is not None:
                records.append(record)

        return ProviderSnapshotBatch(
            provider=self.provider_id,
            records=tuple(records),
            raw_record_count=len(rows),
            normalization_issues=tuple(issues),
            provider_version=installed_akshare_version(),
            provider_timestamp=None,
            provider_metadata={
                "adapter": "AkShareMarketDataProvider",
                "akshare_version": installed_akshare_version(),
                "upstream": "Eastmoney",
                "upstream_function": "stock_zh_a_spot_em",
                "attempt_count": attempt_count,
                "provider_timestamp_available": False,
            },
        )

    def _fetch_with_retry(self) -> tuple[object, int]:
        last_error: ProviderError | None = None
        for attempt in range(1, self._retry_policy.max_attempts + 1):
            try:
                return self._fetcher(), attempt
            except (Timeout, TimeoutError) as exc:
                last_error = ProviderTimeoutError(
                    provider=self.provider_id,
                    message="market-data provider request timed out",
                )
                cause: Exception = exc
            except RequestsJSONDecodeError as exc:
                raise ProviderInvalidResponseError(
                    provider=self.provider_id,
                    message="market-data provider returned invalid JSON",
                ) from exc
            except (RequestException, OSError) as exc:
                last_error = ProviderUnavailableError(
                    provider=self.provider_id,
                    message="market-data provider is unavailable",
                )
                cause = exc
            except Exception as exc:
                raise ProviderInvalidResponseError(
                    provider=self.provider_id,
                    message="market-data provider returned an unreadable response",
                ) from exc

            if attempt < self._retry_policy.max_attempts:
                delay = self._retry_policy.delay_seconds * attempt
                logger.warning(
                    "market_data_provider_retry",
                    extra={
                        "provider": self.provider_id,
                        "attempt": attempt,
                        "next_attempt": attempt + 1,
                        "delay_seconds": delay,
                        "error_type": type(cause).__name__,
                    },
                )
                self._sleeper(delay)

        if last_error is None:  # pragma: no cover - loop executes at least once by validation
            raise AssertionError("retry policy allowed no attempts")
        raise last_error from cause

    def _extract_rows(self, raw_frame: object) -> list[dict[object, object]]:
        if not hasattr(raw_frame, "columns") or not callable(getattr(raw_frame, "to_dict", None)):
            raise ProviderInvalidResponseError(
                provider=self.provider_id,
                message="market-data provider did not return a tabular response",
            )

        frame = cast(_FrameLike, raw_frame)
        columns = {str(column) for column in frame.columns}
        missing_columns = set(_COLUMNS.values()) - columns
        if missing_columns:
            raise ProviderInvalidResponseError(
                provider=self.provider_id,
                message="market-data provider response is missing required columns",
            )

        try:
            rows = frame.to_dict(orient="records")
        except Exception as exc:
            raise ProviderInvalidResponseError(
                provider=self.provider_id,
                message="market-data provider table could not be read",
            ) from exc
        if not isinstance(rows, list) or not rows:
            raise ProviderInvalidResponseError(
                provider=self.provider_id,
                message="market-data provider returned no snapshot rows",
            )
        if not all(isinstance(row, Mapping) for row in rows):
            raise ProviderInvalidResponseError(
                provider=self.provider_id,
                message="market-data provider returned malformed table rows",
            )
        return rows

    def _normalize_row(
        self,
        *,
        row: Mapping[object, object],
        row_number: int,
        fetched_at: datetime,
    ) -> tuple[MarketSnapshotRecord | None, list[NormalizationIssue]]:
        issues: list[NormalizationIssue] = []
        symbol = _optional_text(row.get(_COLUMNS["symbol"]))
        if symbol is None:
            return None, [
                NormalizationIssue(
                    row_number=row_number,
                    code=NormalizationIssueCode.MISSING_SYMBOL,
                    field="symbol",
                )
            ]
        if _SYMBOL_PATTERN.fullmatch(symbol) is None:
            return None, [
                NormalizationIssue(
                    row_number=row_number,
                    code=NormalizationIssueCode.INVALID_SYMBOL,
                    field="symbol",
                )
            ]

        name = _optional_text(row.get(_COLUMNS["name"]))
        if name is None:
            issues.append(
                NormalizationIssue(
                    row_number=row_number,
                    code=NormalizationIssueCode.MISSING_NAME,
                    field="name",
                )
            )

        numeric_values: dict[str, float | None] = {}
        for field in _NUMERIC_FIELDS:
            value, invalid = _optional_number(row.get(_COLUMNS[field]))
            numeric_values[field] = value
            if invalid:
                issues.append(
                    NormalizationIssue(
                        row_number=row_number,
                        code=NormalizationIssueCode.INVALID_NUMERIC_VALUE,
                        field=field,
                    )
                )

        volume_in_lots = numeric_values["volume"]
        if volume_in_lots is not None:
            numeric_values["volume"] = volume_in_lots * _SHARES_PER_LOT

        try:
            record = MarketSnapshotRecord(
                symbol=symbol,
                exchange=infer_a_share_exchange(symbol),
                name=name,
                provider=self.provider_id,
                provider_timestamp=None,
                fetched_at=fetched_at,
                **numeric_values,
            )
        except ValidationError:
            issues.append(
                NormalizationIssue(
                    row_number=row_number,
                    code=NormalizationIssueCode.MALFORMED_ROW,
                )
            )
            return None, issues
        return record, issues

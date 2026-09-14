import json
import math
import re
import time
from collections.abc import Callable, Collection, Mapping
from datetime import datetime
from threading import Lock
from typing import Literal, Protocol, cast

import requests
from pydantic import ValidationError
from requests.exceptions import JSONDecodeError as RequestsJSONDecodeError
from requests.exceptions import RequestException, Timeout

from a_stock_lab.core.logging import get_logger
from a_stock_lab.core.time import MARKET_TIME_ZONE, as_market_timezone, now_in_market_timezone
from a_stock_lab.shared.market_data.errors import (
    ProviderError,
    ProviderInvalidResponseError,
    ProviderTimeoutError,
    ProviderUnavailableError,
)
from a_stock_lab.shared.market_data.models import (
    IntradayBar,
    IntradayBarRequest,
    MarketDataCapability,
    MarketSnapshotRecord,
    NormalizationIssue,
    NormalizationIssueCode,
    ProviderIntradayBarBatch,
    ProviderRetryPolicy,
    ProviderSnapshotBatch,
)
from a_stock_lab.shared.market_data.symbols import infer_a_share_exchange

from .akshare_common import AKSHARE_PROVIDER_ID, installed_akshare_version

logger = get_logger(__name__)

_SHARES_PER_LOT = 100
_SYMBOL_PATTERN = re.compile(r"^\d{6}$")
_MISSING_TEXT = frozenset({"", "-", "--", "nan", "none", "null", "<na>", "n/a"})

_EASTMONEY_DELAYED_SNAPSHOT_URL = "https://push2delay.eastmoney.com/api/qt/clist/get"
_EASTMONEY_DELAYED_PAGE_SIZE = 100
_EASTMONEY_DELAYED_PAGE_DELAY_SECONDS = 0.5
_EASTMONEY_DELAYED_TIMEOUT_SECONDS = 15
_SNAPSHOT_TRANSPORT_METADATA_KEY = "a_stock_lab_snapshot_transport"
_INTRADAY_TRANSPORT_METADATA_KEY = "a_stock_lab_intraday_transport"
_SINA_INTRADAY_URL = (
    "https://quotes.sina.cn/cn/api/jsonp_v2.php/=/CN_MarketDataService.getKLineData"
)
_SINA_INTRADAY_TIMEOUT_SECONDS = 15
_SINA_INTRADAY_MAX_BARS = 1970
_EASTMONEY_SNAPSHOT_FIELD_COLUMNS = {
    "f12": "代码",
    "f14": "名称",
    "f2": "最新价",
    "f3": "涨跌幅",
    "f4": "涨跌额",
    "f5": "成交量",
    "f6": "成交额",
    "f7": "振幅",
    "f15": "最高",
    "f16": "最低",
    "f17": "今开",
    "f18": "昨收",
    "f10": "量比",
    "f8": "换手率",
    "f9": "市盈率-动态",
    "f23": "市净率",
    "f20": "总市值",
    "f21": "流通市值",
}
_EASTMONEY_SNAPSHOT_PARAMS = {
    "pn": "1",
    "pz": str(_EASTMONEY_DELAYED_PAGE_SIZE),
    "po": "1",
    "np": "1",
    "ut": "bd1d9ddb04089700cf9c27f6f7426281",
    "fltt": "2",
    "invt": "2",
    "fid": "f12",
    "fs": "m:0 t:6,m:0 t:80,m:1 t:2,m:1 t:23,m:0 t:81 s:2048",
    "fields": ",".join(_EASTMONEY_SNAPSHOT_FIELD_COLUMNS),
}

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
_INTRADAY_COLUMNS = {
    "ended_at": "时间",
    "open": "开盘",
    "close": "收盘",
    "high": "最高",
    "low": "最低",
    "volume": "成交量",
    "amount": "成交额",
}


class _FrameLike(Protocol):
    columns: Collection[object]

    def to_dict(self, *, orient: Literal["records"]) -> list[dict[object, object]]: ...


class _HttpResponseLike(Protocol):
    text: str

    def raise_for_status(self) -> None: ...

    def json(self) -> object: ...


class _RecordFrame:
    """Minimal frame used only by the adapter's delayed-endpoint fallback."""

    def __init__(self, rows: list[dict[object, object]], *, transport: str) -> None:
        self._rows = rows
        self.columns = tuple(_EASTMONEY_SNAPSHOT_FIELD_COLUMNS.values())
        self.attrs = {_SNAPSHOT_TRANSPORT_METADATA_KEY: transport}

    def to_dict(self, *, orient: Literal["records"]) -> list[dict[object, object]]:
        if orient != "records":  # pragma: no cover - adapter always uses records
            raise ValueError("unsupported frame orientation")
        return [row.copy() for row in self._rows]


class _IntradayRecordFrame:
    """SDK-compatible intraday table used by the adapter's alternate-upstream fallback."""

    def __init__(self, rows: list[dict[object, object]], *, transport: str) -> None:
        self._rows = rows
        self.columns = tuple(_INTRADAY_COLUMNS.values())
        self.attrs = {_INTRADAY_TRANSPORT_METADATA_KEY: transport}

    def to_dict(self, *, orient: Literal["records"]) -> list[dict[object, object]]:
        if orient != "records":  # pragma: no cover - adapter always uses records
            raise ValueError("unsupported frame orientation")
        return [row.copy() for row in self._rows]


def _fetch_live_frame(
    *,
    primary_fetcher: Callable[[], object] | None = None,
    delayed_fetcher: Callable[[], object] | None = None,
) -> object:
    if primary_fetcher is None:
        import akshare  # type: ignore[import-untyped]

        primary_fetcher = akshare.stock_zh_a_spot_em
    if delayed_fetcher is None:
        delayed_fetcher = _fetch_live_frame_from_delayed_endpoint

    try:
        frame = primary_fetcher()
    except (RequestException, OSError) as exc:
        logger.warning(
            "akshare_snapshot_delayed_endpoint_fallback",
            extra={"provider": AKSHARE_PROVIDER_ID, "error_type": type(exc).__name__},
        )
        return delayed_fetcher()

    attrs = getattr(frame, "attrs", None)
    if isinstance(attrs, dict):
        attrs[_SNAPSHOT_TRANSPORT_METADATA_KEY] = "akshare_public_sdk"
    return frame


def _fetch_live_frame_from_delayed_endpoint(
    *,
    requester: Callable[..., _HttpResponseLike] | None = None,
    sleeper: Callable[[float], None] = time.sleep,
) -> object:
    """Fetch the SDK-compatible snapshot from Eastmoney's delayed fallback host."""

    if requester is None:
        requester = cast(Callable[..., _HttpResponseLike], requests.get)
    rows: list[Mapping[object, object]] = []
    total: int | None = None
    page_count: int | None = None
    page = 1
    while page_count is None or page <= page_count:
        if page > 1:
            sleeper(_EASTMONEY_DELAYED_PAGE_DELAY_SECONDS)
        response = requester(
            _EASTMONEY_DELAYED_SNAPSHOT_URL,
            params={**_EASTMONEY_SNAPSHOT_PARAMS, "pn": str(page)},
            timeout=_EASTMONEY_DELAYED_TIMEOUT_SECONDS,
        )
        response.raise_for_status()
        page_total, page_rows = _extract_eastmoney_snapshot_page(response.json())
        if total is None:
            if not page_rows:
                raise ValueError("Eastmoney delayed snapshot returned no rows")
            total = page_total
            page_count = math.ceil(total / len(page_rows))
        elif page_total != total:
            raise ValueError("Eastmoney delayed snapshot total changed during pagination")
        rows.extend(page_rows)
        page += 1

    if total is None or len(rows) != total:
        raise ValueError("Eastmoney delayed snapshot pagination was incomplete")

    normalized_rows: list[dict[object, object]] = [
        {
            column: row.get(provider_field)
            for provider_field, column in _EASTMONEY_SNAPSHOT_FIELD_COLUMNS.items()
        }
        for row in rows
    ]
    return _RecordFrame(
        normalized_rows,
        transport="eastmoney_delayed_endpoint_fallback",
    )


def _extract_eastmoney_snapshot_page(
    payload: object,
) -> tuple[int, list[Mapping[object, object]]]:
    if not isinstance(payload, Mapping):
        raise ValueError("Eastmoney delayed snapshot response was not an object")
    data = payload.get("data")
    if not isinstance(data, Mapping):
        raise ValueError("Eastmoney delayed snapshot response had no data object")
    raw_total = data.get("total")
    if isinstance(raw_total, bool):
        raise ValueError("Eastmoney delayed snapshot total was invalid")
    try:
        total = int(str(raw_total))
    except (TypeError, ValueError) as exc:
        raise ValueError("Eastmoney delayed snapshot total was invalid") from exc
    raw_rows = data.get("diff")
    if total <= 0 or not isinstance(raw_rows, list):
        raise ValueError("Eastmoney delayed snapshot rows were invalid")
    if not all(isinstance(row, Mapping) for row in raw_rows):
        raise ValueError("Eastmoney delayed snapshot contained malformed rows")
    return total, raw_rows


def _fetch_intraday_from_sdk(request: IntradayBarRequest) -> object:
    import akshare

    return akshare.stock_zh_a_hist_min_em(
        symbol=request.symbol,
        start_date=request.start_at.strftime("%Y-%m-%d %H:%M:%S"),
        end_date=request.end_at.strftime("%Y-%m-%d %H:%M:%S"),
        period=str(int(request.interval_minutes)),
        adjust="",
    )


class _LiveIntradayFetcher:
    """Share a short primary-transport cooldown across one provider's candidate calls."""

    def __init__(
        self,
        *,
        primary: Callable[[IntradayBarRequest], object] = _fetch_intraday_from_sdk,
        fallback: Callable[[IntradayBarRequest], object] | None = None,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        self._primary = primary
        self._fallback = fallback or _fetch_live_intraday_frame_from_sina
        self._monotonic = monotonic
        self._retry_primary_at = 0.0
        self._lock = Lock()

    def __call__(self, request: IntradayBarRequest) -> object:
        with self._lock:
            cooling_down = self._monotonic() < self._retry_primary_at
        if cooling_down:
            return self._fallback(request)
        return _fetch_live_intraday_frame(
            request, primary_fetcher=self._try_primary, fallback_fetcher=self._fallback
        )

    def _try_primary(self, request: IntradayBarRequest) -> object:
        try:
            return self._primary(request)
        except (RequestException, OSError):
            with self._lock:
                self._retry_primary_at = self._monotonic() + 60.0
            raise


def _fetch_live_intraday_frame(
    request: IntradayBarRequest,
    *,
    primary_fetcher: Callable[[IntradayBarRequest], object] | None = None,
    fallback_fetcher: Callable[[IntradayBarRequest], object] | None = None,
) -> object:
    if primary_fetcher is None:
        primary_fetcher = _fetch_intraday_from_sdk

    if fallback_fetcher is None:
        fallback_fetcher = _fetch_live_intraday_frame_from_sina

    try:
        frame = primary_fetcher(request)
    except (RequestException, OSError) as exc:
        logger.warning(
            "akshare_intraday_sina_fallback",
            extra={
                "provider": AKSHARE_PROVIDER_ID,
                "symbol": request.symbol,
                "error_type": type(exc).__name__,
            },
        )
        return fallback_fetcher(request)

    attrs = getattr(frame, "attrs", None)
    if isinstance(attrs, dict):
        attrs[_INTRADAY_TRANSPORT_METADATA_KEY] = "akshare_eastmoney_public_sdk"
    return frame


def _fetch_live_intraday_frame_from_sina(
    request: IntradayBarRequest,
    *,
    requester: Callable[..., _HttpResponseLike] | None = None,
) -> object:
    """Fetch recent unadjusted five-minute bars from Sina with an explicit timeout."""

    if requester is None:
        requester = cast(Callable[..., _HttpResponseLike], requests.get)
    prefix = "sh" if request.symbol.startswith("6") else "sz"
    if request.symbol.startswith(("4", "8", "92")):
        prefix = "bj"
    response = requester(
        _SINA_INTRADAY_URL,
        params={
            "symbol": f"{prefix}{request.symbol}",
            "scale": str(int(request.interval_minutes)),
            "ma": "no",
            "datalen": str(_SINA_INTRADAY_MAX_BARS),
        },
        timeout=_SINA_INTRADAY_TIMEOUT_SECONDS,
    )
    response.raise_for_status()
    payload = _parse_sina_jsonp(response.text)
    rows: list[dict[object, object]] = []
    for raw_row in payload:
        raw_ended_at = raw_row.get("day")
        try:
            parsed = datetime.fromisoformat(str(raw_ended_at))
            ended_at = as_market_timezone(
                parsed.replace(tzinfo=MARKET_TIME_ZONE) if parsed.tzinfo is None else parsed
            )
        except (TypeError, ValueError):
            ended_at = None
        if ended_at is not None and not (request.start_at <= ended_at <= request.end_at):
            continue

        rows.append(
            {
                _INTRADAY_COLUMNS["ended_at"]: raw_ended_at,
                _INTRADAY_COLUMNS["open"]: raw_row.get("open"),
                _INTRADAY_COLUMNS["close"]: raw_row.get("close"),
                _INTRADAY_COLUMNS["high"]: raw_row.get("high"),
                _INTRADAY_COLUMNS["low"]: raw_row.get("low"),
                _INTRADAY_COLUMNS["volume"]: raw_row.get("volume"),
                _INTRADAY_COLUMNS["amount"]: raw_row.get("amount"),
            }
        )
    return _IntradayRecordFrame(rows, transport="akshare_sina_fallback")


def _parse_sina_jsonp(text: str) -> list[Mapping[object, object]]:
    start = text.find("=(")
    end = text.rfind(");")
    if start < 0 or end <= start + 2:
        raise ValueError("Sina intraday response was not valid JSONP")
    payload = json.loads(text[start + 2 : end])
    if not isinstance(payload, list) or not all(isinstance(row, Mapping) for row in payload):
        raise ValueError("Sina intraday response contained malformed rows")
    return payload


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


def _snapshot_transport(frame: object) -> str:
    attrs = getattr(frame, "attrs", None)
    if isinstance(attrs, Mapping):
        value = attrs.get(_SNAPSHOT_TRANSPORT_METADATA_KEY)
        if isinstance(value, str) and value:
            return value
    return "injected_or_unknown"


def _intraday_transport(frame: object) -> str:
    attrs = getattr(frame, "attrs", None)
    if isinstance(attrs, Mapping):
        value = attrs.get(_INTRADAY_TRANSPORT_METADATA_KEY)
        if isinstance(value, str) and value:
            return value
    return "injected_or_unknown"


class AkShareMarketDataProvider:
    """AKShare adapter; no SDK schema or exception escapes this module."""

    def __init__(
        self,
        *,
        retry_policy: ProviderRetryPolicy | None = None,
        fetcher: Callable[[], object] = _fetch_live_frame,
        intraday_fetcher: Callable[[IntradayBarRequest], object] | None = None,
        sleeper: Callable[[float], None] = time.sleep,
        clock: Callable[[], datetime] = now_in_market_timezone,
    ) -> None:
        self._retry_policy = retry_policy or ProviderRetryPolicy()
        self._fetcher = fetcher
        self._intraday_fetcher = intraday_fetcher or _LiveIntradayFetcher()
        self._sleeper = sleeper
        self._clock = clock

    @property
    def provider_id(self) -> str:
        return AKSHARE_PROVIDER_ID

    @property
    def capabilities(self) -> frozenset[MarketDataCapability]:
        return frozenset(
            {
                MarketDataCapability.FULL_MARKET_SNAPSHOT,
                MarketDataCapability.INTRADAY_BARS,
            }
        )

    def fetch_full_market_snapshot(self) -> ProviderSnapshotBatch:
        frame, attempt_count = self._fetch_with_retry(
            fetcher=self._fetcher,
            operation="full_market_snapshot",
        )
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
                "snapshot_transport": _snapshot_transport(frame),
                "attempt_count": attempt_count,
                "provider_timestamp_available": False,
            },
        )

    def fetch_intraday_bars(self, request: IntradayBarRequest) -> ProviderIntradayBarBatch:
        frame, attempt_count = self._fetch_with_retry(
            fetcher=lambda: self._intraday_fetcher(request),
            operation="intraday_bars",
        )
        rows = self._extract_intraday_rows(frame)
        transport = _intraday_transport(frame)
        volume_multiplier = 1 if transport == "akshare_sina_fallback" else _SHARES_PER_LOT
        fetched_at = as_market_timezone(self._clock())
        bars: list[IntradayBar] = []
        issue_count = 0
        for row in rows:
            bar = self._normalize_intraday_row(
                row=row,
                request=request,
                fetched_at=fetched_at,
                volume_multiplier=volume_multiplier,
            )
            if bar is None:
                issue_count += 1
            else:
                bars.append(bar)

        return ProviderIntradayBarBatch(
            provider=self.provider_id,
            request=request,
            bars=tuple(bars),
            raw_record_count=len(rows),
            normalization_issue_count=issue_count,
            provider_version=installed_akshare_version(),
            provider_metadata={
                "adapter": "AkShareMarketDataProvider",
                "akshare_version": installed_akshare_version(),
                "upstream": "Sina" if transport == "akshare_sina_fallback" else "Eastmoney",
                "upstream_function": (
                    "CN_MarketDataService.getKLineData"
                    if transport == "akshare_sina_fallback"
                    else "stock_zh_a_hist_min_em"
                ),
                "intraday_transport": transport,
                "attempt_count": attempt_count,
                "adjustment": "none",
                "bar_timestamp_semantics": "bar_end",
                "volume_source_unit": ("share" if transport == "akshare_sina_fallback" else "lot"),
                "volume_normalized_unit": "share",
            },
            fetched_at=fetched_at,
        )

    def _fetch_with_retry(
        self,
        *,
        fetcher: Callable[[], object],
        operation: str,
    ) -> tuple[object, int]:
        last_error: ProviderError | None = None
        for attempt in range(1, self._retry_policy.max_attempts + 1):
            try:
                return fetcher(), attempt
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
                        "operation": operation,
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

    def _extract_intraday_rows(self, raw_frame: object) -> list[dict[object, object]]:
        if not hasattr(raw_frame, "columns") or not callable(getattr(raw_frame, "to_dict", None)):
            raise ProviderInvalidResponseError(
                provider=self.provider_id,
                message="intraday provider did not return a tabular response",
            )
        frame = cast(_FrameLike, raw_frame)
        columns = {str(column) for column in frame.columns}
        missing_columns = set(_INTRADAY_COLUMNS.values()) - columns
        if missing_columns:
            raise ProviderInvalidResponseError(
                provider=self.provider_id,
                message="intraday provider response is missing required columns",
            )
        try:
            rows = frame.to_dict(orient="records")
        except Exception as exc:
            raise ProviderInvalidResponseError(
                provider=self.provider_id,
                message="intraday provider table could not be read",
            ) from exc
        if not isinstance(rows, list) or not all(isinstance(row, Mapping) for row in rows):
            raise ProviderInvalidResponseError(
                provider=self.provider_id,
                message="intraday provider returned malformed table rows",
            )
        return rows

    def _normalize_intraday_row(
        self,
        *,
        row: Mapping[object, object],
        request: IntradayBarRequest,
        fetched_at: datetime,
        volume_multiplier: int,
    ) -> IntradayBar | None:
        ended_at_text = _optional_text(row.get(_INTRADAY_COLUMNS["ended_at"]))
        if ended_at_text is None:
            return None
        try:
            parsed = datetime.fromisoformat(ended_at_text)
        except ValueError:
            return None
        ended_at = as_market_timezone(
            parsed.replace(tzinfo=MARKET_TIME_ZONE) if parsed.tzinfo is None else parsed
        )

        numeric_values: dict[str, float] = {}
        for field in ("open", "high", "low", "close", "volume", "amount"):
            value, invalid = _optional_number(row.get(_INTRADAY_COLUMNS[field]))
            if invalid or value is None:
                return None
            numeric_values[field] = value
        numeric_values["volume"] *= volume_multiplier
        try:
            return IntradayBar(
                symbol=request.symbol,
                interval_minutes=request.interval_minutes,
                ended_at=ended_at,
                provider=self.provider_id,
                provider_timestamp=None,
                fetched_at=fetched_at,
                **numeric_values,
            )
        except ValidationError:
            return None

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

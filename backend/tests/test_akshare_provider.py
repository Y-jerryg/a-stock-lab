from datetime import datetime
from typing import Literal

import pytest
from requests.exceptions import ConnectionError as RequestsConnectionError

from a_stock_lab.core.time import MARKET_TIME_ZONE
from a_stock_lab.shared.market_data.adapters.akshare import (
    AkShareMarketDataProvider,
    _fetch_live_frame,
    _fetch_live_frame_from_delayed_endpoint,
    _fetch_live_intraday_frame,
    _fetch_live_intraday_frame_from_sina,
    _LiveIntradayFetcher,
)
from a_stock_lab.shared.market_data.errors import (
    ProviderInvalidResponseError,
    ProviderTimeoutError,
    ProviderUnavailableError,
)
from a_stock_lab.shared.market_data.models import (
    AShareExchange,
    IntradayBarRequest,
    MarketDataCapability,
    MarketSnapshotRecord,
    NormalizationIssueCode,
    ProviderRetryPolicy,
)

EXPECTED_COLUMNS = [
    "代码",
    "名称",
    "最新价",
    "涨跌幅",
    "涨跌额",
    "成交量",
    "成交额",
    "振幅",
    "最高",
    "最低",
    "今开",
    "昨收",
    "量比",
    "换手率",
    "市盈率-动态",
    "市净率",
    "总市值",
    "流通市值",
]
INTRADAY_COLUMNS: list[object] = [
    "时间",
    "开盘",
    "收盘",
    "最高",
    "最低",
    "成交量",
    "成交额",
]


class FakeFrame:
    def __init__(
        self,
        rows: list[dict[object, object]],
        columns: list[object] | None = None,
    ) -> None:
        self._rows = rows
        self.columns = columns or EXPECTED_COLUMNS

    def to_dict(self, *, orient: Literal["records"]) -> list[dict[object, object]]:
        assert orient == "records"
        return self._rows


class FakeHttpResponse:
    def __init__(self, payload: object, *, text: str = "") -> None:
        self._payload = payload
        self.text = text

    def raise_for_status(self) -> None:
        return None

    def json(self) -> object:
        return self._payload


def valid_row(**overrides: object) -> dict[object, object]:
    row: dict[object, object] = {
        "代码": "600000",
        "名称": "浦发银行",
        "最新价": 10.25,
        "涨跌幅": 1.5,
        "涨跌额": 0.15,
        "成交量": 123_456,
        "成交额": 1_234_567.89,
        "振幅": 2.1,
        "最高": 10.4,
        "最低": 10.1,
        "今开": 10.2,
        "昨收": 10.1,
        "量比": 1.2,
        "换手率": 0.8,
        "市盈率-动态": 6.5,
        "市净率": 0.7,
        "总市值": 300_000_000_000,
        "流通市值": 290_000_000_000,
    }
    row.update(overrides)
    return row


def fixed_clock() -> datetime:
    return datetime(2026, 8, 28, 14, 30, tzinfo=MARKET_TIME_ZONE)


def eastmoney_row(symbol: str) -> dict[str, object]:
    return {
        "f12": symbol,
        "f14": f"测试{symbol}",
        "f2": 10.25,
        "f3": 1.5,
        "f4": 0.15,
        "f5": 123_456,
        "f6": 1_234_567.89,
        "f7": 2.1,
        "f15": 10.4,
        "f16": 10.1,
        "f17": 10.2,
        "f18": 10.1,
        "f10": 1.2,
        "f8": 0.8,
        "f9": 6.5,
        "f23": 0.7,
        "f20": 300_000_000_000,
        "f21": 290_000_000_000,
    }


def test_live_fetch_uses_delayed_endpoint_only_after_sdk_connection_failure() -> None:
    fallback_frame = FakeFrame([valid_row()])
    calls: list[str] = []

    def unavailable_primary() -> object:
        calls.append("primary")
        raise RequestsConnectionError

    def delayed_fallback() -> object:
        calls.append("fallback")
        return fallback_frame

    result = _fetch_live_frame(
        primary_fetcher=unavailable_primary,
        delayed_fetcher=delayed_fallback,
    )

    assert result is fallback_frame
    assert calls == ["primary", "fallback"]


def test_delayed_endpoint_fallback_requires_complete_pagination() -> None:
    calls: list[str] = []
    delays: list[float] = []
    payloads = {
        "1": {"data": {"total": 3, "diff": [eastmoney_row("600000"), eastmoney_row("000001")]}},
        "2": {"data": {"total": 3, "diff": [eastmoney_row("430047")]}},
    }

    def request(_url: str, *, params: dict[str, str], timeout: int) -> FakeHttpResponse:
        assert timeout == 15
        page = params["pn"]
        calls.append(page)
        return FakeHttpResponse(payloads[page])

    frame = _fetch_live_frame_from_delayed_endpoint(
        requester=request,
        sleeper=delays.append,
    )
    provider = AkShareMarketDataProvider(fetcher=lambda: frame, clock=fixed_clock)

    batch = provider.fetch_full_market_snapshot()

    assert calls == ["1", "2"]
    assert delays == [0.5]
    assert batch.raw_record_count == 3
    assert [record.symbol for record in batch.records] == ["600000", "000001", "430047"]
    assert batch.provider_metadata["snapshot_transport"] == ("eastmoney_delayed_endpoint_fallback")


def test_adapter_normalizes_provider_columns_without_leaking_them() -> None:
    provider = AkShareMarketDataProvider(
        fetcher=lambda: FakeFrame([valid_row()]),
        clock=fixed_clock,
    )

    batch = provider.fetch_full_market_snapshot()

    assert provider.capabilities == frozenset(
        {
            MarketDataCapability.FULL_MARKET_SNAPSHOT,
            MarketDataCapability.INTRADAY_BARS,
        }
    )
    assert batch.raw_record_count == 1
    assert batch.normalization_issues == ()
    assert batch.provider_metadata["provider_timestamp_available"] is False
    record = batch.records[0]
    assert record.symbol == "600000"
    assert record.exchange == AShareExchange.SHANGHAI
    assert record.name == "浦发银行"
    assert record.price == 10.25
    assert record.pct_change == 1.5
    assert record.volume == 12_345_600
    assert record.total_market_cap == 300_000_000_000
    assert record.provider == "akshare"
    assert record.provider_timestamp is None
    assert record.fetched_at == fixed_clock()
    assert "最新价" not in MarketSnapshotRecord.model_fields


@pytest.mark.parametrize(
    ("symbol", "exchange"),
    [
        ("600000", AShareExchange.SHANGHAI),
        ("000001", AShareExchange.SHENZHEN),
        ("430047", AShareExchange.BEIJING),
        ("920001", AShareExchange.BEIJING),
    ],
)
def test_adapter_infers_only_known_a_share_exchange_families(
    symbol: str,
    exchange: AShareExchange,
) -> None:
    provider = AkShareMarketDataProvider(
        fetcher=lambda: FakeFrame([valid_row(**{"代码": symbol})]),
        clock=fixed_clock,
    )

    assert provider.fetch_full_market_snapshot().records[0].exchange == exchange


def test_adapter_reports_malformed_values_and_does_not_fabricate_them() -> None:
    provider = AkShareMarketDataProvider(
        fetcher=lambda: FakeFrame(
            [
                valid_row(**{"最新价": "not-a-number", "市净率": "-"}),
                valid_row(**{"代码": "", "名称": "missing symbol"}),
            ]
        ),
        clock=fixed_clock,
    )

    batch = provider.fetch_full_market_snapshot()

    assert batch.raw_record_count == 2
    assert len(batch.records) == 1
    assert batch.records[0].price is None
    assert batch.records[0].pb is None
    assert {(issue.code, issue.field) for issue in batch.normalization_issues} == {
        (NormalizationIssueCode.INVALID_NUMERIC_VALUE, "price"),
        (NormalizationIssueCode.MISSING_SYMBOL, "symbol"),
    }


def test_adapter_retries_once_after_timeout_with_injected_sleep() -> None:
    responses: list[object] = [TimeoutError(), FakeFrame([valid_row()])]
    delays: list[float] = []

    def fetch() -> object:
        response = responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response

    provider = AkShareMarketDataProvider(
        retry_policy=ProviderRetryPolicy(max_attempts=2, delay_seconds=3),
        fetcher=fetch,
        sleeper=delays.append,
        clock=fixed_clock,
    )

    batch = provider.fetch_full_market_snapshot()

    assert batch.provider_metadata["attempt_count"] == 2
    assert delays == [3]


def test_adapter_maps_exhausted_timeout_without_live_network() -> None:
    def fetcher() -> object:
        raise TimeoutError

    provider = AkShareMarketDataProvider(
        retry_policy=ProviderRetryPolicy(max_attempts=2, delay_seconds=0),
        fetcher=fetcher,
        sleeper=lambda _: None,
    )

    with pytest.raises(ProviderTimeoutError):
        provider.fetch_full_market_snapshot()


def test_adapter_maps_exhausted_connection_failure_without_live_network() -> None:
    def fetcher() -> object:
        raise RequestsConnectionError

    provider = AkShareMarketDataProvider(
        retry_policy=ProviderRetryPolicy(max_attempts=1),
        fetcher=fetcher,
    )

    with pytest.raises(ProviderUnavailableError):
        provider.fetch_full_market_snapshot()


def test_adapter_rejects_upstream_schema_drift() -> None:
    provider = AkShareMarketDataProvider(
        fetcher=lambda: FakeFrame([valid_row()], columns=["代码", "名称"]),
    )

    with pytest.raises(ProviderInvalidResponseError, match="missing required columns"):
        provider.fetch_full_market_snapshot()


def test_adapter_normalizes_unadjusted_five_minute_bars_and_share_volume() -> None:
    captured: list[IntradayBarRequest] = []

    def fetch_intraday(request: IntradayBarRequest) -> object:
        captured.append(request)
        return FakeFrame(
            [
                {
                    "时间": "2026-08-28 14:30:00",
                    "开盘": 10.20,
                    "收盘": 10.25,
                    "最高": 10.30,
                    "最低": 10.18,
                    "成交量": 1_234,
                    "成交额": 1_264_850,
                }
            ],
            columns=INTRADAY_COLUMNS,
        )

    request = IntradayBarRequest(
        symbol="600000",
        start_at=datetime(2026, 8, 28, 9, 30, tzinfo=MARKET_TIME_ZONE),
        end_at=fixed_clock(),
    )
    provider = AkShareMarketDataProvider(
        intraday_fetcher=fetch_intraday,
        clock=fixed_clock,
    )

    batch = provider.fetch_intraday_bars(request)

    assert captured == [request]
    assert batch.request == request
    assert batch.normalization_issue_count == 0
    assert batch.provider_metadata["adjustment"] == "none"
    assert batch.provider_metadata["bar_timestamp_semantics"] == "bar_end"
    bar = batch.bars[0]
    assert bar.ended_at == fixed_clock()
    assert bar.volume == 123_400
    assert bar.amount == 1_264_850
    assert bar.provider == "akshare"


def test_live_intraday_fetch_uses_sina_only_after_sdk_connection_failure() -> None:
    request = IntradayBarRequest(
        symbol="600000",
        start_at=datetime(2026, 8, 28, 9, 30, tzinfo=MARKET_TIME_ZONE),
        end_at=fixed_clock(),
    )
    fallback_frame = FakeFrame([], columns=INTRADAY_COLUMNS)
    calls: list[str] = []

    def unavailable_primary(_request: IntradayBarRequest) -> object:
        calls.append("primary")
        raise RequestsConnectionError

    def fallback(_request: IntradayBarRequest) -> object:
        calls.append("fallback")
        return fallback_frame

    result = _fetch_live_intraday_frame(
        request,
        primary_fetcher=unavailable_primary,
        fallback_fetcher=fallback,
    )

    assert result is fallback_frame
    assert calls == ["primary", "fallback"]


def test_sina_intraday_fallback_filters_the_window_and_preserves_share_volume() -> None:
    request = IntradayBarRequest(
        symbol="600000",
        start_at=datetime(2026, 8, 28, 9, 30, tzinfo=MARKET_TIME_ZONE),
        end_at=fixed_clock(),
    )
    response_text = (
        "callback=("
        '[{"day":"2026-08-28 14:30:00","open":"10.20","high":"10.30",'
        '"low":"10.18","close":"10.25","volume":"123457","amount":"1264850"},'
        '{"day":"2026-08-28 14:35:00","open":"10.25","high":"10.35",'
        '"low":"10.20","close":"10.30","volume":"100000","amount":"1030000"}]'
        ");"
    )
    captured: list[tuple[str, dict[str, str], int]] = []

    def requester(url: str, *, params: dict[str, str], timeout: int) -> FakeHttpResponse:
        captured.append((url, params, timeout))
        return FakeHttpResponse({}, text=response_text)

    frame = _fetch_live_intraday_frame_from_sina(request, requester=requester)
    provider = AkShareMarketDataProvider(
        intraday_fetcher=lambda _: frame,
        clock=fixed_clock,
    )

    batch = provider.fetch_intraday_bars(request)

    assert captured[0][1]["symbol"] == "sh600000"
    assert captured[0][1]["scale"] == "5"
    assert captured[0][2] == 15
    assert batch.raw_record_count == 1
    assert batch.bars[0].ended_at == fixed_clock()
    assert batch.bars[0].volume == 123_457
    assert batch.provider_metadata["upstream"] == "Sina"
    assert batch.provider_metadata["intraday_transport"] == "akshare_sina_fallback"


def test_adapter_reports_malformed_intraday_rows_without_fabricating_bars() -> None:
    provider = AkShareMarketDataProvider(
        intraday_fetcher=lambda _: FakeFrame(
            [
                {
                    "时间": "not-a-time",
                    "开盘": 10,
                    "收盘": 10,
                    "最高": 10,
                    "最低": 10,
                    "成交量": 1,
                    "成交额": 10,
                }
            ],
            columns=INTRADAY_COLUMNS,
        ),
        clock=fixed_clock,
    )
    request = IntradayBarRequest(
        symbol="600000",
        start_at=datetime(2026, 8, 28, 9, 30, tzinfo=MARKET_TIME_ZONE),
        end_at=fixed_clock(),
    )

    batch = provider.fetch_intraday_bars(request)

    assert batch.bars == ()
    assert batch.raw_record_count == 1
    assert batch.normalization_issue_count == 1


def test_intraday_cooldown_skips_failing_primary_and_probes_after_expiry() -> None:
    request = IntradayBarRequest(
        symbol="600000",
        start_at=datetime(2026, 8, 28, 9, 30, tzinfo=MARKET_TIME_ZONE),
        end_at=datetime(2026, 8, 28, 14, 30, tzinfo=MARKET_TIME_ZONE),
    )
    calls: list[str] = []
    current = [100.0]
    frame = FakeFrame([], columns=INTRADAY_COLUMNS)

    def primary(_: IntradayBarRequest) -> object:
        calls.append("primary")
        if current[0] < 160:
            raise RequestsConnectionError("unavailable")
        return frame

    def fallback(_: IntradayBarRequest) -> object:
        calls.append("fallback")
        return frame

    fetch = _LiveIntradayFetcher(primary=primary, fallback=fallback, monotonic=lambda: current[0])
    assert fetch(request) is frame
    assert fetch(request) is frame
    assert calls == ["primary", "fallback", "fallback"]
    current[0] = 160
    assert fetch(request) is frame
    assert calls[-1] == "primary"


def test_intraday_schema_failure_does_not_open_transport_cooldown() -> None:
    request = IntradayBarRequest(
        symbol="600000",
        start_at=datetime(2026, 8, 28, 9, 30, tzinfo=MARKET_TIME_ZONE),
        end_at=datetime(2026, 8, 28, 14, 30, tzinfo=MARKET_TIME_ZONE),
    )

    def malformed(_: IntradayBarRequest) -> object:
        raise ValueError("schema drift")

    def fallback(_: IntradayBarRequest) -> object:
        pytest.fail("schema failures must not switch transport")

    with pytest.raises(ValueError, match="schema drift"):
        _LiveIntradayFetcher(primary=malformed, fallback=fallback)(request)

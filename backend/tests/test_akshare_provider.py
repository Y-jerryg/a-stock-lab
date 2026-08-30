from datetime import datetime
from typing import Literal

import pytest
from requests.exceptions import ConnectionError as RequestsConnectionError

from a_stock_lab.core.time import MARKET_TIME_ZONE
from a_stock_lab.shared.market_data.adapters.akshare import AkShareMarketDataProvider
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

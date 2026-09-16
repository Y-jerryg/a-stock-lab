import json
import subprocess
from concurrent.futures import ThreadPoolExecutor
from datetime import date
from itertools import pairwise
from threading import Event, Lock
from unittest.mock import Mock

import pytest

from a_stock_lab.features.trend_radar.adapters.akshare import AkShareTrendProvider
from a_stock_lab.features.trend_radar.adapters.diagnostics import redact
from a_stock_lab.features.trend_radar.config import TrendSettings
from a_stock_lab.features.trend_radar.domain.models import TrendError


def test_provider_timeout_is_bounded_and_sanitized(monkeypatch: pytest.MonkeyPatch) -> None:
    call = Mock(side_effect=subprocess.TimeoutExpired("sensitive-command", 1))
    monkeypatch.setattr(
        "a_stock_lab.features.trend_radar.adapters.akshare.ProviderProcessPool.request", call
    )
    monkeypatch.setattr("time.sleep", lambda _: None)
    provider = AkShareTrendProvider(TrendSettings(_env_file=None))
    with pytest.raises(TrendError, match=r"^provider_error$"):
        provider.fetch_heat()
    assert call.call_count == 3
    assert call.call_args.args[2] == 60


def test_provider_diagnostics_redact_auth_without_losing_traceback() -> None:
    result = redact(
        "Traceback: https://user:pass@provider.example/bars?api_key=key-value&symbol=600000\n"
        "Authorization: Bearer private-bearer\nConnectionError: connection closed"
    )
    assert all(secret not in result for secret in ("user:pass", "key-value", "private-bearer"))
    assert "Traceback" in result and "symbol=600000" in result and "ConnectionError" in result


def test_malformed_provider_response(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "a_stock_lab.features.trend_radar.adapters.akshare.ProviderProcessPool.request",
        Mock(return_value=[{"unexpected": 1}]),
    )
    monkeypatch.setattr("time.sleep", lambda _: None)
    with pytest.raises(TrendError, match="provider_malformed_heat"):
        AkShareTrendProvider(TrendSettings(_env_file=None)).fetch_heat()


def test_attention_mapping_preserves_beijing_and_st(monkeypatch: pytest.MonkeyPatch) -> None:
    rows = [{"代码": "920001", "名称": "ST Example", "关注指数": 99, "交易日": "2026-01-29"}]
    monkeypatch.setattr(
        "a_stock_lab.features.trend_radar.adapters.akshare.ProviderProcessPool.request",
        Mock(return_value=rows),
    )
    monkeypatch.setattr("time.sleep", lambda _: None)
    result = AkShareTrendProvider(TrendSettings(_env_file=None)).fetch_heat()
    assert result[0].symbol == "920001" and result[0].heat_score == 99


def test_calendar_does_not_guess_outside_coverage(monkeypatch: pytest.MonkeyPatch) -> None:
    rows = [{"trade_date": "2026-01-29"}]
    monkeypatch.setattr(
        "a_stock_lab.features.trend_radar.adapters.akshare.ProviderProcessPool.request",
        Mock(return_value=rows),
    )
    monkeypatch.setattr("time.sleep", lambda _: None)
    with pytest.raises(TrendError, match="calendar_out_of_range"):
        AkShareTrendProvider(TrendSettings(_env_file=None)).sessions(date(2027, 1, 1))


def test_missing_attention_is_not_assigned_an_invented_rank(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    rows = [{"代码": "600000", "名称": "Example", "关注指数": None, "交易日": "2026-01-29"}]
    monkeypatch.setattr(
        "a_stock_lab.features.trend_radar.adapters.akshare.ProviderProcessPool.request",
        Mock(return_value=rows),
    )
    monkeypatch.setattr("time.sleep", lambda _: None)
    assert AkShareTrendProvider(TrendSettings(_env_file=None)).fetch_heat() == []


def test_full_exchange_universe_is_independent_of_attention(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Keep identifiers six digits while covering each exchange.
    rows = [{"code": str(600000 + i), "name": "Example"} for i in range(4000)]
    rows.extend([{"code": "000001", "name": "Shenzhen"}, {"code": "920001", "name": "Beijing"}])
    provider = AkShareTrendProvider(TrendSettings(_env_file=None))
    fetch = Mock(return_value=rows)
    monkeypatch.setattr(provider, "_fetch", fetch)
    result = provider.fetch_universe()
    assert len(result) == 4002
    assert result[0].symbol == "000001" and result[-1].symbol == "920001"
    fetch.assert_called_once_with("universe")
    fetch.return_value = rows[:300]
    with pytest.raises(TrendError, match="incomplete_a_share_universe"):
        provider.fetch_universe()
    fetch.return_value = rows[:-1]
    with pytest.raises(TrendError, match="incomplete_a_share_universe"):
        provider.fetch_universe()


def test_daily_fallback_preserves_bounds_and_source_and_logs_child_traceback(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    error = subprocess.CalledProcessError(
        1,
        "provider",
        output=json.dumps(
            {
                "error": {
                    "exception_type": "ConnectionError",
                    "exception_message": "closed connection",
                    "url": "https://provider.example/bars?token=private-value&symbol=600000",
                    "provider_traceback": (
                        "Traceback (most recent call last):\nConnectionError: closed connection"
                    ),
                }
            }
        ),
    )
    row = {
        "日期": "2026-01-29",
        "开盘": 10,
        "最高": 11,
        "最低": 9,
        "收盘": 10,
        "成交量": 100,
        "成交额": 100000,
    }
    call = Mock(
        side_effect=[
            error,
            error,
            error,
            [row],
            [row],
        ]
    )
    monkeypatch.setattr(
        "a_stock_lab.features.trend_radar.adapters.akshare.ProviderProcessPool.request", call
    )
    monkeypatch.setattr("time.sleep", lambda _: None)
    provider = AkShareTrendProvider(TrendSettings(_env_file=None))
    bars = provider.fetch_bars("600000", date(2025, 12, 1), date(2026, 1, 29))
    assert bars[0].source == "sina_daily_qfq"
    assert bars[0].volume == 100 and bars[0].amount == 100000
    provider.fetch_bars("600001", date(2025, 12, 1), date(2026, 1, 29))
    assert [item.args[0] for item in call.call_args_list] == ["bars"] * 3 + ["bars-sina"] * 2
    assert call.call_args_list[3].args[1] == ("600000", "20251201", "20260129")
    logs = [row for row in caplog.records if row.message == "trend_provider_attempt_failed"]
    assert [row.__dict__["attempt"] for row in logs] == [1, 2, 3]
    assert logs[-1].__dict__["exception_type"] == "ConnectionError"
    assert "Traceback" in logs[-1].__dict__["provider_traceback"]
    assert "private-value" not in logs[-1].__dict__["url"]


def test_malformed_daily_values_are_not_hidden_by_fallback(monkeypatch: pytest.MonkeyPatch) -> None:
    call = Mock(return_value=[{"日期": "2026-01-29"}])
    monkeypatch.setattr(
        "a_stock_lab.features.trend_radar.adapters.akshare.ProviderProcessPool.request", call
    )
    monkeypatch.setattr("time.sleep", lambda _: None)
    with pytest.raises(TrendError, match="provider_malformed_bars"):
        AkShareTrendProvider(TrendSettings(_env_file=None)).fetch_bars(
            "600000", date(2025, 12, 1), date(2026, 1, 29)
        )
    assert call.call_count == 1


def test_sina_normalizes_actual_shares_to_lots(monkeypatch: pytest.MonkeyPatch) -> None:
    import pandas as pd  # type: ignore[import-untyped]

    from a_stock_lab.features.trend_radar.adapters.provider_process import fetch_frame

    sdk = Mock(
        return_value=pd.DataFrame(
            [
                {
                    "date": "2026-01-29",
                    "open": 10,
                    "high": 11,
                    "low": 9,
                    "close": 10,
                    "volume": 12345,
                    "amount": 123456,
                }
            ]
        )
    )
    monkeypatch.setattr("akshare.stock_zh_a_daily", sdk)
    frame = fetch_frame("bars-sina", ["600000", "20251201", "20260129"])
    assert frame.iloc[0]["成交量"] == 123.45
    assert frame.iloc[0]["成交额"] == 123456
    sdk.assert_called_once_with(
        symbol="sh600000", start_date="20251201", end_date="20260129", adjust="qfq"
    )


def test_recovery_allows_one_primary_probe_while_other_workers_use_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    provider = AkShareTrendProvider(TrendSettings(_env_file=None))
    provider._primary_retry_at = 1
    entered, release = Event(), Event()
    calls: list[str] = []
    lock = Lock()

    def fetch(action: str, *args: str) -> list[dict[str, object]]:
        with lock:
            calls.append(action)
        if action == "bars":
            entered.set()
            assert release.wait(timeout=5)
        return [
            {
                "日期": "2026-01-29",
                "开盘": 10,
                "最高": 11,
                "最低": 9,
                "收盘": 10,
                "成交量": 100,
                "成交额": 100000,
            }
        ]

    monkeypatch.setattr(provider, "_fetch", fetch)
    with ThreadPoolExecutor(max_workers=3) as executor:
        first = executor.submit(provider.fetch_bars, "600000", date(2026, 1, 1), date(2026, 1, 29))
        try:
            assert entered.wait(timeout=5)
            others = [
                executor.submit(provider.fetch_bars, symbol, date(2026, 1, 1), date(2026, 1, 29))
                for symbol in ("600001", "600002")
            ]
            assert all(f.result(timeout=5)[0].source == "sina_daily_qfq" for f in others)
        finally:
            release.set()
        assert first.result()[0].source == "eastmoney_daily_qfq"
    assert calls.count("bars") == 1 and calls.count("bars-sina") == 2
    assert provider._primary_retry_at == 0


def test_request_pacing_is_shared_across_threads(monkeypatch: pytest.MonkeyPatch) -> None:
    provider = AkShareTrendProvider(TrendSettings(_env_file=None, trend_provider_pace_seconds=0.3))
    clock = [100.0]
    starts: list[float] = []
    monkeypatch.setattr("time.monotonic", lambda: clock[0])

    def sleep(delay: float) -> None:
        clock[0] += delay
        starts.append(clock[0])

    monkeypatch.setattr("time.sleep", sleep)
    with ThreadPoolExecutor(max_workers=4) as executor:
        list(executor.map(provider._pace, [0] * 8))
    assert len(starts) == 8
    assert all(b - a == pytest.approx(0.3) for a, b in pairwise(starts))

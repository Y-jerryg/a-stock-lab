from datetime import timedelta
from unittest.mock import Mock

import pytest

from a_stock_lab.features.trend_radar.application.bar_cache import resolve_bars
from a_stock_lab.features.trend_radar.domain.models import TrendError
from test_trend_radar_service import NOW, Memory, service


def test_same_session_reuses_bars_without_provider_calls() -> None:
    bars = Memory().bars
    provider = Mock(fetch_bars=Mock(side_effect=AssertionError("must reuse")))
    result, mode = resolve_bars(provider, "600000", [bar.trade_date for bar in bars], bars, NOW)
    assert result == bars and mode == "hit"
    provider.fetch_bars.assert_not_called()


def test_next_session_fetches_overlap_and_only_missing_tail() -> None:
    bars = Memory().bars
    tomorrow = NOW + timedelta(days=1)
    new = bars[-1].model_copy(update={"trade_date": tomorrow.date(), "fetched_at": tomorrow})
    fresh = [bar.model_copy(update={"fetched_at": tomorrow}) for bar in bars[-3:]] + [new]
    provider = Mock(fetch_bars=Mock(return_value=fresh))
    sessions = [bar.trade_date for bar in bars[1:]] + [tomorrow.date()]
    result, mode = resolve_bars(provider, "600000", sessions, bars, tomorrow)
    assert mode == "incremental" and len(result) == 29 and result[-1] == new
    assert result[0] == bars[1] and result[0].fetched_at == NOW
    provider.fetch_bars.assert_called_once_with("600000", bars[-3].trade_date, tomorrow.date())


@pytest.mark.parametrize("change", ["source", "adjustment", "missing_overlap"])
def test_changed_overlap_refreshes_entire_window(change: str) -> None:
    bars = Memory().bars
    fresh = list(bars[-4:])
    if change == "source":
        fresh = [bar.model_copy(update={"source": "sina_daily_qfq"}) for bar in fresh]
    elif change == "adjustment":
        fresh[0] = fresh[0].model_copy(update={"close": fresh[0].close - 0.01})
    else:
        fresh = fresh[1:]
    provider = Mock(fetch_bars=Mock(side_effect=[fresh, bars]))
    result, mode = resolve_bars(
        provider, "600000", [bar.trade_date for bar in bars], bars[:-1], NOW
    )
    assert mode == "full" and result == bars
    assert provider.fetch_bars.call_count == 2
    provider.fetch_bars.assert_called_with("600000", bars[0].trade_date, NOW.date())


def test_gap_in_middle_is_backfilled_and_periodic_refresh_is_bounded() -> None:
    bars = Memory().bars
    provider = Mock(fetch_bars=Mock(return_value=bars[5:]))
    result, mode = resolve_bars(
        provider, "600000", [bar.trade_date for bar in bars], bars[:5] + bars[6:], NOW
    )
    assert mode == "incremental" and result == bars
    provider.fetch_bars.assert_called_once_with("600000", bars[5].trade_date, NOW.date())
    provider.fetch_bars.return_value = bars
    _, mode = resolve_bars(
        provider, "600000", [bar.trade_date for bar in bars], bars, NOW + timedelta(days=7)
    )
    assert mode == "full"
    provider.fetch_bars.assert_called_with("600000", bars[0].trade_date, NOW.date())


def test_invalid_provider_tail_cannot_be_hidden_by_merge() -> None:
    bars = Memory().bars
    provider = Mock(fetch_bars=Mock(return_value=[*bars[-3:], bars[-1]]))
    with pytest.raises(TrendError, match="invalid_market_sequence"):
        resolve_bars(provider, "600000", [bar.trade_date for bar in bars], bars[:-1], NOW)


def test_cache_reuse_does_not_skip_screening_or_refresh_attention(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    memory = Memory()
    fetch_heat = Mock(wraps=memory.fetch_heat)
    fetch_bars = Mock(side_effect=AssertionError("must reuse"))
    monkeypatch.setattr(memory, "fetch_heat", fetch_heat)
    monkeypatch.setattr(memory, "fetch_bars", fetch_bars)
    monkeypatch.setattr(memory, "load_bars", lambda *_: memory.bars)
    run = service(memory).scan("cli")
    assert run and run.candidate_count == 1 and run.successful_count == 1
    fetch_heat.assert_called_once()
    fetch_bars.assert_not_called()

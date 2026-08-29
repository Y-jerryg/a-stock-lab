from datetime import datetime

import pytest

from a_stock_lab.core.time import MARKET_TIME_ZONE
from a_stock_lab.shared.market_data.errors import MarketDataQualityError
from a_stock_lab.shared.market_data.models import (
    MarketDataCapability,
    MarketSnapshotRecord,
    NormalizationIssue,
    NormalizationIssueCode,
    ProviderSnapshotBatch,
    SnapshotQualityThresholds,
)
from a_stock_lab.shared.market_data.quality import evaluate_snapshot_quality
from a_stock_lab.shared.market_data.service import FullMarketSnapshotService

NOW = datetime(2026, 8, 28, 14, 30, tzinfo=MARKET_TIME_ZONE)


def record(
    symbol: str,
    *,
    price: float | None = 10,
    pct_change: float | None = 1,
) -> MarketSnapshotRecord:
    return MarketSnapshotRecord(
        symbol=symbol,
        name="Test",
        price=price,
        pct_change=pct_change,
        provider="fake",
        fetched_at=NOW,
    )


def strict_thresholds(*, min_record_count: int = 1) -> SnapshotQualityThresholds:
    return SnapshotQualityThresholds(
        min_record_count=min_record_count,
        max_duplicate_symbols=0,
        max_missing_symbol_ratio=0,
        max_invalid_price_ratio=0,
        max_invalid_pct_change_ratio=0,
        max_malformed_row_ratio=0,
        max_abs_pct_change=100,
    )


def test_quality_report_detects_every_required_failure_class() -> None:
    batch = ProviderSnapshotBatch(
        provider="fake",
        raw_record_count=4,
        records=(
            record("600000", price=-1, pct_change=1_001),
            record("600000"),
        ),
        normalization_issues=(
            NormalizationIssue(
                row_number=3,
                code=NormalizationIssueCode.MISSING_SYMBOL,
                field="symbol",
            ),
            NormalizationIssue(
                row_number=4,
                code=NormalizationIssueCode.INVALID_NUMERIC_VALUE,
                field="price",
            ),
        ),
    )

    report = evaluate_snapshot_quality(batch, strict_thresholds())

    assert report.passed is False
    assert report.duplicate_symbol_count == 1
    assert report.missing_symbol_count == 1
    assert report.invalid_price_count == 2
    assert report.invalid_pct_change_count == 1
    assert report.malformed_row_count == 2
    assert set(report.violations) == {
        "duplicate_symbols_exceeded",
        "missing_symbol_ratio_exceeded",
        "invalid_price_ratio_exceeded",
        "invalid_pct_change_ratio_exceeded",
        "malformed_row_ratio_exceeded",
    }


class FakeProvider:
    provider_id = "fake"
    capabilities = frozenset({MarketDataCapability.FULL_MARKET_SNAPSHOT})

    def __init__(self, batch: ProviderSnapshotBatch) -> None:
        self._batch = batch

    def fetch_full_market_snapshot(self) -> ProviderSnapshotBatch:
        return self._batch


def test_catastrophic_partial_response_never_becomes_official_snapshot() -> None:
    batch = ProviderSnapshotBatch(
        provider="fake",
        raw_record_count=1,
        records=(record("600000"),),
    )
    service = FullMarketSnapshotService(
        provider=FakeProvider(batch),
        thresholds=strict_thresholds(min_record_count=2),
        clock=lambda: NOW,
        timer=iter((10.0, 10.25)).__next__,
    )

    with pytest.raises(MarketDataQualityError) as error:
        service.fetch()

    assert error.value.report.violations == ("record_count_below_minimum",)
    assert error.value.latency_ms == 250


def test_valid_batch_receives_a_versioned_manifest() -> None:
    batch = ProviderSnapshotBatch(
        provider="fake",
        raw_record_count=1,
        records=(record("600000"),),
        provider_metadata={"source_version": "test"},
    )
    service = FullMarketSnapshotService(
        provider=FakeProvider(batch),
        thresholds=strict_thresholds(),
        clock=lambda: NOW,
        timer=iter((10.0, 10.125)).__next__,
    )

    snapshot = service.fetch()

    assert snapshot.manifest.schema_version == 1
    assert snapshot.manifest.record_count == 1
    assert snapshot.manifest.latency_ms == 125
    assert snapshot.manifest.quality_report.passed is True
    assert snapshot.manifest.provider_metadata == {"source_version": "test"}

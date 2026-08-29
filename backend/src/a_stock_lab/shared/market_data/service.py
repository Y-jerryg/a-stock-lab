from collections.abc import Callable
from datetime import datetime
from time import perf_counter
from uuid import uuid4

from a_stock_lab.core.time import as_market_timezone, now_in_market_timezone
from a_stock_lab.shared.market_data.contracts import MarketDataProvider
from a_stock_lab.shared.market_data.errors import (
    MarketDataQualityError,
    ProviderInvalidResponseError,
)
from a_stock_lab.shared.market_data.models import (
    FullMarketSnapshot,
    MarketDataCapability,
    SnapshotManifest,
    SnapshotQualityThresholds,
)
from a_stock_lab.shared.market_data.quality import evaluate_snapshot_quality

SNAPSHOT_SCHEMA_VERSION = 2


class FullMarketSnapshotService:
    """Accept a provider batch only after provider-independent quality validation."""

    def __init__(
        self,
        *,
        provider: MarketDataProvider,
        thresholds: SnapshotQualityThresholds,
        clock: Callable[[], datetime] = now_in_market_timezone,
        timer: Callable[[], float] = perf_counter,
    ) -> None:
        self._provider = provider
        self._thresholds = thresholds
        self._clock = clock
        self._timer = timer

    @property
    def provider_id(self) -> str:
        return self._provider.provider_id

    def fetch(self) -> FullMarketSnapshot:
        if MarketDataCapability.FULL_MARKET_SNAPSHOT not in self._provider.capabilities:
            raise ProviderInvalidResponseError(
                provider=self._provider.provider_id,
                message="provider does not declare full-market snapshot capability",
            )

        actual_fetch_started_at = as_market_timezone(self._clock())
        timer_started_at = self._timer()
        batch = self._provider.fetch_full_market_snapshot()
        latency_ms = round((self._timer() - timer_started_at) * 1_000, 3)
        actual_fetch_finished_at = as_market_timezone(self._clock())

        if batch.provider != self._provider.provider_id:
            raise ProviderInvalidResponseError(
                provider=self._provider.provider_id,
                message="provider identity did not match the returned batch",
            )
        if any(
            not actual_fetch_started_at <= record.fetched_at <= actual_fetch_finished_at
            for record in batch.records
        ):
            raise ProviderInvalidResponseError(
                provider=self._provider.provider_id,
                message="record fetch timestamp fell outside the observed provider call",
            )

        quality_report = evaluate_snapshot_quality(batch, self._thresholds)
        if not quality_report.passed:
            raise MarketDataQualityError(
                provider=batch.provider,
                report=quality_report,
                actual_fetch_started_at=actual_fetch_started_at,
                actual_fetch_finished_at=actual_fetch_finished_at,
                latency_ms=latency_ms,
            )

        manifest = SnapshotManifest(
            snapshot_id=uuid4(),
            provider=batch.provider,
            provider_version=batch.provider_version,
            provider_timestamp=batch.provider_timestamp,
            actual_fetch_started_at=actual_fetch_started_at,
            actual_fetch_finished_at=actual_fetch_finished_at,
            latency_ms=latency_ms,
            record_count=len(batch.records),
            schema_version=SNAPSHOT_SCHEMA_VERSION,
            provider_metadata=batch.provider_metadata,
            quality_report=quality_report,
        )
        return FullMarketSnapshot(manifest=manifest, records=batch.records)

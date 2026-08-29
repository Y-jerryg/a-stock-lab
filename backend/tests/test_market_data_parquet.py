import json
from datetime import datetime
from pathlib import Path
from uuid import UUID

import pyarrow.parquet as pq  # type: ignore[import-untyped]
import pytest

from a_stock_lab.core.time import MARKET_TIME_ZONE
from a_stock_lab.shared.market_data.adapters.parquet import ParquetMarketSnapshotWriter
from a_stock_lab.shared.market_data.errors import SnapshotPersistenceError
from a_stock_lab.shared.market_data.models import (
    FullMarketSnapshot,
    MarketSnapshotRecord,
    SnapshotManifest,
    SnapshotQualityReport,
    SnapshotQualityThresholds,
)


def valid_snapshot(snapshot_id: str) -> FullMarketSnapshot:
    timestamp = datetime(2026, 8, 28, 14, 30, tzinfo=MARKET_TIME_ZONE)
    report = SnapshotQualityReport(
        passed=True,
        raw_record_count=1,
        normalized_record_count=1,
        duplicate_symbol_count=0,
        missing_symbol_count=0,
        invalid_price_count=0,
        invalid_pct_change_count=0,
        malformed_row_count=0,
        missing_symbol_ratio=0,
        invalid_price_ratio=0,
        invalid_pct_change_ratio=0,
        malformed_row_ratio=0,
        thresholds=SnapshotQualityThresholds(min_record_count=1),
    )
    record = MarketSnapshotRecord(
        symbol="600000",
        name="浦发银行",
        price=10.25,
        provider="fake",
        fetched_at=timestamp,
    )
    manifest = SnapshotManifest(
        snapshot_id=UUID(snapshot_id),
        provider="fake",
        request_started_at=timestamp,
        request_finished_at=timestamp,
        latency_ms=10,
        record_count=1,
        schema_version=1,
        quality_report=report,
    )
    return FullMarketSnapshot(manifest=manifest, records=(record,))


def test_parquet_writer_persists_records_and_embedded_manifest_atomically(tmp_path: Path) -> None:
    snapshot = valid_snapshot("11111111-1111-1111-1111-111111111111")

    path = ParquetMarketSnapshotWriter(tmp_path).write(snapshot)

    assert path == (
        tmp_path
        / "market-data"
        / "2026-08-28"
        / "full-market-11111111-1111-1111-1111-111111111111.parquet"
    )
    assert not list(path.parent.glob("*.tmp"))
    table = pq.read_table(path)
    assert table.to_pylist()[0]["symbol"] == "600000"
    manifest_data = json.loads(
        table.schema.metadata[b"a_stock_lab.snapshot_manifest"].decode("utf-8")
    )
    assert manifest_data["snapshot_id"] == "11111111-1111-1111-1111-111111111111"
    assert manifest_data["quality_report"]["passed"] is True


def test_parquet_writer_maps_storage_failure_and_removes_temporary_file(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    snapshot = valid_snapshot("22222222-2222-2222-2222-222222222222")

    def fail_write(*_: object, **__: object) -> None:
        raise OSError("simulated storage failure")

    monkeypatch.setattr(pq, "write_table", fail_write)
    writer = ParquetMarketSnapshotWriter(tmp_path)

    with pytest.raises(SnapshotPersistenceError):
        writer.write(snapshot)

    target_directory = tmp_path / "market-data" / "2026-08-28"
    assert not list(target_directory.glob("*.tmp"))
    assert not list(target_directory.glob("*.parquet"))

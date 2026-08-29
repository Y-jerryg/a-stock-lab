import json
from datetime import datetime
from hashlib import sha256
from pathlib import Path
from uuid import UUID, uuid4

import pyarrow.parquet as pq  # type: ignore[import-untyped]
import pytest

from a_stock_lab.core.time import MARKET_TIME_ZONE
from a_stock_lab.shared.market_data.adapters.parquet import (
    ParquetMarketSnapshotReader,
    ParquetMarketSnapshotWriter,
)
from a_stock_lab.shared.market_data.errors import (
    SnapshotArtifactIntegrityError,
    SnapshotPersistenceError,
)
from a_stock_lab.shared.market_data.models import (
    FullMarketSnapshot,
    MarketSnapshotRecord,
    SnapshotManifest,
    SnapshotManifestStatus,
    SnapshotQualityReport,
    SnapshotQualityThresholds,
)
from a_stock_lab.shared.market_data.persistence_schemas import PersistedSnapshotManifest


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
        actual_fetch_started_at=timestamp,
        actual_fetch_finished_at=timestamp,
        latency_ms=10,
        record_count=1,
        schema_version=1,
        quality_report=report,
    )
    return FullMarketSnapshot(manifest=manifest, records=(record,))


def test_parquet_writer_persists_records_and_embedded_manifest_atomically(tmp_path: Path) -> None:
    snapshot = valid_snapshot("11111111-1111-1111-1111-111111111111")

    writer = ParquetMarketSnapshotWriter(tmp_path)
    stored = writer.write(snapshot)
    path = tmp_path / stored.storage_key

    assert stored.storage_key == (
        "market-data/2026-08-28/full-market-11111111-1111-1111-1111-111111111111.parquet"
    )
    assert len(stored.checksum_sha256) == 64
    assert stored.checksum_sha256 == sha256(path.read_bytes()).hexdigest()
    assert stored.size_bytes == path.stat().st_size
    assert not list(path.parent.glob("*.tmp"))
    table = pq.read_table(path)
    assert table.to_pylist()[0]["symbol"] == "600000"
    manifest_data = json.loads(
        table.schema.metadata[b"a_stock_lab.snapshot_manifest"].decode("utf-8")
    )
    assert manifest_data["snapshot_id"] == "11111111-1111-1111-1111-111111111111"
    assert manifest_data["quality_report"]["passed"] is True

    with pytest.raises(SnapshotPersistenceError):
        writer.write(snapshot)
    assert stored.checksum_sha256 == sha256(path.read_bytes()).hexdigest()


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


def test_parquet_reader_verifies_checksum_and_embedded_snapshot_identity(tmp_path: Path) -> None:
    snapshot = valid_snapshot("33333333-3333-3333-3333-333333333333")
    stored = ParquetMarketSnapshotWriter(tmp_path).write(snapshot)
    timestamp = snapshot.manifest.actual_fetch_finished_at
    persisted = PersistedSnapshotManifest(
        snapshot_id=snapshot.manifest.snapshot_id,
        run_id=uuid4(),
        trade_date=timestamp.date(),
        intended_snapshot_time=timestamp,
        actual_fetch_started_at=snapshot.manifest.actual_fetch_started_at,
        actual_fetch_finished_at=timestamp,
        provider=snapshot.manifest.provider,
        provider_metadata={},
        storage_key=stored.storage_key,
        checksum_sha256=stored.checksum_sha256,
        row_count=1,
        latency_ms=snapshot.manifest.latency_ms,
        quality_report=snapshot.manifest.quality_report,
        schema_version=snapshot.manifest.schema_version,
        status=SnapshotManifestStatus.AVAILABLE,
        persisted_at=timestamp,
    )
    reader = ParquetMarketSnapshotReader(tmp_path)

    assert reader.read(persisted) == snapshot

    path = tmp_path / stored.storage_key
    path.write_bytes(path.read_bytes() + b"tampered")
    with pytest.raises(SnapshotArtifactIntegrityError, match="checksum"):
        reader.read(persisted)

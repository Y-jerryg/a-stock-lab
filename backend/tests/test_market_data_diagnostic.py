import json
from datetime import datetime
from pathlib import Path

import pytest

from a_stock_lab.core.config import Settings
from a_stock_lab.core.time import MARKET_TIME_ZONE
from a_stock_lab.shared.market_data import diagnostic
from a_stock_lab.shared.market_data.errors import SnapshotPersistenceError
from a_stock_lab.shared.market_data.models import (
    FullMarketSnapshot,
    MarketDataCapability,
    MarketSnapshotRecord,
    ProviderSnapshotBatch,
)


class FakeProvider:
    provider_id = "fake"
    capabilities = frozenset({MarketDataCapability.FULL_MARKET_SNAPSHOT})

    def fetch_full_market_snapshot(self) -> ProviderSnapshotBatch:
        fetched_at = datetime(2026, 8, 29, 14, 30, tzinfo=MARKET_TIME_ZONE)
        return ProviderSnapshotBatch(
            provider=self.provider_id,
            raw_record_count=1,
            records=(
                MarketSnapshotRecord(
                    symbol="600000",
                    name="Test",
                    price=10,
                    provider=self.provider_id,
                    fetched_at=fetched_at,
                ),
            ),
        )


def diagnostic_settings(runtime_data_dir: Path) -> Settings:
    return Settings(runtime_data_dir=runtime_data_dir, market_snapshot_min_records=1)


def test_diagnostic_is_non_persistent_by_default(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(diagnostic, "get_settings", lambda: diagnostic_settings(tmp_path))
    monkeypatch.setattr(diagnostic, "build_market_data_provider", lambda _: FakeProvider())

    exit_code = diagnostic.main([])

    payload = json.loads(capsys.readouterr().out)
    assert exit_code == 0
    assert payload["status"] == "success"
    assert payload["record_count"] == 1
    assert payload["quality_report"]["passed"] is True
    assert payload["sample_records"][0]["symbol"] == "600000"
    assert payload["persisted_to"] is None
    assert not (tmp_path / "market-data").exists()


def test_diagnostic_persists_only_with_explicit_flag(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(diagnostic, "get_settings", lambda: diagnostic_settings(tmp_path))
    monkeypatch.setattr(diagnostic, "build_market_data_provider", lambda _: FakeProvider())

    exit_code = diagnostic.main(["--persist", "--samples", "1"])

    payload = json.loads(capsys.readouterr().out)
    persisted_to = Path(payload["persisted_to"])
    assert exit_code == 0
    assert persisted_to.is_file()
    assert persisted_to.is_relative_to(tmp_path / "market-data")


def test_diagnostic_reports_persistence_failure_as_an_observation(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FailingWriter:
        def __init__(self, _: Path) -> None:
            pass

        def write(self, _: FullMarketSnapshot) -> Path:
            raise SnapshotPersistenceError(target=tmp_path / "snapshot.parquet")

    monkeypatch.setattr(diagnostic, "get_settings", lambda: diagnostic_settings(tmp_path))
    monkeypatch.setattr(diagnostic, "build_market_data_provider", lambda _: FakeProvider())
    monkeypatch.setattr(diagnostic, "ParquetMarketSnapshotWriter", FailingWriter)

    exit_code = diagnostic.main(["--persist"])

    payload = json.loads(capsys.readouterr().out)
    assert exit_code == 1
    assert payload["status"] == "persistence_failed"
    assert payload["record_count"] == 1
    assert payload["quality_report"]["passed"] is True
    assert payload["error_type"] == "SnapshotPersistenceError"

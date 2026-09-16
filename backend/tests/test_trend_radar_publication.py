import importlib.util
import json
from datetime import timedelta
from pathlib import Path
from unittest.mock import Mock
from zipfile import ZipFile

import pytest

from a_stock_lab.features.trend_radar.adapters.heartbeat import LocalWorkerHeartbeat
from a_stock_lab.features.trend_radar.adapters.static_publication import StaticResultPublisher
from a_stock_lab.features.trend_radar.domain.models import TrendError
from a_stock_lab.features.trend_radar.domain.publication import PublicRunDetails
from test_trend_radar_service import NOW, Batch, Memory, service


def test_publication_is_read_only_allowlisted_and_keeps_previous_success(tmp_path: Path) -> None:
    memory = Memory()
    scanner = service(memory)
    publisher = StaticResultPublisher(memory, tmp_path / "public")
    scanner.publisher = publisher
    first = scanner.scan("cli")
    assert first and first.status == "success"
    # Even a historical configuration containing private fields must not publish them.
    memory.save_run(
        first.model_copy(
            update={
                "configuration_snapshot": {
                    **first.configuration_snapshot,
                    "private_key": "never-publish",
                },
                "exclusions": {"600001": "private operational detail"},
            }
        )
    )
    memory.failure = True
    scanner.clock = lambda: NOW + timedelta(minutes=10)
    second = scanner.scan("cli")
    assert second and second.status == "failed"
    index = json.loads((tmp_path / "public/index.json").read_text())
    assert index["latest"]["id"] == str(first.id)
    assert index["attempts"][0]["status"] == "failed"
    assert index["latest"]["payload"]["configuration_snapshot"]["rule_version"] == 2
    assert index["latest"]["payload"]["configuration_snapshot"]["universe_scope"] == "all_a"
    assert index["latest"]["payload"]["configuration_snapshot"]["max_single_pullback_pct"] is None
    assert "never-publish" not in json.dumps(index)
    assert "exclusions" not in json.dumps(index)
    assert "provider_timeout_seconds" not in json.dumps(index)
    (tmp_path / "public/private.txt").write_text("not public")
    bundle = tmp_path / "public.zip"
    publisher.bundle(bundle)
    with ZipFile(bundle) as archive:
        assert set(archive.namelist()) == {
            "index.json",
            f"runs/{first.id}.json",
            f"details/{first.id}.json",
        }
        details = json.loads(archive.read(f"details/{first.id}.json"))
        assert len(details["details"][0]["bars"]) == 29
        assert "never-publish" not in json.dumps(details) and "exclusions" not in json.dumps(
            details
        )


def test_historical_rules_remain_legacy_when_exported(tmp_path: Path) -> None:
    memory = Memory()
    run = service(memory).scan("cli")
    assert run
    legacy = dict(run.configuration_snapshot)
    legacy.pop("rule_version")
    legacy.pop("universe_scope")
    legacy.update(max_pullback_days=3, max_single_pullback_pct=1.5)
    memory.save_run(run.model_copy(update={"configuration_snapshot": legacy}))
    StaticResultPublisher(memory, tmp_path).publish()
    config = json.loads((tmp_path / "index.json").read_text())["latest"]["payload"][
        "configuration_snapshot"
    ]
    assert config["rule_version"] == 1 and config["universe_scope"] == "top_heat"
    assert config["max_pullback_days"] == 3 and config["max_single_pullback_pct"] == 1.5


def test_progress_export_does_not_read_historical_evidence(tmp_path: Path) -> None:
    memory = Memory()
    assert service(memory).scan("cli")
    publisher = StaticResultPublisher(memory, tmp_path)
    publisher.publish()
    memory.candidate_inputs = Mock(side_effect=AssertionError("no historical IO"))  # type: ignore[method-assign]
    memory.public_results = Mock(side_effect=AssertionError("no historical IO"))  # type: ignore[method-assign]
    publisher.publish_progress()


def test_bundle_keeps_latest_and_bounds_public_history(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    memory = Memory()
    old = service(memory).scan("cli")
    latest = service(memory, NOW + timedelta(minutes=1)).scan("cli")
    assert old and latest
    publisher = StaticResultPublisher(memory, tmp_path / "export")
    publisher.publish()
    index_size = (publisher.directory / "index.json").stat().st_size
    latest_size = sum(
        (publisher.directory / folder / f"{latest.id}.json").stat().st_size
        for folder in ("runs", "details")
    )
    limit = index_size + latest_size + 10
    monkeypatch.setattr(
        "a_stock_lab.features.trend_radar.adapters.static_publication.MAX_BUNDLE_BYTES", limit
    )
    destination = tmp_path / "bounded.zip"
    publisher.bundle(destination)
    with ZipFile(destination) as archive:
        assert sum(item.file_size for item in archive.infolist()) <= limit
        index = json.loads(archive.read("index.json"))
        assert index["latest"]["id"] == str(latest.id)
        assert [run["id"] for run in index["attempts"]] == [str(latest.id)]
        assert f"runs/{old.id}.json" not in archive.namelist()
    # Public retention never removes local history or the previous valid bundle on failure.
    assert len(memory.public_runs()) == 2
    previous = destination.read_bytes()
    monkeypatch.setattr(
        "a_stock_lab.features.trend_radar.adapters.static_publication.MAX_BUNDLE_BYTES", 1
    )
    with pytest.raises(TrendError, match="publication_latest_exceeds_bundle_limit"):
        publisher.bundle(destination)
    assert destination.read_bytes() == previous


def test_published_chart_is_bounded_without_changing_saved_evidence(tmp_path: Path) -> None:
    memory = Memory()
    run = service(memory).scan("cli")
    assert run
    bars = memory.inputs[run.id]["600000"]
    older = [
        bar.model_copy(update={"trade_date": bar.trade_date - timedelta(days=29)}) for bar in bars
    ]
    memory.inputs[run.id]["600000"] = older + bars
    StaticResultPublisher(memory, tmp_path).publish()
    detail = json.loads((tmp_path / "details" / f"{run.id}.json").read_text())
    assert len(detail["details"][0]["bars"]) == 29
    assert len(memory.inputs[run.id]["600000"]) == 58


def test_publication_prioritizes_attention_before_volume(tmp_path: Path) -> None:
    memory = Batch(set())
    memory.heat = memory.heat[:2]
    run = service(memory).scan("cli")  # attention threshold = 1
    assert run
    hot, cold = memory.results[run.id]
    hot = hot.model_copy(
        update={
            "is_strong_volume_contraction": False,
            "highlight_level": "normal",
            "volume_ratio": 1.0,
        }
    )
    memory.results[run.id] = [cold, hot]
    memory.save_run(run.model_copy(update={"strong_contraction_count": 1}))
    StaticResultPublisher(memory, tmp_path).publish()
    rows = json.loads((tmp_path / "runs" / f"{run.id}.json").read_text())["results"]
    assert [row["heat_rank"] for row in rows] == [1, 2]


def test_failed_export_does_not_destroy_success_and_can_retry_without_market_calls(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    memory = Memory()
    scanner = service(memory)
    scanner.publisher = Mock(publish=Mock(side_effect=TrendError("publication_error")))
    with pytest.raises(TrendError, match="publication_error"):
        scanner.scan("cli")
    assert memory.runs[-1].status == "success"
    monkeypatch.setattr(memory, "fetch_heat", Mock(side_effect=AssertionError("must not fetch")))
    StaticResultPublisher(memory, tmp_path).publish()
    assert json.loads((tmp_path / "index.json").read_text())["latest"]["status"] == "success"


def test_index_is_unchanged_when_new_results_cannot_be_written(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    memory = Memory()
    scanner = service(memory)
    scanner.publisher = StaticResultPublisher(memory, tmp_path)
    assert scanner.scan("cli")
    previous = (tmp_path / "index.json").read_bytes()
    scanner.clock = lambda: NOW + timedelta(minutes=1)
    scanner.publisher = memory
    assert scanner.scan("cli")
    monkeypatch.setattr(
        "a_stock_lab.features.trend_radar.adapters.static_publication.atomic_write",
        Mock(side_effect=OSError("disk full")),
    )
    with pytest.raises(TrendError, match="publication_error"):
        StaticResultPublisher(memory, tmp_path).publish()
    assert (tmp_path / "index.json").read_bytes() == previous


def test_bundle_validator_rejects_extra_paths_before_writing(tmp_path: Path) -> None:
    script = Path(__file__).resolve().parents[2] / "scripts/unpack-trend-data.py"
    spec = importlib.util.spec_from_file_location("unpack_trend_data", script)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    memory = Memory()
    assert service(memory).scan("cli")
    bundle = tmp_path / "public.zip"
    StaticResultPublisher(memory, tmp_path / "export").bundle(bundle)
    module.unpack(bundle, tmp_path / "valid")
    assert (tmp_path / "valid/index.json").is_file()
    with ZipFile(bundle, "a") as archive:
        archive.writestr("../secret.txt", "unexpected")
    with pytest.raises(ValueError, match="unexpected"):
        module.unpack(bundle, tmp_path / "invalid")
    assert not (tmp_path / "invalid").exists()


def test_worker_health_is_local_and_expires(tmp_path: Path) -> None:
    heartbeat = LocalWorkerHeartbeat(tmp_path / "worker.json")
    assert not heartbeat.healthy(NOW)
    heartbeat.write(NOW, "running")
    assert heartbeat.healthy(NOW + timedelta(seconds=30))
    assert not heartbeat.healthy(NOW + timedelta(seconds=61))
    heartbeat.write(NOW, "stopped")
    assert not heartbeat.healthy(NOW)


@pytest.mark.parametrize("problem", ["future", "symbol", "duplicate", "knowledge"])
def test_detail_export_rejects_inconsistent_saved_evidence(tmp_path: Path, problem: str) -> None:
    memory = Memory()
    run = service(memory).scan("cli")
    assert run
    publisher = StaticResultPublisher(memory, tmp_path)
    publisher.publish()
    previous_index = (tmp_path / "index.json").read_bytes()
    bars = memory.inputs[run.id]["600000"]
    if problem == "future":
        bars.append(bars[-1].model_copy(update={"trade_date": NOW.date() + timedelta(days=1)}))
    elif problem == "symbol":
        bars[0] = bars[0].model_copy(update={"symbol": "600001"})
    elif problem == "knowledge":
        bars[0] = bars[0].model_copy(update={"fetched_at": NOW + timedelta(hours=1)})
    else:
        bars.append(bars[-1])
    with pytest.raises(ValueError, match="saved scan boundary"):
        publisher.publish()
    assert (tmp_path / "index.json").read_bytes() == previous_index
    saved = PublicRunDetails.model_validate_json(
        (tmp_path / "details" / f"{run.id}.json").read_text()
    )
    assert len(saved.details[0].bars) == 29


def test_partial_completion_exports_coverage_and_no_private_tracebacks(tmp_path: Path) -> None:
    memory = Batch({"600127"})
    scanner = service(memory)
    scanner.config = scanner.config.model_copy(update={"trend_top_n": 300})
    run = scanner.scan("cli")
    assert run and run.status == "completed_with_warnings"
    publisher = StaticResultPublisher(memory, tmp_path / "public")
    publisher.bundle(tmp_path / "public.zip")
    index = json.loads((tmp_path / "public/index.json").read_text())
    assert index["schema_version"] == 2 and index["latest"]["id"] == str(run.id)
    payload = index["latest"]["payload"]
    assert (payload["requested_count"], payload["successful_count"], payload["failed_count"]) == (
        300,
        299,
        1,
    )
    assert payload["failed_symbols"] == [
        {"symbol": "600127", "name": "Test", "error_code": "provider_error"}
    ]
    assert "exception_message" not in json.dumps(index) and "traceback" not in json.dumps(index)
    with ZipFile(tmp_path / "public.zip") as archive:
        assert f"runs/{run.id}.json" in archive.namelist()


@pytest.mark.parametrize("problem", ["price", "future", "missing_detail", "legacy"])
def test_installer_validates_details_and_accepts_legacy_bundles(
    tmp_path: Path, problem: str
) -> None:
    script = Path(__file__).resolve().parents[2] / "scripts/unpack-trend-data.py"
    spec = importlib.util.spec_from_file_location("unpack_trend_data", script)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    memory = Memory()
    run = service(memory).scan("cli")
    assert run
    original = tmp_path / "original.zip"
    StaticResultPublisher(memory, tmp_path / "export").bundle(original)
    with ZipFile(original) as archive:
        files = {name: json.loads(archive.read(name)) for name in archive.namelist()}
    detail_path = f"details/{run.id}.json"
    if problem == "price":
        files[detail_path]["details"][0]["bars"][0]["low"] = 10000
    elif problem == "future":
        files[detail_path]["details"][0]["bars"][0]["trade_date"] = "2099-01-01"
    else:
        del files[detail_path]
        if problem == "legacy":
            del files["index.json"]["detail_schema_version"]
    changed = tmp_path / "changed.zip"
    with ZipFile(changed, "w") as archive:
        for name, content in files.items():
            archive.writestr(name, json.dumps(content))
    destination = tmp_path / "site"
    if problem == "legacy":
        module.unpack(changed, destination)
        assert (destination / "index.json").is_file()
        assert not (destination / "details").exists()
    else:
        with pytest.raises((ValueError, KeyError)):
            module.unpack(changed, destination)
        assert not destination.exists()

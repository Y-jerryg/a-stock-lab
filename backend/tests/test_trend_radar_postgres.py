"""Real PostgreSQL checks in fresh disposable databases; never mutate the supplied database."""

import os
import subprocess
import sys
from collections.abc import Iterator
from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy import Engine, create_engine, text
from sqlalchemy.engine import make_url

from a_stock_lab.features.trend_radar.adapters.postgres import PostgresTrendRepository
from a_stock_lab.features.trend_radar.adapters.static_publication import StaticResultPublisher
from a_stock_lab.features.trend_radar.domain.models import ScanBusyError, ScanRun
from test_trend_radar_service import NOW, Batch, Memory, service

pytestmark = pytest.mark.postgres
ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
def database() -> Iterator[Engine]:
    raw = os.getenv("TEST_DATABASE_URL")
    if not raw:
        pytest.skip("TEST_DATABASE_URL with CREATEDB permission is required")
    admin = create_engine(raw, isolation_level="AUTOCOMMIT")
    name = "trend_test_" + uuid4().hex
    with admin.connect() as connection:
        connection.execute(text(f'CREATE DATABASE "{name}"'))
    engine = create_engine(make_url(raw).set(database=name))
    try:
        yield engine
    finally:
        engine.dispose()
        with admin.connect() as connection:
            connection.execute(text(f'DROP DATABASE "{name}" WITH (FORCE)'))
        admin.dispose()


def test_local_migration_lock_and_idempotent_writes(database: Engine, tmp_path: Path) -> None:
    environment = dict(os.environ, DATABASE_URL=database.url.render_as_string(hide_password=False))
    result = subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        cwd=ROOT / "backend",
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    repository = PostgresTrendRepository(database)
    with repository.lock(), pytest.raises(ScanBusyError), repository.lock():
        pass
    memory = Memory()
    scanner = service(memory)
    scanner.local = repository
    scanner.publisher = StaticResultPublisher(repository, tmp_path)
    run = scanner.scan("cli")
    assert run and run.status == "success"
    repository.save_bars("600000", NOW.date(), memory.bars)
    with database.connect() as connection:
        assert connection.scalar(text("select count(*) from trend_daily_bars")) == 29
        assert connection.scalar(text("select count(*) from trend_scan_results")) == 1
        assert (
            connection.scalar(
                text("select count(*) from research_artifacts where module='trend_radar'")
            )
            == 1
        )

    assert (tmp_path / "index.json").is_file()
    assert repository.public_results(run.id)[0].symbol == "600000"
    scheduled = ScanRun(
        trigger_type="scheduled",
        started_at=NOW,
        trade_date=NOW.date(),
        configuration_snapshot=scanner.config.snapshot(),
    )
    with repository.lock():
        assert repository.begin(scheduled)
    replacement = scheduled.model_copy(update={"id": uuid4()})
    with repository.lock():
        assert not repository.begin(replacement)
    recovered = next(row for row in repository.public_runs() if row.id == scheduled.id)
    assert recovered.status == "failed" and recovered.error_message == "interrupted"
    assert next(row for row in repository.public_runs() if row.id == run.id).status == "success"
    with database.connect() as connection:
        assert connection.scalar(text("select count(*) from trend_schedule_claims")) == 1

    batch = Batch({"600002"})
    batch.heat = batch.heat[:6]
    scanner = service(batch)
    scanner.config = scanner.config.model_copy(update={"trend_top_n": 6})
    scanner.local = repository
    scanner.publisher = StaticResultPublisher(repository, tmp_path)
    partial = scanner.scan("cli")
    assert partial and partial.status == "completed_with_warnings"
    assert (partial.successful_count, partial.failed_count) == (5, 1)
    assert len(repository.public_results(partial.id)) == 5
    stored = repository.inspect(partial.id)
    assert stored and stored["status"] == "completed_with_warnings"
    with database.connect() as connection:
        assert (
            connection.scalar(
                text(
                    "select count(*) from research_artifacts "
                    "where module='trend_radar' and schema_version=2"
                )
            )
            == 6
        )

    # A shorter refreshed series must not retain rows from the older source/adjustment vintage.
    refreshed = [bar.model_copy(update={"source": "sina_daily_qfq"}) for bar in memory.bars[-10:]]
    repository.save_bars("600000", NOW.date(), refreshed)
    cached = repository.load_bars("600000", NOW.date(), NOW)
    assert cached and len(cached) == 10 and {bar.source for bar in cached} == {"sina_daily_qfq"}
    with database.connect() as connection:
        evidence = connection.scalar(
            text(
                "select input_bars from trend_scan_results where run_id=:run_id and symbol='600000'"
            ),
            {"run_id": partial.id},
        )
        assert len(evidence) == 29 and evidence[0]["source"] == "eastmoney_daily_qfq"
    from a_stock_lab.features.trend_radar.domain.publication import PublicRunDetails

    scanner.publisher.publish()
    detail = PublicRunDetails.model_validate_json(
        (tmp_path / "details" / f"{partial.id}.json").read_text()
    )
    original = next(item for item in detail.details if item.candidate.symbol == "600000")
    assert len(original.bars) == 29 and original.bars[0].source == "eastmoney_daily_qfq"

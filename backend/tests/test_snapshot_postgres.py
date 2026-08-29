import os
from datetime import datetime
from uuid import uuid4

import pytest
from pydantic import ValidationError
from sqlalchemy import create_engine, delete
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from a_stock_lab.core.time import MARKET_TIME_ZONE
from a_stock_lab.shared.execution.models import ExecutionRun, RunStatus
from a_stock_lab.shared.market_data.adapters.postgres import (
    PostgresSnapshotExecutionRepository,
)
from a_stock_lab.shared.market_data.errors import SnapshotExecutionPersistenceError
from a_stock_lab.shared.market_data.execution_models import SnapshotManifestCreate, SnapshotRunKey
from a_stock_lab.shared.market_data.models import (
    SnapshotQualityReport,
    SnapshotQualityThresholds,
)
from a_stock_lab.shared.market_data.persistence_models import MarketSnapshotManifestRecord

pytestmark = pytest.mark.postgres


def test_postgres_claims_one_official_run_and_persists_an_immutable_manifest() -> None:
    database_url = os.getenv("TEST_DATABASE_URL")
    if database_url is None:
        pytest.skip("TEST_DATABASE_URL is required for PostgreSQL integration tests")

    engine = create_engine(database_url, pool_pre_ping=True)
    factory = sessionmaker(bind=engine, expire_on_commit=False, class_=Session)
    repository = PostgresSnapshotExecutionRepository(factory)
    intended = datetime(2026, 8, 28, 14, 30, tzinfo=MARKET_TIME_ZONE)
    job_type = f"test.market_snapshot.{uuid4().hex}"
    key = SnapshotRunKey(
        job_type=job_type,
        trade_date=intended.date(),
        intended_snapshot_time=intended,
        execution_version="test-1",
    )
    run_ids = []
    snapshot_id = uuid4()

    try:
        official = repository.claim_run(
            key=key,
            provider="fake",
            started_at=intended,
            force=False,
        )
        run_ids.append(official.run.run_id)
        duplicate = repository.claim_run(
            key=key,
            provider="fake",
            started_at=intended,
            force=False,
        )
        forced = repository.claim_run(
            key=key,
            provider="fake",
            started_at=intended,
            force=True,
        )
        run_ids.append(forced.run.run_id)

        assert official.created is True
        assert duplicate.created is False
        assert duplicate.run.run_id == official.run.run_id
        assert forced.run.is_official is False
        assert forced.run.rerun_of_run_id == official.run.run_id

        quality_report = SnapshotQualityReport(
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
        persisted_at = intended.replace(minute=31)
        with pytest.raises(
            SnapshotExecutionPersistenceError,
            match="manifest does not match its claimed run",
        ):
            repository.complete_run(
                manifest=SnapshotManifestCreate(
                    snapshot_id=uuid4(),
                    run_id=official.run.run_id,
                    trade_date=intended.date(),
                    intended_snapshot_time=intended,
                    actual_fetch_started_at=intended,
                    actual_fetch_finished_at=persisted_at,
                    provider="different-provider",
                    provider_metadata={},
                    storage_key=f"market-data/2026-08-28/mismatched-{uuid4()}.parquet",
                    checksum_sha256="c" * 64,
                    row_count=1,
                    latency_ms=60_000,
                    quality_report=quality_report,
                    schema_version=2,
                    persisted_at=persisted_at,
                ),
                run_metadata={},
                finished_at=persisted_at,
            )

        completed_run, manifest = repository.complete_run(
            manifest=SnapshotManifestCreate(
                snapshot_id=snapshot_id,
                run_id=official.run.run_id,
                trade_date=intended.date(),
                intended_snapshot_time=intended,
                actual_fetch_started_at=intended,
                actual_fetch_finished_at=persisted_at,
                provider="fake",
                provider_version="fake-1",
                provider_metadata={"source": "integration-test"},
                storage_key=f"market-data/2026-08-28/full-market-{snapshot_id}.parquet",
                checksum_sha256="b" * 64,
                row_count=1,
                latency_ms=60_000,
                quality_report=quality_report,
                schema_version=2,
                persisted_at=persisted_at,
            ),
            run_metadata={"calendar": "fixture"},
            finished_at=persisted_at,
        )

        assert completed_run.status is RunStatus.SUCCEEDED
        assert repository.get_manifest(snapshot_id) == manifest
        assert repository.get_manifest_for_run(official.run.run_id) == manifest
        assert manifest.storage_key.endswith(f"{snapshot_id}.parquet")
        with pytest.raises(ValidationError, match="Instance is frozen"):
            field_name = "storage_key"
            setattr(manifest, field_name, "market-data/replaced.parquet")

        with pytest.raises(IntegrityError):
            with factory.begin() as session:
                session.add_all(
                    [
                        ExecutionRun(
                            job_type=f"{job_type}.constraint",
                            trade_date=intended.date(),
                            intended_execution_time=intended,
                            status=RunStatus.RUNNING,
                            provider="fake",
                            implementation_version="test-1",
                            is_official=True,
                            run_metadata={},
                        )
                        for _ in range(2)
                    ]
                )
                session.flush()
    finally:
        with factory.begin() as session:
            session.execute(
                delete(MarketSnapshotManifestRecord).where(
                    MarketSnapshotManifestRecord.snapshot_id == snapshot_id
                )
            )
            if run_ids:
                session.execute(
                    delete(ExecutionRun).where(ExecutionRun.run_id.in_(reversed(run_ids)))
                )
        engine.dispose()

import os
from datetime import datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, delete
from sqlalchemy.orm import Session, sessionmaker

from a_stock_lab.core.time import MARKET_TIME_ZONE
from a_stock_lab.features.tail_radar.adapters.persistence_models import TailRadarScheduleRecord
from a_stock_lab.features.tail_radar.adapters.schedule_postgres import (
    PostgresTailRadarScheduleRepository,
)
from a_stock_lab.features.tail_radar.application.scheduling_models import (
    TailRadarScheduleStatus,
)

pytestmark = pytest.mark.postgres


def test_postgres_schedule_identity_and_advisory_lock_prevent_duplicate_execution() -> None:
    database_url = os.getenv("TEST_DATABASE_URL")
    if database_url is None:
        pytest.skip("TEST_DATABASE_URL is required for PostgreSQL integration tests")
    engine = create_engine(database_url, pool_pre_ping=True)
    factory = sessionmaker(bind=engine, expire_on_commit=False, class_=Session)
    repository = PostgresTailRadarScheduleRepository(factory)
    test_year = 3000 + (uuid4().int % 6000)
    intended = datetime(test_year, 9, 1, 14, 30, tzinfo=MARKET_TIME_ZONE)
    schedule_id = None
    try:
        first = repository.ensure_schedule(
            intended_snapshot_time=intended,
            is_trading_day=True,
            calendar_provider="fixture-calendar",
            observed_at=intended - timedelta(minutes=1),
        )
        schedule_id = first.schedule_id
        duplicate = repository.ensure_schedule(
            intended_snapshot_time=intended,
            is_trading_day=True,
            calendar_provider="fixture-calendar",
            observed_at=intended,
        )

        assert duplicate.schedule_id == first.schedule_id
        assert duplicate.status is TailRadarScheduleStatus.SCHEDULED
        with repository.execution_lock(intended) as first_lock:
            with repository.execution_lock(intended) as duplicate_lock:
                assert first_lock is True
                assert duplicate_lock is False
    finally:
        if schedule_id is not None:
            with factory() as session:
                session.execute(
                    delete(TailRadarScheduleRecord).where(
                        TailRadarScheduleRecord.schedule_id == schedule_id
                    )
                )
                session.commit()
        engine.dispose()

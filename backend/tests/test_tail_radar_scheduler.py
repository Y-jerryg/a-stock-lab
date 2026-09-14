from collections.abc import Callable
from contextlib import contextmanager
from datetime import UTC, date, datetime, timedelta
from types import SimpleNamespace
from typing import Any, cast
from uuid import UUID
from zoneinfo import ZoneInfo

import pytest

from a_stock_lab.core.time import MARKET_TIME_ZONE, as_market_timezone
from a_stock_lab.features.tail_radar.application.orchestration_models import (
    TAIL_RADAR_WORKFLOW_VERSION,
    TailRadarWorkflowData,
    TailRadarWorkflowLifecycle,
)
from a_stock_lab.features.tail_radar.application.orchestration_service import (
    TailRadarApplicationService,
)
from a_stock_lab.features.tail_radar.application.scheduling_models import (
    TAIL_RADAR_SCHEDULE_JOB_NAME,
    TAIL_RADAR_SCHEDULE_VERSION,
    TailRadarPreflightReport,
    TailRadarScheduleData,
    TailRadarScheduleStatus,
)
from a_stock_lab.features.tail_radar.application.scheduling_service import (
    OFFICIAL_SNAPSHOT_TIME,
    TailRadarScheduledExecutionService,
)
from a_stock_lab.shared.execution.models import RunStatus
from a_stock_lab.shared.market_data.models import MarketDataCapability
from a_stock_lab.shared.market_data.trading_calendar import TradingDay

TRADE_DATE = date(2026, 8, 31)
INTENDED = datetime(2026, 8, 31, 14, 30, tzinfo=MARKET_TIME_ZONE)
SCHEDULE_ID = UUID("10000000-0000-4000-8000-000000000010")
WORKFLOW_ID = UUID("20000000-0000-4000-8000-000000000020")
SNAPSHOT_ID = UUID("30000000-0000-4000-8000-000000000030")


class FakeClock:
    def __init__(self, now: datetime) -> None:
        self.now = now

    def __call__(self) -> datetime:
        return self.now


class FakeCalendar:
    def __init__(self, *, trading_day: bool = True) -> None:
        self.trading_day = trading_day
        self.calls: list[date] = []

    @property
    def provider_id(self) -> str:
        return "fixture-calendar"

    def resolve(self, trade_date: date) -> TradingDay:
        self.calls.append(trade_date)
        return TradingDay(
            trade_date=trade_date,
            is_trading_day=self.trading_day,
            provider=self.provider_id,
        )


class FakeProvider:
    @property
    def provider_id(self) -> str:
        return "fixture-market"

    @property
    def capabilities(self) -> frozenset[MarketDataCapability]:
        return frozenset(
            {
                MarketDataCapability.FULL_MARKET_SNAPSHOT,
                MarketDataCapability.INTRADAY_BARS,
            }
        )


class FakeScheduleRepository:
    def __init__(self) -> None:
        self.schedule: TailRadarScheduleData | None = None
        self.lock_acquisitions = 0

    def ensure_schedule(
        self,
        *,
        intended_snapshot_time: datetime,
        is_trading_day: bool,
        calendar_provider: str,
        observed_at: datetime,
    ) -> TailRadarScheduleData:
        if self.schedule is None:
            self.schedule = TailRadarScheduleData(
                schedule_id=SCHEDULE_ID,
                job_name=TAIL_RADAR_SCHEDULE_JOB_NAME,
                schedule_version=TAIL_RADAR_SCHEDULE_VERSION,
                trade_date=intended_snapshot_time.date(),
                intended_snapshot_time=intended_snapshot_time,
                status=(
                    TailRadarScheduleStatus.SCHEDULED
                    if is_trading_day
                    else TailRadarScheduleStatus.NOT_TRADING_DAY
                ),
                is_trading_day=is_trading_day,
                calendar_provider=calendar_provider,
                created_at=observed_at,
                updated_at=observed_at,
            )
        return self.schedule

    def get_schedule(self, trade_date: date) -> TailRadarScheduleData | None:
        if self.schedule is None or self.schedule.trade_date != trade_date:
            return None
        return self.schedule

    def record_preflight(
        self,
        *,
        schedule_id: UUID,
        started_at: datetime,
        finished_at: datetime,
        report: TailRadarPreflightReport,
    ) -> TailRadarScheduleData:
        assert self.schedule is not None and schedule_id == SCHEDULE_ID
        return self._replace(
            status=(
                TailRadarScheduleStatus.PREFLIGHT_READY
                if report.ready
                else TailRadarScheduleStatus.PREFLIGHT_DEGRADED
            ),
            preflight_started_at=started_at,
            preflight_finished_at=finished_at,
            preflight_report=report,
            updated_at=finished_at,
        )

    def update_schedule(
        self,
        *,
        schedule_id: UUID,
        status: TailRadarScheduleStatus,
        observed_at: datetime,
        workflow_run_id: UUID | None = None,
        error_code: str | None = None,
        error_details: dict[str, object] | None = None,
    ) -> TailRadarScheduleData:
        assert self.schedule is not None and schedule_id == SCHEDULE_ID
        updates: dict[str, object] = {
            "status": status,
            "updated_at": observed_at,
            "error_code": error_code,
            "error_details": error_details or {},
        }
        if workflow_run_id is not None:
            updates["workflow_run_id"] = workflow_run_id
        if status is TailRadarScheduleStatus.EXECUTING:
            updates["execution_started_at"] = self.schedule.execution_started_at or observed_at
            updates["execution_finished_at"] = None
        elif status in {
            TailRadarScheduleStatus.SUCCEEDED,
            TailRadarScheduleStatus.PARTIAL_SUCCESS,
            TailRadarScheduleStatus.FAILED,
            TailRadarScheduleStatus.MISSED,
        }:
            updates["execution_finished_at"] = observed_at
        return self._replace(**updates)

    @contextmanager
    def execution_lock(self, intended_snapshot_time: datetime) -> Any:
        assert intended_snapshot_time == INTENDED
        self.lock_acquisitions += 1
        yield True

    def _replace(self, **updates: object) -> TailRadarScheduleData:
        assert self.schedule is not None
        values = self.schedule.model_dump(mode="python")
        values.update(updates)
        self.schedule = TailRadarScheduleData.model_validate(values)
        return self.schedule


class FakeWorkflowRepository:
    def __init__(self, workflow: TailRadarWorkflowData | None = None) -> None:
        self.workflow = workflow

    def get_workflow_for_intended_time(
        self, *, intended_snapshot_time: datetime, workflow_version: str
    ) -> TailRadarWorkflowData | None:
        assert intended_snapshot_time == INTENDED
        assert workflow_version == TAIL_RADAR_WORKFLOW_VERSION
        return self.workflow

    def get_workflow(self, workflow_run_id: UUID) -> TailRadarWorkflowData | None:
        return self.workflow if workflow_run_id == WORKFLOW_ID else None


class FakeApplication:
    def __init__(self, repository: FakeWorkflowRepository, *, fail: bool = False) -> None:
        self.repository = repository
        self.fail = fail
        self.execute_calls = 0
        self.resume_calls = 0

    def execute(self, *, intended_snapshot_time: datetime) -> SimpleNamespace:
        self.execute_calls += 1
        if self.fail:
            raise RuntimeError("provider unavailable")
        self.repository.workflow = workflow(TailRadarWorkflowLifecycle.SUCCEEDED)
        return SimpleNamespace(workflow=self.repository.workflow)

    def resume(self, *, workflow_run_id: UUID) -> SimpleNamespace:
        assert workflow_run_id == WORKFLOW_ID
        self.resume_calls += 1
        self.repository.workflow = workflow(TailRadarWorkflowLifecycle.SUCCEEDED)
        return SimpleNamespace(workflow=self.repository.workflow)


def workflow(lifecycle: TailRadarWorkflowLifecycle) -> TailRadarWorkflowData:
    terminal = lifecycle in {
        TailRadarWorkflowLifecycle.SUCCEEDED,
        TailRadarWorkflowLifecycle.PARTIAL_SUCCESS,
        TailRadarWorkflowLifecycle.FAILED,
    }
    return TailRadarWorkflowData(
        workflow_run_id=WORKFLOW_ID,
        trade_date=TRADE_DATE,
        intended_snapshot_time=INTENDED,
        analysis_as_of=(INTENDED + timedelta(minutes=1) if terminal else None),
        workflow_version=TAIL_RADAR_WORKFLOW_VERSION,
        lifecycle=lifecycle,
        execution_status=(
            RunStatus.FAILED
            if lifecycle is TailRadarWorkflowLifecycle.FAILED
            else RunStatus.SUCCEEDED
            if terminal
            else RunStatus.RUNNING
        ),
        snapshot_run_id=(WORKFLOW_ID if terminal else None),
        snapshot_id=(SNAPSHOT_ID if terminal else None),
        screening_run_id=None,
        candidate_count=None,
        technical_succeeded_count=0,
        technical_failed_count=0,
        technical_pending_count=0,
        research_succeeded_count=0,
        research_no_evidence_count=0,
        research_failed_count=0,
        research_pending_count=0,
        error_stage=("snapshot" if lifecycle is TailRadarWorkflowLifecycle.FAILED else None),
        error_code=(
            "provider_unavailable" if lifecycle is TailRadarWorkflowLifecycle.FAILED else None
        ),
        actual_started_at=INTENDED,
        actual_finished_at=(INTENDED + timedelta(seconds=5) if terminal else None),
        created_at=INTENDED,
        updated_at=INTENDED,
    )


def build_scheduler(
    now: datetime,
    *,
    trading_day: bool = True,
    existing_workflow: TailRadarWorkflowData | None = None,
    application_fail: bool = False,
    openai_configured: bool = True,
) -> tuple[
    TailRadarScheduledExecutionService,
    FakeScheduleRepository,
    FakeCalendar,
    FakeWorkflowRepository,
    FakeApplication,
]:
    clock = FakeClock(now)
    calendar = FakeCalendar(trading_day=trading_day)
    schedules = FakeScheduleRepository()
    workflows = FakeWorkflowRepository(existing_workflow)
    application = FakeApplication(workflows, fail=application_fail)
    scheduler = TailRadarScheduledExecutionService(
        trading_calendar=calendar,
        market_data_provider=FakeProvider(),  # type: ignore[arg-type]
        schedule_repository=schedules,
        workflow_repository=workflows,  # type: ignore[arg-type]
        application_factory=cast(
            Callable[[], TailRadarApplicationService],
            lambda: application,
        ),
        openai_configured=openai_configured,
        clock=clock,
    )
    return scheduler, schedules, calendar, workflows, application


def test_trading_day_preflight_and_official_execution_are_idempotent() -> None:
    scheduler, schedules, _, _, application = build_scheduler(INTENDED - timedelta(seconds=30))

    preflight = scheduler.tick()
    assert preflight.status is TailRadarScheduleStatus.PREFLIGHT_READY
    assert preflight.preflight_report is not None

    scheduler._clock.now = INTENDED  # type: ignore[attr-defined]
    first = scheduler.tick()
    second = scheduler.tick()

    assert first.status is TailRadarScheduleStatus.SUCCEEDED
    assert second.status is TailRadarScheduleStatus.SUCCEEDED
    assert first.intended_snapshot_time == INTENDED
    assert application.execute_calls == 1
    assert schedules.lock_acquisitions == 1


def test_missing_openai_configuration_does_not_degrade_deterministic_preflight() -> None:
    scheduler, _, _, _, _ = build_scheduler(
        INTENDED - timedelta(seconds=30),
        openai_configured=False,
    )

    preflight = scheduler.tick()

    assert preflight.status is TailRadarScheduleStatus.PREFLIGHT_READY
    assert preflight.preflight_report is not None
    assert preflight.preflight_report.openai_configured is False


def test_holiday_never_executes_a_workflow() -> None:
    scheduler, _, calendar, _, application = build_scheduler(INTENDED, trading_day=False)

    result = scheduler.tick()

    assert result.status is TailRadarScheduleStatus.NOT_TRADING_DAY
    assert calendar.calls == [TRADE_DATE]
    assert application.execute_calls == 0


def test_provider_failure_is_recorded_without_fabricating_success() -> None:
    scheduler, _, _, _, application = build_scheduler(INTENDED, application_fail=True)

    result = scheduler.tick()

    assert result.status is TailRadarScheduleStatus.FAILED
    assert result.error_code == "RuntimeError"
    assert application.execute_calls == 1


def test_restart_resumes_an_existing_in_progress_workflow() -> None:
    active = workflow(TailRadarWorkflowLifecycle.SNAPSHOT_RUNNING)
    scheduler, schedules, _, _, application = build_scheduler(
        INTENDED + timedelta(seconds=10),
        existing_workflow=active,
    )
    schedules.ensure_schedule(
        intended_snapshot_time=INTENDED,
        is_trading_day=True,
        calendar_provider="fixture-calendar",
        observed_at=INTENDED,
    )
    schedules.update_schedule(
        schedule_id=SCHEDULE_ID,
        status=TailRadarScheduleStatus.EXECUTING,
        observed_at=INTENDED,
        workflow_run_id=WORKFLOW_ID,
    )

    result = scheduler.tick()

    assert result.status is TailRadarScheduleStatus.SUCCEEDED
    assert application.execute_calls == 0
    assert application.resume_calls == 1


def test_late_start_is_preserved_as_missed_and_never_backdated() -> None:
    scheduler, _, _, _, application = build_scheduler(INTENDED + timedelta(seconds=31))

    result = scheduler.tick()

    assert result.status is TailRadarScheduleStatus.MISSED
    assert result.workflow_run_id is None
    assert result.error_code == "official_snapshot_start_window_missed"
    assert application.execute_calls == 0


def test_schedule_is_independent_of_utc_or_system_timezone() -> None:
    utc_now = datetime(2026, 8, 31, 6, 30, tzinfo=UTC)
    tokyo_now = datetime(2026, 8, 31, 15, 30, tzinfo=ZoneInfo("Asia/Tokyo"))
    utc_scheduler, _, _, _, _ = build_scheduler(utc_now)
    tokyo_scheduler, _, _, _, _ = build_scheduler(tokyo_now)

    utc_result = utc_scheduler.tick()
    tokyo_result = tokyo_scheduler.tick()

    assert utc_result.intended_snapshot_time == INTENDED
    assert tokyo_result.intended_snapshot_time == INTENDED
    assert utc_result.intended_snapshot_time.utcoffset() == timedelta(hours=8)


@pytest.mark.parametrize(
    "utc_observation",
    [
        datetime(2026, 1, 15, 6, 30, tzinfo=UTC),
        datetime(2026, 7, 15, 6, 30, tzinfo=UTC),
    ],
)
def test_official_slot_does_not_shift_with_daylight_seasons(
    utc_observation: datetime,
) -> None:
    shanghai_observation = as_market_timezone(utc_observation)
    intended = datetime.combine(
        shanghai_observation.date(), OFFICIAL_SNAPSHOT_TIME, MARKET_TIME_ZONE
    )

    assert intended.hour == 14
    assert intended.minute == 30
    assert intended.utcoffset() == timedelta(hours=8)

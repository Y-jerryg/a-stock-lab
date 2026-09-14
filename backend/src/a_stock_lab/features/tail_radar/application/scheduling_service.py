from collections.abc import Callable
from datetime import date, datetime, time, timedelta

from a_stock_lab.core.logging import get_logger
from a_stock_lab.core.time import MARKET_TIME_ZONE, as_market_timezone, now_in_market_timezone
from a_stock_lab.features.tail_radar.application.contracts import (
    TailRadarScheduleRepository,
    TailRadarWorkflowRepository,
)
from a_stock_lab.features.tail_radar.application.orchestration_models import (
    TAIL_RADAR_WORKFLOW_VERSION,
    TailRadarWorkflowData,
    TailRadarWorkflowLifecycle,
)
from a_stock_lab.features.tail_radar.application.orchestration_service import (
    TailRadarApplicationService,
)
from a_stock_lab.features.tail_radar.application.scheduling_models import (
    TailRadarPreflightReport,
    TailRadarScheduleData,
    TailRadarScheduleStatus,
)
from a_stock_lab.features.tail_radar.domain.errors import TailRadarSchedulingError
from a_stock_lab.shared.market_data.contracts import MarketDataProvider, TradingCalendar
from a_stock_lab.shared.market_data.models import MarketDataCapability

OFFICIAL_SNAPSHOT_TIME = time(hour=14, minute=30)
logger = get_logger(__name__)


class TailRadarScheduledExecutionService:
    """Make one deterministic scheduling decision for the official Shanghai slot."""

    def __init__(
        self,
        *,
        trading_calendar: TradingCalendar,
        market_data_provider: MarketDataProvider,
        schedule_repository: TailRadarScheduleRepository,
        workflow_repository: TailRadarWorkflowRepository,
        application_factory: Callable[[], TailRadarApplicationService],
        openai_configured: bool,
        preflight_lead: timedelta = timedelta(seconds=60),
        maximum_start_delay: timedelta = timedelta(seconds=30),
        clock: Callable[[], datetime] = now_in_market_timezone,
    ) -> None:
        if preflight_lead <= timedelta(0):
            raise ValueError("preflight lead must be positive")
        if maximum_start_delay < timedelta(0):
            raise ValueError("maximum start delay cannot be negative")
        self._trading_calendar = trading_calendar
        self._market_data_provider = market_data_provider
        self._schedule_repository = schedule_repository
        self._workflow_repository = workflow_repository
        self._application_factory = application_factory
        self._openai_configured = openai_configured
        self._preflight_lead = preflight_lead
        self._maximum_start_delay = maximum_start_delay
        self._clock = clock

    def tick(self, observed_at: datetime | None = None) -> TailRadarScheduleData:
        observed = as_market_timezone(observed_at or self._clock())
        existing_schedule = self._schedule_repository.get_schedule(observed.date())
        if existing_schedule is not None and existing_schedule.status in _WORKER_TERMINAL_STATUSES:
            return existing_schedule

        intended = datetime.combine(observed.date(), OFFICIAL_SNAPSHOT_TIME, MARKET_TIME_ZONE)
        trading_day = self._trading_calendar.resolve(observed.date())
        schedule = self._schedule_repository.ensure_schedule(
            intended_snapshot_time=intended,
            is_trading_day=trading_day.is_trading_day,
            calendar_provider=trading_day.provider,
            observed_at=observed,
        )
        if not trading_day.is_trading_day:
            return schedule

        preflight_at = intended - self._preflight_lead
        if observed < preflight_at:
            return schedule
        if observed < intended:
            if schedule.preflight_report is None:
                schedule = self._record_preflight(schedule, observed)
            return schedule

        if schedule.preflight_report is None:
            schedule = self._record_preflight(schedule, observed)

        existing_workflow = self._workflow_repository.get_workflow_for_intended_time(
            intended_snapshot_time=intended,
            workflow_version=TAIL_RADAR_WORKFLOW_VERSION,
        )
        if existing_workflow is None and observed > intended + self._maximum_start_delay:
            return self._schedule_repository.update_schedule(
                schedule_id=schedule.schedule_id,
                status=TailRadarScheduleStatus.MISSED,
                observed_at=observed,
                error_code="official_snapshot_start_window_missed",
                error_details={
                    "intended_snapshot_time": intended.isoformat(),
                    "observed_at": observed.isoformat(),
                    "maximum_start_delay_seconds": self._maximum_start_delay.total_seconds(),
                },
            )

        with self._schedule_repository.execution_lock(intended) as acquired:
            if not acquired:
                return self._schedule_repository.get_schedule(observed.date()) or schedule
            existing_workflow = self._workflow_repository.get_workflow_for_intended_time(
                intended_snapshot_time=intended,
                workflow_version=TAIL_RADAR_WORKFLOW_VERSION,
            )
            if (
                existing_workflow is None
                and as_market_timezone(self._clock()) > intended + self._maximum_start_delay
            ):
                return self._schedule_repository.update_schedule(
                    schedule_id=schedule.schedule_id,
                    status=TailRadarScheduleStatus.MISSED,
                    observed_at=as_market_timezone(self._clock()),
                    error_code="official_snapshot_start_window_missed",
                    error_details={"intended_snapshot_time": intended.isoformat()},
                )
            if existing_workflow is not None and existing_workflow.lifecycle in {
                TailRadarWorkflowLifecycle.SUCCEEDED,
                TailRadarWorkflowLifecycle.PARTIAL_SUCCESS,
            }:
                return self._record_workflow_result(schedule, existing_workflow)
            if existing_workflow is not None and (
                existing_workflow.lifecycle is TailRadarWorkflowLifecycle.FAILED
            ):
                return self._record_failed_workflow(schedule, existing_workflow)

            started_at = as_market_timezone(self._clock())
            schedule = self._schedule_repository.update_schedule(
                schedule_id=schedule.schedule_id,
                status=TailRadarScheduleStatus.EXECUTING,
                observed_at=started_at,
                workflow_run_id=(
                    None if existing_workflow is None else existing_workflow.workflow_run_id
                ),
            )
            try:
                application = self._application_factory()
                if existing_workflow is None:
                    result = application.execute(intended_snapshot_time=intended)
                    if result.workflow.lifecycle not in {
                        TailRadarWorkflowLifecycle.SUCCEEDED,
                        TailRadarWorkflowLifecycle.PARTIAL_SUCCESS,
                    }:
                        result = application.resume(
                            workflow_run_id=result.workflow.workflow_run_id,
                        )
                else:
                    result = application.resume(
                        workflow_run_id=existing_workflow.workflow_run_id,
                    )
                return self._record_workflow_result(schedule, result.workflow)
            except Exception as exc:
                workflow = self._workflow_repository.get_workflow_for_intended_time(
                    intended_snapshot_time=intended,
                    workflow_version=TAIL_RADAR_WORKFLOW_VERSION,
                )
                self._log_execution_failure(
                    error=exc,
                    schedule=schedule,
                    intended_snapshot_time=intended,
                    workflow=workflow,
                )
                return self._schedule_repository.update_schedule(
                    schedule_id=schedule.schedule_id,
                    status=TailRadarScheduleStatus.FAILED,
                    observed_at=as_market_timezone(self._clock()),
                    workflow_run_id=None if workflow is None else workflow.workflow_run_id,
                    error_code=_error_code(exc),
                    error_details={"error_type": type(exc).__name__},
                )

    def inspect(self, trade_date: date | None = None) -> TailRadarScheduleData | None:
        target_date = trade_date or as_market_timezone(self._clock()).date()
        return self._schedule_repository.get_schedule(target_date)

    def retry_incomplete(
        self,
        *,
        trade_date: date | None = None,
    ) -> TailRadarScheduleData:
        target_date = trade_date or as_market_timezone(self._clock()).date()
        schedule = self._schedule_repository.get_schedule(target_date)
        if schedule is None:
            raise TailRadarSchedulingError("no scheduled Tail Radar status exists for this date")
        if schedule.status in {
            TailRadarScheduleStatus.MISSED,
            TailRadarScheduleStatus.NOT_TRADING_DAY,
        }:
            raise TailRadarSchedulingError(
                "a missed or closed-market official snapshot cannot be reconstructed later"
            )
        workflow = (
            None
            if schedule.workflow_run_id is None
            else self._workflow_repository.get_workflow(schedule.workflow_run_id)
        )
        if workflow is None or workflow.snapshot_id is None:
            raise TailRadarSchedulingError(
                "no captured official snapshot is available for analysis-only retry"
            )
        with self._schedule_repository.execution_lock(schedule.intended_snapshot_time) as acquired:
            if not acquired:
                raise TailRadarSchedulingError("the scheduled workflow is already executing")
            started_at = as_market_timezone(self._clock())
            schedule = self._schedule_repository.update_schedule(
                schedule_id=schedule.schedule_id,
                status=TailRadarScheduleStatus.EXECUTING,
                observed_at=started_at,
                workflow_run_id=workflow.workflow_run_id,
            )
            try:
                result = self._application_factory().resume(
                    workflow_run_id=workflow.workflow_run_id,
                )
            except Exception as exc:
                self._log_execution_failure(
                    error=exc,
                    schedule=schedule,
                    intended_snapshot_time=schedule.intended_snapshot_time,
                    workflow=workflow,
                )
                return self._schedule_repository.update_schedule(
                    schedule_id=schedule.schedule_id,
                    status=TailRadarScheduleStatus.FAILED,
                    observed_at=as_market_timezone(self._clock()),
                    workflow_run_id=workflow.workflow_run_id,
                    error_code=_error_code(exc),
                    error_details={"error_type": type(exc).__name__},
                )
            return self._record_workflow_result(schedule, result.workflow)

    @staticmethod
    def _log_execution_failure(
        *,
        error: Exception,
        schedule: TailRadarScheduleData,
        intended_snapshot_time: datetime,
        workflow: TailRadarWorkflowData | None,
    ) -> None:
        logger.exception(
            "tail_radar_scheduled_execution_failed",
            extra={
                "feature": "tail_radar",
                "schedule_id": str(schedule.schedule_id),
                "workflow_run_id": (None if workflow is None else str(workflow.workflow_run_id)),
                "intended_snapshot_time": intended_snapshot_time.isoformat(),
                "error_code": _error_code(error),
                "error_type": type(error).__name__,
            },
        )

    def _record_preflight(
        self, schedule: TailRadarScheduleData, started_at: datetime
    ) -> TailRadarScheduleData:
        capabilities = self._market_data_provider.capabilities
        notes: list[str] = []
        if not self._openai_configured:
            notes.append(
                "OpenAI research is not enabled or configured; deterministic official capture "
                "remains ready"
            )
        report = TailRadarPreflightReport(
            database_available=True,
            trading_day=True,
            calendar_provider=self._trading_calendar.provider_id,
            quote_provider=self._market_data_provider.provider_id,
            full_snapshot_capability=(MarketDataCapability.FULL_MARKET_SNAPSHOT in capabilities),
            intraday_capability=MarketDataCapability.INTRADAY_BARS in capabilities,
            openai_configured=self._openai_configured,
            notes=tuple(notes),
        )
        return self._schedule_repository.record_preflight(
            schedule_id=schedule.schedule_id,
            started_at=started_at,
            finished_at=as_market_timezone(self._clock()),
            report=report,
        )

    def _record_workflow_result(
        self, schedule: TailRadarScheduleData, workflow: TailRadarWorkflowData
    ) -> TailRadarScheduleData:
        if workflow.lifecycle is TailRadarWorkflowLifecycle.SUCCEEDED:
            status = TailRadarScheduleStatus.SUCCEEDED
        elif workflow.lifecycle is TailRadarWorkflowLifecycle.PARTIAL_SUCCESS:
            status = TailRadarScheduleStatus.PARTIAL_SUCCESS
        elif workflow.lifecycle is TailRadarWorkflowLifecycle.FAILED:
            return self._record_failed_workflow(schedule, workflow)
        else:
            status = TailRadarScheduleStatus.FAILED
        return self._schedule_repository.update_schedule(
            schedule_id=schedule.schedule_id,
            status=status,
            observed_at=as_market_timezone(self._clock()),
            workflow_run_id=workflow.workflow_run_id,
            error_code=(
                None
                if status is not TailRadarScheduleStatus.FAILED
                else "workflow_did_not_reach_terminal_state"
            ),
        )

    def _record_failed_workflow(
        self, schedule: TailRadarScheduleData, workflow: TailRadarWorkflowData
    ) -> TailRadarScheduleData:
        return self._schedule_repository.update_schedule(
            schedule_id=schedule.schedule_id,
            status=TailRadarScheduleStatus.FAILED,
            observed_at=as_market_timezone(self._clock()),
            workflow_run_id=workflow.workflow_run_id,
            error_code=workflow.error_code or "workflow_failed",
            error_details={"error_stage": workflow.error_stage or "unknown"},
        )


def _error_code(error: Exception) -> str:
    code = getattr(error, "code", None)
    return code if isinstance(code, str) and code else type(error).__name__


_WORKER_TERMINAL_STATUSES = {
    TailRadarScheduleStatus.SUCCEEDED,
    TailRadarScheduleStatus.PARTIAL_SUCCESS,
    TailRadarScheduleStatus.FAILED,
    TailRadarScheduleStatus.MISSED,
    TailRadarScheduleStatus.NOT_TRADING_DAY,
}

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import date, datetime
from uuid import UUID

from pydantic import ValidationError
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker

from a_stock_lab.features.tail_radar.adapters.persistence_models import TailRadarScheduleRecord
from a_stock_lab.features.tail_radar.application.scheduling_models import (
    TAIL_RADAR_SCHEDULE_JOB_NAME,
    TAIL_RADAR_SCHEDULE_VERSION,
    TailRadarPreflightReport,
    TailRadarScheduleData,
    TailRadarScheduleStatus,
)
from a_stock_lab.features.tail_radar.domain.errors import TailRadarSchedulingError


class PostgresTailRadarScheduleRepository:
    """PostgreSQL schedule state plus a connection-scoped execution mutex."""

    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self._session_factory = session_factory

    def ensure_schedule(
        self,
        *,
        intended_snapshot_time: datetime,
        is_trading_day: bool,
        calendar_provider: str,
        observed_at: datetime,
    ) -> TailRadarScheduleData:
        with self._session_factory() as session:
            try:
                existing = self._find(session, intended_snapshot_time.date())
                if existing is not None:
                    self._validate_calendar_identity(
                        existing,
                        intended_snapshot_time=intended_snapshot_time,
                        is_trading_day=is_trading_day,
                        calendar_provider=calendar_provider,
                    )
                    return self._data(existing)
                record = TailRadarScheduleRecord(
                    job_name=TAIL_RADAR_SCHEDULE_JOB_NAME,
                    schedule_version=TAIL_RADAR_SCHEDULE_VERSION,
                    trade_date=intended_snapshot_time.date(),
                    intended_snapshot_time=intended_snapshot_time,
                    status=(
                        TailRadarScheduleStatus.SCHEDULED.value
                        if is_trading_day
                        else TailRadarScheduleStatus.NOT_TRADING_DAY.value
                    ),
                    is_trading_day=is_trading_day,
                    calendar_provider=calendar_provider,
                    error_details={},
                    created_at=observed_at,
                    updated_at=observed_at,
                )
                session.add(record)
                session.flush()
                data = self._data(record)
                session.commit()
                return data
            except IntegrityError as exc:
                session.rollback()
                try:
                    existing = self._find(session, intended_snapshot_time.date())
                    if existing is None:
                        raise TailRadarSchedulingError(
                            "Tail Radar schedule could not be claimed"
                        ) from exc
                    self._validate_calendar_identity(
                        existing,
                        intended_snapshot_time=intended_snapshot_time,
                        is_trading_day=is_trading_day,
                        calendar_provider=calendar_provider,
                    )
                    return self._data(existing)
                except SQLAlchemyError as lookup_error:
                    raise TailRadarSchedulingError(
                        "conflicting Tail Radar schedule could not be read"
                    ) from lookup_error
            except (SQLAlchemyError, ValidationError) as exc:
                session.rollback()
                raise TailRadarSchedulingError("Tail Radar schedule could not be stored") from exc

    def get_schedule(self, trade_date: date) -> TailRadarScheduleData | None:
        with self._session_factory() as session:
            try:
                record = self._find(session, trade_date)
                return None if record is None else self._data(record)
            except (SQLAlchemyError, ValidationError) as exc:
                raise TailRadarSchedulingError("Tail Radar schedule could not be read") from exc

    def record_preflight(
        self,
        *,
        schedule_id: UUID,
        started_at: datetime,
        finished_at: datetime,
        report: TailRadarPreflightReport,
    ) -> TailRadarScheduleData:
        with self._session_factory() as session:
            try:
                record = self._locked(session, schedule_id)
                if record.status in _TERMINAL_STATUSES:
                    return self._data(record)
                record.status = (
                    TailRadarScheduleStatus.PREFLIGHT_READY.value
                    if report.ready
                    else TailRadarScheduleStatus.PREFLIGHT_DEGRADED.value
                )
                record.preflight_started_at = started_at
                record.preflight_finished_at = finished_at
                record.preflight_report = report.model_dump(mode="json")
                record.updated_at = finished_at
                session.flush()
                data = self._data(record)
                session.commit()
                return data
            except TailRadarSchedulingError:
                session.rollback()
                raise
            except (SQLAlchemyError, ValidationError) as exc:
                session.rollback()
                raise TailRadarSchedulingError(
                    "Tail Radar preflight could not be recorded"
                ) from exc

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
        with self._session_factory() as session:
            try:
                record = self._locked(session, schedule_id)
                record.status = status.value
                if workflow_run_id is not None:
                    record.workflow_run_id = workflow_run_id
                if status is TailRadarScheduleStatus.EXECUTING:
                    record.execution_started_at = record.execution_started_at or observed_at
                    record.execution_finished_at = None
                elif status in {
                    TailRadarScheduleStatus.SUCCEEDED,
                    TailRadarScheduleStatus.PARTIAL_SUCCESS,
                    TailRadarScheduleStatus.FAILED,
                    TailRadarScheduleStatus.MISSED,
                }:
                    record.execution_finished_at = observed_at
                record.error_code = error_code[:128] if error_code else None
                record.error_details = error_details or {}
                record.updated_at = observed_at
                session.flush()
                data = self._data(record)
                session.commit()
                return data
            except TailRadarSchedulingError:
                session.rollback()
                raise
            except (IntegrityError, SQLAlchemyError, ValidationError) as exc:
                session.rollback()
                raise TailRadarSchedulingError("Tail Radar schedule could not be updated") from exc

    @contextmanager
    def execution_lock(self, intended_snapshot_time: datetime) -> Iterator[bool]:
        lock_key = (
            f"{TAIL_RADAR_SCHEDULE_JOB_NAME}|{TAIL_RADAR_SCHEDULE_VERSION}|"
            f"{intended_snapshot_time.isoformat()}"
        )
        with self._session_factory() as session:
            try:
                acquired = bool(
                    session.execute(
                        text("SELECT pg_try_advisory_lock(hashtextextended(:lock_key, 0))"),
                        {"lock_key": lock_key},
                    ).scalar_one()
                )
            except SQLAlchemyError as exc:
                raise TailRadarSchedulingError(
                    "Tail Radar database execution lock could not be acquired"
                ) from exc
            try:
                yield acquired
            finally:
                if acquired:
                    try:
                        session.execute(
                            text("SELECT pg_advisory_unlock(hashtextextended(:lock_key, 0))"),
                            {"lock_key": lock_key},
                        )
                    except SQLAlchemyError:
                        session.invalidate()

    @staticmethod
    def _validate_calendar_identity(
        record: TailRadarScheduleRecord,
        *,
        intended_snapshot_time: datetime,
        is_trading_day: bool,
        calendar_provider: str,
    ) -> None:
        if (
            record.intended_snapshot_time != intended_snapshot_time
            or record.is_trading_day != is_trading_day
            or record.calendar_provider != calendar_provider
        ):
            raise TailRadarSchedulingError(
                "persisted Tail Radar schedule conflicts with current calendar evidence"
            )

    @staticmethod
    def _find(session: Session, trade_date: date) -> TailRadarScheduleRecord | None:
        return session.scalar(
            select(TailRadarScheduleRecord).where(
                TailRadarScheduleRecord.job_name == TAIL_RADAR_SCHEDULE_JOB_NAME,
                TailRadarScheduleRecord.trade_date == trade_date,
                TailRadarScheduleRecord.schedule_version == TAIL_RADAR_SCHEDULE_VERSION,
            )
        )

    @staticmethod
    def _locked(session: Session, schedule_id: UUID) -> TailRadarScheduleRecord:
        record = session.scalar(
            select(TailRadarScheduleRecord)
            .where(TailRadarScheduleRecord.schedule_id == schedule_id)
            .with_for_update()
        )
        if record is None:
            raise TailRadarSchedulingError("Tail Radar schedule was not found")
        return record

    @staticmethod
    def _data(record: TailRadarScheduleRecord) -> TailRadarScheduleData:
        return TailRadarScheduleData(
            schedule_id=record.schedule_id,
            job_name=record.job_name,
            schedule_version=record.schedule_version,
            trade_date=record.trade_date,
            intended_snapshot_time=record.intended_snapshot_time,
            status=TailRadarScheduleStatus(record.status),
            is_trading_day=record.is_trading_day,
            calendar_provider=record.calendar_provider,
            preflight_started_at=record.preflight_started_at,
            preflight_finished_at=record.preflight_finished_at,
            preflight_report=(
                None
                if record.preflight_report is None
                else TailRadarPreflightReport.model_validate(record.preflight_report)
            ),
            workflow_run_id=record.workflow_run_id,
            execution_started_at=record.execution_started_at,
            execution_finished_at=record.execution_finished_at,
            error_code=record.error_code,
            error_details=record.error_details,
            created_at=record.created_at,
            updated_at=record.updated_at,
        )


_TERMINAL_STATUSES = {
    TailRadarScheduleStatus.SUCCEEDED.value,
    TailRadarScheduleStatus.PARTIAL_SUCCESS.value,
    TailRadarScheduleStatus.FAILED.value,
    TailRadarScheduleStatus.MISSED.value,
    TailRadarScheduleStatus.NOT_TRADING_DAY.value,
}

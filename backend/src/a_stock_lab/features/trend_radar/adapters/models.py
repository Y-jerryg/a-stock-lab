from datetime import date, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import DateTime, ForeignKey, Index, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from a_stock_lab.database.base import Base


class TrendScanRunRecord(Base):
    __tablename__ = "trend_scan_runs"
    __table_args__ = (Index("ix_trend_scan_runs_status_started", "status", "started_at"),)
    id: Mapped[UUID] = mapped_column(primary_key=True)
    trade_date: Mapped[date | None]
    status: Mapped[str] = mapped_column(String(32))
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB)


class TrendHeatRecord(Base):
    __tablename__ = "trend_daily_heat"
    run_id: Mapped[UUID] = mapped_column(ForeignKey("trend_scan_runs.id"), primary_key=True)
    symbol: Mapped[str] = mapped_column(String(6), primary_key=True)
    trade_date: Mapped[date] = mapped_column(index=True)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB)


class TrendBarRecord(Base):
    __tablename__ = "trend_daily_bars"
    symbol: Mapped[str] = mapped_column(String(6), primary_key=True)
    trade_date: Mapped[date] = mapped_column(primary_key=True)
    vintage_date: Mapped[date] = mapped_column(primary_key=True)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB)


class TrendScanResultRecord(Base):
    __tablename__ = "trend_scan_results"
    run_id: Mapped[UUID] = mapped_column(ForeignKey("trend_scan_runs.id"), primary_key=True)
    symbol: Mapped[str] = mapped_column(String(6), primary_key=True)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB)
    input_bars: Mapped[list[dict[str, Any]]] = mapped_column(JSONB)


class TrendScheduleClaimRecord(Base):
    __tablename__ = "trend_schedule_claims"
    trade_date: Mapped[date] = mapped_column(primary_key=True)
    run_id: Mapped[UUID] = mapped_column(ForeignKey("trend_scan_runs.id"), unique=True)

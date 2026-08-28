import uuid
from datetime import date, datetime
from typing import Any

from sqlalchemy import CheckConstraint, Date, DateTime, Index, Integer, String, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from a_stock_lab.database.base import Base


class ResearchArtifact(Base):
    """Durable structured output published by any research module."""

    __tablename__ = "research_artifacts"
    __table_args__ = (
        CheckConstraint("schema_version > 0", name="schema_version_positive"),
        Index("ix_research_artifacts_module_as_of", "module", "as_of"),
        Index("ix_research_artifacts_symbol_trade_date", "symbol", "trade_date"),
    )

    artifact_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    module: Mapped[str] = mapped_column(String(64), nullable=False)
    artifact_type: Mapped[str] = mapped_column(String(128), nullable=False)
    symbol: Mapped[str | None] = mapped_column(String(32))
    trade_date: Mapped[date | None] = mapped_column(Date)
    as_of: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    schema_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

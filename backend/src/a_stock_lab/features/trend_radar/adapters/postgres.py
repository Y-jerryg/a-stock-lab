from collections.abc import Iterator
from contextlib import contextmanager
from datetime import date, datetime
from uuid import UUID, uuid5

from sqlalchemy import Engine, delete, func, select, text
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from a_stock_lab.features.trend_radar.adapters.models import (
    TrendBarRecord,
    TrendHeatRecord,
    TrendScanResultRecord,
    TrendScanRunRecord,
    TrendScheduleClaimRecord,
)
from a_stock_lab.features.trend_radar.domain.models import (
    COMPLETED_STATUSES,
    Bar,
    Candidate,
    Heat,
    ScanBusyError,
    ScanRun,
)
from a_stock_lab.shared.artifacts.models import ResearchArtifact

LOCK_ID = 782319047


class PostgresTrendRepository:
    def __init__(self, engine: Engine) -> None:
        self.engine = engine

    def begin(self, run: ScanRun) -> bool:
        """Caller holds the shared advisory lock for recovery, claiming and all scan work."""
        with Session(self.engine) as session, session.begin() as transaction:
            # Owning the lock proves an earlier running process no longer owns the scan.
            for abandoned in session.scalars(
                select(TrendScanRunRecord).where(TrendScanRunRecord.status == "running")
            ):
                abandoned.status = "failed"
                abandoned.payload = {
                    **abandoned.payload,
                    "status": "failed",
                    "error_message": "interrupted",
                    "finished_at": run.started_at.isoformat(),
                }
            session.flush()
            if (
                run.trigger_type == "scheduled"
                and session.get(TrendScheduleClaimRecord, run.trade_date) is not None
            ):
                return False
            session.add(
                TrendScanRunRecord(
                    id=run.id,
                    trade_date=run.trade_date,
                    status=run.status,
                    started_at=run.started_at,
                    payload=run.model_dump(mode="json"),
                )
            )
            session.flush()
            if run.trigger_type == "scheduled":
                claimed = session.scalar(
                    insert(TrendScheduleClaimRecord)
                    .values(
                        trade_date=run.trade_date,
                        run_id=run.id,
                    )
                    .on_conflict_do_nothing()
                    .returning(TrendScheduleClaimRecord.trade_date)
                )
                if claimed is None:
                    transaction.rollback()
                    return False
            return True

    def public_runs(self) -> list[ScanRun]:
        with Session(self.engine) as session:
            query = select(TrendScanRunRecord).order_by(
                TrendScanRunRecord.started_at.desc(), TrendScanRunRecord.id.desc()
            )
            rows = list(session.scalars(query.limit(100)))
            latest = session.scalar(
                query.where(TrendScanRunRecord.status.in_(COMPLETED_STATUSES)).limit(1)
            )
            if latest is not None and all(row.id != latest.id for row in rows):
                rows.append(latest)
            return [ScanRun.model_validate(row.payload) for row in rows]

    def public_results(self, run_id: UUID) -> list[Candidate]:
        with Session(self.engine) as session:
            return [
                Candidate.model_validate(row.payload)
                for row in session.scalars(
                    select(TrendScanResultRecord).where(TrendScanResultRecord.run_id == run_id)
                )
            ]

    def candidate_inputs(self, run_id: UUID) -> dict[str, list[Bar]]:
        # Read immutable per-run evidence, never the refreshed daily cache.
        with Session(self.engine) as session:
            return {
                row.symbol: [Bar.model_validate(bar) for bar in row.input_bars]
                for row in session.scalars(
                    select(TrendScanResultRecord).where(TrendScanResultRecord.run_id == run_id)
                )
            }

    @contextmanager
    def lock(self) -> Iterator[None]:
        with self.engine.connect() as connection:
            if not connection.scalar(text("SELECT pg_try_advisory_lock(:key)"), {"key": LOCK_ID}):
                raise ScanBusyError()
            connection.commit()
            try:
                yield
            finally:
                connection.execute(text("SELECT pg_advisory_unlock(:key)"), {"key": LOCK_ID})
                connection.commit()

    def save_run(self, run: ScanRun) -> None:
        values = {
            "id": run.id,
            "trade_date": run.trade_date,
            "status": run.status,
            "started_at": run.started_at,
            "payload": run.model_dump(mode="json"),
        }
        with self.engine.begin() as connection:
            statement = insert(TrendScanRunRecord).values(**values)
            connection.execute(statement.on_conflict_do_update(index_elements=["id"], set_=values))

    def save_heat(self, run_id: UUID, heat: list[Heat]) -> None:
        with self.engine.begin() as connection:
            connection.execute(
                insert(TrendHeatRecord)
                .values(
                    [
                        {
                            "run_id": run_id,
                            "symbol": row.symbol,
                            "trade_date": row.data_date,
                            "payload": row.model_dump(mode="json"),
                        }
                        for row in heat
                    ]
                )
                .on_conflict_do_nothing()
            )

    def load_bars(self, symbol: str, vintage: date, now: datetime) -> list[Bar] | None:
        with Session(self.engine) as session:
            latest = (
                select(func.max(TrendBarRecord.vintage_date))
                .where(TrendBarRecord.symbol == symbol, TrendBarRecord.vintage_date <= vintage)
                .scalar_subquery()
            )
            records = session.scalars(
                select(TrendBarRecord)
                .where(TrendBarRecord.symbol == symbol, TrendBarRecord.vintage_date == latest)
                .order_by(TrendBarRecord.trade_date)
            ).all()
            bars = [Bar.model_validate(row.payload) for row in records]
            # Application validates overlap before combining adjustment vintages.
            if bars and all(bar.fetched_at <= now for bar in bars):
                return bars
            return None

    def save_bars(self, symbol: str, vintage: date, bars: list[Bar]) -> None:
        if not bars:
            return
        with self.engine.begin() as connection:
            connection.execute(
                delete(TrendBarRecord).where(
                    TrendBarRecord.symbol == symbol, TrendBarRecord.vintage_date <= vintage
                )
            )
            statement = insert(TrendBarRecord).values(
                [
                    {
                        "symbol": symbol,
                        "trade_date": row.trade_date,
                        "vintage_date": vintage,
                        "payload": row.model_dump(mode="json"),
                    }
                    for row in bars
                ]
            )
            connection.execute(
                statement.on_conflict_do_update(
                    index_elements=["symbol", "trade_date", "vintage_date"],
                    set_={"payload": statement.excluded.payload},
                )
            )

    def prune_bars(self, before: date) -> None:
        # Only the mutable cache is pruned; per-run evidence and artifacts stay immutable.
        with self.engine.begin() as connection:
            connection.execute(delete(TrendBarRecord).where(TrendBarRecord.trade_date < before))
            connection.execute(
                text(
                    "DELETE FROM trend_daily_bars AS old USING "
                    "(SELECT symbol, max(vintage_date) AS latest FROM trend_daily_bars "
                    "GROUP BY symbol) AS current "
                    "WHERE old.symbol=current.symbol AND old.vintage_date < current.latest"
                )
            )

    def checkpoint(self, run: ScanRun, candidate: Candidate | None, bars: list[Bar]) -> None:
        with Session(self.engine) as session, session.begin():
            record = session.get(TrendScanRunRecord, run.id)
            if record is None:
                raise RuntimeError("scan run missing")
            record.trade_date = run.trade_date
            record.payload = run.model_dump(mode="json")
            if candidate:
                session.merge(
                    TrendScanResultRecord(
                        run_id=run.id,
                        symbol=candidate.symbol,
                        payload=candidate.model_dump(mode="json"),
                        input_bars=[bar.model_dump(mode="json") for bar in bars],
                    )
                )

    def complete(
        self, run: ScanRun, results: list[Candidate], inputs: dict[str, list[Bar]]
    ) -> None:
        with Session(self.engine) as session, session.begin():
            record = session.get(TrendScanRunRecord, run.id)
            if record is None:
                raise RuntimeError("scan run missing")
            record.status = run.status
            record.trade_date = run.trade_date
            record.payload = run.model_dump(mode="json")
            for result in results:
                session.merge(
                    TrendScanResultRecord(
                        run_id=run.id,
                        symbol=result.symbol,
                        payload=result.model_dump(mode="json"),
                        input_bars=[bar.model_dump(mode="json") for bar in inputs[result.symbol]],
                    )
                )
                session.merge(
                    ResearchArtifact(
                        artifact_id=uuid5(run.id, result.symbol),
                        module="trend_radar",
                        artifact_type="trend_radar.candidate",
                        symbol=result.symbol,
                        trade_date=run.trade_date,
                        as_of=run.data_as_of,
                        schema_version=run.schema_version,
                        payload={
                            "run": run.model_dump(mode="json"),
                            "candidate": result.model_dump(mode="json"),
                        },
                    )
                )

    def inspect(self, run_id: UUID | None) -> dict[str, object] | None:
        with Session(self.engine) as session:
            query = (
                select(TrendScanRunRecord).order_by(TrendScanRunRecord.started_at.desc()).limit(1)
            )
            if run_id:
                query = query.where(TrendScanRunRecord.id == run_id)
            record = session.scalar(query)
            return record.payload if record else None

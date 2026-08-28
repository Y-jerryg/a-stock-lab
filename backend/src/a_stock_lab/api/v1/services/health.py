from typing import Annotated

from fastapi import Depends
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from a_stock_lab import __version__
from a_stock_lab.api.v1.schemas.health import HealthResponse
from a_stock_lab.core.logging import get_logger
from a_stock_lab.core.time import now_in_market_timezone
from a_stock_lab.database.session import get_db_session

logger = get_logger(__name__)


class HealthService:
    def __init__(self, session: Session) -> None:
        self._session = session

    def check(self) -> HealthResponse:
        generated_at = now_in_market_timezone()
        try:
            self._session.execute(text("SELECT 1"))
        except SQLAlchemyError:
            logger.exception("database_health_check_failed", extra={"feature": "system"})
            return HealthResponse.degraded(version=__version__, generated_at=generated_at)
        return HealthResponse.healthy(version=__version__, generated_at=generated_at)


def get_health_service(
    session: Annotated[Session, Depends(get_db_session)],
) -> HealthService:
    return HealthService(session)

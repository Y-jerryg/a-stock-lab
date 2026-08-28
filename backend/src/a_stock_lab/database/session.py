from collections.abc import Generator

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from a_stock_lab.core.config import get_settings

settings = get_settings()
engine = create_engine(settings.resolved_database_url, pool_pre_ping=True)
SessionFactory = sessionmaker(bind=engine, expire_on_commit=False, class_=Session)


def get_db_session() -> Generator[Session, None, None]:
    with SessionFactory() as session:
        yield session

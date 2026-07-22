from functools import lru_cache

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine
from sqlalchemy.exc import SQLAlchemyError

from rural_basic_income.config import Settings, get_settings


class DatabaseUnavailable(RuntimeError):
    """Raised when the configured database cannot answer a simple query."""


def create_db_engine(settings: Settings | None = None) -> Engine:
    resolved_settings = settings or get_settings()
    return create_engine(
        resolved_settings.sqlalchemy_database_url,
        pool_pre_ping=True,
    )


@lru_cache
def get_engine() -> Engine:
    return create_db_engine()


def dispose_engine() -> None:
    if get_engine.cache_info().currsize:
        get_engine().dispose()
        get_engine.cache_clear()


def assert_database_ready(engine: Engine | None = None) -> None:
    db_engine = engine or get_engine()

    try:
        with db_engine.connect() as connection:
            connection.execute(text("SELECT 1"))
    except SQLAlchemyError as exc:
        raise DatabaseUnavailable("database unavailable") from exc


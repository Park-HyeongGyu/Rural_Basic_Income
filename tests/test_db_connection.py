from rural_basic_income.config import Settings
from rural_basic_income.db.connection import create_db_engine


def test_create_db_engine_uses_configured_database_url() -> None:
    settings = Settings(
        _env_file=None,
        database_url="postgresql+psycopg://user:password@localhost:5432/example",
    )
    engine = create_db_engine(settings)

    try:
        assert engine.url.drivername == "postgresql+psycopg"
        assert engine.url.username == "user"
        assert engine.url.password == "password"
        assert engine.url.host == "localhost"
        assert engine.url.port == 5432
        assert engine.url.database == "example"
    finally:
        engine.dispose()

from rural_basic_income.config import Settings


def test_settings_builds_database_url_from_postgres_parts() -> None:
    settings = Settings(
        _env_file=None,
        app_env="test",
        postgres_user="rbi",
        postgres_password="passrbi",
        postgres_db="rural_basic_income",
        postgres_host="127.0.0.1",
        postgres_port=5432,
        database_url=None,
    )

    assert (
        settings.sqlalchemy_database_url
        == "postgresql+psycopg://rbi:passrbi@127.0.0.1:5432/rural_basic_income"
    )


def test_settings_database_url_override_wins() -> None:
    settings = Settings(
        _env_file=None,
        database_url="postgresql+psycopg://user:password@db:5432/custom",
    )

    assert (
        settings.sqlalchemy_database_url
        == "postgresql+psycopg://user:password@db:5432/custom"
    )


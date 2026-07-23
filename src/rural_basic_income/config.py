from functools import lru_cache
from urllib.parse import quote

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    app_env: str = "development"
    postgres_user: str = "rbi"
    postgres_password: str = "passrbi"
    postgres_db: str = "rural_basic_income"
    postgres_host: str = "127.0.0.1"
    postgres_port: int = 5432
    database_url: str | None = None
    kosis_api_key: str | None = None

    @property
    def sqlalchemy_database_url(self) -> str:
        if self.database_url:
            return self.database_url

        user = quote(self.postgres_user, safe="")
        password = quote(self.postgres_password, safe="")
        host = self.postgres_host
        port = self.postgres_port
        db = quote(self.postgres_db, safe="")
        return f"postgresql+psycopg://{user}:{password}@{host}:{port}/{db}"


@lru_cache
def get_settings() -> Settings:
    return Settings()

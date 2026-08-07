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
    kepco_api_key: str | None = None
    data_go_kr_api_key: str | None = None
    telegram_bot_token: str | None = None
    telegram_chat_id: str | None = None
    enable_success_telegram: bool = False
    enable_failure_telegram: bool = False
    redis_url: str = "redis://127.0.0.1:6379/0"
    celery_broker_url: str | None = None
    celery_result_backend: str | None = None
    analysis_cache_ttl_seconds: int = 60 * 60 * 24 * 30
    analysis_task_soft_time_limit_seconds: int = 60 * 20
    analysis_task_time_limit_seconds: int = 60 * 30
    analysis_running_lock_ttl_seconds: int = 60 * 35
    analysis_rate_limit_requests: int = 300
    analysis_rate_limit_window_seconds: int = 60
    export_csv_dir: str = "/export/csv"
    export_dta_dir: str = "/export/dta"
    rbi_latest_start_period: str = "202501"

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

    @property
    def resolved_celery_broker_url(self) -> str:
        return self.celery_broker_url or self.redis_url

    @property
    def resolved_celery_result_backend(self) -> str:
        return self.celery_result_backend or self.redis_url


@lru_cache
def get_settings() -> Settings:
    return Settings()

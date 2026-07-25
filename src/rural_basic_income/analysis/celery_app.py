from __future__ import annotations

from celery import Celery

from rural_basic_income.config import Settings, get_settings


def create_celery_app(settings: Settings | None = None) -> Celery:
    resolved_settings = settings or get_settings()
    celery_app = Celery(
        "rural_basic_income.analysis",
        broker=resolved_settings.resolved_celery_broker_url,
        backend=resolved_settings.resolved_celery_result_backend,
        include=("rural_basic_income.analysis.tasks",),
    )
    celery_app.conf.update(
        accept_content=("json",),
        result_serializer="json",
        task_acks_late=False,
        task_serializer="json",
        task_soft_time_limit=resolved_settings.analysis_task_soft_time_limit_seconds,
        task_time_limit=resolved_settings.analysis_task_time_limit_seconds,
        task_track_started=True,
        worker_prefetch_multiplier=1,
    )
    return celery_app


app = create_celery_app()

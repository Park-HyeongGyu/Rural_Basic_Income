from __future__ import annotations

from dataclasses import asdict
from typing import Any, Callable, Mapping

from redis import Redis
from sqlalchemy.engine import Connection, Engine

from rural_basic_income.analysis.cache import (
    ANALYSIS_VERSION,
    clear_running_task,
    fetch_data_revision,
    make_analysis_cache_key,
    read_cached_result,
    write_cached_result,
)
from rural_basic_income.analysis.celery_app import app
from rural_basic_income.analysis.data_loader import (
    LoadedAnalysisPanel,
    load_analysis_panel,
)
from rural_basic_income.analysis.panel import AnalysisPanel
from rural_basic_income.analysis.regression import (
    EventStudyResult,
    TwfeResult,
    fit_traditional_event_study,
    fit_twfe_did,
)
from rural_basic_income.analysis.specification import (
    AnalysisRequest,
    analysis_request_to_payload,
    parse_analysis_request,
)
from rural_basic_income.config import Settings, get_settings
from rural_basic_income.db.connection import get_engine


PanelLoader = Callable[[Connection, Any, Any], LoadedAnalysisPanel]
TwfeRunner = Callable[[Any], TwfeResult]
EventStudyRunner = Callable[[Any], EventStudyResult]


def create_redis_client(settings: Settings | None = None) -> Redis:
    resolved_settings = settings or get_settings()
    return Redis.from_url(resolved_settings.redis_url, decode_responses=True)


@app.task(bind=True, name="rural_basic_income.analysis.run")
def run_analysis_task(self: Any, payload: dict[str, Any]) -> dict[str, Any]:
    return run_analysis_job(
        payload,
        running_task_id=str(self.request.id) if self.request.id else None,
    )


def run_analysis_job(
    payload: Mapping[str, Any],
    *,
    engine: Engine | None = None,
    connection: Connection | None = None,
    redis_client: Any | None = None,
    settings: Settings | None = None,
    panel_loader: PanelLoader = load_analysis_panel,
    twfe_runner: TwfeRunner = fit_twfe_did,
    event_study_runner: EventStudyRunner = fit_traditional_event_study,
    running_task_id: str | None = None,
) -> dict[str, Any]:
    resolved_settings = settings or get_settings()
    request = parse_analysis_request(payload)

    if connection is not None:
        return run_analysis_job_with_connection(
            payload=payload,
            request=request,
            connection=connection,
            redis_client=redis_client,
            settings=resolved_settings,
            panel_loader=panel_loader,
            twfe_runner=twfe_runner,
            event_study_runner=event_study_runner,
            running_task_id=running_task_id,
        )

    db_engine = engine or get_engine()
    with db_engine.connect() as db_connection:
        return run_analysis_job_with_connection(
            payload=payload,
            request=request,
            connection=db_connection,
            redis_client=redis_client,
            settings=resolved_settings,
            panel_loader=panel_loader,
            twfe_runner=twfe_runner,
            event_study_runner=event_study_runner,
            running_task_id=running_task_id,
        )


def run_analysis_job_with_connection(
    *,
    payload: Mapping[str, Any],
    request: AnalysisRequest,
    connection: Connection,
    redis_client: Any | None,
    settings: Settings,
    panel_loader: PanelLoader,
    twfe_runner: TwfeRunner,
    event_study_runner: EventStudyRunner,
    running_task_id: str | None,
) -> dict[str, Any]:
    data_revision = fetch_data_revision(connection)
    cache_key = make_analysis_cache_key(payload, data_revision=data_revision)
    cache_client = (
        redis_client if redis_client is not None else create_redis_client(settings)
    )

    try:
        if not request.force:
            cached_result = read_cached_result(cache_client, cache_key)
            if cached_result is not None:
                return {
                    "status": "success",
                    "cached": True,
                    "cache_key": cache_key,
                    "data_revision": data_revision,
                    "analysis_version": ANALYSIS_VERSION,
                    "result": cached_result,
                }

        loaded_panel = panel_loader(connection, request.outcome, request.spec)
        twfe_result = twfe_runner(loaded_panel.panel.data)
        event_study_result = event_study_runner(loaded_panel.panel.data)

        result = analysis_result_to_dict(
            request=request,
            panel=loaded_panel.panel,
            twfe_result=twfe_result,
            event_study_result=event_study_result,
        )
        write_cached_result(
            cache_client,
            cache_key,
            result,
            ttl_seconds=settings.analysis_cache_ttl_seconds,
        )
        return {
            "status": "success",
            "cached": False,
            "cache_key": cache_key,
            "data_revision": data_revision,
            "analysis_version": ANALYSIS_VERSION,
            "result": result,
        }
    finally:
        if running_task_id is not None:
            clear_running_task(cache_client, cache_key, task_id=running_task_id)


def analysis_result_to_dict(
    *,
    request: AnalysisRequest,
    panel: AnalysisPanel,
    twfe_result: TwfeResult,
    event_study_result: EventStudyResult,
) -> dict[str, Any]:
    return {
        "request": analysis_request_to_payload(request),
        "warnings": [asdict(warning) for warning in panel.warnings],
        "diagnostics": {
            "n_observations": len(panel.data),
            "n_regions": int(panel.data["region_id"].nunique()),
            "n_periods": int(panel.data["period"].nunique()),
            "missing_region_periods": [
                {
                    "region_sido": region.region_sido,
                    "region_sigungu": region.region_sigungu,
                    "period": period,
                }
                for region, period in panel.missing_region_periods
            ],
        },
        "twfe": {
            "coefficient": asdict(twfe_result.coefficient),
            "n_observations": twfe_result.n_observations,
            "n_regions": twfe_result.n_regions,
            "n_clusters": twfe_result.n_clusters,
            "n_periods": twfe_result.n_periods,
        },
        "event_study": {
            "points": [asdict(point) for point in event_study_result.points],
            "n_observations": event_study_result.n_observations,
            "n_regions": event_study_result.n_regions,
            "n_clusters": event_study_result.n_clusters,
            "n_periods": event_study_result.n_periods,
        },
    }

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Callable, Mapping

from redis import Redis
from sqlalchemy import text
from sqlalchemy.engine import Connection, Engine

from rural_basic_income.analysis.cache import (
    ANALYSIS_VERSION,
    clear_running_task,
    fetch_analysis_data_revision,
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
CLAIMED_CACHE_KEY_FIELD = "_claimed_cache_key"


@dataclass(frozen=True)
class PreparedAnalysisRun:
    data_revision: str
    cache_key: str
    cached_result: dict[str, Any] | None = None
    loaded_panel: LoadedAnalysisPanel | None = None


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
    cache_client = (
        redis_client
        if redis_client is not None
        else create_redis_client(resolved_settings)
    )
    claimed_cache_key = payload.get(CLAIMED_CACHE_KEY_FIELD)
    cache_key: str | None = None
    cache_key_holder: dict[str, str] = {}

    try:
        if connection is not None:
            prepared = prepare_analysis_run(
                payload=payload,
                request=request,
                connection=connection,
                cache_client=cache_client,
                panel_loader=panel_loader,
                cache_key_holder=cache_key_holder,
            )
        else:
            db_engine = engine or get_engine()
            with db_engine.connect() as db_connection:
                snapshot_connection = db_connection.execution_options(
                    isolation_level="REPEATABLE READ",
                )
                with snapshot_connection.begin():
                    snapshot_connection.execute(text("SET TRANSACTION READ ONLY"))
                    prepared = prepare_analysis_run(
                        payload=payload,
                        request=request,
                        connection=snapshot_connection,
                        cache_client=cache_client,
                        panel_loader=panel_loader,
                        cache_key_holder=cache_key_holder,
                    )
        cache_key = prepared.cache_key
        return complete_analysis_run(
            prepared=prepared,
            request=request,
            cache_client=cache_client,
            settings=resolved_settings,
            twfe_runner=twfe_runner,
            event_study_runner=event_study_runner,
        )
    finally:
        if running_task_id is not None:
            keys_to_clear = {
                key
                for key in (
                    cache_key,
                    cache_key_holder.get("cache_key"),
                    claimed_cache_key,
                )
                if isinstance(key, str) and key
            }
            for key in keys_to_clear:
                clear_running_task(cache_client, key, task_id=running_task_id)


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
    cache_client = (
        redis_client if redis_client is not None else create_redis_client(settings)
    )
    cache_key_holder: dict[str, str] = {}
    try:
        prepared = prepare_analysis_run(
            payload=payload,
            request=request,
            connection=connection,
            cache_client=cache_client,
            panel_loader=panel_loader,
            cache_key_holder=cache_key_holder,
        )
        return complete_analysis_run(
            prepared=prepared,
            request=request,
            cache_client=cache_client,
            settings=settings,
            twfe_runner=twfe_runner,
            event_study_runner=event_study_runner,
        )
    finally:
        if running_task_id is not None:
            cache_key = cache_key_holder.get("cache_key")
            if cache_key:
                clear_running_task(
                    cache_client,
                    cache_key,
                    task_id=running_task_id,
                )


def prepare_analysis_run(
    *,
    payload: Mapping[str, Any],
    request: AnalysisRequest,
    connection: Connection,
    cache_client: Any,
    panel_loader: PanelLoader,
    cache_key_holder: dict[str, str] | None = None,
) -> PreparedAnalysisRun:
    data_revision = fetch_analysis_data_revision(
        connection,
        outcome_table=request.outcome.table,
    )
    cache_key = make_analysis_cache_key(payload, data_revision=data_revision)
    if cache_key_holder is not None:
        cache_key_holder["cache_key"] = cache_key

    if not request.force:
        cached_result = read_cached_result(cache_client, cache_key)
        if cached_result is not None:
            return PreparedAnalysisRun(
                data_revision=data_revision,
                cache_key=cache_key,
                cached_result=cached_result,
            )

    loaded_panel = panel_loader(connection, request.outcome, request.spec)
    return PreparedAnalysisRun(
        data_revision=data_revision,
        cache_key=cache_key,
        loaded_panel=loaded_panel,
    )


def complete_analysis_run(
    *,
    prepared: PreparedAnalysisRun,
    request: AnalysisRequest,
    cache_client: Any,
    settings: Settings,
    twfe_runner: TwfeRunner,
    event_study_runner: EventStudyRunner,
) -> dict[str, Any]:
    if prepared.cached_result is not None:
        return {
            "status": "success",
            "cached": True,
            "cache_key": prepared.cache_key,
            "data_revision": prepared.data_revision,
            "analysis_version": ANALYSIS_VERSION,
            "result": prepared.cached_result,
        }

    if prepared.loaded_panel is None:
        raise RuntimeError("analysis panel was not loaded")

    twfe_result = twfe_runner(prepared.loaded_panel.panel.data)
    event_study_result = event_study_runner(prepared.loaded_panel.panel.data)

    result = analysis_result_to_dict(
        request=request,
        panel=prepared.loaded_panel.panel,
        twfe_result=twfe_result,
        event_study_result=event_study_result,
        data_revision=prepared.data_revision,
    )
    write_cached_result(
        cache_client,
        prepared.cache_key,
        result,
        ttl_seconds=settings.analysis_cache_ttl_seconds,
    )
    return {
        "status": "success",
        "cached": False,
        "cache_key": prepared.cache_key,
        "data_revision": prepared.data_revision,
        "analysis_version": ANALYSIS_VERSION,
        "result": result,
    }


def analysis_result_to_dict(
    *,
    request: AnalysisRequest,
    panel: AnalysisPanel,
    twfe_result: TwfeResult,
    event_study_result: EventStudyResult,
    data_revision: str,
) -> dict[str, Any]:
    return {
        "request": analysis_request_to_payload(request),
        "data_revision": data_revision,
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

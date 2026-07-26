from __future__ import annotations

import hashlib
import time
from typing import Any, Mapping
from uuid import uuid4

from celery.result import AsyncResult
from fastapi import APIRouter, HTTPException, Request, status
from redis.exceptions import RedisError
from sqlalchemy.exc import SQLAlchemyError

from rural_basic_income.analysis.cache import (
    ANALYSIS_VERSION,
    AnalysisDataRevisionError,
    claim_running_task,
    clear_running_task,
    fetch_analysis_data_revision,
    make_analysis_cache_key,
    read_cached_result,
    read_running_task_id,
)
from rural_basic_income.analysis.exceptions import AnalysisSpecError
from rural_basic_income.analysis.saved import (
    SavedAnalysisError,
    create_saved_analysis,
    delete_saved_analysis,
    get_saved_analysis,
    list_saved_analyses,
    update_saved_analysis,
)
from rural_basic_income.analysis.specification import parse_analysis_request
from rural_basic_income.analysis.tasks import (
    CLAIMED_CACHE_KEY_FIELD,
    create_redis_client,
    run_analysis_task,
)
from rural_basic_income.config import get_settings
from rural_basic_income.db.connection import get_engine
from rural_basic_income.web.api.data import (
    clean_table_metadata,
    fetch_clean_table_names,
    list_regions,
)


router = APIRouter(prefix="/api/analysis", tags=["analysis"])


def enqueue_analysis_task(payload: Mapping[str, Any], *, task_id: str) -> str:
    result = run_analysis_task.apply_async(args=[dict(payload)], task_id=task_id)
    return str(result.id)


def task_status_result(task_id: str) -> AsyncResult:
    return AsyncResult(task_id, app=run_analysis_task.app)


def client_identifier(request: Request) -> str:
    forwarded_for = request.headers.get("x-forwarded-for")
    if forwarded_for:
        return forwarded_for.split(",", 1)[0].strip()
    if request.client and request.client.host:
        return request.client.host
    return "unknown"


def rate_limit_key(identifier: str, *, timestamp: float, window_seconds: int) -> str:
    window = int(timestamp // window_seconds)
    identifier_hash = hashlib.sha256(identifier.encode("utf-8")).hexdigest()[:24]
    return f"rbi:analysis:rate:{identifier_hash}:{window}"


def enforce_rate_limit(redis_client: Any, request: Request) -> None:
    settings = get_settings()
    window_seconds = settings.analysis_rate_limit_window_seconds
    limit = settings.analysis_rate_limit_requests
    key = rate_limit_key(
        client_identifier(request),
        timestamp=time.time(),
        window_seconds=window_seconds,
    )
    count = int(redis_client.incr(key))
    if count == 1:
        redis_client.expire(key, window_seconds)
    if count > limit:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail={
                "message": "too many analysis job requests",
                "limit": limit,
                "window_seconds": window_seconds,
            },
            headers={"Retry-After": str(window_seconds)},
        )


def normalize_task_result(result: Any) -> dict[str, Any]:
    if isinstance(result, Mapping):
        normalized = dict(result)
        cache_key = normalized.get("cache_key")
        if cache_key is not None:
            normalized["result_url"] = f"/api/analysis/results/{cache_key}"
        return normalized
    return {"value": str(result)}


@router.post("/jobs")
def create_analysis_job(
    request: Request,
    payload: dict[str, Any],
) -> dict[str, Any]:
    settings = get_settings()

    try:
        redis_client = create_redis_client(settings)
        enforce_rate_limit(redis_client, request)
        request_spec = parse_analysis_request(payload)
        with get_engine().connect() as connection:
            data_revision = fetch_analysis_data_revision(
                connection,
                outcome_table=request_spec.outcome.table,
            )
        cache_key = make_analysis_cache_key(payload, data_revision=data_revision)
    except AnalysisSpecError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"message": str(exc)},
        ) from exc
    except AnalysisDataRevisionError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"message": str(exc)},
        ) from exc
    except (RedisError, SQLAlchemyError) as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="analysis service unavailable",
        ) from exc

    try:
        if not bool(payload.get("force", False)):
            cached_result = read_cached_result(redis_client, cache_key)
            if cached_result is not None:
                return {
                    "status": "success",
                    "cached": True,
                    "cache_key": cache_key,
                    "data_revision": data_revision,
                    "analysis_version": ANALYSIS_VERSION,
                    "result_url": f"/api/analysis/results/{cache_key}",
                    "result": cached_result,
                }

        existing_task_id = read_running_task_id(redis_client, cache_key)
        if existing_task_id is not None:
            return {
                "status": "running",
                "cached": False,
                "task_id": existing_task_id,
                "cache_key": cache_key,
                "data_revision": data_revision,
                "analysis_version": ANALYSIS_VERSION,
            }

        task_id = uuid4().hex
        task_payload = dict(payload)
        task_payload[CLAIMED_CACHE_KEY_FIELD] = cache_key
        claimed = claim_running_task(
            redis_client,
            cache_key,
            task_id,
            ttl_seconds=settings.analysis_running_lock_ttl_seconds,
        )
        if not claimed:
            existing_task_id = read_running_task_id(redis_client, cache_key)
            return {
                "status": "running",
                "cached": False,
                "task_id": existing_task_id,
                "cache_key": cache_key,
                "data_revision": data_revision,
                "analysis_version": ANALYSIS_VERSION,
            }

        try:
            queued_task_id = enqueue_analysis_task(task_payload, task_id=task_id)
        except Exception as exc:
            clear_running_task(redis_client, cache_key, task_id=task_id)
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="analysis queue unavailable",
            ) from exc
    except RedisError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="analysis service unavailable",
        ) from exc

    return {
        "status": "queued",
        "cached": False,
        "task_id": queued_task_id,
        "cache_key": cache_key,
        "data_revision": data_revision,
        "analysis_version": ANALYSIS_VERSION,
    }


@router.get("/jobs/{task_id}")
def get_analysis_job(task_id: str) -> dict[str, Any]:
    try:
        task_result = task_status_result(task_id)
        response: dict[str, Any] = {
            "task_id": task_id,
            "status": task_result.state,
        }
        if task_result.successful():
            result = normalize_task_result(task_result.result)
            response.update(
                {
                    "cache_key": result.get("cache_key"),
                    "cached": result.get("cached", False),
                    "data_revision": result.get("data_revision"),
                    "analysis_version": result.get("analysis_version"),
                    "result_url": result.get("result_url"),
                    "result_available": result.get("cache_key") is not None,
                }
            )
        elif task_result.failed():
            response["error"] = str(task_result.result)
        return response
    except RedisError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="analysis service unavailable",
        ) from exc


@router.get("/results/{cache_key}")
def get_analysis_result(cache_key: str) -> dict[str, Any]:
    try:
        redis_client = create_redis_client(get_settings())
        result = read_cached_result(redis_client, cache_key)
    except RedisError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="analysis service unavailable",
        ) from exc

    if result is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="analysis result not found",
        )

    return {
        "status": "success",
        "cached": True,
        "cache_key": cache_key,
        "data_revision": result.get("data_revision"),
        "analysis_version": ANALYSIS_VERSION,
        "result": result,
    }


@router.get("/options")
def analysis_options() -> dict[str, Any]:
    try:
        with get_engine().connect() as connection:
            table_names = fetch_clean_table_names(connection)
            tables = [
                clean_table_metadata(connection, table_name)
                for table_name in table_names
            ]
    except SQLAlchemyError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="database unavailable",
        ) from exc

    usable_tables = [
        table
        for table in tables
        if {"date", "region_sido", "region_sigungu"}.issubset(
            {column["name"] for column in table["columns"]}
        )
        and table["selectable_variables"]
    ]
    return {
        "analysis_version": ANALYSIS_VERSION,
        "tables": usable_tables,
        "regions": list_regions()["regions"],
        "rate_limit": {
            "requests": get_settings().analysis_rate_limit_requests,
            "window_seconds": get_settings().analysis_rate_limit_window_seconds,
        },
    }


@router.get("/saved")
def list_saved_analysis_items() -> dict[str, Any]:
    try:
        with get_engine().connect() as connection:
            saved = list_saved_analyses(connection)
    except SQLAlchemyError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="database unavailable",
        ) from exc

    return {"saved": list(saved)}


@router.post("/saved", status_code=status.HTTP_201_CREATED)
def create_saved_analysis_item(payload: dict[str, Any]) -> dict[str, Any]:
    try:
        with get_engine().begin() as connection:
            saved = create_saved_analysis(connection, payload)
    except SavedAnalysisError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"message": str(exc)},
        ) from exc
    except SQLAlchemyError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="database unavailable",
        ) from exc

    return {"saved": saved}


@router.get("/saved/{saved_id}")
def get_saved_analysis_item(saved_id: str) -> dict[str, Any]:
    try:
        with get_engine().connect() as connection:
            saved = get_saved_analysis(connection, saved_id)
    except SavedAnalysisError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"message": str(exc)},
        ) from exc
    except SQLAlchemyError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="database unavailable",
        ) from exc

    if saved is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="saved analysis not found",
        )
    return {"saved": saved}


@router.patch("/saved/{saved_id}")
def update_saved_analysis_item(saved_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    try:
        with get_engine().begin() as connection:
            saved = update_saved_analysis(connection, saved_id, payload)
    except SavedAnalysisError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"message": str(exc)},
        ) from exc
    except SQLAlchemyError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="database unavailable",
        ) from exc

    if saved is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="saved analysis not found",
        )
    return {"saved": saved}


@router.delete("/saved/{saved_id}")
def delete_saved_analysis_item(saved_id: str) -> dict[str, Any]:
    try:
        with get_engine().begin() as connection:
            deleted = delete_saved_analysis(connection, saved_id)
    except SavedAnalysisError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"message": str(exc)},
        ) from exc
    except SQLAlchemyError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="database unavailable",
        ) from exc

    if not deleted:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="saved analysis not found",
        )
    return {"status": "deleted", "id": saved_id}

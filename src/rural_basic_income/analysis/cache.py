from __future__ import annotations

import hashlib
import json
from typing import Any, Mapping

from sqlalchemy import text
from sqlalchemy.engine import Connection
from sqlalchemy.exc import SQLAlchemyError

from rural_basic_income.analysis.specification import (
    analysis_request_to_payload,
    parse_analysis_request,
)


ANALYSIS_VERSION = "0.3.0"
RESULT_KEY_PREFIX = "rbi:analysis:result:"
RUNNING_KEY_PREFIX = "rbi:analysis:running:"


def fetch_data_revision(connection: Connection) -> str:
    try:
        result = connection.execute(
            text(
                """
                SELECT
                    count(*) AS success_count,
                    coalesce(max(downloaded_at)::text, '') AS latest_success_at
                FROM metadata.download_status
                WHERE status = 1
                """
            )
        ).mappings().one()
    except SQLAlchemyError:
        return "metadata.download_status:unavailable"

    return (
        "metadata.download_status:"
        f"{int(result['success_count'] or 0)}:"
        f"{result['latest_success_at'] or ''}"
    )


def canonical_analysis_payload(
    payload: Mapping[str, Any],
    *,
    data_revision: str,
    analysis_version: str = ANALYSIS_VERSION,
) -> dict[str, Any]:
    request = parse_analysis_request(payload)
    canonical = analysis_request_to_payload(request)
    canonical["normalization"] = {"mode": "ratio", "base_value": 1}
    canonical["analysis_version"] = analysis_version
    canonical["data_revision"] = data_revision
    return canonical


def make_analysis_cache_key(
    payload: Mapping[str, Any],
    *,
    data_revision: str,
    analysis_version: str = ANALYSIS_VERSION,
) -> str:
    canonical = canonical_analysis_payload(
        payload,
        data_revision=data_revision,
        analysis_version=analysis_version,
    )
    encoded = json.dumps(
        canonical,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def result_cache_key(cache_key: str) -> str:
    return f"{RESULT_KEY_PREFIX}{cache_key}"


def running_task_key(cache_key: str) -> str:
    return f"{RUNNING_KEY_PREFIX}{cache_key}"


def read_cached_result(redis_client: Any, cache_key: str) -> dict[str, Any] | None:
    raw_value = redis_client.get(result_cache_key(cache_key))
    if raw_value is None:
        return None
    if isinstance(raw_value, bytes):
        raw_value = raw_value.decode("utf-8")
    value = json.loads(raw_value)
    if not isinstance(value, dict):
        return None
    return value


def write_cached_result(
    redis_client: Any,
    cache_key: str,
    result: Mapping[str, Any],
    *,
    ttl_seconds: int,
) -> None:
    redis_client.setex(
        result_cache_key(cache_key),
        ttl_seconds,
        json.dumps(result, ensure_ascii=False, sort_keys=True),
    )


def read_running_task_id(redis_client: Any, cache_key: str) -> str | None:
    task_id = redis_client.get(running_task_key(cache_key))
    if task_id is None:
        return None
    if isinstance(task_id, bytes):
        return task_id.decode("utf-8")
    return str(task_id)


def claim_running_task(
    redis_client: Any,
    cache_key: str,
    task_id: str,
    *,
    ttl_seconds: int,
) -> bool:
    claimed = redis_client.set(
        running_task_key(cache_key),
        task_id,
        nx=True,
        ex=ttl_seconds,
    )
    return bool(claimed)


def clear_running_task(
    redis_client: Any,
    cache_key: str,
    *,
    task_id: str | None = None,
) -> None:
    key = running_task_key(cache_key)
    if task_id is None:
        redis_client.delete(key)
        return

    # Delete only our own lock so a late-finishing task cannot clear a newer run.
    compare_and_delete = """
    if redis.call("get", KEYS[1]) == ARGV[1] then
        return redis.call("del", KEYS[1])
    end
    return 0
    """
    try:
        redis_client.eval(compare_and_delete, 1, key, task_id)
    except AttributeError:
        if read_running_task_id(redis_client, cache_key) == task_id:
            redis_client.delete(key)

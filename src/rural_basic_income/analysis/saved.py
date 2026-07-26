from __future__ import annotations

import json
from collections.abc import Mapping
from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import bindparam, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.engine import Connection

from rural_basic_income.analysis.cache import ANALYSIS_VERSION
from rural_basic_income.analysis.exceptions import AnalysisSpecError
from rural_basic_income.analysis.specification import (
    analysis_request_to_payload,
    parse_analysis_request,
)


LIST_SAVED_SQL = text(
    """
    SELECT
        id,
        title,
        description,
        request_payload,
        result_payload,
        cache_key,
        data_revision,
        analysis_version,
        created_at,
        updated_at,
        last_run_at
    FROM saved.saved_analysis
    ORDER BY updated_at DESC, created_at DESC
    """
)

GET_SAVED_SQL = text(
    """
    SELECT
        id,
        title,
        description,
        request_payload,
        result_payload,
        cache_key,
        data_revision,
        analysis_version,
        created_at,
        updated_at,
        last_run_at
    FROM saved.saved_analysis
    WHERE id = :saved_id
    """
)

INSERT_SAVED_SQL = text(
    """
    INSERT INTO saved.saved_analysis (
        id,
        title,
        description,
        request_payload,
        result_payload,
        cache_key,
        data_revision,
        analysis_version,
        last_run_at
    )
    VALUES (
        :id,
        :title,
        :description,
        :request_payload,
        :result_payload,
        :cache_key,
        :data_revision,
        :analysis_version,
        now()
    )
    RETURNING
        id,
        title,
        description,
        request_payload,
        result_payload,
        cache_key,
        data_revision,
        analysis_version,
        created_at,
        updated_at,
        last_run_at
    """
).bindparams(
    bindparam("request_payload", type_=JSONB),
    bindparam("result_payload", type_=JSONB),
)

UPDATE_SAVED_SQL = text(
    """
    UPDATE saved.saved_analysis
    SET
        title = COALESCE(:title, title),
        description = COALESCE(:description, description),
        request_payload = COALESCE(:request_payload, request_payload),
        result_payload = COALESCE(:result_payload, result_payload),
        cache_key = COALESCE(:cache_key, cache_key),
        data_revision = COALESCE(:data_revision, data_revision),
        analysis_version = COALESCE(:analysis_version, analysis_version),
        updated_at = now(),
        last_run_at = CASE
            WHEN :result_payload IS NULL THEN last_run_at
            ELSE now()
        END
    WHERE id = :saved_id
    RETURNING
        id,
        title,
        description,
        request_payload,
        result_payload,
        cache_key,
        data_revision,
        analysis_version,
        created_at,
        updated_at,
        last_run_at
    """
).bindparams(
    bindparam("request_payload", type_=JSONB),
    bindparam("result_payload", type_=JSONB),
)


class SavedAnalysisError(ValueError):
    """Raised when a saved analysis payload cannot be stored."""


def ensure_saved_analysis_schema(connection: Connection) -> None:
    connection.execute(text("CREATE SCHEMA IF NOT EXISTS saved"))
    connection.execute(
        text(
            """
            CREATE TABLE IF NOT EXISTS saved.saved_analysis (
                id uuid PRIMARY KEY,
                title text NOT NULL,
                description text NOT NULL DEFAULT '',
                request_payload jsonb NOT NULL,
                result_payload jsonb NOT NULL,
                cache_key text,
                data_revision text,
                analysis_version text NOT NULL,
                created_at timestamptz NOT NULL DEFAULT now(),
                updated_at timestamptz NOT NULL DEFAULT now(),
                last_run_at timestamptz NOT NULL DEFAULT now()
            )
            """
        )
    )
    connection.execute(
        text(
            """
            CREATE INDEX IF NOT EXISTS saved_analysis_updated_at_idx
            ON saved.saved_analysis (updated_at DESC)
            """
        )
    )


def normalize_saved_payload(payload: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(payload, Mapping):
        raise SavedAnalysisError("saved analysis payload must be an object")
    try:
        request = parse_analysis_request(payload)
    except AnalysisSpecError as exc:
        raise SavedAnalysisError(str(exc)) from exc
    return analysis_request_to_payload(request)


def normalize_result_payload(payload: Any) -> dict[str, Any]:
    if not isinstance(payload, Mapping):
        raise SavedAnalysisError("result_payload must be an object")
    return dict(payload)


def normalize_title(title: Any, request_payload: Mapping[str, Any]) -> str:
    if title is None:
        return default_saved_title(request_payload)
    normalized = str(title).strip()
    if not normalized:
        return default_saved_title(request_payload)
    return normalized[:160]


def default_saved_title(request_payload: Mapping[str, Any]) -> str:
    outcome = request_payload.get("outcome", {})
    period = request_payload.get("period", {})
    treatments = request_payload.get("treatments", [])
    variable = str(outcome.get("variable") or "analysis")
    start = str(period.get("start") or "")
    end = str(period.get("end") or "")
    treatment_name = "처리지역"
    if treatments:
        treatment = treatments[0]
        treatment_name = (
            f"{treatment.get('region_sido', '')} "
            f"{treatment.get('region_sigungu', '')}"
        ).strip()
    return f"{variable} {treatment_name} {start}-{end}".strip()


def parse_saved_id(value: str | UUID) -> UUID:
    if isinstance(value, UUID):
        return value
    try:
        return UUID(str(value))
    except ValueError as exc:
        raise SavedAnalysisError("invalid saved analysis id") from exc


def encode_json_payload(value: Mapping[str, Any]) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def decode_json_payload(value: Any) -> dict[str, Any]:
    if value is None:
        return {}
    if isinstance(value, Mapping):
        return dict(value)
    if isinstance(value, str):
        decoded = json.loads(value)
        if isinstance(decoded, Mapping):
            return dict(decoded)
    return {}


def serialize_datetime(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value)


def saved_analysis_row_to_dict(
    row: Mapping[str, Any],
    *,
    include_payloads: bool,
) -> dict[str, Any]:
    request_payload = decode_json_payload(row.get("request_payload"))
    result_payload = decode_json_payload(row.get("result_payload"))
    response = {
        "id": str(row["id"]),
        "title": row["title"],
        "description": row.get("description") or "",
        "cache_key": row.get("cache_key"),
        "data_revision": row.get("data_revision"),
        "analysis_version": row.get("analysis_version"),
        "created_at": serialize_datetime(row.get("created_at")),
        "updated_at": serialize_datetime(row.get("updated_at")),
        "last_run_at": serialize_datetime(row.get("last_run_at")),
        "summary": saved_analysis_summary(request_payload, result_payload),
    }
    if include_payloads:
        response["request_payload"] = request_payload
        response["result_payload"] = result_payload
    return response


def saved_analysis_summary(
    request_payload: Mapping[str, Any],
    result_payload: Mapping[str, Any],
) -> dict[str, Any]:
    outcome = request_payload.get("outcome", {})
    period = request_payload.get("period", {})
    treatments = request_payload.get("treatments", [])
    controls = request_payload.get("controls", [])
    coefficient = (
        result_payload.get("twfe", {})
        .get("coefficient", {})
        if isinstance(result_payload, Mapping)
        else {}
    )
    return {
        "outcome_table": outcome.get("table"),
        "outcome_variable": outcome.get("variable"),
        "start_period": period.get("start"),
        "end_period": period.get("end"),
        "normalization_base": period.get("normalization_base"),
        "treatment_count": len(treatments) if isinstance(treatments, list) else 0,
        "control_count": len(controls) if isinstance(controls, list) else 0,
        "first_treatment": treatments[0] if treatments else None,
        "estimate": coefficient.get("estimate") if isinstance(coefficient, Mapping) else None,
        "standard_error": (
            coefficient.get("standard_error")
            if isinstance(coefficient, Mapping)
            else None
        ),
    }


def list_saved_analyses(connection: Connection) -> tuple[dict[str, Any], ...]:
    ensure_saved_analysis_schema(connection)
    rows = connection.execute(LIST_SAVED_SQL).mappings()
    return tuple(
        saved_analysis_row_to_dict(row, include_payloads=False)
        for row in rows
    )


def get_saved_analysis(
    connection: Connection,
    saved_id: str | UUID,
) -> dict[str, Any] | None:
    ensure_saved_analysis_schema(connection)
    row = (
        connection.execute(GET_SAVED_SQL, {"saved_id": parse_saved_id(saved_id)})
        .mappings()
        .one_or_none()
    )
    if row is None:
        return None
    return saved_analysis_row_to_dict(row, include_payloads=True)


def create_saved_analysis(
    connection: Connection,
    payload: Mapping[str, Any],
) -> dict[str, Any]:
    ensure_saved_analysis_schema(connection)
    request_payload = normalize_saved_payload(payload.get("request_payload", {}))
    result_payload = normalize_result_payload(payload.get("result_payload"))
    title = normalize_title(payload.get("title"), request_payload)
    description = str(payload.get("description") or "").strip()
    row = (
        connection.execute(
            INSERT_SAVED_SQL,
            {
                "id": uuid4(),
                "title": title,
                "description": description,
                "request_payload": request_payload,
                "result_payload": result_payload,
                "cache_key": payload.get("cache_key"),
                "data_revision": payload.get("data_revision"),
                "analysis_version": payload.get("analysis_version") or ANALYSIS_VERSION,
            },
        )
        .mappings()
        .one()
    )
    return saved_analysis_row_to_dict(row, include_payloads=True)


def update_saved_analysis(
    connection: Connection,
    saved_id: str | UUID,
    payload: Mapping[str, Any],
) -> dict[str, Any] | None:
    ensure_saved_analysis_schema(connection)
    request_payload = None
    result_payload = None
    if "request_payload" in payload:
        request_payload = normalize_saved_payload(payload["request_payload"])
    if "result_payload" in payload:
        result_payload = normalize_result_payload(payload["result_payload"])

    title = None
    if "title" in payload and payload["title"] is not None:
        if request_payload is None:
            existing = get_saved_analysis(connection, saved_id)
            if existing is None:
                return None
            request_payload = existing["request_payload"]
        title = normalize_title(payload["title"], request_payload)

    description = None
    if "description" in payload and payload["description"] is not None:
        description = str(payload["description"]).strip()

    row = (
        connection.execute(
            UPDATE_SAVED_SQL,
            {
                "saved_id": parse_saved_id(saved_id),
                "title": title,
                "description": description,
                "request_payload": request_payload,
                "result_payload": result_payload,
                "cache_key": payload.get("cache_key"),
                "data_revision": payload.get("data_revision"),
                "analysis_version": payload.get("analysis_version"),
            },
        )
        .mappings()
        .one_or_none()
    )
    if row is None:
        return None
    return saved_analysis_row_to_dict(row, include_payloads=True)


def delete_saved_analysis(connection: Connection, saved_id: str | UUID) -> bool:
    ensure_saved_analysis_schema(connection)
    result = connection.execute(
        text("DELETE FROM saved.saved_analysis WHERE id = :saved_id"),
        {"saved_id": parse_saved_id(saved_id)},
    )
    return bool(result.rowcount)

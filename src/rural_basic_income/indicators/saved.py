from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import bindparam, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.engine import Connection


LIST_SAVED_INDICATORS_SQL = text(
    """
    SELECT
        id,
        title,
        description,
        request_payload,
        result_payload,
        created_at,
        updated_at,
        last_viewed_at
    FROM saved.saved_indicator
    ORDER BY updated_at DESC, created_at DESC
    """
)

GET_SAVED_INDICATOR_SQL = text(
    """
    SELECT
        id,
        title,
        description,
        request_payload,
        result_payload,
        created_at,
        updated_at,
        last_viewed_at
    FROM saved.saved_indicator
    WHERE id = :saved_id
    """
)

INSERT_SAVED_INDICATOR_SQL = text(
    """
    INSERT INTO saved.saved_indicator (
        id,
        title,
        description,
        request_payload,
        result_payload,
        last_viewed_at
    )
    VALUES (
        :id,
        :title,
        :description,
        :request_payload,
        :result_payload,
        now()
    )
    RETURNING
        id,
        title,
        description,
        request_payload,
        result_payload,
        created_at,
        updated_at,
        last_viewed_at
    """
).bindparams(
    bindparam("request_payload", type_=JSONB),
    bindparam("result_payload", type_=JSONB),
)

UPDATE_SAVED_INDICATOR_SQL = text(
    """
    UPDATE saved.saved_indicator
    SET
        title = COALESCE(:title, title),
        description = COALESCE(:description, description),
        request_payload = COALESCE(:request_payload, request_payload),
        result_payload = COALESCE(:result_payload, result_payload),
        updated_at = now(),
        last_viewed_at = CASE
            WHEN :result_payload IS NULL THEN last_viewed_at
            ELSE now()
        END
    WHERE id = :saved_id
    RETURNING
        id,
        title,
        description,
        request_payload,
        result_payload,
        created_at,
        updated_at,
        last_viewed_at
    """
).bindparams(
    bindparam("request_payload", type_=JSONB),
    bindparam("result_payload", type_=JSONB),
)


class SavedIndicatorError(ValueError):
    """Raised when a saved indicator payload cannot be stored."""


def ensure_saved_indicator_schema(connection: Connection) -> None:
    connection.execute(text("CREATE SCHEMA IF NOT EXISTS saved"))
    connection.execute(
        text(
            """
            CREATE TABLE IF NOT EXISTS saved.saved_indicator (
                id uuid PRIMARY KEY,
                title text NOT NULL,
                description text NOT NULL DEFAULT '',
                request_payload jsonb NOT NULL,
                result_payload jsonb NOT NULL,
                created_at timestamptz NOT NULL DEFAULT now(),
                updated_at timestamptz NOT NULL DEFAULT now(),
                last_viewed_at timestamptz NOT NULL DEFAULT now()
            )
            """
        )
    )
    connection.execute(
        text(
            """
            CREATE INDEX IF NOT EXISTS saved_indicator_updated_at_idx
            ON saved.saved_indicator (updated_at DESC)
            """
        )
    )


def normalize_saved_indicator_payload(payload: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(payload, Mapping):
        raise SavedIndicatorError("indicator request payload must be an object")

    table = require_string(payload, "table")
    variables = require_string_list(payload, "variables")
    regions = require_regions(payload.get("regions"))
    filters = optional_string_mapping(payload.get("filters", {}))
    normalization = normalize_normalization(payload.get("normalization", {}))

    return {
        "table": table,
        "variables": variables,
        "regions": regions,
        "filters": dict(sorted(filters.items())),
        "normalization": normalization,
    }


def normalize_result_payload(payload: Any) -> dict[str, Any]:
    if not isinstance(payload, Mapping):
        raise SavedIndicatorError("result_payload must be an object")
    return dict(payload)


def require_string(payload: Mapping[str, Any], key: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not value.strip():
        raise SavedIndicatorError(f"{key} must be a non-empty string")
    return value.strip()


def require_string_list(payload: Mapping[str, Any], key: str) -> list[str]:
    value = payload.get(key)
    if not isinstance(value, Sequence) or isinstance(value, str):
        raise SavedIndicatorError(f"{key} must be an array")
    values = [str(item).strip() for item in value if str(item).strip()]
    if not values:
        raise SavedIndicatorError(f"{key} must not be empty")
    return values


def require_regions(value: Any) -> list[dict[str, str]]:
    if not isinstance(value, Sequence) or isinstance(value, str):
        raise SavedIndicatorError("regions must be an array")
    regions = []
    for item in value:
        if not isinstance(item, Mapping):
            raise SavedIndicatorError("each region must be an object")
        regions.append(
            {
                "region_sido": require_string(item, "region_sido"),
                "region_sigungu": require_string(item, "region_sigungu"),
            }
        )
    if not regions:
        raise SavedIndicatorError("regions must not be empty")
    return regions


def optional_string_mapping(value: Any) -> dict[str, str | list[str]]:
    if not isinstance(value, Mapping):
        raise SavedIndicatorError("filters must be an object")
    return {
        str(key): normalize_filter_value(item_value)
        for key, item_value in value.items()
    }


def normalize_filter_value(value: Any) -> str | list[str]:
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, Sequence):
        values = [str(item).strip() for item in value if str(item).strip()]
        if not values:
            raise SavedIndicatorError("filter arrays must not be empty")
        return values
    return str(value).strip()


def normalize_normalization(value: Any) -> dict[str, str | None]:
    if value is None:
        value = {}
    if not isinstance(value, Mapping):
        raise SavedIndicatorError("normalization must be an object")
    mode = str(value.get("mode") or "raw")
    if mode not in {"raw", "base100"}:
        raise SavedIndicatorError("normalization mode must be raw or base100")
    base_period = value.get("base_period")
    if mode == "base100":
        if not isinstance(base_period, str) or not base_period.strip():
            raise SavedIndicatorError("normalization base_period is required")
        base_period = base_period.strip()
    else:
        base_period = None
    return {"mode": mode, "base_period": base_period}


def normalize_title(title: Any, request_payload: Mapping[str, Any]) -> str:
    if title is None:
        return default_saved_indicator_title(request_payload)
    normalized = str(title).strip()
    if not normalized:
        return default_saved_indicator_title(request_payload)
    return normalized[:160]


def default_saved_indicator_title(request_payload: Mapping[str, Any]) -> str:
    variables = request_payload.get("variables") or ["indicator"]
    regions = request_payload.get("regions") or []
    normalization = request_payload.get("normalization") or {}
    first_region = "지역"
    if regions:
        first_region = (
            f"{regions[0].get('region_sido', '')} "
            f"{regions[0].get('region_sigungu', '')}"
        ).strip()
    suffix = ""
    if normalization.get("mode") == "base100":
        suffix = f" {normalization.get('base_period')}=100"
    return f"{variables[0]} {first_region}{suffix}".strip()


def parse_saved_id(value: str | UUID) -> UUID:
    if isinstance(value, UUID):
        return value
    try:
        return UUID(str(value))
    except ValueError as exc:
        raise SavedIndicatorError("invalid saved indicator id") from exc


def serialize_datetime(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value)


def decode_json_payload(value: Any) -> dict[str, Any]:
    if value is None:
        return {}
    if isinstance(value, Mapping):
        return dict(value)
    return {}


def saved_indicator_summary(
    request_payload: Mapping[str, Any],
    result_payload: Mapping[str, Any],
) -> dict[str, Any]:
    groups = result_payload.get("groups", []) if isinstance(result_payload, Mapping) else []
    total_points = 0
    if isinstance(groups, list):
        for group in groups:
            if isinstance(group, Mapping) and isinstance(group.get("points"), list):
                total_points += len(group["points"])
    normalization = request_payload.get("normalization") or {}
    return {
        "table": request_payload.get("table"),
        "variables": request_payload.get("variables") or [],
        "regions": request_payload.get("regions") or [],
        "region_count": len(request_payload.get("regions") or []),
        "variable_count": len(request_payload.get("variables") or []),
        "normalization_mode": normalization.get("mode", "raw"),
        "normalization_base_period": normalization.get("base_period"),
        "group_count": len(groups) if isinstance(groups, list) else 0,
        "point_count": total_points,
    }


def saved_indicator_row_to_dict(
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
        "created_at": serialize_datetime(row.get("created_at")),
        "updated_at": serialize_datetime(row.get("updated_at")),
        "last_viewed_at": serialize_datetime(row.get("last_viewed_at")),
        "summary": saved_indicator_summary(request_payload, result_payload),
    }
    if include_payloads:
        response["request_payload"] = request_payload
        response["result_payload"] = result_payload
    return response


def list_saved_indicators(connection: Connection) -> tuple[dict[str, Any], ...]:
    ensure_saved_indicator_schema(connection)
    rows = connection.execute(LIST_SAVED_INDICATORS_SQL).mappings()
    return tuple(
        saved_indicator_row_to_dict(row, include_payloads=False)
        for row in rows
    )


def get_saved_indicator(
    connection: Connection,
    saved_id: str | UUID,
) -> dict[str, Any] | None:
    ensure_saved_indicator_schema(connection)
    row = (
        connection.execute(GET_SAVED_INDICATOR_SQL, {"saved_id": parse_saved_id(saved_id)})
        .mappings()
        .one_or_none()
    )
    if row is None:
        return None
    return saved_indicator_row_to_dict(row, include_payloads=True)


def create_saved_indicator(
    connection: Connection,
    payload: Mapping[str, Any],
) -> dict[str, Any]:
    ensure_saved_indicator_schema(connection)
    request_payload = normalize_saved_indicator_payload(payload.get("request_payload", {}))
    result_payload = normalize_result_payload(payload.get("result_payload"))
    title = normalize_title(payload.get("title"), request_payload)
    description = str(payload.get("description") or "").strip()
    row = (
        connection.execute(
            INSERT_SAVED_INDICATOR_SQL,
            {
                "id": uuid4(),
                "title": title,
                "description": description,
                "request_payload": request_payload,
                "result_payload": result_payload,
            },
        )
        .mappings()
        .one()
    )
    return saved_indicator_row_to_dict(row, include_payloads=True)


def update_saved_indicator(
    connection: Connection,
    saved_id: str | UUID,
    payload: Mapping[str, Any],
) -> dict[str, Any] | None:
    ensure_saved_indicator_schema(connection)
    request_payload = None
    result_payload = None
    if "request_payload" in payload:
        request_payload = normalize_saved_indicator_payload(payload["request_payload"])
    if "result_payload" in payload:
        result_payload = normalize_result_payload(payload["result_payload"])

    title = None
    if "title" in payload and payload["title"] is not None:
        if request_payload is None:
            existing = get_saved_indicator(connection, saved_id)
            if existing is None:
                return None
            request_payload = existing["request_payload"]
        title = normalize_title(payload["title"], request_payload)

    description = None
    if "description" in payload and payload["description"] is not None:
        description = str(payload["description"]).strip()

    row = (
        connection.execute(
            UPDATE_SAVED_INDICATOR_SQL,
            {
                "saved_id": parse_saved_id(saved_id),
                "title": title,
                "description": description,
                "request_payload": request_payload,
                "result_payload": result_payload,
            },
        )
        .mappings()
        .one_or_none()
    )
    if row is None:
        return None
    return saved_indicator_row_to_dict(row, include_payloads=True)


def delete_saved_indicator(connection: Connection, saved_id: str | UUID) -> bool:
    ensure_saved_indicator_schema(connection)
    result = connection.execute(
        text("DELETE FROM saved.saved_indicator WHERE id = :saved_id"),
        {"saved_id": parse_saved_id(saved_id)},
    )
    return bool(result.rowcount)

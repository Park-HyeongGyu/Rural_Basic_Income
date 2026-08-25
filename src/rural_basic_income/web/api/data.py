from __future__ import annotations

import csv
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, Query, Request, status
from sqlalchemy import text
from sqlalchemy.engine import Connection
from sqlalchemy.exc import SQLAlchemyError

from rural_basic_income.db.connection import get_engine
from rural_basic_income.indicators.saved import (
    SavedIndicatorError,
    create_saved_indicator,
    delete_saved_indicator,
    get_saved_indicator,
    list_saved_indicators,
    update_saved_indicator,
)

CLEAN_SCHEMA = "clean"
PROJECT_ROOT = Path(__file__).resolve().parents[4]
REGION_MERGE_KEY_PATH = (
    PROJECT_ROOT
    / "src"
    / "rural_basic_income"
    / "worker"
    / "resources"
    / "region_merge_key.csv"
)
BASE_SERIES_COLUMNS = ("date", "region_sido", "region_sigungu")
FILTER_COLUMNS = ("sex", "age", "contract_type")
OD_CLEAN_TABLES = {
    "clean_inflow",
    "clean_inflow_sex",
    "clean_inflow_age",
    "clean_inflow_sex_age",
    "clean_outflow",
    "clean_outflow_sex",
    "clean_outflow_age",
    "clean_outflow_sex_age",
}
NON_VARIABLE_COLUMNS = {
    "date",
    "region_sido",
    "region_sigungu",
    "region_type",
    "sex",
    "age",
    "contract_type",
    "is_gun",
}
NUMERIC_DATA_TYPES = {
    "bigint",
    "double precision",
    "integer",
    "numeric",
    "real",
    "smallint",
}
VARIABLE_LABELS = {
    "household": "세대수",
    "population": "인구",
    "inflow": "전입",
    "outflow": "전출",
    "aggregate_inflow": "총 전입",
    "over_300k_inflow": "30만 이상 지역발 전입",
    "population_decline_inflow": "인구감소지역발 전입",
    "other_inflow": "기타 지역발 전입",
    "aggregate_outflow": "총 전출",
    "over_300k_outflow": "30만 이상 지역행 전출",
    "population_decline_outflow": "인구감소지역행 전출",
    "other_outflow": "기타 지역행 전출",
    "net_migration": "순이동",
    "within_sigungu_migration": "시군구내 이동",
    "intra_sido_inflow": "시도내 시군구간 전입",
    "intra_sido_outflow": "시도내 시군구간 전출",
    "inter_sido_inflow": "시도간 전입",
    "inter_sido_outflow": "시도간 전출",
    "payment_amount": "결제금액",
    "payment_count": "결제건수",
    "customer_count": "고객호수",
    "power_usage": "전력사용량",
    "bill": "전기요금",
    "unit_cost": "평균단가",
    "contract_power": "계약전력",
    "living_population": "생활인구",
    "registered_population": "주민등록인구",
    "stay_population": "체류인구",
    "foreign_population": "외국인",
    "living_population_suppressed": "생활인구 비공개",
    "registered_population_suppressed": "주민등록인구 비공개",
    "stay_population_suppressed": "체류인구 비공개",
    "foreign_population_suppressed": "외국인 비공개",
}
FILTER_LABELS = {
    "sex": "성별",
    "age": "연령",
    "contract_type": "계약종별",
}
FILTER_VALUE_LABELS = {
    "sex": {
        "all": "전체",
        "male": "남자",
        "female": "여자",
        "unknown": "미상",
    },
    "age": {
        "all": "전체",
        "60-": "60세 이상",
        "80-": "80세 이상",
        "unknown": "미상",
    },
}
FILTER_VALUE_ORDER = {
    "sex": ("all", "male", "female", "unknown"),
    "contract_type": (
        "주택용",
        "일반용",
        "산업용",
        "농사용",
        "교육용",
        "가로등",
        "심야",
    ),
}

router = APIRouter(prefix="/api", tags=["data"])


def quote_identifier(identifier: str) -> str:
    return '"' + identifier.replace('"', '""') + '"'


def qualified_table_name(table_name: str) -> str:
    return f"{quote_identifier(CLEAN_SCHEMA)}.{quote_identifier(table_name)}"


def normalize_table_name(table: str) -> str:
    normalized = table.strip()
    if normalized.startswith(f"{CLEAN_SCHEMA}."):
        normalized = normalized.split(".", 1)[1]
    if not normalized:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="table must not be empty",
        )
    return normalized


def fetch_clean_table_names(connection: Connection) -> list[str]:
    return [
        table_name
        for table_name in (
        connection.execute(
            text(
                """
                SELECT table_name
                FROM information_schema.tables
                WHERE table_schema = :schema
                  AND table_type = 'BASE TABLE'
                ORDER BY table_name
                """
            ),
            {"schema": CLEAN_SCHEMA},
        ).scalars()
        )
        if table_name not in OD_CLEAN_TABLES
    ]


def fetch_table_columns(connection: Connection, table_name: str) -> list[dict[str, str]]:
    result = connection.execute(
        text(
            """
            SELECT column_name, data_type
            FROM information_schema.columns
            WHERE table_schema = :schema
              AND table_name = :table_name
            ORDER BY ordinal_position
            """
        ),
        {"schema": CLEAN_SCHEMA, "table_name": table_name},
    )
    return [
        {"name": row.column_name, "data_type": row.data_type}
        for row in result
    ]


def selectable_variables(columns: list[dict[str, str]]) -> list[dict[str, str]]:
    variables = []
    for column in columns:
        name = column["name"]
        if name in NON_VARIABLE_COLUMNS:
            continue
        if column["data_type"] not in NUMERIC_DATA_TYPES:
            continue
        variables.append(
            {
                "name": name,
                "label": VARIABLE_LABELS.get(name, name),
                "data_type": column["data_type"],
            }
        )
    return variables


def filter_columns(columns: list[dict[str, str]]) -> list[str]:
    column_names = {column["name"] for column in columns}
    return [column for column in FILTER_COLUMNS if column in column_names]


def leading_integer(value: str) -> int | None:
    digits = []
    for char in value:
        if char.isdigit():
            digits.append(char)
        else:
            break
    if not digits:
        return None
    return int("".join(digits))


def filter_value_sort_key(filter_name: str, value: str) -> tuple[int, int | str]:
    ordered_values = FILTER_VALUE_ORDER.get(filter_name)
    if ordered_values and value in ordered_values:
        return (0, ordered_values.index(value))
    if value == "all":
        return (0, -1)
    if value == "unknown":
        return (2, value)

    numeric_prefix = leading_integer(value)
    if numeric_prefix is not None:
        return (1, numeric_prefix)
    return (1, value)


def filter_value_label(filter_name: str, value: str) -> str:
    label_map = FILTER_VALUE_LABELS.get(filter_name, {})
    if value in label_map:
        return label_map[value]
    if filter_name == "age":
        return f"{value}세"
    return value


def filter_values(
    connection: Connection,
    table_name: str,
    filter_name: str,
) -> list[dict[str, str]]:
    values = [
        value
        for value in connection.execute(
            text(
                f"""
                SELECT DISTINCT {quote_identifier(filter_name)} AS filter_value
                FROM {qualified_table_name(table_name)}
                WHERE {quote_identifier(filter_name)} IS NOT NULL
                """
            )
        ).scalars()
        if value is not None
    ]
    values = sorted(
        {str(value) for value in values},
        key=lambda value: filter_value_sort_key(filter_name, value),
    )
    return [
        {
            "value": value,
            "label": filter_value_label(filter_name, value),
        }
        for value in values
    ]


def filter_metadata(
    connection: Connection,
    table_name: str,
    columns: list[dict[str, str]],
) -> list[dict[str, Any]]:
    return [
        {
            "name": column,
            "label": FILTER_LABELS.get(column, column),
            "values": filter_values(connection, table_name, column),
        }
        for column in filter_columns(columns)
    ]


def dimension_columns(columns: list[dict[str, str]]) -> list[str]:
    column_names = {column["name"] for column in columns}
    dimensions = [
        column
        for column in (*BASE_SERIES_COLUMNS, *filter_columns(columns))
        if column in column_names
    ]
    return dimensions


def table_period_status(
    connection: Connection,
    table_name: str,
    columns: list[dict[str, str]],
) -> dict[str, int | None]:
    column_names = {column["name"] for column in columns}
    if "date" not in column_names:
        row_count = connection.execute(
            text(f"SELECT count(*) FROM {qualified_table_name(table_name)}")
        ).scalar_one()
        return {
            "row_count": row_count,
            "date_count": None,
            "min_date": None,
            "max_date": None,
        }

    result = connection.execute(
        text(
            f"""
            SELECT
                count(*) AS row_count,
                count(DISTINCT date) AS date_count,
                min(date) AS min_date,
                max(date) AS max_date
            FROM {qualified_table_name(table_name)}
            """
        )
    ).mappings().one()
    return {
        "row_count": result["row_count"],
        "date_count": result["date_count"],
        "min_date": result["min_date"],
        "max_date": result["max_date"],
    }


def clean_table_metadata(connection: Connection, table_name: str) -> dict[str, Any]:
    columns = fetch_table_columns(connection, table_name)
    status_values = table_period_status(connection, table_name, columns)
    return {
        "schema": CLEAN_SCHEMA,
        "table_name": table_name,
        "table": f"{CLEAN_SCHEMA}.{table_name}",
        "columns": columns,
        "dimensions": dimension_columns(columns),
        "filters": filter_metadata(connection, table_name, columns),
        "selectable_variables": selectable_variables(columns),
        **status_values,
    }


@router.get("/regions")
def list_regions() -> dict[str, Any]:
    if not REGION_MERGE_KEY_PATH.exists():
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="region_merge_key.csv is missing",
        )

    with REGION_MERGE_KEY_PATH.open("r", encoding="utf-8-sig", newline="") as csv_file:
        rows = list(csv.DictReader(csv_file))

    regions = [
        {
            "region_sido": row["region_sido"],
            "region_sigungu": row["region_sigungu"],
            "is_gun": int(row["is_gun"]),
        }
        for row in rows
    ]
    regions.sort(key=lambda row: (row["region_sido"], row["region_sigungu"]))
    return {
        "count": len(regions),
        "regions": regions,
    }


@router.get("/data-status")
def data_status() -> dict[str, Any]:
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

    return {
        "schema": CLEAN_SCHEMA,
        "table_count": len(tables),
        "tables": tables,
    }


@router.get("/series")
def series(
    request: Request,
    region_sido: str = Query(...),
    region_sigungu: str = Query(...),
    table: str = Query("clean_population"),
    variable: str = Query("population"),
) -> dict[str, Any]:
    table_name = normalize_table_name(table)

    try:
        with get_engine().connect() as connection:
            table_names = set(fetch_clean_table_names(connection))
            if table_name not in table_names:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail=f"clean table not found: {table_name}",
                )

            metadata = clean_table_metadata(connection, table_name)
            columns = {column["name"] for column in metadata["columns"]}
            variables = {
                candidate["name"]
                for candidate in metadata["selectable_variables"]
            }

            missing_columns = [
                column for column in BASE_SERIES_COLUMNS if column not in columns
            ]
            if missing_columns:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail={
                        "message": "table cannot be used as a regional time series",
                        "missing_columns": missing_columns,
                    },
                )

            if variable not in variables:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail={
                        "message": "variable is not selectable for this table",
                        "allowed_variables": sorted(variables),
                    },
                )

            filters: dict[str, str] = {}
            where_clauses = [
                "region_sido = :region_sido",
                "region_sigungu = :region_sigungu",
            ]
            params: dict[str, str] = {
                "region_sido": region_sido,
                "region_sigungu": region_sigungu,
            }

            for filter_def in metadata["filters"]:
                filter_name = filter_def["name"]
                allowed_values = {
                    item["value"]
                    for item in filter_def["values"]
                }
                if not allowed_values:
                    continue

                requested_value = request.query_params.get(filter_name)
                if requested_value is None:
                    requested_value = (
                        "all"
                        if "all" in allowed_values
                        else filter_def["values"][0]["value"]
                    )

                if requested_value not in allowed_values:
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail={
                            "message": "filter value is not selectable for this table",
                            "filter": filter_name,
                            "allowed_values": sorted(allowed_values),
                        },
                    )

                param_name = f"filter_{filter_name}"
                filters[filter_name] = requested_value
                where_clauses.append(
                    f"{quote_identifier(filter_name)} = :{param_name}"
                )
                params[param_name] = requested_value

            value_column = quote_identifier(variable)
            query = text(
                f"""
                SELECT
                    date,
                    {value_column} AS value
                FROM {qualified_table_name(table_name)}
                WHERE {" AND ".join(where_clauses)}
                ORDER BY date
                """
            )
            rows = connection.execute(query, params).mappings().all()
    except HTTPException:
        raise
    except SQLAlchemyError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="database unavailable",
        ) from exc

    return {
        "table": f"{CLEAN_SCHEMA}.{table_name}",
        "table_name": table_name,
        "variable": variable,
        "region": {
            "region_sido": region_sido,
            "region_sigungu": region_sigungu,
        },
        "filters": filters,
        "count": len(rows),
        "series": [
            {
                "date": row["date"],
                "value": row["value"],
            }
            for row in rows
        ],
    }


@router.get("/indicators/saved")
def list_saved_indicator_items() -> dict[str, Any]:
    try:
        with get_engine().connect() as connection:
            saved = list_saved_indicators(connection)
    except SQLAlchemyError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="database unavailable",
        ) from exc

    return {"saved": list(saved)}


@router.post("/indicators/saved", status_code=status.HTTP_201_CREATED)
def create_saved_indicator_item(payload: dict[str, Any]) -> dict[str, Any]:
    try:
        with get_engine().begin() as connection:
            saved = create_saved_indicator(connection, payload)
    except SavedIndicatorError as exc:
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


@router.get("/indicators/saved/{saved_id}")
def get_saved_indicator_item(saved_id: str) -> dict[str, Any]:
    try:
        with get_engine().connect() as connection:
            saved = get_saved_indicator(connection, saved_id)
    except SavedIndicatorError as exc:
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
            detail="saved indicator not found",
        )
    return {"saved": saved}


@router.patch("/indicators/saved/{saved_id}")
def update_saved_indicator_item(saved_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    try:
        with get_engine().begin() as connection:
            saved = update_saved_indicator(connection, saved_id, payload)
    except SavedIndicatorError as exc:
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
            detail="saved indicator not found",
        )
    return {"saved": saved}


@router.delete("/indicators/saved/{saved_id}")
def delete_saved_indicator_item(saved_id: str) -> dict[str, Any]:
    try:
        with get_engine().begin() as connection:
            deleted = delete_saved_indicator(connection, saved_id)
    except SavedIndicatorError as exc:
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
            detail="saved indicator not found",
        )
    return {"status": "deleted", "id": saved_id}

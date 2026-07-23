from __future__ import annotations

import csv
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, Query, status
from sqlalchemy import text
from sqlalchemy.engine import Connection
from sqlalchemy.exc import SQLAlchemyError

from rural_basic_income.db.connection import get_engine

CLEAN_SCHEMA = "clean"
PROJECT_ROOT = Path(__file__).resolve().parents[4]
REGION_MERGE_KEY_PATH = (
    PROJECT_ROOT / "src" / "rural_basic_income" / "pipeline" / "region_merge_key.csv"
)
BASE_SERIES_COLUMNS = ("date", "region_sido", "region_sigungu")
FILTER_COLUMNS = ("sex", "age")
NON_VARIABLE_COLUMNS = {
    "date",
    "region_sido",
    "region_sigungu",
    "sex",
    "age",
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
    "net_migration": "순이동",
    "within_sigungu_migration": "시군구내 이동",
    "intra_sido_inflow": "시도내 시군구간 전입",
    "intra_sido_outflow": "시도내 시군구간 전출",
    "inter_sido_inflow": "시도간 전입",
    "inter_sido_outflow": "시도간 전출",
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
    return list(
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


def dimension_columns(columns: list[dict[str, str]]) -> list[str]:
    column_names = {column["name"] for column in columns}
    dimensions = [
        column
        for column in (*BASE_SERIES_COLUMNS, *FILTER_COLUMNS, "is_gun")
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
    region_sido: str = Query(...),
    region_sigungu: str = Query(...),
    table: str = Query("clean_population"),
    variable: str = Query("population"),
    sex: str | None = Query(None),
    age: str | None = Query(None),
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

            if "sex" in columns:
                filters["sex"] = sex or "all"
                where_clauses.append("sex = :sex")
                params["sex"] = filters["sex"]
            if "age" in columns:
                filters["age"] = age or "all"
                where_clauses.append("age = :age")
                params["age"] = filters["age"]

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

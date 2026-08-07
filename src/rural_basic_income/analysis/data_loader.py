from __future__ import annotations

import csv
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pandas as pd
from sqlalchemy import text
from sqlalchemy.engine import Connection

from rural_basic_income.analysis.exceptions import AnalysisSpecError
from rural_basic_income.analysis.panel import AnalysisPanel, build_analysis_panel
from rural_basic_income.analysis.schemas import (
    AnalysisOutcome,
    AnalysisSpec,
    RegionKey,
)


CLEAN_SCHEMA = "clean"
PROJECT_ROOT = Path(__file__).resolve().parents[3]
REGION_MERGE_KEY_PATH = (
    PROJECT_ROOT
    / "src"
    / "rural_basic_income"
    / "worker"
    / "resources"
    / "region_merge_key.csv"
)
BASE_COLUMNS = ("date", "region_sido", "region_sigungu")
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


@dataclass(frozen=True)
class ColumnMetadata:
    name: str
    data_type: str


@dataclass(frozen=True)
class FilterMetadata:
    name: str
    values: tuple[str, ...]


@dataclass(frozen=True)
class AnalysisTableMetadata:
    table_name: str
    columns: tuple[ColumnMetadata, ...]
    selectable_variables: tuple[str, ...]
    filters: tuple[FilterMetadata, ...]

    @property
    def column_names(self) -> set[str]:
        return {column.name for column in self.columns}

    @property
    def filter_by_name(self) -> dict[str, FilterMetadata]:
        return {item.name: item for item in self.filters}


@dataclass(frozen=True)
class LoadedAnalysisPanel:
    outcome: AnalysisOutcome
    table_metadata: AnalysisTableMetadata
    panel: AnalysisPanel


def quote_identifier(identifier: str) -> str:
    return '"' + identifier.replace('"', '""') + '"'


def qualified_table_name(table_name: str) -> str:
    return f"{quote_identifier(CLEAN_SCHEMA)}.{quote_identifier(table_name)}"


def fetch_clean_table_names(connection: Connection) -> tuple[str, ...]:
    return tuple(
        table_name
        for table_name in connection.execute(
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
        if table_name not in OD_CLEAN_TABLES
    )


def fetch_table_columns(
    connection: Connection,
    table_name: str,
) -> tuple[ColumnMetadata, ...]:
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
    return tuple(
        ColumnMetadata(name=row.column_name, data_type=row.data_type)
        for row in result
    )


def selectable_variables(columns: tuple[ColumnMetadata, ...]) -> tuple[str, ...]:
    return tuple(
        column.name
        for column in columns
        if column.name not in NON_VARIABLE_COLUMNS
        and column.data_type in NUMERIC_DATA_TYPES
    )


def fetch_filter_values(
    connection: Connection,
    table_name: str,
    filter_name: str,
) -> tuple[str, ...]:
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
    return tuple(sorted({str(value) for value in values}))


def load_table_metadata(
    connection: Connection,
    table_name: str,
) -> AnalysisTableMetadata:
    clean_table_names = set(fetch_clean_table_names(connection))
    if table_name not in clean_table_names:
        raise AnalysisSpecError(f"clean table is not available: {table_name}")

    columns = fetch_table_columns(connection, table_name)
    column_names = {column.name for column in columns}
    missing_base_columns = [
        column for column in BASE_COLUMNS if column not in column_names
    ]
    if missing_base_columns:
        raise AnalysisSpecError(
            "clean table cannot be used for regional analysis; missing columns: "
            + ", ".join(missing_base_columns)
        )

    filters = tuple(
        FilterMetadata(
            name=filter_name,
            values=fetch_filter_values(connection, table_name, filter_name),
        )
        for filter_name in FILTER_COLUMNS
        if filter_name in column_names
    )
    variables = selectable_variables(columns)
    if not variables:
        raise AnalysisSpecError(
            f"clean table has no selectable numeric variables: {table_name}"
        )
    return AnalysisTableMetadata(
        table_name=table_name,
        columns=columns,
        selectable_variables=variables,
        filters=filters,
    )


def validate_outcome(
    outcome: AnalysisOutcome,
    metadata: AnalysisTableMetadata,
) -> None:
    if outcome.variable not in metadata.selectable_variables:
        raise AnalysisSpecError(
            "outcome variable is not selectable for this table: "
            f"{outcome.variable}"
        )

    available_filters = metadata.filter_by_name
    unknown_filters = sorted(set(outcome.filters).difference(available_filters))
    if unknown_filters:
        raise AnalysisSpecError(
            "outcome filters are not available for this table: "
            + ", ".join(unknown_filters)
        )

    missing_filters = sorted(set(available_filters).difference(outcome.filters))
    if missing_filters:
        raise AnalysisSpecError(
            "outcome filters are required for this table: "
            + ", ".join(missing_filters)
        )

    invalid_filter_values = []
    for filter_name, filter_values in outcome.filters.items():
        allowed_values = available_filters[filter_name].values
        for filter_value in filter_values:
            if filter_value not in allowed_values:
                invalid_filter_values.append(
                    f"{filter_name}={filter_value} allowed={list(allowed_values)}"
                )
    if invalid_filter_values:
        raise AnalysisSpecError(
            "outcome filter values are not selectable: "
            + "; ".join(invalid_filter_values)
        )


def load_region_keys(
    path: Path = REGION_MERGE_KEY_PATH,
) -> set[RegionKey]:
    with path.open("r", encoding="utf-8-sig", newline="") as csv_file:
        return {
            RegionKey(row["region_sido"], row["region_sigungu"])
            for row in csv.DictReader(csv_file)
        }


def validate_regions(
    spec: AnalysisSpec,
    available_regions: set[RegionKey],
) -> None:
    missing_regions = sorted(set(spec.all_regions).difference(available_regions))
    if missing_regions:
        raise AnalysisSpecError(
            "analysis regions are not in region_merge_key: "
            + ", ".join(region.region_id for region in missing_regions)
        )


def fetch_analysis_rows(
    connection: Connection,
    outcome: AnalysisOutcome,
    spec: AnalysisSpec,
) -> list[dict[str, Any]]:
    params: dict[str, Any] = {
        "start_period": int(spec.period.start_period),
        "end_period": int(spec.period.end_period),
        "normalization_base": int(spec.period.normalization_base),
    }
    where_clauses = [
        "((date BETWEEN :start_period AND :end_period) "
        "OR date = :normalization_base)"
    ]

    region_clauses = []
    for index, region in enumerate(spec.all_regions):
        sido_param = f"region_sido_{index}"
        sigungu_param = f"region_sigungu_{index}"
        region_clauses.append(
            f"(region_sido = :{sido_param} AND region_sigungu = :{sigungu_param})"
        )
        params[sido_param] = region.region_sido
        params[sigungu_param] = region.region_sigungu
    where_clauses.append("(" + " OR ".join(region_clauses) + ")")

    for filter_name, filter_values in outcome.filters.items():
        if len(filter_values) == 1:
            param_name = f"filter_{filter_name}"
            where_clauses.append(f"{quote_identifier(filter_name)} = :{param_name}")
            params[param_name] = filter_values[0]
            continue

        param_names = []
        for index, filter_value in enumerate(filter_values):
            param_name = f"filter_{filter_name}_{index}"
            param_names.append(f":{param_name}")
            params[param_name] = filter_value
        where_clauses.append(
            f"{quote_identifier(filter_name)} IN ({', '.join(param_names)})"
        )

    statement = text(
        f"""
        SELECT
            date,
            region_sido,
            region_sigungu,
            SUM({quote_identifier(outcome.variable)}) AS raw_value
        FROM {qualified_table_name(outcome.table)}
        WHERE {' AND '.join(where_clauses)}
        GROUP BY date, region_sido, region_sigungu
        ORDER BY region_sido, region_sigungu, date
        """
    )
    return [
        dict(row)
        for row in connection.execute(statement, params).mappings()
    ]


def load_analysis_panel(
    connection: Connection,
    outcome: AnalysisOutcome,
    spec: AnalysisSpec,
    *,
    region_merge_key_path: Path = REGION_MERGE_KEY_PATH,
) -> LoadedAnalysisPanel:
    metadata = load_table_metadata(connection, outcome.table)
    validate_outcome(outcome, metadata)
    validate_regions(spec, load_region_keys(region_merge_key_path))

    rows = fetch_analysis_rows(connection, outcome, spec)
    panel = build_analysis_panel(
        pd.DataFrame(rows),
        spec,
        outcome_column="raw_value",
    )
    return LoadedAnalysisPanel(
        outcome=outcome,
        table_metadata=metadata,
        panel=panel,
    )

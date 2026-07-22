from __future__ import annotations

import csv
import json
from collections import OrderedDict
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sqlalchemy import text
from sqlalchemy.engine import Engine

from rural_basic_income.db.connection import get_engine
from rural_basic_income.pipeline.kosis import fetch_statistics_parameter_data

DOWNLOAD_STATUS_NOT_DOWNLOADED = 0
DOWNLOAD_STATUS_OK = 1
DOWNLOAD_STATUS_PROBLEM = 2


@dataclass(frozen=True)
class KosisRawSpec:
    source_name: str
    source_name_kor: str
    source_org_id: str
    source_table_id: str
    raw_table: str


HOUSEHOLD_SPEC = KosisRawSpec(
    source_name="household",
    source_name_kor="행정구역(시군구)별 주민등록세대수",
    source_org_id="101",
    source_table_id="DT_1B040B3",
    raw_table="household",
)
POPULATION_SPEC = KosisRawSpec(
    source_name="population",
    source_name_kor="행정구역(시군구)별/1세별 주민등록인구",
    source_org_id="101",
    source_table_id="DT_1B04006",
    raw_table="population",
)
MOVER_SPEC = KosisRawSpec(
    source_name="mover",
    source_name_kor="시군구/성/연령(5세)별 이동자수",
    source_org_id="101",
    source_table_id="DT_1B26001",
    raw_table="mover",
)

KOSIS_RAW_SPECS = (HOUSEHOLD_SPEC, POPULATION_SPEC, MOVER_SPEC)


def quote_identifier(identifier: str) -> str:
    return '"' + identifier.replace('"', '""') + '"'


def make_chunks(values: Sequence[str], chunk_size: int) -> list[list[str]]:
    if chunk_size < 1:
        raise ValueError("chunk_size must be at least 1")

    return [
        list(values[start : start + chunk_size])
        for start in range(0, len(values), chunk_size)
    ]


def dedupe_preserve_order(values: Iterable[str]) -> list[str]:
    seen = set()
    deduped = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        deduped.append(value)
    return deduped


def get_dimension_specs(rows: Sequence[Mapping[str, Any]]) -> list[tuple[str, str, str]]:
    if not rows:
        return []

    first_row = rows[0]
    dimensions = []
    for index in range(1, 9):
        obj_key = f"C{index}_OBJ_NM"
        code_key = f"C{index}"
        name_key = f"C{index}_NM"
        obj_name = first_row.get(obj_key)
        if not obj_name or code_key not in first_row or name_key not in first_row:
            continue
        dimensions.append((code_key, name_key, str(obj_name)))

    return dimensions


def get_item_column_name(row: Mapping[str, Any]) -> str:
    item_name = str(row.get("ITM_NM") or "값")
    unit_name = row.get("UNIT_NM")
    if unit_name:
        return f"{item_name} ({unit_name})"
    return item_name


def kosis_rows_to_raw_rows(
    rows: Sequence[Mapping[str, Any]],
) -> tuple[list[str], list[dict[str, str]]]:
    if not rows:
        return ["시점"], []

    dimension_specs = get_dimension_specs(rows)
    base_columns = ["시점"]
    for code_key, _name_key, obj_name in dimension_specs:
        base_columns.extend([f"C{obj_name}", obj_name])

    item_columns: OrderedDict[str, None] = OrderedDict()
    grouped_rows: OrderedDict[tuple[str, ...], dict[str, str]] = OrderedDict()

    for row in rows:
        item_column = get_item_column_name(row)
        item_columns.setdefault(item_column, None)

        output_row: dict[str, str] = {"시점": str(row.get("PRD_DE") or "")}
        key_parts = [output_row["시점"]]
        for code_key, name_key, obj_name in dimension_specs:
            code_column = f"C{obj_name}"
            name_column = obj_name
            output_row[code_column] = str(row.get(code_key) or "")
            output_row[name_column] = str(row.get(name_key) or "")
            key_parts.extend([output_row[code_column], output_row[name_column]])

        key = tuple(key_parts)
        if key not in grouped_rows:
            grouped_rows[key] = output_row
        grouped_rows[key][item_column] = str(row.get("DT") or "")

    columns = base_columns + list(item_columns.keys()) + ["downloaded_at"]
    downloaded_at = datetime.now(UTC).isoformat()
    output_rows = []
    for row in grouped_rows.values():
        complete_row = {column: row.get(column, "") for column in columns}
        complete_row["downloaded_at"] = downloaded_at
        output_rows.append(complete_row)

    return columns, output_rows


def base_params(spec: KosisRawSpec, period: str) -> dict[str, str]:
    return {
        "orgId": spec.source_org_id,
        "tblId": spec.source_table_id,
        "prdSe": "M",
        "startPrdDe": period,
        "endPrdDe": period,
        "itmId": "ALL",
    }


def fetch_kosis_raw_payloads(
    period: str,
    *,
    population_chunk_size: int = 100,
    mover_chunk_size: int = 70,
) -> dict[str, list[tuple[dict[str, str], list[dict[str, Any]]]]]:
    household_params = {
        **base_params(HOUSEHOLD_SPEC, period),
        "objL1": "ALL",
    }
    household_rows = fetch_statistics_parameter_data(household_params)
    region_codes = dedupe_preserve_order(
        str(row["C1"])
        for row in household_rows
        if row.get("C1")
    )

    payloads: dict[str, list[tuple[dict[str, str], list[dict[str, Any]]]]] = {
        HOUSEHOLD_SPEC.source_name: [(household_params, household_rows)],
        POPULATION_SPEC.source_name: [],
        MOVER_SPEC.source_name: [],
    }

    for chunk in make_chunks(region_codes, population_chunk_size):
        params = {
            **base_params(POPULATION_SPEC, period),
            "objL1": "+".join(chunk),
            "objL2": "ALL",
        }
        payloads[POPULATION_SPEC.source_name].append(
            (params, fetch_statistics_parameter_data(params))
        )

    for chunk in make_chunks(region_codes, mover_chunk_size):
        params = {
            **base_params(MOVER_SPEC, period),
            "objL1": "+".join(chunk),
            "objL2": "ALL",
            "objL3": "ALL",
        }
        payloads[MOVER_SPEC.source_name].append(
            (params, fetch_statistics_parameter_data(params))
        )

    return payloads


def create_tracking_tables(engine: Engine) -> None:
    statements = [
        "CREATE SCHEMA IF NOT EXISTS raw_json",
        "CREATE SCHEMA IF NOT EXISTS raw",
        "CREATE SCHEMA IF NOT EXISTS metadata",
        """
        CREATE TABLE IF NOT EXISTS raw_json.kosis_payloads (
            id bigserial PRIMARY KEY,
            source_name text NOT NULL,
            source_name_kor text NOT NULL,
            source_org_id text NOT NULL,
            source_table_id text NOT NULL,
            period text NOT NULL,
            request_params jsonb NOT NULL,
            response_payload jsonb NOT NULL,
            row_count integer NOT NULL,
            downloaded_at timestamptz NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS metadata.download_status (
            source_name text NOT NULL,
            source_name_kor text NOT NULL,
            source_table_id text NOT NULL,
            period text NOT NULL,
            status smallint NOT NULL,
            row_count integer,
            downloaded_at timestamptz NOT NULL DEFAULT CURRENT_TIMESTAMP,
            error_message text,
            PRIMARY KEY (source_name, period)
        )
        """,
    ]
    with engine.begin() as connection:
        for statement in statements:
            connection.execute(text(statement))


def reset_period(engine: Engine, period: str) -> None:
    source_names = [spec.source_name for spec in KOSIS_RAW_SPECS]
    with engine.begin() as connection:
        connection.execute(
            text(
                """
                DELETE FROM raw_json.kosis_payloads
                WHERE period = :period
                  AND source_name = ANY(:source_names)
                """
            ),
            {"period": period, "source_names": source_names},
        )
        connection.execute(
            text(
                """
                DELETE FROM metadata.download_status
                WHERE period = :period
                  AND source_name = ANY(:source_names)
                """
            ),
            {"period": period, "source_names": source_names},
        )
        for spec in KOSIS_RAW_SPECS:
            connection.execute(
                text(f"DROP TABLE IF EXISTS raw.{quote_identifier(spec.raw_table)}")
            )


def insert_payload_chunks(
    engine: Engine,
    spec: KosisRawSpec,
    period: str,
    chunks: Sequence[tuple[dict[str, str], list[dict[str, Any]]]],
) -> None:
    rows = [
        {
            "source_name": spec.source_name,
            "source_name_kor": spec.source_name_kor,
            "source_org_id": spec.source_org_id,
            "source_table_id": spec.source_table_id,
            "period": period,
            "request_params": json.dumps(params, ensure_ascii=False),
            "response_payload": json.dumps(payload, ensure_ascii=False),
            "row_count": len(payload),
        }
        for params, payload in chunks
    ]
    if not rows:
        return

    with engine.begin() as connection:
        connection.execute(
            text(
                """
                INSERT INTO raw_json.kosis_payloads (
                    source_name,
                    source_name_kor,
                    source_org_id,
                    source_table_id,
                    period,
                    request_params,
                    response_payload,
                    row_count
                )
                VALUES (
                    :source_name,
                    :source_name_kor,
                    :source_org_id,
                    :source_table_id,
                    :period,
                    CAST(:request_params AS jsonb),
                    CAST(:response_payload AS jsonb),
                    :row_count
                )
                """
            ),
            rows,
        )


def create_raw_table(
    engine: Engine,
    table_name: str,
    columns: Sequence[str],
) -> None:
    column_definitions = []
    for column in columns:
        column_type = "timestamptz" if column == "downloaded_at" else "text"
        column_definitions.append(f"{quote_identifier(column)} {column_type}")

    ddl = (
        f"CREATE TABLE raw.{quote_identifier(table_name)} "
        f"({', '.join(column_definitions)})"
    )
    with engine.begin() as connection:
        connection.execute(text(ddl))


def insert_raw_rows(
    engine: Engine,
    table_name: str,
    columns: Sequence[str],
    rows: Sequence[Mapping[str, str]],
) -> None:
    if not rows:
        return

    insert_columns = [column for column in columns if column != "downloaded_at"]
    quoted_columns = ", ".join(
        quote_identifier(column)
        for column in insert_columns + ["downloaded_at"]
    )
    value_placeholders = ", ".join(
        f":col_{index}" for index, _column in enumerate(insert_columns)
    )
    sql = (
        f"INSERT INTO raw.{quote_identifier(table_name)} ({quoted_columns}) "
        f"VALUES ({value_placeholders}, CURRENT_TIMESTAMP)"
    )
    parameters = [
        {
            f"col_{index}": row.get(column, "")
            for index, column in enumerate(insert_columns)
        }
        for row in rows
    ]

    with engine.begin() as connection:
        connection.execute(text(sql), parameters)


def update_download_status(
    engine: Engine,
    spec: KosisRawSpec,
    period: str,
    *,
    status: int,
    row_count: int | None,
    error_message: str | None = None,
) -> None:
    with engine.begin() as connection:
        connection.execute(
            text(
                """
                INSERT INTO metadata.download_status (
                    source_name,
                    source_name_kor,
                    source_table_id,
                    period,
                    status,
                    row_count,
                    error_message
                )
                VALUES (
                    :source_name,
                    :source_name_kor,
                    :source_table_id,
                    :period,
                    :status,
                    :row_count,
                    :error_message
                )
                ON CONFLICT (source_name, period)
                DO UPDATE SET
                    source_name_kor = EXCLUDED.source_name_kor,
                    source_table_id = EXCLUDED.source_table_id,
                    status = EXCLUDED.status,
                    row_count = EXCLUDED.row_count,
                    downloaded_at = CURRENT_TIMESTAMP,
                    error_message = EXCLUDED.error_message
                """
            ),
            {
                "source_name": spec.source_name,
                "source_name_kor": spec.source_name_kor,
                "source_table_id": spec.source_table_id,
                "period": period,
                "status": status,
                "row_count": row_count,
                "error_message": error_message,
            },
        )


def load_raw_tables(
    period: str = "202601",
    *,
    engine: Engine | None = None,
) -> dict[str, int]:
    db_engine = engine or get_engine()
    create_tracking_tables(db_engine)
    reset_period(db_engine, period)

    payloads = fetch_kosis_raw_payloads(period)
    row_counts: dict[str, int] = {}

    for spec in KOSIS_RAW_SPECS:
        chunks = payloads[spec.source_name]
        long_rows = [
            row
            for _params, payload in chunks
            for row in payload
        ]
        columns, raw_rows = kosis_rows_to_raw_rows(long_rows)

        insert_payload_chunks(db_engine, spec, period, chunks)
        create_raw_table(db_engine, spec.raw_table, columns)
        insert_raw_rows(db_engine, spec.raw_table, columns, raw_rows)
        update_download_status(
            db_engine,
            spec,
            period,
            status=DOWNLOAD_STATUS_OK,
            row_count=len(raw_rows),
        )
        row_counts[spec.source_name] = len(raw_rows)

    return row_counts


def get_table_columns(engine: Engine, schema_name: str, table_name: str) -> list[str]:
    with engine.begin() as connection:
        result = connection.execute(
            text(
                """
                SELECT column_name
                FROM information_schema.columns
                WHERE table_schema = :schema_name
                  AND table_name = :table_name
                ORDER BY ordinal_position
                """
            ),
            {"schema_name": schema_name, "table_name": table_name},
        )
        return [row[0] for row in result]


def export_table_to_csv(
    engine: Engine,
    schema_name: str,
    table_name: str,
    output_path: Path,
) -> None:
    columns = get_table_columns(engine, schema_name, table_name)
    quoted_columns = ", ".join(quote_identifier(column) for column in columns)
    sql = (
        f"SELECT {quoted_columns} "
        f"FROM {quote_identifier(schema_name)}.{quote_identifier(table_name)}"
    )

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with engine.begin() as connection, output_path.open(
        "w",
        encoding="utf-8-sig",
        newline="",
    ) as output_file:
        writer = csv.writer(output_file)
        writer.writerow(columns)
        for row in connection.execute(text(sql)):
            writer.writerow([
                json.dumps(value, ensure_ascii=False)
                if isinstance(value, (dict, list))
                else value
                for value in row
            ])


def export_raw_test_tables(
    output_dir: Path = Path("data/temp"),
    *,
    engine: Engine | None = None,
) -> list[Path]:
    db_engine = engine or get_engine()
    tables = [
        ("raw_json", "kosis_payloads"),
        ("raw", "household"),
        ("raw", "population"),
        ("raw", "mover"),
        ("metadata", "download_status"),
    ]
    exported_paths = []
    for schema_name, table_name in tables:
        output_path = output_dir / f"{schema_name}_{table_name}.csv"
        export_table_to_csv(db_engine, schema_name, table_name, output_path)
        exported_paths.append(output_path)

    return exported_paths

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Literal

from sqlalchemy import text
from sqlalchemy.engine import Connection, Engine

from rural_basic_income.db.connection import get_engine
from rural_basic_income.worker.download import PeriodDownload, SourcePeriodDownload

DOWNLOAD_STATUS_OK = 1

RawWriteStatus = Literal["written", "skipped"]


class RawWriterError(RuntimeError):
    """Raised when a download result cannot be written as raw data."""


@dataclass(frozen=True)
class RawWriteResult:
    source_name: str
    period: str
    status: RawWriteStatus
    row_count: int


def quote_identifier(identifier: str) -> str:
    if not identifier or "\x00" in identifier:
        raise RawWriterError(f"invalid SQL identifier: {identifier!r}")
    return '"' + identifier.replace('"', '""') + '"'


def column_type(column: str) -> str:
    if column == "downloaded_at":
        return "timestamptz"
    return "text"


def create_writer_tables(connection: Connection) -> None:
    statements = [
        "CREATE SCHEMA IF NOT EXISTS raw_json",
        "CREATE SCHEMA IF NOT EXISTS raw",
        "CREATE SCHEMA IF NOT EXISTS metadata",
        """
        CREATE TABLE IF NOT EXISTS raw_json.payloads (
            id bigserial PRIMARY KEY,
            source_name text NOT NULL,
            source_name_kor text NOT NULL,
            source_org_id text NOT NULL,
            source_table_id text NOT NULL,
            raw_table text NOT NULL,
            period text NOT NULL,
            chunk_index integer NOT NULL,
            request_params jsonb NOT NULL,
            response_payload jsonb NOT NULL,
            row_count integer NOT NULL,
            downloaded_at timestamptz NOT NULL DEFAULT CURRENT_TIMESTAMP,
            UNIQUE (source_name, period, chunk_index)
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
    for statement in statements:
        connection.execute(text(statement))


def table_exists(
    connection: Connection,
    schema_name: str,
    table_name: str,
) -> bool:
    exists = connection.execute(
        text(
            """
            SELECT 1
            FROM information_schema.tables
            WHERE table_schema = :schema_name
              AND table_name = :table_name
            """
        ),
        {"schema_name": schema_name, "table_name": table_name},
    ).scalar_one_or_none()
    return exists is not None


def get_table_columns(
    connection: Connection,
    schema_name: str,
    table_name: str,
) -> list[str]:
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


def ensure_raw_table(
    connection: Connection,
    table_name: str,
    columns: Sequence[str],
) -> None:
    if not columns:
        raise RawWriterError("raw_columns must contain at least one column")

    column_definitions = ", ".join(
        f"{quote_identifier(column)} {column_type(column)}"
        for column in columns
    )
    connection.execute(
        text(
            f"""
            CREATE TABLE IF NOT EXISTS raw.{quote_identifier(table_name)}
            ({column_definitions})
            """
        )
    )

    existing_columns = set(get_table_columns(connection, "raw", table_name))
    for column in columns:
        if column in existing_columns:
            continue
        connection.execute(
            text(
                f"""
                ALTER TABLE raw.{quote_identifier(table_name)}
                ADD COLUMN {quote_identifier(column)} {column_type(column)}
                """
            )
        )


def successful_row_count(
    connection: Connection,
    download: SourcePeriodDownload,
) -> int | None:
    row_count = connection.execute(
        text(
            """
            SELECT row_count
            FROM metadata.download_status
            WHERE source_name = :source_name
              AND period = :period
              AND status = :status
            """
        ),
        {
            "source_name": download.source_name,
            "period": download.period,
            "status": DOWNLOAD_STATUS_OK,
        },
    ).scalar_one_or_none()
    if row_count is None:
        return None
    return int(row_count or 0)


def acquire_source_period_lock(
    connection: Connection,
    download: SourcePeriodDownload,
) -> None:
    lock_key = f"{download.source_name}:{download.period}"
    connection.execute(
        text("SELECT pg_advisory_xact_lock(hashtext(:lock_key))"),
        {"lock_key": lock_key},
    )


def period_delete_predicate(
    columns: Sequence[str],
    period: str,
) -> tuple[str, dict[str, str]]:
    column_set = set(columns)
    if "시점" in column_set:
        return f"{quote_identifier('시점')} = :period", {"period": period}
    if "crtr_ym" in column_set:
        return f"{quote_identifier('crtr_ym')} = :period", {"period": period}
    if {"year", "month"}.issubset(column_set):
        return (
            f"{quote_identifier('year')} = :year "
            f"AND {quote_identifier('month')} = :month",
            {"year": period[:4], "month": period[4:6]},
        )
    raise RawWriterError(
        "cannot infer period columns for raw delete; "
        f"columns={tuple(columns)!r}"
    )


def delete_existing_source_period(
    connection: Connection,
    download: SourcePeriodDownload,
) -> None:
    connection.execute(
        text(
            """
            DELETE FROM raw_json.payloads
            WHERE source_name = :source_name
              AND period = :period
            """
        ),
        {"source_name": download.source_name, "period": download.period},
    )

    if table_exists(connection, "raw", download.raw_table):
        columns = get_table_columns(connection, "raw", download.raw_table)
        predicate, parameters = period_delete_predicate(columns, download.period)
        connection.execute(
            text(
                f"""
                DELETE FROM raw.{quote_identifier(download.raw_table)}
                WHERE {predicate}
                """
            ),
            parameters,
        )

    connection.execute(
        text(
            """
            DELETE FROM metadata.download_status
            WHERE source_name = :source_name
              AND period = :period
            """
        ),
        {"source_name": download.source_name, "period": download.period},
    )


def insert_payload_chunks(
    connection: Connection,
    download: SourcePeriodDownload,
) -> None:
    rows = []
    for chunk_index, chunk in enumerate(download.payload_chunks, start=1):
        rows.append(
            {
                "source_name": download.source_name,
                "source_name_kor": download.source_name_kor,
                "source_org_id": download.source_org_id,
                "source_table_id": download.source_table_id,
                "raw_table": download.raw_table,
                "period": download.period,
                "chunk_index": chunk_index,
                "request_params": json.dumps(
                    dict(chunk.request_params),
                    ensure_ascii=False,
                ),
                "response_payload": json.dumps(
                    [dict(row) for row in chunk.response_payload],
                    ensure_ascii=False,
                ),
                "row_count": chunk.row_count,
            }
        )

    if not rows:
        return

    connection.execute(
        text(
            """
            INSERT INTO raw_json.payloads (
                source_name,
                source_name_kor,
                source_org_id,
                source_table_id,
                raw_table,
                period,
                chunk_index,
                request_params,
                response_payload,
                row_count
            )
            VALUES (
                :source_name,
                :source_name_kor,
                :source_org_id,
                :source_table_id,
                :raw_table,
                :period,
                :chunk_index,
                CAST(:request_params AS jsonb),
                CAST(:response_payload AS jsonb),
                :row_count
            )
            """
        ),
        rows,
    )


def raw_row_parameters(
    columns: Sequence[str],
    rows: Sequence[Mapping[str, str]],
) -> list[dict[str, str]]:
    fallback_downloaded_at = datetime.now(UTC).isoformat()
    parameters = []
    for row in rows:
        parameter_row = {}
        for index, column in enumerate(columns):
            value = row.get(column)
            if column == "downloaded_at" and not value:
                value = fallback_downloaded_at
            parameter_row[f"col_{index}"] = "" if value is None else str(value)
        parameters.append(parameter_row)
    return parameters


def insert_raw_rows(
    connection: Connection,
    download: SourcePeriodDownload,
) -> None:
    if not download.raw_rows:
        return

    quoted_columns = ", ".join(
        quote_identifier(column)
        for column in download.raw_columns
    )
    value_placeholders = ", ".join(
        f":col_{index}"
        for index, _column in enumerate(download.raw_columns)
    )

    connection.execute(
        text(
            f"""
            INSERT INTO raw.{quote_identifier(download.raw_table)}
            ({quoted_columns})
            VALUES ({value_placeholders})
            """
        ),
        raw_row_parameters(download.raw_columns, download.raw_rows),
    )


def mark_source_period_success(
    connection: Connection,
    download: SourcePeriodDownload,
) -> None:
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
                NULL
            )
            ON CONFLICT (source_name, period)
            DO UPDATE SET
                source_name_kor = EXCLUDED.source_name_kor,
                source_table_id = EXCLUDED.source_table_id,
                status = EXCLUDED.status,
                row_count = EXCLUDED.row_count,
                downloaded_at = CURRENT_TIMESTAMP,
                error_message = NULL
            """
        ),
        {
            "source_name": download.source_name,
            "source_name_kor": download.source_name_kor,
            "source_table_id": download.source_table_id,
            "period": download.period,
            "status": DOWNLOAD_STATUS_OK,
            "row_count": download.raw_row_count,
        },
    )


def write_source_period_download(
    download: SourcePeriodDownload,
    *,
    engine: Engine | None = None,
    force: bool = False,
) -> RawWriteResult:
    db_engine = engine or get_engine()
    with db_engine.begin() as connection:
        create_writer_tables(connection)
        acquire_source_period_lock(connection, download)

        existing_row_count = successful_row_count(connection, download)
        if existing_row_count is not None and not force:
            return RawWriteResult(
                source_name=download.source_name,
                period=download.period,
                status="skipped",
                row_count=existing_row_count,
            )

        ensure_raw_table(connection, download.raw_table, download.raw_columns)
        if force:
            delete_existing_source_period(connection, download)

        insert_payload_chunks(connection, download)
        insert_raw_rows(connection, download)
        mark_source_period_success(connection, download)

    return RawWriteResult(
        source_name=download.source_name,
        period=download.period,
        status="written",
        row_count=download.raw_row_count,
    )


def write_period_download(
    download: PeriodDownload,
    *,
    engine: Engine | None = None,
    force: bool = False,
) -> tuple[RawWriteResult, ...]:
    db_engine = engine or get_engine()
    return tuple(
        write_source_period_download(
            source_download,
            engine=db_engine,
            force=force,
        )
        for source_download in download.sources
    )

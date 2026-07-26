from __future__ import annotations

import csv
import json
import logging
import shutil
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from uuid import uuid4

from sqlalchemy import bindparam, text
from sqlalchemy.engine import Connection, Engine

from rural_basic_income.config import get_settings
from rural_basic_income.db.connection import get_engine

LOGGER = logging.getLogger(__name__)
DEFAULT_EXPORT_SCHEMAS = ("raw", "clean")
LIST_TABLES_SQL = text(
    """
    SELECT table_schema, table_name
    FROM information_schema.tables
    WHERE table_schema IN :schemas
      AND table_type = 'BASE TABLE'
    ORDER BY table_schema, table_name
    """
).bindparams(bindparam("schemas", expanding=True))


class ExportError(RuntimeError):
    """Raised when CSV export cannot be completed."""


@dataclass(frozen=True)
class ExportTable:
    schema_name: str
    table_name: str


@dataclass(frozen=True)
class ExportTableResult:
    schema_name: str
    table_name: str
    file_path: Path
    row_count: int


@dataclass(frozen=True)
class ExportResult:
    export_dir: Path
    tables: tuple[ExportTableResult, ...]


def quote_identifier(identifier: str) -> str:
    if not identifier or "\x00" in identifier:
        raise ExportError(f"invalid SQL identifier: {identifier!r}")
    return '"' + identifier.replace('"', '""') + '"'


def csv_file_name(schema_name: str, table_name: str) -> str:
    prefix = f"{schema_name}_"
    if table_name.startswith(prefix):
        return f"{table_name}.csv"
    return f"{schema_name}_{table_name}.csv"


def serialize_csv_value(value) -> str | int | float | Decimal:
    if value is None:
        return ""
    if isinstance(value, dict | list):
        return json.dumps(value, ensure_ascii=False, separators=(",", ":"))
    if isinstance(value, datetime | date):
        return value.isoformat()
    if isinstance(value, bytes):
        return value.decode("utf-8")
    return value


def list_export_tables(
    connection: Connection,
    *,
    schemas: tuple[str, ...] = DEFAULT_EXPORT_SCHEMAS,
) -> tuple[ExportTable, ...]:
    if not schemas:
        raise ExportError("at least one export schema is required")

    unknown = sorted(set(schemas) - set(DEFAULT_EXPORT_SCHEMAS))
    if unknown:
        raise ExportError(
            "unknown export schema: "
            f"{', '.join(unknown)}. valid schemas: {', '.join(DEFAULT_EXPORT_SCHEMAS)}"
        )

    rows = connection.execute(LIST_TABLES_SQL, {"schemas": list(schemas)})
    return tuple(
        ExportTable(schema_name=row[0], table_name=row[1])
        for row in rows
    )


def export_table_to_csv(
    connection: Connection,
    table: ExportTable,
    *,
    output_dir: Path,
) -> ExportTableResult:
    file_path = output_dir / csv_file_name(table.schema_name, table.table_name)
    sql = (
        "SELECT * FROM "
        f"{quote_identifier(table.schema_name)}.{quote_identifier(table.table_name)}"
    )

    LOGGER.info(
        "csv export table start table=%s.%s file=%s",
        table.schema_name,
        table.table_name,
        file_path,
    )
    result = connection.execution_options(stream_results=True).exec_driver_sql(sql)
    columns = tuple(result.keys())
    row_count = 0

    with file_path.open("w", encoding="utf-8-sig", newline="") as csv_file:
        writer = csv.writer(csv_file)
        writer.writerow(columns)
        for row in result:
            writer.writerow([serialize_csv_value(value) for value in row])
            row_count += 1

    LOGGER.info(
        "csv export table complete table=%s.%s rows=%d file=%s",
        table.schema_name,
        table.table_name,
        row_count,
        file_path,
    )
    return ExportTableResult(
        schema_name=table.schema_name,
        table_name=table.table_name,
        file_path=file_path,
        row_count=row_count,
    )


def cleanup_stale_export_dirs(parent_dir: Path, target_name: str) -> None:
    for path in parent_dir.glob(f".{target_name}.*"):
        if path.is_dir():
            shutil.rmtree(path, ignore_errors=True)


def publish_csv_directory(temp_dir: Path, target_dir: Path) -> Path:
    target_dir.parent.mkdir(parents=True, exist_ok=True)
    backup_dir = target_dir.parent / f".{target_dir.name}.old-{uuid4().hex}"

    if target_dir.exists():
        target_dir.rename(backup_dir)

    try:
        temp_dir.rename(target_dir)
    except Exception:
        if backup_dir.exists() and not target_dir.exists():
            backup_dir.rename(target_dir)
        raise

    if backup_dir.exists():
        shutil.rmtree(backup_dir)
    return target_dir


def resolve_export_csv_dir(export_csv_dir: str | Path | None = None) -> Path:
    return Path(export_csv_dir or get_settings().export_csv_dir).expanduser()


def export_csv(
    *,
    schemas: tuple[str, ...] = DEFAULT_EXPORT_SCHEMAS,
    export_csv_dir: str | Path | None = None,
    engine: Engine | None = None,
) -> ExportResult:
    db_engine = engine or get_engine()
    target_dir = resolve_export_csv_dir(export_csv_dir)
    temp_dir = target_dir.parent / f".{target_dir.name}.tmp-{uuid4().hex}"
    cleanup_stale_export_dirs(target_dir.parent, target_dir.name)
    temp_dir.mkdir(parents=True, exist_ok=False)

    try:
        with db_engine.connect() as connection:
            tables = list_export_tables(connection, schemas=schemas)
            table_results = tuple(
                export_table_to_csv(
                    connection,
                    table,
                    output_dir=temp_dir,
                )
                for table in tables
            )
        publish_csv_directory(temp_dir, target_dir)
    except Exception:
        shutil.rmtree(temp_dir, ignore_errors=True)
        LOGGER.exception("csv export failed target_dir=%s", target_dir)
        raise

    published_results = tuple(
        ExportTableResult(
            schema_name=result.schema_name,
            table_name=result.table_name,
            file_path=target_dir / result.file_path.name,
            row_count=result.row_count,
        )
        for result in table_results
    )
    LOGGER.info(
        "csv export complete target_dir=%s tables=%d",
        target_dir,
        len(published_results),
    )
    return ExportResult(export_dir=target_dir, tables=published_results)

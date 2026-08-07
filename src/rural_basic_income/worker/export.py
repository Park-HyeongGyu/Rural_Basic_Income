from __future__ import annotations

import csv
import json
import logging
import shutil
import warnings
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from uuid import uuid4

import pandas as pd
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
    """Raised when data export cannot be completed."""


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


@dataclass(frozen=True)
class ExportRunResult:
    csv: ExportResult
    dta: ExportResult | None = None


def quote_identifier(identifier: str) -> str:
    if not identifier or "\x00" in identifier:
        raise ExportError(f"invalid SQL identifier: {identifier!r}")
    return '"' + identifier.replace('"', '""') + '"'


def export_file_name(schema_name: str, table_name: str, extension: str) -> str:
    prefix = f"{schema_name}_"
    if table_name.startswith(prefix):
        return f"{table_name}.{extension}"
    return f"{schema_name}_{table_name}.{extension}"


def csv_file_name(schema_name: str, table_name: str) -> str:
    return export_file_name(schema_name, table_name, "csv")


def dta_file_name(schema_name: str, table_name: str) -> str:
    return export_file_name(schema_name, table_name, "dta")


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


def serialize_stata_value(value):
    if isinstance(value, dict | list):
        return json.dumps(value, ensure_ascii=False, separators=(",", ":"))
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


def table_select_sql(table: ExportTable) -> str:
    return (
        "SELECT * FROM "
        f"{quote_identifier(table.schema_name)}.{quote_identifier(table.table_name)}"
    )


def export_table_to_csv(
    connection: Connection,
    table: ExportTable,
    *,
    output_dir: Path,
) -> ExportTableResult:
    file_path = output_dir / csv_file_name(table.schema_name, table.table_name)
    sql = table_select_sql(table)

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


def prepare_dataframe_for_stata(dataframe: pd.DataFrame) -> pd.DataFrame:
    prepared = dataframe.copy()
    for column in prepared.columns:
        series = prepared[column]
        if isinstance(series.dtype, pd.DatetimeTZDtype):
            prepared[column] = series.dt.strftime("%Y-%m-%dT%H:%M:%S.%f%z")
            continue
        if series.dtype == "object":
            prepared[column] = series.map(serialize_stata_value)
    return prepared


def export_table_to_dta(
    connection: Connection,
    table: ExportTable,
    *,
    output_dir: Path,
) -> ExportTableResult:
    file_path = output_dir / dta_file_name(table.schema_name, table.table_name)
    sql = table_select_sql(table)

    LOGGER.info(
        "dta export table start table=%s.%s file=%s",
        table.schema_name,
        table.table_name,
        file_path,
    )
    dataframe = pd.read_sql_query(sql, connection)
    dataframe = prepare_dataframe_for_stata(dataframe)
    with warnings.catch_warnings(record=True) as caught_warnings:
        warnings.simplefilter("always")
        dataframe.to_stata(file_path, write_index=False, version=118)
    for warning in caught_warnings:
        LOGGER.warning(
            "dta export warning table=%s.%s message=%s",
            table.schema_name,
            table.table_name,
            warning.message,
        )

    LOGGER.info(
        "dta export table complete table=%s.%s rows=%d file=%s",
        table.schema_name,
        table.table_name,
        len(dataframe),
        file_path,
    )
    return ExportTableResult(
        schema_name=table.schema_name,
        table_name=table.table_name,
        file_path=file_path,
        row_count=len(dataframe),
    )


def cleanup_stale_export_dirs(parent_dir: Path, target_name: str) -> None:
    for path in parent_dir.glob(f".{target_name}.*"):
        if path.is_dir():
            shutil.rmtree(path, ignore_errors=True)


def create_export_temp_dir(target_dir: Path) -> Path:
    target_dir.mkdir(parents=True, exist_ok=True)
    cleanup_stale_export_dirs(target_dir, "tmp")
    temp_dir = target_dir / f".tmp.{uuid4().hex}"
    temp_dir.mkdir(parents=True, exist_ok=False)
    return temp_dir


def remove_export_path(path: Path) -> None:
    if path.is_dir() and not path.is_symlink():
        shutil.rmtree(path)
        return
    path.unlink()


def publish_export_directory(temp_dir: Path, target_dir: Path) -> Path:
    target_dir.mkdir(parents=True, exist_ok=True)
    if not temp_dir.exists():
        raise ExportError(f"export temp directory does not exist: {temp_dir}")
    if temp_dir.resolve() == target_dir.resolve():
        raise ExportError("export temp directory must differ from target directory")

    for path in tuple(target_dir.iterdir()):
        if path == temp_dir:
            continue
        remove_export_path(path)

    for path in tuple(temp_dir.iterdir()):
        shutil.move(str(path), str(target_dir / path.name))

    shutil.rmtree(temp_dir, ignore_errors=True)
    return target_dir


publish_csv_directory = publish_export_directory


def resolve_export_csv_dir(export_csv_dir: str | Path | None = None) -> Path:
    return Path(export_csv_dir or get_settings().export_csv_dir).expanduser()


def resolve_export_dta_dir(export_dta_dir: str | Path | None = None) -> Path:
    return Path(export_dta_dir or get_settings().export_dta_dir).expanduser()


def export_csv(
    *,
    schemas: tuple[str, ...] = DEFAULT_EXPORT_SCHEMAS,
    export_csv_dir: str | Path | None = None,
    engine: Engine | None = None,
) -> ExportResult:
    db_engine = engine or get_engine()
    target_dir = resolve_export_csv_dir(export_csv_dir)
    cleanup_stale_export_dirs(target_dir.parent, target_dir.name)
    temp_dir = create_export_temp_dir(target_dir)

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
        publish_export_directory(temp_dir, target_dir)
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


def export_dta(
    *,
    schemas: tuple[str, ...] = DEFAULT_EXPORT_SCHEMAS,
    export_dta_dir: str | Path | None = None,
    engine: Engine | None = None,
) -> ExportResult:
    db_engine = engine or get_engine()
    target_dir = resolve_export_dta_dir(export_dta_dir)
    cleanup_stale_export_dirs(target_dir.parent, target_dir.name)
    temp_dir = create_export_temp_dir(target_dir)

    try:
        with db_engine.connect() as connection:
            tables = list_export_tables(connection, schemas=schemas)
            table_results = tuple(
                export_table_to_dta(
                    connection,
                    table,
                    output_dir=temp_dir,
                )
                for table in tables
            )
        publish_export_directory(temp_dir, target_dir)
    except Exception:
        shutil.rmtree(temp_dir, ignore_errors=True)
        LOGGER.exception("dta export failed target_dir=%s", target_dir)
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
        "dta export complete target_dir=%s tables=%d",
        target_dir,
        len(published_results),
    )
    return ExportResult(export_dir=target_dir, tables=published_results)


def export_csv_only(
    *,
    schemas: tuple[str, ...] = DEFAULT_EXPORT_SCHEMAS,
    export_csv_dir: str | Path | None = None,
    export_dta_dir: str | Path | None = None,
    engine: Engine | None = None,
) -> ExportRunResult:
    # DTA export is intentionally kept as a module-level function but not run
    # from the public CLI by default because large OD tables can exceed server RAM.
    _ = export_dta_dir
    csv_result = export_csv(
        schemas=schemas,
        export_csv_dir=export_csv_dir,
        engine=engine,
    )
    return ExportRunResult(csv=csv_result)


def export_all(
    *,
    schemas: tuple[str, ...] = DEFAULT_EXPORT_SCHEMAS,
    export_csv_dir: str | Path | None = None,
    export_dta_dir: str | Path | None = None,
    engine: Engine | None = None,
) -> ExportRunResult:
    db_engine = engine or get_engine()
    csv_target_dir = resolve_export_csv_dir(export_csv_dir)
    dta_target_dir = resolve_export_dta_dir(export_dta_dir)

    cleanup_stale_export_dirs(csv_target_dir.parent, csv_target_dir.name)
    cleanup_stale_export_dirs(dta_target_dir.parent, dta_target_dir.name)
    csv_temp_dir = create_export_temp_dir(csv_target_dir)
    dta_temp_dir = create_export_temp_dir(dta_target_dir)

    try:
        with db_engine.connect() as connection:
            tables = list_export_tables(connection, schemas=schemas)
            csv_results = tuple(
                export_table_to_csv(
                    connection,
                    table,
                    output_dir=csv_temp_dir,
                )
                for table in tables
            )
            dta_results = tuple(
                export_table_to_dta(
                    connection,
                    table,
                    output_dir=dta_temp_dir,
                )
                for table in tables
            )
        publish_export_directory(csv_temp_dir, csv_target_dir)
        publish_export_directory(dta_temp_dir, dta_target_dir)
    except Exception:
        shutil.rmtree(csv_temp_dir, ignore_errors=True)
        shutil.rmtree(dta_temp_dir, ignore_errors=True)
        LOGGER.exception(
            "data export failed csv_target_dir=%s dta_target_dir=%s",
            csv_target_dir,
            dta_target_dir,
        )
        raise

    csv_published = tuple(
        ExportTableResult(
            schema_name=result.schema_name,
            table_name=result.table_name,
            file_path=csv_target_dir / result.file_path.name,
            row_count=result.row_count,
        )
        for result in csv_results
    )
    dta_published = tuple(
        ExportTableResult(
            schema_name=result.schema_name,
            table_name=result.table_name,
            file_path=dta_target_dir / result.file_path.name,
            row_count=result.row_count,
        )
        for result in dta_results
    )
    LOGGER.info(
        "data export complete csv_target_dir=%s dta_target_dir=%s tables=%d",
        csv_target_dir,
        dta_target_dir,
        len(csv_published),
    )
    return ExportRunResult(
        csv=ExportResult(export_dir=csv_target_dir, tables=csv_published),
        dta=ExportResult(export_dir=dta_target_dir, tables=dta_published),
    )

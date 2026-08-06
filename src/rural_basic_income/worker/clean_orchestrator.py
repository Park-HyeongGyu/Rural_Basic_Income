from __future__ import annotations

import csv
import logging
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy import text
from sqlalchemy.engine import Connection, Engine

from rural_basic_income.db.connection import get_engine
from rural_basic_income.worker.periods import iter_month_periods

PROJECT_ROOT = Path(__file__).resolve().parents[3]
REGION_MERGE_KEY_PATH = (
    PROJECT_ROOT
    / "src"
    / "rural_basic_income"
    / "worker"
    / "resources"
    / "region_merge_key.csv"
)
LOCAL_CURRENCY_REGION_CODES_PATH = (
    PROJECT_ROOT
    / "src"
    / "rural_basic_income"
    / "worker"
    / "resources"
    / "local_currency_region_codes.csv"
)
CLEAN_SQL_LOCK_KEY = "rural_basic_income.clean_sql"
LOGGER = logging.getLogger(__name__)


class CleanOrchestratorError(RuntimeError):
    """Raised when a clean SQL run cannot be orchestrated."""


@dataclass(frozen=True)
class CleanDatasetSpec:
    dataset_name: str
    sql_file: Path
    clean_tables: tuple[str, ...]


@dataclass(frozen=True)
class CleanDatasetResult:
    dataset_name: str
    sql_file: Path
    statement_count: int
    affected_row_count: int = 0
    revision: int | None = None
    revision_changed: bool = False


@dataclass(frozen=True)
class CleanSqlRunResult:
    statement_count: int
    affected_row_count: int
    revision: int | None
    revision_changed: bool


CLEAN_DATASETS = (
    CleanDatasetSpec(
        "population",
        PROJECT_ROOT / "sql" / "clean" / "clean_population.sql",
        (
            "clean_population",
            "clean_population_sex",
            "clean_population_age",
            "clean_population_sex_age",
        ),
    ),
    CleanDatasetSpec(
        "mover",
        PROJECT_ROOT / "sql" / "clean" / "clean_mover.sql",
        (
            "clean_mover",
            "clean_mover_sex",
            "clean_mover_age",
            "clean_mover_sex_age",
        ),
    ),
    CleanDatasetSpec(
        "household",
        PROJECT_ROOT / "sql" / "clean" / "clean_household.sql",
        ("clean_household",),
    ),
    CleanDatasetSpec(
        "electricity",
        PROJECT_ROOT / "sql" / "clean" / "clean_electricity.sql",
        ("clean_electricity",),
    ),
    CleanDatasetSpec(
        "local_currency",
        PROJECT_ROOT / "sql" / "clean" / "clean_local_currency.sql",
        (
            "clean_local_currency",
            "clean_local_currency_sex",
            "clean_local_currency_age",
            "clean_local_currency_sex_age",
        ),
    ),
    CleanDatasetSpec(
        "migration_od",
        PROJECT_ROOT / "sql" / "clean" / "clean_migration_od.sql",
        (
            "clean_inflow",
            "clean_inflow_sex",
            "clean_inflow_age",
            "clean_inflow_sex_age",
            "clean_outflow",
            "clean_outflow_sex",
            "clean_outflow_age",
            "clean_outflow_sex_age",
        ),
    ),
    CleanDatasetSpec(
        "living_population",
        PROJECT_ROOT / "sql" / "clean" / "clean_living_population.sql",
        (
            "clean_living_population",
            "clean_living_population_age",
        ),
    ),
)
DEFAULT_CLEAN_DATASETS = (
    "population",
    "mover",
    "household",
    "electricity",
    "local_currency",
    "migration_od",
)


def clean_dataset_by_name() -> dict[str, CleanDatasetSpec]:
    return {spec.dataset_name: spec for spec in CLEAN_DATASETS}


def clean_dataset_by_table() -> dict[str, CleanDatasetSpec]:
    return {
        table_name: spec
        for spec in CLEAN_DATASETS
        for table_name in spec.clean_tables
    }


def unqualified_clean_table_name(table_name: str) -> str:
    normalized = table_name.strip().strip('"')
    if normalized.startswith("clean."):
        normalized = normalized.removeprefix("clean.").strip('"')
    return normalized


def clean_dataset_name_for_table(table_name: str) -> str:
    clean_table_name = unqualified_clean_table_name(table_name)
    try:
        return clean_dataset_by_table()[clean_table_name].dataset_name
    except KeyError as exc:
        valid_tables = ", ".join(sorted(clean_dataset_by_table()))
        raise CleanOrchestratorError(
            f"unknown clean table for dataset revision: {table_name}. "
            f"valid clean tables: {valid_tables}"
        ) from exc


def read_sql_statements(path: Path) -> list[str]:
    sql = path.read_text(encoding="utf-8")
    return [
        statement.strip()
        for statement in sql.split(";")
        if statement.strip()
    ]


def driver_sql_statement(statement: str) -> str:
    """Escape DBAPI pyformat percent markers for raw SQL file execution."""
    return statement.replace("%", "%%")


def quote_identifier(identifier: str) -> str:
    if not identifier or "\x00" in identifier:
        raise CleanOrchestratorError(f"invalid SQL identifier: {identifier!r}")
    return '"' + identifier.replace('"', '""') + '"'


def setup_statement(statement: str) -> bool:
    normalized = statement.strip().upper()
    return (
        normalized.startswith("CREATE SCHEMA")
        or normalized.startswith("CREATE TABLE")
        or normalized.startswith("CREATE UNIQUE INDEX")
        or normalized.startswith("CREATE INDEX")
    )


def clean_data_statement(statement: str) -> bool:
    normalized = statement.strip().upper()
    return (
        normalized.startswith("INSERT INTO CLEAN.")
        or normalized.startswith("UPDATE CLEAN.")
        or normalized.startswith("DELETE FROM CLEAN.")
    )


def delete_clean_periods(
    connection: Connection,
    *,
    clean_tables: Sequence[str],
    periods: Sequence[str],
) -> int:
    validated_periods = tuple(str(int(period)) for period in periods)
    period_values = ", ".join(str(int(period)) for period in validated_periods)
    affected_row_count = 0

    for table_name in clean_tables:
        LOGGER.info(
            "clean rebuild delete table=clean.%s periods=%s",
            table_name,
            validated_periods,
        )
        result = connection.exec_driver_sql(
            f"""
            DELETE FROM clean.{quote_identifier(table_name)}
            WHERE date IN ({period_values})
            """
        )
        row_count = getattr(result, "rowcount", -1)
        if row_count and row_count > 0:
            affected_row_count += int(row_count)

    return affected_row_count


def ensure_clean_dataset_revision_table(
    connection: Connection,
    *,
    datasets: Sequence[str] | None = None,
) -> None:
    dataset_names = tuple(datasets or DEFAULT_CLEAN_DATASETS)
    unknown = sorted(set(dataset_names) - set(clean_dataset_by_name()))
    if unknown:
        raise CleanOrchestratorError(
            f"unknown clean dataset revision row: {', '.join(unknown)}"
        )

    connection.execute(text("CREATE SCHEMA IF NOT EXISTS metadata"))
    connection.execute(
        text(
            """
            CREATE TABLE IF NOT EXISTS metadata.clean_dataset_revision (
                dataset_name text PRIMARY KEY,
                revision bigint NOT NULL DEFAULT 0,
                updated_at timestamptz NOT NULL DEFAULT now()
            )
            """
        )
    )
    connection.execute(
        text(
            """
            INSERT INTO metadata.clean_dataset_revision (
                dataset_name,
                revision,
                updated_at
            )
            VALUES (:dataset_name, 0, now())
            ON CONFLICT (dataset_name) DO NOTHING
            """
        ),
        [{"dataset_name": dataset_name} for dataset_name in dataset_names],
    )


def bump_clean_dataset_revision(
    connection: Connection,
    *,
    dataset_name: str,
) -> int:
    if dataset_name not in clean_dataset_by_name():
        raise CleanOrchestratorError(
            f"unknown clean dataset revision bump: {dataset_name}"
        )

    revision = connection.execute(
        text(
            """
            INSERT INTO metadata.clean_dataset_revision (
                dataset_name,
                revision,
                updated_at
            )
            VALUES (:dataset_name, 1, now())
            ON CONFLICT (dataset_name)
            DO UPDATE SET
                revision = metadata.clean_dataset_revision.revision + 1,
                updated_at = now()
            RETURNING revision
            """
        ),
        {"dataset_name": dataset_name},
    ).scalar_one()
    return int(revision)


def fetch_clean_dataset_revision(
    connection: Connection,
    *,
    dataset_name: str,
) -> int:
    revision = connection.execute(
        text(
            """
            SELECT revision
            FROM metadata.clean_dataset_revision
            WHERE dataset_name = :dataset_name
            """
        ),
        {"dataset_name": dataset_name},
    ).scalar_one_or_none()
    if revision is None:
        raise CleanOrchestratorError(
            "clean dataset revision is missing: "
            f"{dataset_name}. Run `rbi clean --datasets {dataset_name}` "
            "or `rbi update --latest` before analysis."
        )
    return int(revision)


def load_region_merge_key(
    connection: Connection,
    path: Path = REGION_MERGE_KEY_PATH,
) -> int:
    with path.open("r", encoding="utf-8-sig", newline="") as csv_file:
        rows = list(csv.DictReader(csv_file))

    expected_columns = ["region_sido", "region_sigungu", "is_gun"]
    if not rows:
        raise ValueError(f"{path} must contain at least one region row")
    if list(rows[0]) != expected_columns:
        raise ValueError(f"{path} must have columns {expected_columns}")

    connection.execute(text("DROP TABLE IF EXISTS pg_temp.region_merge_key"))
    connection.execute(
        text(
            """
            CREATE TEMP TABLE region_merge_key (
                region_sido text NOT NULL,
                region_sigungu text NOT NULL,
                is_gun smallint NOT NULL CHECK (is_gun IN (0, 1)),
                PRIMARY KEY (region_sido, region_sigungu)
            ) ON COMMIT PRESERVE ROWS
            """
        )
    )
    connection.execute(
        text(
            """
            INSERT INTO region_merge_key (
                region_sido,
                region_sigungu,
                is_gun
            )
            VALUES (
                :region_sido,
                :region_sigungu,
                :is_gun
            )
            """
        ),
        [
            {
                "region_sido": row["region_sido"],
                "region_sigungu": row["region_sigungu"],
                "is_gun": int(row["is_gun"]),
            }
            for row in rows
        ],
    )

    return len(rows)


def load_local_currency_region_codes(
    connection: Connection,
    path: Path = LOCAL_CURRENCY_REGION_CODES_PATH,
) -> int:
    with path.open("r", encoding="utf-8-sig", newline="") as csv_file:
        rows = list(csv.DictReader(csv_file))

    expected_columns = [
        "usage_rgn_cd",
        "region_sido",
        "region_sigungu",
        "drop_reason",
        "mapping_note",
    ]
    if not rows:
        raise ValueError(f"{path} must contain at least one region-code row")
    if list(rows[0]) != expected_columns:
        raise ValueError(f"{path} must have columns {expected_columns}")

    connection.execute(text("DROP TABLE IF EXISTS pg_temp.local_currency_region_code"))
    connection.execute(
        text(
            """
            CREATE TEMP TABLE local_currency_region_code (
                usage_rgn_cd text PRIMARY KEY,
                region_sido text,
                region_sigungu text,
                drop_reason text NOT NULL DEFAULT '',
                mapping_note text NOT NULL DEFAULT ''
            ) ON COMMIT PRESERVE ROWS
            """
        )
    )
    connection.execute(
        text(
            """
            INSERT INTO local_currency_region_code (
                usage_rgn_cd,
                region_sido,
                region_sigungu,
                drop_reason,
                mapping_note
            )
            VALUES (
                :usage_rgn_cd,
                :region_sido,
                :region_sigungu,
                :drop_reason,
                :mapping_note
            )
            """
        ),
        [
            {
                "usage_rgn_cd": row["usage_rgn_cd"],
                "region_sido": row["region_sido"] or None,
                "region_sigungu": row["region_sigungu"] or None,
                "drop_reason": row["drop_reason"],
                "mapping_note": row["mapping_note"],
            }
            for row in rows
        ],
    )

    return len(rows)


def load_clean_dependencies(connection: Connection) -> dict[str, int]:
    LOGGER.info("clean dependencies load start")
    dependencies = {
        "region_merge_key_rows": load_region_merge_key(connection),
        "local_currency_region_code_rows": load_local_currency_region_codes(
            connection,
        ),
    }
    LOGGER.info("clean dependencies load complete %s", dependencies)
    return dependencies


def clean_dataset_specs(
    datasets: Sequence[str] | None = None,
) -> tuple[CleanDatasetSpec, ...]:
    requested = tuple(datasets or DEFAULT_CLEAN_DATASETS)
    specs_by_name = {spec.dataset_name: spec for spec in CLEAN_DATASETS}

    unknown = sorted(set(requested) - set(specs_by_name))
    if unknown:
        valid_datasets = ", ".join(sorted(specs_by_name))
        raise CleanOrchestratorError(
            f"unknown clean dataset: {', '.join(unknown)}. "
            f"valid datasets: {valid_datasets}"
        )

    return tuple(specs_by_name[dataset_name] for dataset_name in requested)


def run_sql_file(
    connection: Connection,
    path: Path,
    *,
    dataset_name: str | None = None,
    rebuild_tables: Sequence[str] = (),
    rebuild_periods: Sequence[str] = (),
) -> CleanSqlRunResult:
    statements = read_sql_statements(path)
    LOGGER.info(
        "clean sql file execute start file=%s statements=%d",
        path,
        len(statements),
    )
    try:
        in_transaction = False
        rebuild_deleted = False
        affected_row_count = 0
        revision: int | None = None
        revision_changed = False
        for statement in statements:
            if statement.upper() == "BEGIN":
                connection.exec_driver_sql(statement)
                in_transaction = True
                continue

            if statement.upper() == "COMMIT":
                if dataset_name is not None:
                    if affected_row_count > 0:
                        revision = bump_clean_dataset_revision(
                            connection,
                            dataset_name=dataset_name,
                        )
                        revision_changed = True
                    else:
                        revision = fetch_clean_dataset_revision(
                            connection,
                            dataset_name=dataset_name,
                        )
                connection.exec_driver_sql(statement)
                in_transaction = False
                continue

            if (
                in_transaction
                and rebuild_tables
                and rebuild_periods
                and not rebuild_deleted
                and not setup_statement(statement)
            ):
                affected_row_count += delete_clean_periods(
                    connection,
                    clean_tables=rebuild_tables,
                    periods=rebuild_periods,
                )
                rebuild_deleted = True
            result = connection.exec_driver_sql(driver_sql_statement(statement))
            if clean_data_statement(statement):
                row_count = getattr(result, "rowcount", -1)
                if row_count and row_count > 0:
                    affected_row_count += int(row_count)
    except Exception:
        LOGGER.exception(
            "clean sql file failed file=%s transaction=rollback",
            path,
        )
        connection.exec_driver_sql("ROLLBACK")
        raise

    LOGGER.info(
        "clean sql file execute complete file=%s statements=%d "
        "affected_rows=%d revision=%s revision_changed=%s",
        path,
        len(statements),
        affected_row_count,
        revision,
        revision_changed,
    )
    return CleanSqlRunResult(
        statement_count=len(statements),
        affected_row_count=affected_row_count,
        revision=revision,
        revision_changed=revision_changed,
    )


def relation_exists(connection: Connection, relation_name: str) -> bool:
    relation = connection.execute(
        text("SELECT to_regclass(:relation_name)"),
        {"relation_name": relation_name},
    ).scalar_one_or_none()
    return relation is not None


def raw_migration_od_periods(
    connection: Connection,
    *,
    periods: Sequence[str] = (),
) -> tuple[str, ...]:
    if not relation_exists(connection, "raw.migration_od"):
        return ()

    where_clause = ""
    if periods:
        period_values = ", ".join(str(int(period)) for period in periods)
        where_clause = f'WHERE "statsYm"::integer IN ({period_values})'

    rows = connection.exec_driver_sql(
        f"""
        SELECT DISTINCT "statsYm"::integer AS date
        FROM raw.migration_od
        {where_clause}
        ORDER BY date
        """
    ).fetchall()
    return tuple(str(int(row[0])) for row in rows)


def migration_od_clean_missing_periods(
    connection: Connection,
    spec: CleanDatasetSpec,
) -> tuple[str, ...]:
    raw_periods = raw_migration_od_periods(connection)
    if not raw_periods:
        return ()

    missing_tables = [
        table_name
        for table_name in spec.clean_tables
        if not relation_exists(connection, f"clean.{table_name}")
    ]
    if missing_tables:
        LOGGER.info(
            "migration_od clean target all raw periods because clean tables "
            "are missing tables=%s",
            tuple(missing_tables),
        )
        return raw_periods

    missing_predicates = "\nOR ".join(
        f"""
        NOT EXISTS (
            SELECT 1
            FROM clean.{quote_identifier(table_name)} AS existing
            WHERE existing.date = raw_dates.date
        )
        """.strip()
        for table_name in spec.clean_tables
    )
    rows = connection.exec_driver_sql(
        f"""
        WITH raw_dates AS (
            SELECT DISTINCT "statsYm"::integer AS date
            FROM raw.migration_od
        )
        SELECT raw_dates.date
        FROM raw_dates
        WHERE {missing_predicates}
        ORDER BY raw_dates.date
        """
    ).fetchall()
    return tuple(str(int(row[0])) for row in rows)


def migration_od_clean_target_periods(
    connection: Connection,
    spec: CleanDatasetSpec,
    *,
    rebuild_periods: Sequence[str] = (),
) -> tuple[str, ...]:
    if rebuild_periods:
        return raw_migration_od_periods(connection, periods=rebuild_periods)
    return migration_od_clean_missing_periods(connection, spec)


def set_migration_od_requested_period(
    connection: Connection,
    period: str,
) -> None:
    connection.exec_driver_sql(
        """
        CREATE TEMP TABLE IF NOT EXISTS clean_migration_od_requested_dates (
            date integer PRIMARY KEY
        ) ON COMMIT PRESERVE ROWS
        """
    )
    connection.exec_driver_sql("TRUNCATE clean_migration_od_requested_dates")
    connection.execute(
        text(
            """
            INSERT INTO clean_migration_od_requested_dates (date)
            VALUES (:date)
            """
        ),
        {"date": int(period)},
    )


def run_migration_od_clean_dataset(
    connection: Connection,
    spec: CleanDatasetSpec,
    *,
    rebuild_periods: Sequence[str] = (),
) -> CleanSqlRunResult:
    target_periods = migration_od_clean_target_periods(
        connection,
        spec,
        rebuild_periods=rebuild_periods,
    )
    if not target_periods:
        revision = fetch_clean_dataset_revision(
            connection,
            dataset_name=spec.dataset_name,
        )
        LOGGER.info(
            "migration_od clean no target periods revision=%s",
            revision,
        )
        return CleanSqlRunResult(
            statement_count=0,
            affected_row_count=0,
            revision=revision,
            revision_changed=False,
        )

    LOGGER.info(
        "migration_od clean target periods=%s",
        target_periods,
    )
    statement_count = 0
    affected_row_count = 0
    revision: int | None = None
    revision_changed = False
    for period in target_periods:
        LOGGER.info("migration_od clean period start period=%s", period)
        set_migration_od_requested_period(connection, period)
        sql_result = run_sql_file(
            connection,
            spec.sql_file,
            dataset_name=spec.dataset_name,
        )
        statement_count += sql_result.statement_count
        affected_row_count += sql_result.affected_row_count
        revision = sql_result.revision
        revision_changed = revision_changed or sql_result.revision_changed
        LOGGER.info(
            "migration_od clean period complete period=%s affected_rows=%d "
            "revision=%s revision_changed=%s",
            period,
            sql_result.affected_row_count,
            sql_result.revision,
            sql_result.revision_changed,
        )

    return CleanSqlRunResult(
        statement_count=statement_count,
        affected_row_count=affected_row_count,
        revision=revision,
        revision_changed=revision_changed,
    )


def run_clean_datasets(
    datasets: Sequence[str] | None = None,
    *,
    engine: Engine | None = None,
    rebuild: bool = False,
    start_period: str | None = None,
    end_period: str | None = None,
    exact_rebuild_periods: Sequence[str] | None = None,
) -> tuple[CleanDatasetResult, ...]:
    """Run clean SQL files with each SQL file owning its transaction boundary."""
    db_engine = engine or get_engine()
    specs = clean_dataset_specs(datasets)
    results: list[CleanDatasetResult] = []
    rebuild_periods: tuple[str, ...] = ()
    if exact_rebuild_periods is not None:
        rebuild_periods = tuple(str(int(period)) for period in exact_rebuild_periods)
        if not rebuild_periods:
            raise CleanOrchestratorError("clean rebuild_periods must not be empty")
        rebuild = True
    elif rebuild:
        if not start_period or not end_period:
            raise CleanOrchestratorError(
                "clean rebuild requires start_period and end_period"
            )
        rebuild_periods = tuple(iter_month_periods(start_period, end_period))

    LOGGER.info(
        "clean datasets start datasets=%s rebuild=%s periods=%s",
        tuple(spec.dataset_name for spec in specs),
        rebuild,
        rebuild_periods,
    )
    with db_engine.connect() as base_connection:
        connection = base_connection.execution_options(isolation_level="AUTOCOMMIT")
        connection.execute(
            text("SELECT pg_advisory_lock(hashtext(:lock_key))"),
            {"lock_key": CLEAN_SQL_LOCK_KEY},
        )
        LOGGER.info("clean sql lock acquired")
        try:
            ensure_clean_dataset_revision_table(
                connection,
                datasets=tuple(spec.dataset_name for spec in specs),
            )
            load_clean_dependencies(connection)
            for spec in specs:
                LOGGER.info(
                    "clean dataset start dataset=%s sql_file=%s",
                    spec.dataset_name,
                    spec.sql_file,
                )
                if spec.dataset_name == "migration_od":
                    sql_result = run_migration_od_clean_dataset(
                        connection,
                        spec,
                        rebuild_periods=rebuild_periods,
                    )
                else:
                    sql_result = run_sql_file(
                        connection,
                        spec.sql_file,
                        dataset_name=spec.dataset_name,
                        rebuild_tables=spec.clean_tables if rebuild else (),
                        rebuild_periods=rebuild_periods,
                    )
                results.append(
                    CleanDatasetResult(
                        dataset_name=spec.dataset_name,
                        sql_file=spec.sql_file,
                        statement_count=sql_result.statement_count,
                        affected_row_count=sql_result.affected_row_count,
                        revision=sql_result.revision,
                        revision_changed=sql_result.revision_changed,
                    )
                )
                LOGGER.info(
                    "clean dataset complete dataset=%s statements=%d "
                    "affected_rows=%d revision=%s revision_changed=%s",
                    spec.dataset_name,
                    sql_result.statement_count,
                    sql_result.affected_row_count,
                    sql_result.revision,
                    sql_result.revision_changed,
                )
        finally:
            connection.execute(
                text("SELECT pg_advisory_unlock(hashtext(:lock_key))"),
                {"lock_key": CLEAN_SQL_LOCK_KEY},
            )
            LOGGER.info("clean sql lock released")

    LOGGER.info("clean datasets complete results=%d", len(results))
    return tuple(results)

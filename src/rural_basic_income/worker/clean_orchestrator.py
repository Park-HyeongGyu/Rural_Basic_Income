from __future__ import annotations

import csv
import logging
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy import text
from sqlalchemy.engine import Connection, Engine

from rural_basic_income.db.connection import get_engine

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


@dataclass(frozen=True)
class CleanDatasetResult:
    dataset_name: str
    sql_file: Path
    statement_count: int


CLEAN_DATASETS = (
    CleanDatasetSpec(
        "population",
        PROJECT_ROOT / "sql" / "clean" / "clean_population.sql",
    ),
    CleanDatasetSpec(
        "mover",
        PROJECT_ROOT / "sql" / "clean" / "clean_mover.sql",
    ),
    CleanDatasetSpec(
        "household",
        PROJECT_ROOT / "sql" / "clean" / "clean_household.sql",
    ),
    CleanDatasetSpec(
        "electricity",
        PROJECT_ROOT / "sql" / "clean" / "clean_electricity.sql",
    ),
    CleanDatasetSpec(
        "local_currency",
        PROJECT_ROOT / "sql" / "clean" / "clean_local_currency.sql",
    ),
)
DEFAULT_CLEAN_DATASETS = tuple(spec.dataset_name for spec in CLEAN_DATASETS)


def read_sql_statements(path: Path) -> list[str]:
    sql = path.read_text(encoding="utf-8")
    return [
        statement.strip()
        for statement in sql.split(";")
        if statement.strip()
    ]


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
        valid_datasets = ", ".join(DEFAULT_CLEAN_DATASETS)
        raise CleanOrchestratorError(
            f"unknown clean dataset: {', '.join(unknown)}. "
            f"valid datasets: {valid_datasets}"
        )

    return tuple(specs_by_name[dataset_name] for dataset_name in requested)


def run_sql_file(connection: Connection, path: Path) -> int:
    statements = read_sql_statements(path)
    LOGGER.info(
        "clean sql file execute start file=%s statements=%d",
        path,
        len(statements),
    )
    try:
        for statement in statements:
            connection.exec_driver_sql(statement)
    except Exception:
        LOGGER.exception(
            "clean sql file failed file=%s transaction=rollback",
            path,
        )
        connection.exec_driver_sql("ROLLBACK")
        raise

    LOGGER.info(
        "clean sql file execute complete file=%s statements=%d",
        path,
        len(statements),
    )
    return len(statements)


def run_clean_datasets(
    datasets: Sequence[str] | None = None,
    *,
    engine: Engine | None = None,
) -> tuple[CleanDatasetResult, ...]:
    """Run clean SQL files with each SQL file owning its transaction boundary."""
    db_engine = engine or get_engine()
    specs = clean_dataset_specs(datasets)
    results: list[CleanDatasetResult] = []

    LOGGER.info(
        "clean datasets start datasets=%s",
        tuple(spec.dataset_name for spec in specs),
    )
    with db_engine.connect() as base_connection:
        connection = base_connection.execution_options(isolation_level="AUTOCOMMIT")
        connection.execute(
            text("SELECT pg_advisory_lock(hashtext(:lock_key))"),
            {"lock_key": CLEAN_SQL_LOCK_KEY},
        )
        LOGGER.info("clean sql lock acquired")
        try:
            load_clean_dependencies(connection)
            for spec in specs:
                LOGGER.info(
                    "clean dataset start dataset=%s sql_file=%s",
                    spec.dataset_name,
                    spec.sql_file,
                )
                statement_count = run_sql_file(connection, spec.sql_file)
                results.append(
                    CleanDatasetResult(
                        dataset_name=spec.dataset_name,
                        sql_file=spec.sql_file,
                        statement_count=statement_count,
                    )
                )
                LOGGER.info(
                    "clean dataset complete dataset=%s statements=%d",
                    spec.dataset_name,
                    statement_count,
                )
        finally:
            connection.execute(
                text("SELECT pg_advisory_unlock(hashtext(:lock_key))"),
                {"lock_key": CLEAN_SQL_LOCK_KEY},
            )
            LOGGER.info("clean sql lock released")

    LOGGER.info("clean datasets complete results=%d", len(results))
    return tuple(results)


def run_clean_sql(engine: Engine | None = None) -> dict[str, int]:
    """Compatibility return shape for the old pipeline clean runner."""
    executed_counts: dict[str, int] = {}
    db_engine = engine or get_engine()

    with db_engine.connect() as base_connection:
        connection = base_connection.execution_options(isolation_level="AUTOCOMMIT")
        connection.execute(
            text("SELECT pg_advisory_lock(hashtext(:lock_key))"),
            {"lock_key": CLEAN_SQL_LOCK_KEY},
        )
        try:
            executed_counts.update(load_clean_dependencies(connection))
            for spec in clean_dataset_specs():
                executed_counts[spec.sql_file.name] = run_sql_file(
                    connection,
                    spec.sql_file,
                )
        finally:
            connection.execute(
                text("SELECT pg_advisory_unlock(hashtext(:lock_key))"),
                {"lock_key": CLEAN_SQL_LOCK_KEY},
            )

    return executed_counts

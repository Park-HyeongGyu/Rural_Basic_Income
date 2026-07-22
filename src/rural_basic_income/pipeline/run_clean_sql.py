from __future__ import annotations

import csv
from pathlib import Path

from sqlalchemy import text
from sqlalchemy.engine import Connection, Engine

from rural_basic_income.db.connection import get_engine

PROJECT_ROOT = Path(__file__).resolve().parents[3]
REGION_MERGE_KEY_PATH = (
    PROJECT_ROOT / "src" / "rural_basic_income" / "pipeline" / "region_merge_key.csv"
)
SQL_FILES = (
    PROJECT_ROOT / "sql" / "clean" / "clean_population.sql",
    PROJECT_ROOT / "sql" / "clean" / "clean_mover.sql",
    PROJECT_ROOT / "sql" / "clean" / "clean_household.sql",
)
CLEAN_SQL_LOCK_KEY = "rural_basic_income.clean_sql"


def read_sql_statements(path: Path) -> list[str]:
    sql = path.read_text(encoding="utf-8")
    return [
        statement.strip()
        for statement in sql.split(";")
        if statement.strip()
    ]


def load_region_merge_key(connection: Connection, path: Path = REGION_MERGE_KEY_PATH) -> int:
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
    if rows:
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


def run_sql_file(connection: Connection, path: Path) -> int:
    statements = read_sql_statements(path)
    try:
        for statement in statements:
            connection.exec_driver_sql(statement)
    except Exception:
        connection.exec_driver_sql("ROLLBACK")
        raise

    return len(statements)


def run_clean_sql(engine: Engine | None = None) -> dict[str, int]:
    """Run clean SQL files with transaction boundaries inside each SQL file.

    Each SQL file owns its `BEGIN`/`COMMIT` block, so a completed file is saved
    before the next file starts. If a file fails, roll it back and re-raise.
    """
    db_engine = engine or get_engine()
    executed_counts: dict[str, int] = {}

    with db_engine.connect() as base_connection:
        connection = base_connection.execution_options(isolation_level="AUTOCOMMIT")
        connection.execute(
            text("SELECT pg_advisory_lock(hashtext(:lock_key))"),
            {"lock_key": CLEAN_SQL_LOCK_KEY},
        )
        try:
            executed_counts["region_merge_key_rows"] = load_region_merge_key(connection)
            for sql_file in SQL_FILES:
                executed_counts[sql_file.name] = run_sql_file(connection, sql_file)
        finally:
            connection.execute(
                text("SELECT pg_advisory_unlock(hashtext(:lock_key))"),
                {"lock_key": CLEAN_SQL_LOCK_KEY},
            )

    return executed_counts


def main() -> None:
    executed_counts = run_clean_sql()
    for name, count in executed_counts.items():
        print(f"{name}: {count}")


if __name__ == "__main__":
    main()

import os
from pathlib import Path

import pytest
from sqlalchemy import text

import rural_basic_income.pipeline.run_clean_sql as clean_runner
from rural_basic_income.db.connection import get_engine


PROBE_TABLE = "metadata.clean_sql_transaction_probe"
PROBE_KEY = "file_commit_probe"


@pytest.mark.skipif(
    os.environ.get("RUN_CLEAN_SQL_TRANSACTION_TEST") != "1",
    reason="set RUN_CLEAN_SQL_TRANSACTION_TEST=1 to verify clean SQL rollback behavior",
)
def test_clean_sql_files_commit_individually_and_failed_file_rolls_back(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cleanup_probe_table()
    commit_sql = tmp_path / "10_commit.sql"
    fail_sql = tmp_path / "20_fail.sql"

    commit_sql.write_text(
        f"""
        BEGIN;

        CREATE SCHEMA IF NOT EXISTS metadata;

        CREATE TABLE IF NOT EXISTS {PROBE_TABLE} (
            probe_key text PRIMARY KEY,
            probe_value integer NOT NULL
        );

        INSERT INTO {PROBE_TABLE} (probe_key, probe_value)
        VALUES ('{PROBE_KEY}', 1)
        ON CONFLICT (probe_key)
        DO UPDATE SET probe_value = EXCLUDED.probe_value;

        COMMIT;
        """,
        encoding="utf-8",
    )
    fail_sql.write_text(
        f"""
        BEGIN;

        UPDATE {PROBE_TABLE}
        SET probe_value = 2
        WHERE probe_key = '{PROBE_KEY}';

        SELECT 1 / 0;

        COMMIT;
        """,
        encoding="utf-8",
    )

    monkeypatch.setattr(clean_runner, "SQL_FILES", (commit_sql, fail_sql))

    try:
        with pytest.raises(Exception):
            clean_runner.run_clean_sql()

        assert fetch_probe_value() == 1
    finally:
        cleanup_probe_table()


def fetch_probe_value() -> int | None:
    with get_engine().connect() as connection:
        table_exists = connection.execute(
            text(f"SELECT to_regclass('{PROBE_TABLE}')")
        ).scalar_one()
        if table_exists is None:
            return None

        return connection.execute(
            text(
                f"""
                SELECT probe_value
                FROM {PROBE_TABLE}
                WHERE probe_key = :probe_key
                """
            ),
            {"probe_key": PROBE_KEY},
        ).scalar_one_or_none()


def cleanup_probe_table() -> None:
    with get_engine().begin() as connection:
        connection.execute(text(f"DROP TABLE IF EXISTS {PROBE_TABLE}"))

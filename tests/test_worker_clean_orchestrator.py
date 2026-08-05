from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from rural_basic_income.worker import clean_orchestrator


class ResultStub:
    def __init__(self, *, rowcount: int = -1, scalar_value: Any = None) -> None:
        self.rowcount = rowcount
        self.scalar_value = scalar_value

    def scalar_one(self):
        return self.scalar_value

    def scalar_one_or_none(self):
        return self.scalar_value


class RecordingConnection:
    def __init__(
        self,
        *,
        fail_on_statement: str | None = None,
        rowcounts: dict[str, int] | None = None,
        revision: int = 0,
    ) -> None:
        self.fail_on_statement = fail_on_statement
        self.rowcounts = rowcounts or {}
        self.revision = revision
        self.calls: list[tuple[str, Any, Any]] = []

    def execution_options(self, **kwargs):
        self.calls.append(("execution_options", kwargs, None))
        return self

    def execute(self, statement, parameters=None):
        self.calls.append(("execute", str(statement), parameters))
        sql = str(statement)
        if "RETURNING revision" in sql:
            self.revision += 1
            return ResultStub(scalar_value=self.revision)
        if "SELECT revision" in sql:
            return ResultStub(scalar_value=self.revision)
        return ResultStub()

    def exec_driver_sql(self, statement: str):
        self.calls.append(("exec_driver_sql", statement, None))
        if statement == self.fail_on_statement:
            raise RuntimeError("boom")
        return ResultStub(rowcount=self.rowcounts.get(statement.strip(), -1))


class RecordingConnectionContext:
    def __init__(self, connection: RecordingConnection) -> None:
        self.connection = connection

    def __enter__(self):
        return self.connection

    def __exit__(self, exc_type, exc, traceback):
        return False


class RecordingEngine:
    def __init__(self, connection: RecordingConnection) -> None:
        self.connection = connection

    def connect(self):
        return RecordingConnectionContext(self.connection)


def write_sql(path: Path, sql: str) -> Path:
    path.write_text(sql, encoding="utf-8")
    return path


def test_run_clean_datasets_runs_requested_sql_files_in_order(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    population_sql = write_sql(tmp_path / "population.sql", "BEGIN; SELECT 1; COMMIT;")
    electricity_sql = write_sql(
        tmp_path / "electricity.sql",
        "BEGIN; SELECT 2; COMMIT;",
    )
    specs = (
        clean_orchestrator.CleanDatasetSpec(
            "population",
            population_sql,
            ("clean_population",),
        ),
        clean_orchestrator.CleanDatasetSpec(
            "electricity",
            electricity_sql,
            ("clean_electricity",),
        ),
    )
    connection = RecordingConnection()

    monkeypatch.setattr(clean_orchestrator, "CLEAN_DATASETS", specs)
    monkeypatch.setattr(
        clean_orchestrator,
        "DEFAULT_CLEAN_DATASETS",
        tuple(spec.dataset_name for spec in specs),
    )
    monkeypatch.setattr(
        clean_orchestrator,
        "load_clean_dependencies",
        lambda connection: {"region_merge_key_rows": 2},
    )

    results = clean_orchestrator.run_clean_datasets(
        ("electricity", "population"),
        engine=RecordingEngine(connection),
    )

    assert [result.dataset_name for result in results] == [
        "electricity",
        "population",
    ]
    assert [result.statement_count for result in results] == [3, 3]
    assert [
        call[1]
        for call in connection.calls
        if call[0] == "exec_driver_sql"
    ] == [
        "BEGIN",
        "SELECT 2",
        "COMMIT",
        "BEGIN",
        "SELECT 1",
        "COMMIT",
    ]


def test_run_clean_datasets_unlocks_and_rolls_back_failed_sql_file(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    broken_sql = write_sql(tmp_path / "broken.sql", "BEGIN; SELECT broken; COMMIT;")
    specs = (
        clean_orchestrator.CleanDatasetSpec("broken", broken_sql, ("clean_broken",)),
    )
    connection = RecordingConnection(fail_on_statement="SELECT broken")

    monkeypatch.setattr(clean_orchestrator, "CLEAN_DATASETS", specs)
    monkeypatch.setattr(clean_orchestrator, "DEFAULT_CLEAN_DATASETS", ("broken",))
    monkeypatch.setattr(
        clean_orchestrator,
        "load_clean_dependencies",
        lambda connection: {"region_merge_key_rows": 2},
    )

    with pytest.raises(RuntimeError, match="boom"):
        clean_orchestrator.run_clean_datasets(engine=RecordingEngine(connection))

    assert [
        call[1]
        for call in connection.calls
        if call[0] == "exec_driver_sql"
    ] == ["BEGIN", "SELECT broken", "ROLLBACK"]
    assert any(
        call[0] == "execute" and "pg_advisory_unlock" in call[1]
        for call in connection.calls
    )


def test_clean_dataset_specs_rejects_unknown_dataset() -> None:
    with pytest.raises(
        clean_orchestrator.CleanOrchestratorError,
        match="unknown clean dataset",
    ):
        clean_orchestrator.clean_dataset_specs(("not_a_dataset",))


def test_clean_dataset_registry_includes_od_and_keeps_manual_out_of_default() -> None:
    dataset_names = {
        spec.dataset_name
        for spec in clean_orchestrator.clean_dataset_specs(
            ("migration_od", "living_population")
        )
    }

    assert dataset_names == {"migration_od", "living_population"}
    assert "migration_od" in clean_orchestrator.DEFAULT_CLEAN_DATASETS
    assert "living_population" not in clean_orchestrator.DEFAULT_CLEAN_DATASETS


def test_driver_sql_statement_escapes_percent_for_psycopg_raw_execution() -> None:
    statement = "SELECT * FROM raw.migration_od WHERE name LIKE '%시 %구'"

    assert clean_orchestrator.driver_sql_statement(statement) == (
        "SELECT * FROM raw.migration_od WHERE name LIKE '%%시 %%구'"
    )


def test_run_clean_datasets_bumps_revision_when_clean_rows_change(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    electricity_sql = write_sql(
        tmp_path / "electricity.sql",
        "BEGIN; INSERT INTO clean.clean_electricity VALUES (1); COMMIT;",
    )
    specs = (
        clean_orchestrator.CleanDatasetSpec(
            "electricity",
            electricity_sql,
            ("clean_electricity",),
        ),
    )
    connection = RecordingConnection(
        rowcounts={"INSERT INTO clean.clean_electricity VALUES (1)": 3},
    )

    monkeypatch.setattr(clean_orchestrator, "CLEAN_DATASETS", specs)
    monkeypatch.setattr(clean_orchestrator, "DEFAULT_CLEAN_DATASETS", ("electricity",))
    monkeypatch.setattr(
        clean_orchestrator,
        "load_clean_dependencies",
        lambda connection: {"region_merge_key_rows": 2},
    )

    results = clean_orchestrator.run_clean_datasets(
        ("electricity",),
        engine=RecordingEngine(connection),
    )

    assert results[0].affected_row_count == 3
    assert results[0].revision == 1
    assert results[0].revision_changed is True

    sql_calls = [
        call[1]
        for call in connection.calls
        if call[0] == "exec_driver_sql"
    ]
    bump_index = next(
        index
        for index, call in enumerate(connection.calls)
        if call[0] == "execute" and "RETURNING revision" in call[1]
    )
    commit_index = next(
        index
        for index, call in enumerate(connection.calls)
        if call[0] == "exec_driver_sql" and call[1] == "COMMIT"
    )
    assert bump_index < commit_index
    assert sql_calls == [
        "BEGIN",
        "INSERT INTO clean.clean_electricity VALUES (1)",
        "COMMIT",
    ]


def test_run_clean_datasets_does_not_bump_revision_on_noop(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    electricity_sql = write_sql(
        tmp_path / "electricity.sql",
        "BEGIN; INSERT INTO clean.clean_electricity VALUES (1); COMMIT;",
    )
    specs = (
        clean_orchestrator.CleanDatasetSpec(
            "electricity",
            electricity_sql,
            ("clean_electricity",),
        ),
    )
    connection = RecordingConnection(
        rowcounts={"INSERT INTO clean.clean_electricity VALUES (1)": 0},
        revision=5,
    )

    monkeypatch.setattr(clean_orchestrator, "CLEAN_DATASETS", specs)
    monkeypatch.setattr(clean_orchestrator, "DEFAULT_CLEAN_DATASETS", ("electricity",))
    monkeypatch.setattr(
        clean_orchestrator,
        "load_clean_dependencies",
        lambda connection: {"region_merge_key_rows": 2},
    )

    results = clean_orchestrator.run_clean_datasets(
        ("electricity",),
        engine=RecordingEngine(connection),
    )

    assert results[0].affected_row_count == 0
    assert results[0].revision == 5
    assert results[0].revision_changed is False
    assert not any(
        call[0] == "execute" and "RETURNING revision" in call[1]
        for call in connection.calls
    )


def test_run_clean_datasets_rebuild_deletes_periods_inside_sql_transaction(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    electricity_sql = write_sql(
        tmp_path / "electricity.sql",
        """
        BEGIN;
        CREATE SCHEMA IF NOT EXISTS clean;
        CREATE TABLE IF NOT EXISTS clean.clean_electricity (date integer);
        CREATE TEMP TABLE base AS SELECT 1;
        COMMIT;
        """,
    )
    specs = (
        clean_orchestrator.CleanDatasetSpec(
            "electricity",
            electricity_sql,
            ("clean_electricity",),
        ),
    )
    connection = RecordingConnection()

    monkeypatch.setattr(clean_orchestrator, "CLEAN_DATASETS", specs)
    monkeypatch.setattr(clean_orchestrator, "DEFAULT_CLEAN_DATASETS", ("electricity",))
    monkeypatch.setattr(
        clean_orchestrator,
        "load_clean_dependencies",
        lambda connection: {"region_merge_key_rows": 2},
    )

    clean_orchestrator.run_clean_datasets(
        ("electricity",),
        engine=RecordingEngine(connection),
        rebuild=True,
        start_period="202601",
        end_period="202602",
    )

    sql_calls = [
        call[1]
        for call in connection.calls
        if call[0] == "exec_driver_sql"
    ]
    delete_index = next(
        index
        for index, sql in enumerate(sql_calls)
        if "DELETE FROM clean.\"clean_electricity\"" in sql
    )
    assert sql_calls[delete_index - 1].startswith("CREATE TABLE")
    assert sql_calls[delete_index + 1].startswith("CREATE TEMP TABLE")
    assert "202601, 202602" in sql_calls[delete_index]

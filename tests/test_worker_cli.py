from __future__ import annotations

import io
from pathlib import Path
from typing import Any

import pytest

from rural_basic_income.worker import cli, clean_orchestrator
from rural_basic_income.worker import export as csv_export
from rural_basic_income.worker import raw_orchestrator


class ScalarResult:
    def __init__(self, value):
        self.value = value

    def scalar_one(self):
        return self.value


class LockingConnection:
    def __init__(self, *, lock_result: bool) -> None:
        self.lock_result = lock_result
        self.calls: list[tuple[str, object]] = []

    def execute(self, statement, parameters=None):
        sql = str(statement)
        self.calls.append((sql, parameters))
        if "pg_try_advisory_lock" in sql:
            return ScalarResult(self.lock_result)
        return ScalarResult(True)


class LockingConnectionContext:
    def __init__(self, connection: LockingConnection) -> None:
        self.connection = connection

    def __enter__(self):
        return self.connection

    def __exit__(self, exc_type, exc, traceback):
        return False


class LockingEngine:
    def __init__(self, connection: LockingConnection) -> None:
        self.connection = connection

    def connect(self):
        return LockingConnectionContext(self.connection)


def test_split_option_values_accepts_commas_and_repeated_values() -> None:
    assert cli.split_option_values(
        ("population,mover", " electricity ", "local_currency,"),
    ) == (
        "population",
        "mover",
        "electricity",
        "local_currency",
    )


def test_run_update_runs_raw_then_clean_with_selected_options() -> None:
    calls: list[tuple[str, Any]] = []
    output = io.StringIO()
    engine = object()

    def raw_runner(
        start_period,
        end_period,
        *,
        sources=None,
        engine=None,
        force=False,
    ):
        calls.append(
            (
                "raw",
                start_period,
                end_period,
                tuple(sources or ()),
                engine,
                force,
            )
        )
        return (
            raw_orchestrator.RawRefreshResult(
                source_name="population",
                period="202601",
                status="downloaded_written",
                row_count=10,
            ),
        )

    def clean_runner(datasets=None, *, engine=None):
        calls.append(("clean", tuple(datasets or ()), engine))
        return (
            clean_orchestrator.CleanDatasetResult(
                dataset_name="population",
                sql_file=Path("clean_population.sql"),
                statement_count=16,
            ),
        )

    result = cli.run_update(
        start_period="202601",
        end_period="202602",
        sources=("population",),
        datasets=("population",),
        force_raw=True,
        engine=engine,
        raw_runner=raw_runner,
        clean_runner=clean_runner,
        output=output,
        lock_update=False,
    )

    assert calls == [
        ("raw", "202601", "202602", ("population",), engine, True),
        ("clean", ("population",), engine),
    ]
    assert result.raw_results[0].row_count == 10
    assert result.clean_results[0].statement_count == 16
    assert "202601 population: downloaded_written rows=10" in output.getvalue()
    assert "population: clean_population.sql statements=16" in output.getvalue()


def test_run_update_exports_when_raw_was_written() -> None:
    calls: list[tuple[str, Any]] = []
    output = io.StringIO()
    engine = object()

    def raw_runner(*args, **kwargs):
        calls.append(("raw", kwargs["engine"]))
        return (
            raw_orchestrator.RawRefreshResult(
                source_name="population",
                period="202601",
                status="downloaded_written",
                row_count=10,
            ),
        )

    def clean_runner(*args, **kwargs):
        calls.append(("clean", kwargs["engine"]))
        return ()

    def export_runner(**kwargs):
        calls.append(("export", kwargs["engine"], kwargs["export_csv_dir"]))
        return csv_export.ExportResult(
            export_dir=Path("/tmp/rbi-export"),
            tables=(
                csv_export.ExportTableResult(
                    schema_name="clean",
                    table_name="clean_population",
                    file_path=Path("/tmp/rbi-export/clean_population.csv"),
                    row_count=1,
                ),
            ),
        )

    result = cli.run_update(
        start_period="202601",
        end_period="202601",
        engine=engine,
        raw_runner=raw_runner,
        clean_runner=clean_runner,
        export_requested=True,
        export_csv_dir="/tmp/rbi-export",
        export_runner=export_runner,
        output=output,
        lock_update=False,
    )

    assert calls == [
        ("raw", engine),
        ("clean", engine),
        ("export", engine, "/tmp/rbi-export"),
    ]
    assert result.export_result is not None
    assert "clean.clean_population: clean_population.csv rows=1" in output.getvalue()


def test_run_update_skips_export_when_nothing_was_written() -> None:
    output = io.StringIO()

    def raw_runner(*args, **kwargs):
        return (
            raw_orchestrator.RawRefreshResult(
                source_name="population",
                period="202601",
                status="skipped_existing",
                row_count=10,
            ),
        )

    def fail_export_runner(**kwargs):
        raise AssertionError("export should not run without raw writes")

    result = cli.run_update(
        start_period="202601",
        end_period="202601",
        engine=object(),
        raw_runner=raw_runner,
        clean_runner=lambda *args, **kwargs: (),
        export_requested=True,
        export_runner=fail_export_runner,
        output=output,
        lock_update=False,
    )

    assert result.export_result is None
    assert "skipped: no raw writes or clean rebuild" in output.getvalue()


def test_run_update_uses_update_overlap_lock() -> None:
    calls: list[str] = []
    connection = LockingConnection(lock_result=True)
    engine = LockingEngine(connection)

    def raw_runner(*args, **kwargs):
        calls.append("raw")
        return ()

    def clean_runner(*args, **kwargs):
        calls.append("clean")
        return ()

    cli.run_update(
        start_period="202601",
        end_period="202601",
        engine=engine,
        raw_runner=raw_runner,
        clean_runner=clean_runner,
        output=io.StringIO(),
    )

    assert calls == ["raw", "clean"]
    assert any("pg_try_advisory_lock" in call[0] for call in connection.calls)
    assert any("pg_advisory_unlock" in call[0] for call in connection.calls)


def test_run_update_rejects_overlapping_update() -> None:
    connection = LockingConnection(lock_result=False)
    engine = LockingEngine(connection)

    def fail_raw_runner(*args, **kwargs):
        raise AssertionError("raw runner should not start without update lock")

    with pytest.raises(cli.WorkerCliError, match="already running"):
        cli.run_update(
            start_period="202601",
            end_period="202601",
            engine=engine,
            raw_runner=fail_raw_runner,
            output=io.StringIO(),
        )


def test_update_command_parses_sources_and_datasets(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = []

    def fake_run_update(**kwargs):
        calls.append(kwargs)
        return cli.WorkerUpdateResult(raw_results=(), clean_results=())

    monkeypatch.setattr(cli, "run_update", fake_run_update)
    exit_code = cli.main(
        (
            "update",
            "--start-period",
            "202601",
            "--end-period",
            "202602",
            "--sources",
            "population,mover",
            "--sources",
            "electricity",
            "--datasets",
            "population",
            "--datasets",
            "electricity,local_currency",
            "--force-raw",
            "--export",
            "--export-csv-dir",
            "/tmp/rbi-export",
        )
    )

    assert exit_code == 0
    assert calls == [
        {
            "start_period": "202601",
            "end_period": "202602",
            "sources": ("population", "mover", "electricity"),
            "datasets": ("population", "electricity", "local_currency"),
            "force_raw": True,
            "export_requested": True,
            "export_csv_dir": "/tmp/rbi-export",
        }
    ]


def test_update_command_uses_default_sources_and_datasets(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = []

    def fake_run_update(**kwargs):
        calls.append(kwargs)
        return cli.WorkerUpdateResult(raw_results=(), clean_results=())

    monkeypatch.setattr(cli, "run_update", fake_run_update)
    exit_code = cli.main(
        (
            "update",
            "--start-period",
            "202601",
            "--end-period",
            "202601",
        )
    )

    assert exit_code == 0
    assert calls == [
        {
            "start_period": "202601",
            "end_period": "202601",
            "sources": None,
            "datasets": None,
            "force_raw": False,
            "export_requested": False,
            "export_csv_dir": None,
        }
    ]


def test_update_command_accepts_legacy_force_as_raw_force(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = []

    def fake_run_update(**kwargs):
        calls.append(kwargs)
        return cli.WorkerUpdateResult(raw_results=(), clean_results=())

    monkeypatch.setattr(cli, "run_update", fake_run_update)
    exit_code = cli.main(
        (
            "update",
            "--start-period",
            "202601",
            "--end-period",
            "202601",
            "--force",
        )
    )

    assert exit_code == 0
    assert calls[0]["force_raw"] is True
    assert calls[0]["export_requested"] is False


def test_update_latest_command_calls_latest_runner(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = []

    def fake_run_update_latest(**kwargs):
        calls.append(kwargs)
        return cli.WorkerUpdateResult(raw_results=(), clean_results=())

    monkeypatch.setattr(cli, "run_update_latest", fake_run_update_latest)
    exit_code = cli.main(
        (
            "update",
            "--latest",
            "--start-period",
            "202501",
            "--end-period",
            "202606",
            "--sources",
            "population",
            "--datasets",
            "population",
        )
    )

    assert exit_code == 0
    assert calls == [
        {
            "sources": ("population",),
            "datasets": ("population",),
            "fallback_start_period": "202501",
            "end_period": "202606",
            "force_raw": False,
            "export_requested": False,
            "export_csv_dir": None,
        }
    ]


def test_update_command_requires_periods_without_latest() -> None:
    with pytest.raises(SystemExit) as exc_info:
        cli.main(("update", "--sources", "population"))

    assert exc_info.value.code == 2


def test_clean_command_parses_rebuild_periods(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = []

    def fake_run_clean(**kwargs):
        calls.append(kwargs)
        return ()

    monkeypatch.setattr(cli, "run_clean", fake_run_clean)
    exit_code = cli.main(
        (
            "clean",
            "--datasets",
            "electricity,local_currency",
            "--rebuild",
            "--start-period",
            "202601",
            "--end-period",
            "202602",
            "--export",
            "--export-csv-dir",
            "/tmp/rbi-export",
        )
    )

    assert exit_code == 0
    assert calls == [
        {
            "datasets": ("electricity", "local_currency"),
            "rebuild": True,
            "start_period": "202601",
            "end_period": "202602",
            "export_requested": True,
            "export_csv_dir": "/tmp/rbi-export",
        }
    ]


def test_export_command_runs_current_db_export(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = []

    def fake_run_export(**kwargs):
        calls.append(kwargs)
        return csv_export.ExportResult(export_dir=Path("/tmp/rbi-export"), tables=())

    monkeypatch.setattr(cli, "run_export", fake_run_export)
    exit_code = cli.main(("export", "--export-csv-dir", "/tmp/rbi-export"))

    assert exit_code == 0
    assert calls == [{"export_csv_dir": "/tmp/rbi-export"}]


def test_status_command_parses_sources(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = []

    def fake_run_status(**kwargs):
        calls.append(kwargs)
        return cli.WorkerStatusResult(source_statuses=())

    monkeypatch.setattr(cli, "run_status", fake_run_status)
    exit_code = cli.main(("status", "--sources", "population,mover"))

    assert exit_code == 0
    assert calls == [{"sources": ("population", "mover")}]

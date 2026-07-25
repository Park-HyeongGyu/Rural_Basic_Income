from __future__ import annotations

import io
from pathlib import Path
from typing import Any

import pytest

from rural_basic_income.worker import cli, clean_orchestrator, raw_orchestrator


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
        force=True,
        engine=engine,
        raw_runner=raw_runner,
        clean_runner=clean_runner,
        output=output,
    )

    assert calls == [
        ("raw", "202601", "202602", ("population",), engine, True),
        ("clean", ("population",), engine),
    ]
    assert result.raw_results[0].row_count == 10
    assert result.clean_results[0].statement_count == 16
    assert "202601 population: downloaded_written rows=10" in output.getvalue()
    assert "population: clean_population.sql statements=16" in output.getvalue()


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
            "--force",
        )
    )

    assert exit_code == 0
    assert calls == [
        {
            "start_period": "202601",
            "end_period": "202602",
            "sources": ("population", "mover", "electricity"),
            "datasets": ("population", "electricity", "local_currency"),
            "force": True,
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
            "force": False,
        }
    ]

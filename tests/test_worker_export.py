from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any

import pytest

from rural_basic_income.worker import export


class FakeTableListResult:
    def __init__(self, rows: list[tuple[str, str]]) -> None:
        self.rows = rows

    def __iter__(self):
        return iter(self.rows)


class FakeSelectResult:
    def __init__(self, columns: tuple[str, ...], rows: list[tuple[Any, ...]]) -> None:
        self.columns = columns
        self.rows = rows

    def keys(self):
        return self.columns

    def __iter__(self):
        return iter(self.rows)


class FakeConnection:
    def __init__(self) -> None:
        self.sql_calls: list[str] = []

    def execute(self, statement, parameters=None):
        self.sql_calls.append(str(statement))
        assert parameters == {"schemas": ["raw", "clean"]}
        return FakeTableListResult(
            [
                ("raw", "population"),
                ("clean", "clean_population"),
            ]
        )

    def execution_options(self, **kwargs):
        assert kwargs == {"stream_results": True}
        return self

    def exec_driver_sql(self, statement: str):
        self.sql_calls.append(statement)
        if statement == 'SELECT * FROM "raw"."population"':
            return FakeSelectResult(
                ("시점", "행정구역", "값"),
                [
                    ("202601", "전북 임실군", 10),
                    ("202601", "전북 고창군", {"nested": ["값"]}),
                ],
            )
        if statement == 'SELECT * FROM "clean"."clean_population"':
            return FakeSelectResult(
                ("date", "region_sido", "region_sigungu", "population"),
                [(202601, "전북", "임실군", 25259)],
            )
        raise AssertionError(f"unexpected SQL: {statement}")


class FakeConnectionContext:
    def __init__(self, connection: FakeConnection) -> None:
        self.connection = connection

    def __enter__(self):
        return self.connection

    def __exit__(self, exc_type, exc, traceback):
        return False


class FakeEngine:
    def __init__(self, connection: FakeConnection) -> None:
        self.connection = connection

    def connect(self):
        return FakeConnectionContext(self.connection)


def read_csv(path: Path) -> list[list[str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as csv_file:
        return list(csv.reader(csv_file))


def test_export_csv_writes_flat_latest_raw_and_clean_files(tmp_path: Path) -> None:
    target_dir = tmp_path / "csv"
    target_dir.mkdir()
    (target_dir / "stale.csv").write_text("old", encoding="utf-8")
    (target_dir / "notes.txt").write_text("keep", encoding="utf-8")

    result = export.export_csv(
        export_csv_dir=target_dir,
        engine=FakeEngine(FakeConnection()),
    )

    assert result.export_dir == target_dir
    assert sorted(path.name for path in target_dir.iterdir()) == [
        "clean_population.csv",
        "raw_population.csv",
    ]
    assert [table.file_path.name for table in result.tables] == [
        "raw_population.csv",
        "clean_population.csv",
    ]
    assert read_csv(target_dir / "raw_population.csv") == [
        ["시점", "행정구역", "값"],
        ["202601", "전북 임실군", "10"],
        ["202601", "전북 고창군", json.dumps({"nested": ["값"]}, ensure_ascii=False, separators=(",", ":"))],
    ]
    assert read_csv(target_dir / "clean_population.csv") == [
        ["date", "region_sido", "region_sigungu", "population"],
        ["202601", "전북", "임실군", "25259"],
    ]
    assert not any(path.is_dir() for path in target_dir.iterdir())


def test_csv_file_name_avoids_double_clean_prefix() -> None:
    assert export.csv_file_name("raw", "population") == "raw_population.csv"
    assert export.csv_file_name("clean", "clean_population") == "clean_population.csv"
    assert export.csv_file_name("clean", "electricity") == "clean_electricity.csv"


def test_list_export_tables_rejects_unknown_schema() -> None:
    with pytest.raises(export.ExportError, match="unknown export schema"):
        export.list_export_tables(FakeConnection(), schemas=("metadata",))

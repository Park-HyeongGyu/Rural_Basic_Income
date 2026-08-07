from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any

import pandas as pd
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
        [
            "202601",
            "전북 고창군",
            json.dumps(
                {"nested": ["값"]},
                ensure_ascii=False,
                separators=(",", ":"),
            ),
        ],
    ]
    assert read_csv(target_dir / "clean_population.csv") == [
        ["date", "region_sido", "region_sigungu", "population"],
        ["202601", "전북", "임실군", "25259"],
    ]
    assert not any(path.is_dir() for path in target_dir.iterdir())


def test_export_csv_only_does_not_write_dta_files(tmp_path: Path) -> None:
    csv_dir = tmp_path / "csv"
    dta_dir = tmp_path / "dta"

    result = export.export_csv_only(
        export_csv_dir=csv_dir,
        export_dta_dir=dta_dir,
        engine=FakeEngine(FakeConnection()),
    )

    assert result.csv.export_dir == csv_dir
    assert result.dta is None
    assert sorted(path.name for path in csv_dir.iterdir()) == [
        "clean_population.csv",
        "raw_population.csv",
    ]
    assert not dta_dir.exists()


def test_publish_export_directory_keeps_target_directory_in_place(tmp_path: Path) -> None:
    target_dir = tmp_path / "csv"
    target_dir.mkdir()
    target_inode = target_dir.stat().st_ino
    (target_dir / "stale.csv").write_text("old", encoding="utf-8")
    temp_dir = target_dir / ".tmp.test"
    temp_dir.mkdir()
    (temp_dir / "fresh.csv").write_text("new", encoding="utf-8")

    result = export.publish_export_directory(temp_dir, target_dir)

    assert result == target_dir
    assert target_dir.stat().st_ino == target_inode
    assert sorted(path.name for path in target_dir.iterdir()) == ["fresh.csv"]
    assert (target_dir / "fresh.csv").read_text(encoding="utf-8") == "new"


def test_csv_file_name_avoids_double_clean_prefix() -> None:
    assert export.csv_file_name("raw", "population") == "raw_population.csv"
    assert export.csv_file_name("clean", "clean_population") == "clean_population.csv"
    assert export.csv_file_name("clean", "electricity") == "clean_electricity.csv"
    assert export.dta_file_name("raw", "population") == "raw_population.dta"
    assert export.dta_file_name("clean", "clean_population") == "clean_population.dta"


def test_export_table_to_dta_keeps_unicode_variable_names(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_read_sql_query(sql: str, connection) -> pd.DataFrame:
        assert sql == 'SELECT * FROM "raw"."household"'
        return pd.DataFrame(
            {
                "시점": [202601],
                "행정구역(시군구)별": ["전북 임실군"],
                "세대수 (세대)": [123],
                "downloaded_at": pd.to_datetime(
                    ["2026-07-26T00:00:00+00:00"],
                    utc=True,
                ),
            }
        )

    monkeypatch.setattr(export.pd, "read_sql_query", fake_read_sql_query)

    result = export.export_table_to_dta(
        object(),
        export.ExportTable("raw", "household"),
        output_dir=tmp_path,
    )

    assert result.file_path == tmp_path / "raw_household.dta"
    assert result.row_count == 1
    dataframe = pd.read_stata(result.file_path)
    assert "시점" in dataframe.columns
    assert "행정구역_시군구_별" in dataframe.columns
    assert "세대수__세대_" in dataframe.columns
    assert dataframe.loc[0, "행정구역_시군구_별"] == "전북 임실군"
    assert dataframe.loc[0, "downloaded_at"].startswith("2026-07-26T")


def test_list_export_tables_rejects_unknown_schema() -> None:
    with pytest.raises(export.ExportError, match="unknown export schema"):
        export.list_export_tables(FakeConnection(), schemas=("metadata",))

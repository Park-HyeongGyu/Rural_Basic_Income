from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from rural_basic_income.analysis.data_loader import load_analysis_panel
from rural_basic_income.analysis.exceptions import AnalysisSpecError
from rural_basic_income.analysis.schemas import (
    AnalysisOutcome,
    AnalysisPeriod,
    AnalysisSpec,
    ControlRegion,
    RegionKey,
    TreatmentRegion,
)


class ScalarResult:
    def __init__(self, values):
        self.values = values

    def scalars(self):
        return iter(self.values)


class RowResult:
    def __init__(self, rows):
        self.rows = rows

    def __iter__(self):
        return iter(self.rows)


class MappingResult:
    def __init__(self, rows):
        self.rows = rows

    def mappings(self):
        return iter(self.rows)


class FakeConnection:
    def __init__(self, rows):
        self.rows = rows
        self.calls = []

    def execute(self, statement, parameters=None):
        sql = str(statement)
        self.calls.append((sql, parameters or {}))
        if "information_schema.tables" in sql:
            return ScalarResult(("clean_population_sex",))
        if "information_schema.columns" in sql:
            return RowResult(
                (
                    SimpleNamespace(column_name="date", data_type="integer"),
                    SimpleNamespace(column_name="region_sido", data_type="text"),
                    SimpleNamespace(column_name="region_sigungu", data_type="text"),
                    SimpleNamespace(column_name="sex", data_type="text"),
                    SimpleNamespace(column_name="population", data_type="bigint"),
                )
            )
        if 'SELECT DISTINCT "sex"' in sql:
            return ScalarResult(("all", "male", "female"))
        if 'FROM "clean"."clean_population_sex"' in sql:
            return MappingResult(self.rows)
        raise AssertionError(f"unexpected SQL: {sql}")


def write_region_key(path: Path) -> Path:
    path.write_text(
        "\n".join(
            [
                "region_sido,region_sigungu,is_gun",
                "전북,임실군,1",
                "전북,고창군,1",
            ]
        ),
        encoding="utf-8",
    )
    return path


def make_spec() -> AnalysisSpec:
    return AnalysisSpec(
        period=AnalysisPeriod("202512", "202602", "202512"),
        treatments=(TreatmentRegion(RegionKey("전북", "임실군"), "202601"),),
        controls=(ControlRegion(RegionKey("전북", "고창군")),),
    )


def make_rows():
    return [
        {
            "date": 202512,
            "region_sido": "전북",
            "region_sigungu": "임실군",
            "raw_value": 100,
        },
        {
            "date": 202601,
            "region_sido": "전북",
            "region_sigungu": "임실군",
            "raw_value": 110,
        },
        {
            "date": 202602,
            "region_sido": "전북",
            "region_sigungu": "임실군",
            "raw_value": 120,
        },
        {
            "date": 202512,
            "region_sido": "전북",
            "region_sigungu": "고창군",
            "raw_value": 200,
        },
        {
            "date": 202601,
            "region_sido": "전북",
            "region_sigungu": "고창군",
            "raw_value": 220,
        },
        {
            "date": 202602,
            "region_sido": "전북",
            "region_sigungu": "고창군",
            "raw_value": 240,
        },
    ]


def test_load_analysis_panel_validates_metadata_and_builds_panel(tmp_path: Path) -> None:
    connection = FakeConnection(make_rows())

    loaded = load_analysis_panel(
        connection,
        AnalysisOutcome(
            table="clean.clean_population_sex",
            variable="population",
            filters={"sex": "all"},
        ),
        make_spec(),
        region_merge_key_path=write_region_key(tmp_path / "region_merge_key.csv"),
    )

    assert loaded.table_metadata.table_name == "clean_population_sex"
    assert loaded.table_metadata.selectable_variables == ("population",)
    assert len(loaded.panel.data) == 6
    imsil_202601 = loaded.panel.data[
        (loaded.panel.data["region_sido"] == "전북")
        & (loaded.panel.data["region_sigungu"] == "임실군")
        & (loaded.panel.data["period"] == "202601")
    ].iloc[0]
    assert imsil_202601["normalized_value"] == 1.1
    assert imsil_202601["did"] == 1

    source_sql, source_params = connection.calls[-1]
    assert 'FROM "clean"."clean_population_sex"' in source_sql
    assert 'SUM("population") AS raw_value' in source_sql
    assert '"sex" = :filter_sex' in source_sql
    assert "GROUP BY date, region_sido, region_sigungu" in source_sql
    assert source_params["filter_sex"] == "all"
    assert source_params["start_period"] == 202512
    assert source_params["normalization_base"] == 202512


def test_load_analysis_panel_accepts_multiple_filter_values(tmp_path: Path) -> None:
    connection = FakeConnection(make_rows())

    load_analysis_panel(
        connection,
        AnalysisOutcome(
            table="clean.clean_population_sex",
            variable="population",
            filters={"sex": ["male", "female"]},
        ),
        make_spec(),
        region_merge_key_path=write_region_key(tmp_path / "region_merge_key.csv"),
    )

    source_sql, source_params = connection.calls[-1]
    assert '"sex" IN (:filter_sex_0, :filter_sex_1)' in source_sql
    assert source_params["filter_sex_0"] == "male"
    assert source_params["filter_sex_1"] == "female"


def test_load_analysis_panel_rejects_unknown_variable(tmp_path: Path) -> None:
    connection = FakeConnection(make_rows())

    with pytest.raises(AnalysisSpecError, match="not selectable"):
        load_analysis_panel(
            connection,
            AnalysisOutcome(
                table="clean.clean_population_sex",
                variable="not_a_column",
                filters={"sex": "all"},
            ),
            make_spec(),
            region_merge_key_path=write_region_key(tmp_path / "region_merge_key.csv"),
        )


def test_load_analysis_panel_requires_dimension_filters(tmp_path: Path) -> None:
    connection = FakeConnection(make_rows())

    with pytest.raises(AnalysisSpecError, match="filters are required"):
        load_analysis_panel(
            connection,
            AnalysisOutcome(
                table="clean.clean_population_sex",
                variable="population",
                filters={},
            ),
            make_spec(),
            region_merge_key_path=write_region_key(tmp_path / "region_merge_key.csv"),
        )


def test_load_analysis_panel_rejects_invalid_filter_value(tmp_path: Path) -> None:
    connection = FakeConnection(make_rows())

    with pytest.raises(AnalysisSpecError, match="not selectable"):
        load_analysis_panel(
            connection,
            AnalysisOutcome(
                table="clean.clean_population_sex",
                variable="population",
                filters={"sex": "unknown"},
            ),
            make_spec(),
            region_merge_key_path=write_region_key(tmp_path / "region_merge_key.csv"),
        )


def test_load_analysis_panel_rejects_region_outside_merge_key(tmp_path: Path) -> None:
    connection = FakeConnection(make_rows())
    region_key_path = tmp_path / "region_merge_key.csv"
    region_key_path.write_text(
        "\n".join(
            [
                "region_sido,region_sigungu,is_gun",
                "전북,임실군,1",
            ]
        ),
        encoding="utf-8",
    )

    with pytest.raises(AnalysisSpecError, match="region_merge_key"):
        load_analysis_panel(
            connection,
            AnalysisOutcome(
                table="clean.clean_population_sex",
                variable="population",
                filters={"sex": "all"},
            ),
            make_spec(),
            region_merge_key_path=region_key_path,
        )

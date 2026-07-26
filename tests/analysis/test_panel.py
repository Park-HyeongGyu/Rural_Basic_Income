from __future__ import annotations

import pandas as pd
import pytest

from rural_basic_income.analysis import (
    AnalysisPeriod,
    AnalysisSpec,
    ControlRegion,
    RegionKey,
    TreatmentRegion,
    build_analysis_panel,
)
from rural_basic_income.analysis.exceptions import (
    AnalysisSpecError,
    PanelConstructionError,
)


def make_spec(
    *,
    start_period: str = "202512",
    end_period: str = "202603",
    normalization_base: str = "202512",
) -> AnalysisSpec:
    return AnalysisSpec(
        period=AnalysisPeriod(start_period, end_period, normalization_base),
        treatments=(
            TreatmentRegion(RegionKey("전북", "임실군"), "202601"),
            TreatmentRegion(RegionKey("전북", "순창군"), "202602"),
        ),
        controls=(
            ControlRegion(RegionKey("전북", "고창군")),
            ControlRegion(RegionKey("전남", "곡성군")),
        ),
    )


def make_rows() -> pd.DataFrame:
    regions = [
        ("전북", "임실군", 100.0),
        ("전북", "순창군", 200.0),
        ("전북", "고창군", 150.0),
        ("전남", "곡성군", 120.0),
    ]
    periods = ["202512", "202601", "202602", "202603"]
    rows = []
    for sido, sigungu, baseline in regions:
        for offset, period in enumerate(periods):
            rows.append(
                {
                    "date": int(period),
                    "region_sido": sido,
                    "region_sigungu": sigungu,
                    "value": baseline + offset * 10,
                }
            )
    return pd.DataFrame(rows)


def test_build_analysis_panel_normalizes_each_region_by_own_baseline() -> None:
    panel = build_analysis_panel(make_rows(), make_spec(), outcome_column="value")
    data = panel.data

    base_rows = data[data["period"] == "202512"]
    assert set(base_rows["normalized_value"]) == {1.0}

    imsil = data[(data["region_sido"] == "전북") & (data["region_sigungu"] == "임실군")]
    sunchang = data[
        (data["region_sido"] == "전북") & (data["region_sigungu"] == "순창군")
    ]
    assert imsil.loc[imsil["period"] == "202601", "normalized_value"].item() == 1.1
    assert sunchang.loc[sunchang["period"] == "202601", "normalized_value"].item() == 1.05


def test_build_analysis_panel_sets_treatment_timing_across_year_boundary() -> None:
    panel = build_analysis_panel(make_rows(), make_spec(), outcome_column="value")
    data = panel.data

    imsil = data[(data["region_sido"] == "전북") & (data["region_sigungu"] == "임실군")]
    assert imsil.loc[imsil["period"] == "202512", "event_time"].item() == -1
    assert imsil.loc[imsil["period"] == "202601", "event_time"].item() == 0
    assert imsil.loc[imsil["period"] == "202602", "did"].item() == 1

    sunchang = data[
        (data["region_sido"] == "전북") & (data["region_sigungu"] == "순창군")
    ]
    assert sunchang.loc[sunchang["period"] == "202601", "event_time"].item() == -1
    assert sunchang.loc[sunchang["period"] == "202602", "event_time"].item() == 0

    controls = data[~data["is_treatment_region"]]
    assert controls["did"].sum() == 0
    assert controls["event_time"].isna().all()


def test_build_analysis_panel_warns_when_base_is_not_before_treatment() -> None:
    spec = make_spec(
        start_period="202512",
        end_period="202603",
        normalization_base="202601",
    )
    panel = build_analysis_panel(make_rows(), spec, outcome_column="value")

    assert [warning.code for warning in panel.warnings] == [
        "normalization_base_not_pre_treatment"
    ]
    assert panel.warnings[0].details["normalization_base"] == "202601"


def test_build_analysis_panel_reports_unbalanced_panel_warning() -> None:
    rows = make_rows()
    rows = rows[
        ~(
            (rows["region_sido"] == "전남")
            & (rows["region_sigungu"] == "곡성군")
            & (rows["date"] == 202603)
        )
    ]

    panel = build_analysis_panel(rows, make_spec(), outcome_column="value")

    assert [warning.code for warning in panel.warnings] == ["unbalanced_panel"]
    assert panel.missing_region_periods == ((RegionKey("전남", "곡성군"), "202603"),)


def test_build_analysis_panel_rejects_missing_baseline() -> None:
    rows = make_rows()
    rows = rows[
        ~(
            (rows["region_sido"] == "전북")
            & (rows["region_sigungu"] == "임실군")
            & (rows["date"] == 202512)
        )
    ]

    with pytest.raises(PanelConstructionError, match="baseline is missing"):
        build_analysis_panel(rows, make_spec(), outcome_column="value")


def test_build_analysis_panel_rejects_zero_baseline() -> None:
    rows = make_rows()
    rows.loc[
        (rows["region_sido"] == "전북")
        & (rows["region_sigungu"] == "임실군")
        & (rows["date"] == 202512),
        "value",
    ] = 0

    with pytest.raises(PanelConstructionError, match="baseline is zero"):
        build_analysis_panel(rows, make_spec(), outcome_column="value")


def test_build_analysis_panel_rejects_duplicate_region_period() -> None:
    rows = pd.concat([make_rows(), make_rows().head(1)], ignore_index=True)

    with pytest.raises(PanelConstructionError, match="must be unique"):
        build_analysis_panel(rows, make_spec(), outcome_column="value")


def test_analysis_spec_rejects_treatment_control_overlap() -> None:
    with pytest.raises(AnalysisSpecError, match="both treatment and control"):
        AnalysisSpec(
            period=AnalysisPeriod("202512", "202603", "202512"),
            treatments=(
                TreatmentRegion(RegionKey("전북", "임실군"), "202601"),
            ),
            controls=(
                ControlRegion(RegionKey("전북", "임실군")),
            ),
        )

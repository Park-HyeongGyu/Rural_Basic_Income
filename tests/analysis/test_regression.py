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
    fit_traditional_event_study,
    fit_twfe_did,
)
from rural_basic_income.analysis.exceptions import RegressionDependencyError


def require_pyfixest_runtime() -> None:
    try:
        from rural_basic_income.analysis.regression import import_pyfixest

        import_pyfixest()
    except RegressionDependencyError as exc:
        pytest.skip(str(exc))


def make_regression_panel() -> pd.DataFrame:
    require_pyfixest_runtime()
    spec = AnalysisSpec(
        period=AnalysisPeriod("202512", "202605", "202512"),
        treatments=(
            TreatmentRegion(RegionKey("전북", "임실군"), "202602"),
            TreatmentRegion(RegionKey("전북", "순창군"), "202603"),
        ),
        controls=(
            ControlRegion(RegionKey("전북", "고창군")),
            ControlRegion(RegionKey("전남", "곡성군")),
        ),
    )
    rows = []
    periods = ["202512", "202601", "202602", "202603", "202604", "202605"]
    regions = [
        ("전북", "임실군", "202602", 100.0),
        ("전북", "순창군", "202603", 120.0),
        ("전북", "고창군", None, 90.0),
        ("전남", "곡성군", None, 110.0),
    ]
    for region_index, (sido, sigungu, treatment_period, baseline) in enumerate(regions):
        for time_index, period in enumerate(periods):
            treated = treatment_period is not None and period >= treatment_period
            outcome = baseline + region_index * 2 + time_index
            if treated:
                outcome += 20
            rows.append(
                {
                    "date": int(period),
                    "region_sido": sido,
                    "region_sigungu": sigungu,
                    "value": outcome,
                }
            )
    return build_analysis_panel(
        pd.DataFrame(rows),
        spec,
        outcome_column="value",
    ).data


def test_fit_twfe_did_returns_treatment_coefficient() -> None:
    panel = make_regression_panel()

    result = fit_twfe_did(panel)

    assert result.n_observations == len(panel)
    assert result.n_regions == 4
    assert result.n_clusters == 4
    assert result.n_periods == 6
    assert result.coefficient.estimate > 0
    assert result.coefficient.standard_error is not None


def test_fit_traditional_event_study_includes_reference_point() -> None:
    panel = make_regression_panel()

    result = fit_traditional_event_study(panel)

    points = {point.event_time: point for point in result.points}
    assert points[-1].is_reference is True
    assert points[-1].estimate == 0.0
    assert points[-1].standard_error is None
    assert 0 in points
    assert 1 in points
    assert points[0].is_reference is False
    assert points[0].treated_region_count > 0

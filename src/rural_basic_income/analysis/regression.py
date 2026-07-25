from __future__ import annotations

import importlib
from dataclasses import dataclass
from typing import Any

import pandas as pd

from rural_basic_income.analysis.exceptions import (
    RegressionDependencyError,
    RegressionError,
)


REFERENCE_EVENT_TIME = -1


@dataclass(frozen=True)
class CoefficientEstimate:
    estimate: float
    standard_error: float | None
    t_statistic: float | None
    p_value: float | None
    ci_lower_95: float | None
    ci_upper_95: float | None


@dataclass(frozen=True)
class TwfeResult:
    coefficient: CoefficientEstimate
    n_observations: int
    n_regions: int
    n_clusters: int
    n_periods: int


@dataclass(frozen=True)
class EventStudyPoint:
    event_time: int
    estimate: float
    standard_error: float | None
    t_statistic: float | None
    p_value: float | None
    ci_lower_95: float | None
    ci_upper_95: float | None
    is_reference: bool
    treated_region_count: int
    observation_count: int


@dataclass(frozen=True)
class EventStudyResult:
    points: tuple[EventStudyPoint, ...]
    n_observations: int
    n_regions: int
    n_clusters: int
    n_periods: int


def import_pyfixest():
    try:
        import pyfixest as pf

        # Accessing feols triggers PyFixest's lazy imports and catches incomplete
        # local installations early. Importing report catches PyFixest 0.60's
        # table-rendering dependency chain before a model fit starts.
        getattr(pf, "feols")
        importlib.import_module("pyfixest.report")
    except ModuleNotFoundError as exc:
        raise RegressionDependencyError(
            "PyFixest is not fully available in this Python environment. "
            "Use the project container or a Python 3.13 virtualenv."
        ) from exc
    return pf


def fit_twfe_did(panel: pd.DataFrame) -> TwfeResult:
    require_columns(
        panel,
        {
            "normalized_value",
            "did",
            "region_id",
            "period",
        },
    )
    pf = import_pyfixest()
    data = panel.copy()
    data["period"] = data["period"].astype(str)
    try:
        fit = pf.feols(
            "normalized_value ~ did | region_id + period",
            data=data,
            vcov={"CRV1": "region_id"},
        )
    except Exception as exc:  # pragma: no cover - depends on pyfixest internals
        raise RegressionError("TWFE DiD regression failed") from exc

    tidy = fit.tidy()
    coefficient = coefficient_from_tidy(tidy, "did")
    return TwfeResult(
        coefficient=coefficient,
        n_observations=len(data),
        n_regions=data["region_id"].nunique(),
        n_clusters=data["region_id"].nunique(),
        n_periods=data["period"].nunique(),
    )


def fit_traditional_event_study(panel: pd.DataFrame) -> EventStudyResult:
    require_columns(
        panel,
        {
            "normalized_value",
            "event_time",
            "is_treatment_region",
            "region_id",
            "period",
        },
    )
    pf = import_pyfixest()
    data = panel.copy()
    data["period"] = data["period"].astype(str)
    event_columns = add_event_time_dummies(data)
    if not event_columns:
        raise RegressionError("event study has no non-reference event-time dummies")

    formula = (
        "normalized_value ~ "
        + " + ".join(column for column, _event_time in event_columns)
        + " | region_id + period"
    )
    try:
        fit = pf.feols(formula, data=data, vcov={"CRV1": "region_id"})
    except Exception as exc:  # pragma: no cover - depends on pyfixest internals
        raise RegressionError("TWFE event-study regression failed") from exc

    tidy = fit.tidy()
    points = [reference_event_point(data)]
    for column, event_time in event_columns:
        points.append(
            event_point_from_tidy(
                tidy=tidy,
                data=data,
                coefficient_name=column,
                event_time=event_time,
            )
        )

    return EventStudyResult(
        points=tuple(sorted(points, key=lambda point: point.event_time)),
        n_observations=len(data),
        n_regions=data["region_id"].nunique(),
        n_clusters=data["region_id"].nunique(),
        n_periods=data["period"].nunique(),
    )


def add_event_time_dummies(data: pd.DataFrame) -> list[tuple[str, int]]:
    observed_event_times = sorted(
        int(event_time)
        for event_time in data.loc[
            data["is_treatment_region"] & data["event_time"].notna(),
            "event_time",
        ].unique()
        if int(event_time) != REFERENCE_EVENT_TIME
    )
    event_columns = []
    for event_time in observed_event_times:
        column = event_time_column_name(event_time)
        data[column] = (
            data["is_treatment_region"] & (data["event_time"] == event_time)
        ).astype(int)
        event_columns.append((column, event_time))
    return event_columns


def event_time_column_name(event_time: int) -> str:
    if event_time < 0:
        return f"event_time_m{abs(event_time)}"
    if event_time > 0:
        return f"event_time_p{event_time}"
    return "event_time_0"


def reference_event_point(data: pd.DataFrame) -> EventStudyPoint:
    support = event_time_support(data, REFERENCE_EVENT_TIME)
    return EventStudyPoint(
        event_time=REFERENCE_EVENT_TIME,
        estimate=0.0,
        standard_error=None,
        t_statistic=None,
        p_value=None,
        ci_lower_95=None,
        ci_upper_95=None,
        is_reference=True,
        treated_region_count=support["treated_region_count"],
        observation_count=support["observation_count"],
    )


def event_point_from_tidy(
    *,
    tidy: pd.DataFrame,
    data: pd.DataFrame,
    coefficient_name: str,
    event_time: int,
) -> EventStudyPoint:
    coefficient = coefficient_from_tidy(tidy, coefficient_name)
    support = event_time_support(data, event_time)
    return EventStudyPoint(
        event_time=event_time,
        estimate=coefficient.estimate,
        standard_error=coefficient.standard_error,
        t_statistic=coefficient.t_statistic,
        p_value=coefficient.p_value,
        ci_lower_95=coefficient.ci_lower_95,
        ci_upper_95=coefficient.ci_upper_95,
        is_reference=False,
        treated_region_count=support["treated_region_count"],
        observation_count=support["observation_count"],
    )


def event_time_support(data: pd.DataFrame, event_time: int) -> dict[str, int]:
    event_rows = data[
        data["is_treatment_region"] & (data["event_time"] == event_time)
    ]
    return {
        "treated_region_count": event_rows["region_id"].nunique(),
        "observation_count": len(event_rows),
    }


def coefficient_from_tidy(
    tidy: pd.DataFrame,
    coefficient_name: str,
) -> CoefficientEstimate:
    if coefficient_name not in tidy.index:
        raise RegressionError(f"coefficient was not estimated: {coefficient_name}")
    row = tidy.loc[coefficient_name]
    if isinstance(row, pd.DataFrame):
        row = row.iloc[0]
    return CoefficientEstimate(
        estimate=optional_float(row, "Estimate") or 0.0,
        standard_error=optional_float(row, "Std. Error"),
        t_statistic=optional_float(row, "t value"),
        p_value=optional_float(row, "Pr(>|t|)"),
        ci_lower_95=optional_float(row, "2.5%"),
        ci_upper_95=optional_float(row, "97.5%"),
    )


def optional_float(row: pd.Series, column: str) -> float | None:
    value = row.get(column)
    if value is None or pd.isna(value):
        return None
    return float(value)


def require_columns(data: pd.DataFrame, columns: set[str]) -> None:
    missing = sorted(columns.difference(data.columns))
    if missing:
        raise RegressionError(
            "regression panel is missing columns: " + ", ".join(missing)
        )

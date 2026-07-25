from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pandas as pd

from rural_basic_income.analysis.exceptions import PanelConstructionError
from rural_basic_income.analysis.schemas import AnalysisSpec, RegionKey
from rural_basic_income.worker.periods import validate_period


@dataclass(frozen=True)
class AnalysisWarning:
    code: str
    message: str
    details: dict[str, Any]


@dataclass(frozen=True)
class AnalysisPanel:
    data: pd.DataFrame
    warnings: tuple[AnalysisWarning, ...]
    missing_region_periods: tuple[tuple[RegionKey, str], ...]


def normalize_period_value(value: object) -> str:
    if pd.isna(value):
        raise PanelConstructionError("period value must not be null")
    if isinstance(value, float) and value.is_integer():
        value = int(value)
    return validate_period(str(value).strip())


def period_to_month_index(period: str) -> int:
    validated = validate_period(str(period))
    return int(validated[:4]) * 12 + int(validated[4:6]) - 1


def month_difference(period: str, reference_period: str) -> int:
    return period_to_month_index(period) - period_to_month_index(reference_period)


def build_analysis_panel(
    rows: pd.DataFrame,
    spec: AnalysisSpec,
    *,
    outcome_column: str,
    period_column: str = "date",
) -> AnalysisPanel:
    required_columns = {
        "region_sido",
        "region_sigungu",
        period_column,
        outcome_column,
    }
    missing_columns = sorted(required_columns.difference(rows.columns))
    if missing_columns:
        raise PanelConstructionError(
            "analysis rows are missing columns: " + ", ".join(missing_columns)
        )

    source = rows.loc[:, list(required_columns)].copy()
    source["period"] = source[period_column].map(normalize_period_value)
    source["raw_value"] = pd.to_numeric(source[outcome_column], errors="raise")
    source["region_sido"] = source["region_sido"].astype(str).str.strip()
    source["region_sigungu"] = source["region_sigungu"].astype(str).str.strip()
    source["region_id"] = source["region_sido"] + "::" + source["region_sigungu"]

    selected_region_ids = {region.region_id for region in spec.all_regions}
    required_periods = set(spec.period.periods)
    required_periods.add(spec.period.normalization_base)
    source = source[
        source["region_id"].isin(selected_region_ids)
        & source["period"].isin(required_periods)
    ].copy()
    if source.empty:
        raise PanelConstructionError("selected analysis rows are empty")

    duplicate_mask = source.duplicated(["region_id", "period"], keep=False)
    if duplicate_mask.any():
        duplicates = (
            source.loc[duplicate_mask, ["region_id", "period"]]
            .drop_duplicates()
            .sort_values(["region_id", "period"])
        )
        raise PanelConstructionError(
            "region-period rows must be unique: "
            + ", ".join(
                f"{row.region_id}/{row.period}" for row in duplicates.itertuples()
            )
        )

    baseline = source[source["period"] == spec.period.normalization_base].copy()
    baseline_by_region = dict(zip(baseline["region_id"], baseline["raw_value"]))
    missing_baselines = sorted(selected_region_ids.difference(baseline_by_region))
    if missing_baselines:
        raise PanelConstructionError(
            "normalization baseline is missing for regions: "
            + ", ".join(missing_baselines)
        )

    null_baselines = sorted(
        region_id
        for region_id, value in baseline_by_region.items()
        if pd.isna(value)
    )
    zero_baselines = sorted(
        region_id for region_id, value in baseline_by_region.items() if value == 0
    )
    if null_baselines:
        raise PanelConstructionError(
            "normalization baseline is null for regions: "
            + ", ".join(null_baselines)
        )
    if zero_baselines:
        raise PanelConstructionError(
            "normalization baseline is zero for regions: "
            + ", ".join(zero_baselines)
        )

    panel = source[source["period"].isin(spec.period.periods)].copy()
    panel["baseline_value"] = panel["region_id"].map(baseline_by_region)
    panel["normalized_value"] = panel["raw_value"] / panel["baseline_value"]

    treatment_by_region_id = {
        item.region.region_id: item for item in spec.treatments
    }
    panel["is_treatment_region"] = panel["region_id"].isin(treatment_by_region_id)
    panel["treatment_period"] = panel["region_id"].map(
        {
            region_id: treatment.treatment_period
            for region_id, treatment in treatment_by_region_id.items()
        }
    )
    panel["period_index"] = panel["period"].map(period_to_month_index)
    panel["cohort_index"] = panel["treatment_period"].map(
        lambda value: period_to_month_index(value) if isinstance(value, str) else 0
    )
    panel["post"] = (
        panel["is_treatment_region"]
        & (panel["period"] >= panel["treatment_period"].fillna("999999"))
    )
    panel["did"] = panel["post"].astype(int)
    panel["event_time"] = panel.apply(event_time_for_row, axis=1)

    missing_region_periods = find_missing_region_periods(panel, spec)
    warnings = list(build_warnings(spec))
    if missing_region_periods:
        warnings.append(
            AnalysisWarning(
                code="unbalanced_panel",
                message="some selected region-period rows are missing",
                details={
                    "missing_count": len(missing_region_periods),
                    "missing": [
                        {
                            "region_sido": region.region_sido,
                            "region_sigungu": region.region_sigungu,
                            "period": period,
                        }
                        for region, period in missing_region_periods
                    ],
                },
            )
        )

    validate_treatment_support(panel, spec)
    panel = panel.sort_values(["region_id", "period"]).reset_index(drop=True)
    return AnalysisPanel(
        data=panel[
            [
                "region_sido",
                "region_sigungu",
                "region_id",
                "period",
                "period_index",
                "raw_value",
                "baseline_value",
                "normalized_value",
                "is_treatment_region",
                "treatment_period",
                "cohort_index",
                "post",
                "did",
                "event_time",
            ]
        ],
        warnings=tuple(warnings),
        missing_region_periods=tuple(missing_region_periods),
    )


def event_time_for_row(row: pd.Series) -> int | None:
    if not row["is_treatment_region"]:
        return None
    return month_difference(str(row["period"]), str(row["treatment_period"]))


def find_missing_region_periods(
    panel: pd.DataFrame,
    spec: AnalysisSpec,
) -> list[tuple[RegionKey, str]]:
    observed = set(zip(panel["region_id"], panel["period"]))
    missing: list[tuple[RegionKey, str]] = []
    for region in spec.all_regions:
        for period in spec.period.periods:
            if (region.region_id, period) not in observed:
                missing.append((region, period))
    return missing


def build_warnings(spec: AnalysisSpec) -> tuple[AnalysisWarning, ...]:
    affected = [
        item
        for item in spec.treatments
        if spec.period.normalization_base >= item.treatment_period
    ]
    if not affected:
        return ()
    return (
        AnalysisWarning(
            code="normalization_base_not_pre_treatment",
            message=(
                "normalization base period is the same as or later than at least "
                "one treatment period"
            ),
            details={
                "normalization_base": spec.period.normalization_base,
                "treatments": [
                    {
                        "region_sido": item.region.region_sido,
                        "region_sigungu": item.region.region_sigungu,
                        "treatment_period": item.treatment_period,
                    }
                    for item in affected
                ],
            },
        ),
    )


def validate_treatment_support(panel: pd.DataFrame, spec: AnalysisSpec) -> None:
    for treatment in spec.treatments:
        region_panel = panel[panel["region_id"] == treatment.region.region_id]
        if region_panel.empty:
            raise PanelConstructionError(
                f"treatment region has no rows: {treatment.region.region_id}"
            )
        if not (region_panel["event_time"] == -1).any():
            raise PanelConstructionError(
                "treatment region has no event_time=-1 row: "
                + treatment.region.region_id
            )
        if not (region_panel["did"] == 1).any():
            raise PanelConstructionError(
                "treatment region has no post-treatment row: "
                + treatment.region.region_id
            )

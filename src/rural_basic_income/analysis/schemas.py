from __future__ import annotations

from dataclasses import dataclass, field
from typing import Mapping

from rural_basic_income.analysis.exceptions import AnalysisSpecError
from rural_basic_income.worker.periods import iter_month_periods, validate_period


CLEAN_SCHEMA = "clean"


@dataclass(frozen=True)
class AnalysisOutcome:
    table: str
    variable: str
    filters: Mapping[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        table = self.table.strip()
        if table.startswith(f"{CLEAN_SCHEMA}."):
            table = table.split(".", 1)[1]
        if not table:
            raise AnalysisSpecError("outcome table must not be empty")
        if "." in table:
            raise AnalysisSpecError(
                f"outcome table must be in {CLEAN_SCHEMA} schema: {self.table}"
            )

        variable = self.variable.strip()
        if not variable:
            raise AnalysisSpecError("outcome variable must not be empty")

        filters = {
            str(key).strip(): str(value).strip()
            for key, value in self.filters.items()
        }
        empty_filter_keys = [key for key in filters if not key]
        empty_filter_values = [key for key, value in filters.items() if not value]
        if empty_filter_keys:
            raise AnalysisSpecError("outcome filter names must not be empty")
        if empty_filter_values:
            raise AnalysisSpecError(
                "outcome filter values must not be empty: "
                + ", ".join(sorted(empty_filter_values))
            )

        object.__setattr__(self, "table", table)
        object.__setattr__(self, "variable", variable)
        object.__setattr__(self, "filters", filters)


@dataclass(frozen=True, order=True)
class RegionKey:
    region_sido: str
    region_sigungu: str

    def __post_init__(self) -> None:
        if not self.region_sido.strip():
            raise AnalysisSpecError("region_sido must not be empty")
        if not self.region_sigungu.strip():
            raise AnalysisSpecError("region_sigungu must not be empty")
        object.__setattr__(self, "region_sido", self.region_sido.strip())
        object.__setattr__(self, "region_sigungu", self.region_sigungu.strip())

    @property
    def region_id(self) -> str:
        return f"{self.region_sido}::{self.region_sigungu}"


@dataclass(frozen=True, order=True)
class TreatmentRegion:
    region: RegionKey
    treatment_period: str

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "treatment_period",
            validate_period(str(self.treatment_period)),
        )


@dataclass(frozen=True, order=True)
class ControlRegion:
    region: RegionKey


@dataclass(frozen=True)
class AnalysisPeriod:
    start_period: str
    end_period: str
    normalization_base: str

    def __post_init__(self) -> None:
        start_period = validate_period(str(self.start_period))
        end_period = validate_period(str(self.end_period))
        normalization_base = validate_period(str(self.normalization_base))
        iter_month_periods(start_period, end_period)
        object.__setattr__(self, "start_period", start_period)
        object.__setattr__(self, "end_period", end_period)
        object.__setattr__(self, "normalization_base", normalization_base)

    @property
    def periods(self) -> tuple[str, ...]:
        return tuple(iter_month_periods(self.start_period, self.end_period))

    def contains(self, period: str) -> bool:
        validated = validate_period(str(period))
        return self.start_period <= validated <= self.end_period


@dataclass(frozen=True)
class AnalysisSpec:
    period: AnalysisPeriod
    treatments: tuple[TreatmentRegion, ...]
    controls: tuple[ControlRegion, ...]

    def __post_init__(self) -> None:
        treatments = tuple(self.treatments)
        controls = tuple(self.controls)
        if not treatments:
            raise AnalysisSpecError("at least one treatment region is required")
        if not controls:
            raise AnalysisSpecError("at least one control region is required")

        treatment_regions = [item.region for item in treatments]
        control_regions = [item.region for item in controls]
        duplicate_treatments = duplicated_regions(treatment_regions)
        duplicate_controls = duplicated_regions(control_regions)
        if duplicate_treatments:
            raise AnalysisSpecError(
                "duplicate treatment regions: "
                + ", ".join(region.region_id for region in duplicate_treatments)
            )
        if duplicate_controls:
            raise AnalysisSpecError(
                "duplicate control regions: "
                + ", ".join(region.region_id for region in duplicate_controls)
            )

        overlap = sorted(set(treatment_regions).intersection(control_regions))
        if overlap:
            raise AnalysisSpecError(
                "regions cannot be both treatment and control: "
                + ", ".join(region.region_id for region in overlap)
            )

        outside = [
            item
            for item in treatments
            if not self.period.contains(item.treatment_period)
        ]
        if outside:
            raise AnalysisSpecError(
                "treatment_period must be inside analysis period: "
                + ", ".join(
                    f"{item.region.region_id}={item.treatment_period}"
                    for item in outside
                )
            )

        object.__setattr__(self, "treatments", treatments)
        object.__setattr__(self, "controls", controls)

    @property
    def treatment_by_region(self) -> dict[RegionKey, TreatmentRegion]:
        return {item.region: item for item in self.treatments}

    @property
    def treatment_regions(self) -> tuple[RegionKey, ...]:
        return tuple(item.region for item in self.treatments)

    @property
    def control_regions(self) -> tuple[RegionKey, ...]:
        return tuple(item.region for item in self.controls)

    @property
    def all_regions(self) -> tuple[RegionKey, ...]:
        return self.treatment_regions + self.control_regions


def duplicated_regions(regions: list[RegionKey]) -> list[RegionKey]:
    seen: set[RegionKey] = set()
    duplicates: set[RegionKey] = set()
    for region in regions:
        if region in seen:
            duplicates.add(region)
        seen.add(region)
    return sorted(duplicates)

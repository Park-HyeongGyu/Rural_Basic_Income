from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any, Mapping

from rural_basic_income.analysis.exceptions import AnalysisSpecError
from rural_basic_income.analysis.schemas import (
    AnalysisOutcome,
    AnalysisPeriod,
    AnalysisSpec,
    ControlRegion,
    RegionKey,
    TreatmentRegion,
)


@dataclass(frozen=True)
class AnalysisRequest:
    outcome: AnalysisOutcome
    spec: AnalysisSpec
    force: bool = False


def parse_analysis_request(payload: Mapping[str, Any]) -> AnalysisRequest:
    if not isinstance(payload, Mapping):
        raise AnalysisSpecError("analysis request payload must be an object")

    outcome_payload = require_mapping(payload, "outcome")
    period_payload = require_mapping(payload, "period")
    treatments_payload = require_sequence(payload, "treatments")
    controls_payload = require_sequence(payload, "controls")

    outcome = AnalysisOutcome(
        table=require_string(outcome_payload, "table"),
        variable=require_string(outcome_payload, "variable"),
        filters=optional_mapping(outcome_payload, "filters"),
    )
    period = AnalysisPeriod(
        start_period=require_string(period_payload, "start"),
        end_period=require_string(period_payload, "end"),
        normalization_base=require_string(period_payload, "normalization_base"),
    )

    return AnalysisRequest(
        outcome=outcome,
        spec=AnalysisSpec(
            period=period,
            treatments=tuple(parse_treatment(item) for item in treatments_payload),
            controls=tuple(parse_control(item) for item in controls_payload),
        ),
        force=bool(payload.get("force", False)),
    )


def require_mapping(payload: Mapping[str, Any], key: str) -> Mapping[str, Any]:
    value = payload.get(key)
    if not isinstance(value, Mapping):
        raise AnalysisSpecError(f"{key} must be an object")
    return value


def optional_mapping(payload: Mapping[str, Any], key: str) -> dict[str, str | list[str]]:
    value = payload.get(key, {})
    if not isinstance(value, Mapping):
        raise AnalysisSpecError(f"{key} must be an object")
    return {
        str(item_key): normalize_filter_payload_value(item_value)
        for item_key, item_value in value.items()
    }


def normalize_filter_payload_value(value: Any) -> str | list[str]:
    if isinstance(value, str):
        return value
    if isinstance(value, Sequence):
        return [str(item) for item in value]
    return str(value)


def require_sequence(payload: Mapping[str, Any], key: str) -> list[Any]:
    value = payload.get(key)
    if not isinstance(value, list):
        raise AnalysisSpecError(f"{key} must be an array")
    return value


def require_string(payload: Mapping[str, Any], key: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str):
        raise AnalysisSpecError(f"{key} must be a string")
    return value


def parse_region(payload: Mapping[str, Any]) -> RegionKey:
    return RegionKey(
        region_sido=require_string(payload, "region_sido"),
        region_sigungu=require_string(payload, "region_sigungu"),
    )


def parse_treatment(value: Any) -> TreatmentRegion:
    if not isinstance(value, Mapping):
        raise AnalysisSpecError("each treatment must be an object")
    return TreatmentRegion(
        region=parse_region(value),
        treatment_period=require_string(value, "treatment_period"),
    )


def parse_control(value: Any) -> ControlRegion:
    if not isinstance(value, Mapping):
        raise AnalysisSpecError("each control must be an object")
    return ControlRegion(region=parse_region(value))


def analysis_request_to_payload(request: AnalysisRequest) -> dict[str, Any]:
    filters = {
        key: values[0] if len(values) == 1 else list(values)
        for key, values in sorted(request.outcome.filters.items())
    }
    return {
        "outcome": {
            "table": request.outcome.table,
            "variable": request.outcome.variable,
            "filters": filters,
        },
        "period": {
            "start": request.spec.period.start_period,
            "end": request.spec.period.end_period,
            "normalization_base": request.spec.period.normalization_base,
        },
        "treatments": [
            {
                "region_sido": treatment.region.region_sido,
                "region_sigungu": treatment.region.region_sigungu,
                "treatment_period": treatment.treatment_period,
            }
            for treatment in sorted(
                request.spec.treatments,
                key=lambda item: (
                    item.region.region_sido,
                    item.region.region_sigungu,
                    item.treatment_period,
                ),
            )
        ],
        "controls": [
            {
                "region_sido": control.region.region_sido,
                "region_sigungu": control.region.region_sigungu,
            }
            for control in sorted(
                request.spec.controls,
                key=lambda item: (
                    item.region.region_sido,
                    item.region.region_sigungu,
                ),
            )
        ],
    }

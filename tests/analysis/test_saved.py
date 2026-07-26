from __future__ import annotations

from rural_basic_income.analysis.saved import (
    default_saved_title,
    normalize_saved_payload,
    saved_analysis_summary,
)


def make_saved_request_payload() -> dict:
    return {
        "outcome": {
            "table": "clean_population",
            "variable": "population",
            "filters": {},
        },
        "period": {
            "start": "202501",
            "end": "202506",
            "normalization_base": "202501",
        },
        "treatments": [
            {
                "region_sido": "전북",
                "region_sigungu": "임실군",
                "treatment_period": "202503",
            }
        ],
        "controls": [
            {"region_sido": "전북", "region_sigungu": "고창군"},
        ],
        "force": True,
    }


def test_normalize_saved_payload_validates_and_drops_force() -> None:
    normalized = normalize_saved_payload(make_saved_request_payload())

    assert normalized["outcome"]["table"] == "clean_population"
    assert normalized["treatments"][0]["region_sigungu"] == "임실군"
    assert "force" not in normalized


def test_default_saved_title_uses_variable_region_and_period() -> None:
    normalized = normalize_saved_payload(make_saved_request_payload())

    assert default_saved_title(normalized) == "population 전북 임실군 202501-202506"


def test_saved_analysis_summary_extracts_follow_up_fields() -> None:
    request_payload = normalize_saved_payload(make_saved_request_payload())
    result_payload = {
        "twfe": {
            "coefficient": {
                "estimate": 0.12,
                "standard_error": 0.03,
            }
        }
    }

    summary = saved_analysis_summary(request_payload, result_payload)

    assert summary["outcome_variable"] == "population"
    assert summary["start_period"] == "202501"
    assert summary["end_period"] == "202506"
    assert summary["treatment_count"] == 1
    assert summary["control_count"] == 1
    assert summary["estimate"] == 0.12
    assert summary["standard_error"] == 0.03

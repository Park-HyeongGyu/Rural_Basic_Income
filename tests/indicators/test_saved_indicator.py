from __future__ import annotations

from rural_basic_income.indicators.saved import (
    default_saved_indicator_title,
    normalize_saved_indicator_payload,
    saved_indicator_summary,
)


def make_indicator_payload() -> dict:
    return {
        "table": "clean_population",
        "variables": ["population"],
        "regions": [
            {"region_sido": "전북", "region_sigungu": "임실군"},
            {"region_sido": "전북", "region_sigungu": "고창군"},
        ],
        "filters": {},
        "normalization": {
            "mode": "base100",
            "base_period": "202501",
        },
    }


def test_normalize_saved_indicator_payload_keeps_dashboard_state() -> None:
    normalized = normalize_saved_indicator_payload(make_indicator_payload())

    assert normalized["table"] == "clean_population"
    assert normalized["variables"] == ["population"]
    assert normalized["regions"][0]["region_sigungu"] == "임실군"
    assert normalized["normalization"] == {
        "mode": "base100",
        "base_period": "202501",
    }


def test_default_saved_indicator_title_uses_base_period() -> None:
    normalized = normalize_saved_indicator_payload(make_indicator_payload())

    assert default_saved_indicator_title(normalized) == "population 전북 임실군 202501=100"


def test_saved_indicator_summary_counts_groups_and_points() -> None:
    request_payload = normalize_saved_indicator_payload(make_indicator_payload())
    result_payload = {
        "groups": [
            {"label": "임실군", "points": [{"date": 202501, "value": 100}]},
            {
                "label": "고창군",
                "points": [
                    {"date": 202501, "value": 100},
                    {"date": 202502, "value": 101},
                ],
            },
        ]
    }

    summary = saved_indicator_summary(request_payload, result_payload)

    assert summary["table"] == "clean_population"
    assert summary["region_count"] == 2
    assert summary["variable_count"] == 1
    assert summary["normalization_mode"] == "base100"
    assert summary["normalization_base_period"] == "202501"
    assert summary["group_count"] == 2
    assert summary["point_count"] == 3

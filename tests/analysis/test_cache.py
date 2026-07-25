from __future__ import annotations

import json

from rural_basic_income.analysis.cache import (
    canonical_analysis_payload,
    make_analysis_cache_key,
    read_cached_result,
    result_cache_key,
    write_cached_result,
)


class DictRedis:
    def __init__(self) -> None:
        self.values: dict[str, str] = {}
        self.ttl_by_key: dict[str, int] = {}

    def get(self, key: str):
        return self.values.get(key)

    def setex(self, key: str, ttl: int, value: str) -> None:
        self.values[key] = value
        self.ttl_by_key[key] = ttl


def make_payload() -> dict:
    return {
        "outcome": {
            "table": "clean.clean_mover",
            "variable": "inflow",
            "filters": {"sex": "all", "age": "all"},
        },
        "period": {
            "start": "202501",
            "end": "202512",
            "normalization_base": "202501",
        },
        "treatments": [
            {
                "region_sido": "전북",
                "region_sigungu": "순창군",
                "treatment_period": "202507",
            },
            {
                "region_sido": "전북",
                "region_sigungu": "임실군",
                "treatment_period": "202506",
            },
        ],
        "controls": [
            {"region_sido": "전남", "region_sigungu": "곡성군"},
            {"region_sido": "전북", "region_sigungu": "고창군"},
        ],
        "force": True,
    }


def test_cache_key_is_stable_for_selection_order_and_ignores_force() -> None:
    payload = make_payload()
    reordered = make_payload()
    reordered["force"] = False
    reordered["treatments"] = list(reversed(reordered["treatments"]))
    reordered["controls"] = list(reversed(reordered["controls"]))

    assert make_analysis_cache_key(
        payload,
        data_revision="rev-1",
    ) == make_analysis_cache_key(reordered, data_revision="rev-1")


def test_cache_key_changes_when_data_revision_changes() -> None:
    payload = make_payload()

    assert make_analysis_cache_key(
        payload,
        data_revision="rev-1",
    ) != make_analysis_cache_key(payload, data_revision="rev-2")


def test_canonical_payload_is_json_serializable() -> None:
    canonical = canonical_analysis_payload(make_payload(), data_revision="rev-1")

    encoded = json.dumps(canonical, ensure_ascii=False, sort_keys=True)

    assert "순창군" in encoded
    assert "force" not in canonical


def test_read_and_write_cached_result_round_trip() -> None:
    redis_client = DictRedis()

    write_cached_result(
        redis_client,
        "abc",
        {"result": "ok"},
        ttl_seconds=30,
    )

    assert read_cached_result(redis_client, "abc") == {"result": "ok"}
    assert redis_client.ttl_by_key[result_cache_key("abc")] == 30

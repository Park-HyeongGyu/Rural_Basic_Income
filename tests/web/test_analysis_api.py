from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pytest
from fastapi import HTTPException
from starlette.requests import Request

from rural_basic_income.analysis.cache import (
    claim_running_task,
    make_analysis_cache_key,
    read_running_task_id,
    result_cache_key,
)
from rural_basic_income.web.api import analysis as analysis_api
from rural_basic_income.web.main import create_app


DATA_REVISION = "metadata.clean_dataset_revision:population:7"


class ScalarResult:
    def scalar_one_or_none(self):
        return 7


class FakeConnection:
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        return None

    def execute(self, statement, parameters=None):
        if "metadata.clean_dataset_revision" in str(statement):
            assert parameters == {"dataset_name": "population"}
            return ScalarResult()
        raise AssertionError(f"unexpected SQL: {statement}")


class FakeEngine:
    def connect(self):
        return FakeConnection()

    def begin(self):
        return FakeConnection()


class DictRedis:
    def __init__(self) -> None:
        self.values: dict[str, str] = {}
        self.ttl_by_key: dict[str, int] = {}

    def get(self, key: str):
        return self.values.get(key)

    def set(self, key: str, value: str, *, nx: bool = False, ex: int | None = None):
        if nx and key in self.values:
            return False
        self.values[key] = value
        if ex is not None:
            self.ttl_by_key[key] = ex
        return True

    def setex(self, key: str, ttl: int, value: str) -> None:
        self.values[key] = value
        self.ttl_by_key[key] = ttl

    def delete(self, key: str) -> int:
        existed = key in self.values
        self.values.pop(key, None)
        self.ttl_by_key.pop(key, None)
        return int(existed)

    def incr(self, key: str) -> int:
        value = int(self.values.get(key, "0")) + 1
        self.values[key] = str(value)
        return value

    def expire(self, key: str, ttl: int) -> None:
        self.ttl_by_key[key] = ttl


@dataclass(frozen=True)
class SettingsStub:
    redis_url: str = "redis://127.0.0.1:6379/0"
    analysis_cache_ttl_seconds: int = 60
    analysis_running_lock_ttl_seconds: int = 90
    analysis_rate_limit_requests: int = 300
    analysis_rate_limit_window_seconds: int = 60


def make_payload(*, force: bool = False) -> dict[str, Any]:
    return {
        "outcome": {
            "table": "clean.clean_population",
            "variable": "population",
            "filters": {},
        },
        "period": {
            "start": "202501",
            "end": "202503",
            "normalization_base": "202501",
        },
        "treatments": [
            {
                "region_sido": "전북",
                "region_sigungu": "임실군",
                "treatment_period": "202502",
            }
        ],
        "controls": [
            {"region_sido": "전북", "region_sigungu": "고창군"},
        ],
        "force": force,
    }


def make_request(*, client_host: str = "127.0.0.1") -> Request:
    return Request(
        {
            "type": "http",
            "method": "POST",
            "path": "/api/analysis/jobs",
            "headers": [],
            "client": (client_host, 1234),
        }
    )


def install_common_fakes(monkeypatch, redis_client, settings=None) -> None:
    resolved_settings = settings or SettingsStub()
    monkeypatch.setattr(analysis_api, "get_settings", lambda: resolved_settings)
    monkeypatch.setattr(analysis_api, "create_redis_client", lambda _settings: redis_client)
    monkeypatch.setattr(analysis_api, "get_engine", lambda: FakeEngine())


def test_create_job_queues_task_and_sets_running_lock(monkeypatch) -> None:
    redis_client = DictRedis()
    install_common_fakes(monkeypatch, redis_client)
    queued: list[tuple[dict[str, Any], str]] = []

    def enqueue(payload, *, task_id):
        queued.append((payload, task_id))
        return task_id

    monkeypatch.setattr(analysis_api, "enqueue_analysis_task", enqueue)

    body = analysis_api.create_analysis_job(make_request(), make_payload())

    assert body["status"] == "queued"
    assert body["cached"] is False
    queued_payload = dict(make_payload())
    queued_payload["_claimed_cache_key"] = body["cache_key"]
    assert queued == [(queued_payload, body["task_id"])]
    assert read_running_task_id(redis_client, body["cache_key"]) == body["task_id"]


def test_create_job_returns_cached_result_without_enqueue(monkeypatch) -> None:
    redis_client = DictRedis()
    install_common_fakes(monkeypatch, redis_client)
    payload = make_payload()
    cache_key = make_analysis_cache_key(payload, data_revision=DATA_REVISION)
    redis_client.setex(
        result_cache_key(cache_key),
        60,
        '{"twfe": {"coefficient": {"estimate": 0.2}}}',
    )
    monkeypatch.setattr(
        analysis_api,
        "enqueue_analysis_task",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("queued")),
    )

    body = analysis_api.create_analysis_job(make_request(), payload)

    assert body["status"] == "success"
    assert body["cached"] is True
    assert body["cache_key"] == cache_key
    assert body["result"]["twfe"]["coefficient"]["estimate"] == 0.2


def test_create_job_returns_existing_running_task(monkeypatch) -> None:
    redis_client = DictRedis()
    install_common_fakes(monkeypatch, redis_client)
    payload = make_payload()
    cache_key = make_analysis_cache_key(payload, data_revision=DATA_REVISION)
    claim_running_task(redis_client, cache_key, "task-existing", ttl_seconds=90)

    body = analysis_api.create_analysis_job(make_request(), payload)

    assert body["status"] == "running"
    assert body["task_id"] == "task-existing"


def test_create_job_rate_limit_is_applied_to_post_only(monkeypatch) -> None:
    redis_client = DictRedis()
    install_common_fakes(
        monkeypatch,
        redis_client,
        SettingsStub(analysis_rate_limit_requests=1),
    )
    monkeypatch.setattr(
        analysis_api,
        "enqueue_analysis_task",
        lambda payload, *, task_id: task_id,
    )
    first = analysis_api.create_analysis_job(make_request(), make_payload())
    with pytest.raises(HTTPException) as exc_info:
        analysis_api.create_analysis_job(make_request(), make_payload())

    assert first["status"] == "queued"
    assert exc_info.value.status_code == 429
    assert exc_info.value.detail["limit"] == 1


def test_get_analysis_result_returns_cached_payload(monkeypatch) -> None:
    redis_client = DictRedis()
    install_common_fakes(monkeypatch, redis_client)
    redis_client.setex(
        result_cache_key("abc"),
        60,
        '{"ok": true}',
    )
    response = analysis_api.get_analysis_result("abc")
    with pytest.raises(HTTPException) as exc_info:
        analysis_api.get_analysis_result("missing")

    assert response["result"] == {"ok": True}
    assert exc_info.value.status_code == 404


def test_get_analysis_job_reports_success_metadata(monkeypatch) -> None:
    class FakeTaskStatus:
        state = "SUCCESS"
        result = {
            "status": "success",
            "cached": False,
            "cache_key": "abc",
        }

        def successful(self):
            return True

        def failed(self):
            return False

    monkeypatch.setattr(analysis_api, "task_status_result", lambda task_id: FakeTaskStatus())

    assert analysis_api.get_analysis_job("task-1") == {
        "task_id": "task-1",
        "status": "SUCCESS",
        "cache_key": "abc",
        "cached": False,
        "data_revision": None,
        "analysis_version": None,
        "result_url": "/api/analysis/results/abc",
        "result_available": True,
    }


def test_analysis_options_reuses_clean_metadata_and_regions(monkeypatch) -> None:
    redis_client = DictRedis()
    install_common_fakes(monkeypatch, redis_client)
    monkeypatch.setattr(analysis_api, "fetch_clean_table_names", lambda _connection: ["clean_population"])
    monkeypatch.setattr(
        analysis_api,
        "clean_table_metadata",
        lambda _connection, _table_name: {
            "table_name": "clean_population",
            "columns": [
                {"name": "date", "data_type": "integer"},
                {"name": "region_sido", "data_type": "text"},
                {"name": "region_sigungu", "data_type": "text"},
                {"name": "population", "data_type": "bigint"},
            ],
            "selectable_variables": [
                {"name": "population", "label": "인구", "data_type": "bigint"}
            ],
            "filters": [],
        },
    )
    monkeypatch.setattr(
        analysis_api,
        "list_regions",
        lambda: {
            "regions": [
                {"region_sido": "전북", "region_sigungu": "임실군", "is_gun": 1}
            ]
        },
    )

    body = analysis_api.analysis_options()

    assert body["tables"][0]["table_name"] == "clean_population"
    assert body["regions"][0]["region_sigungu"] == "임실군"
    assert body["rate_limit"]["requests"] == 300


def test_analysis_routes_are_registered() -> None:
    paths = set()
    for route in create_app().routes:
        if hasattr(route, "path"):
            paths.add(route.path)
        if hasattr(route, "original_router"):
            paths.update(child.path for child in route.original_router.routes)

    assert "/api/analysis/jobs" in paths
    assert "/api/analysis/jobs/{task_id}" in paths
    assert "/api/analysis/results/{cache_key}" in paths
    assert "/api/analysis/options" in paths
    assert "/api/analysis/saved" in paths
    assert "/api/analysis/saved/{saved_id}" in paths


def test_list_saved_analysis_items(monkeypatch) -> None:
    redis_client = DictRedis()
    install_common_fakes(monkeypatch, redis_client)
    monkeypatch.setattr(
        analysis_api,
        "list_saved_analyses",
        lambda _connection: (
            {
                "id": "saved-1",
                "title": "인구 follow up",
                "summary": {"outcome_variable": "population"},
            },
        ),
    )

    body = analysis_api.list_saved_analysis_items()

    assert body["saved"][0]["title"] == "인구 follow up"


def test_create_saved_analysis_item(monkeypatch) -> None:
    redis_client = DictRedis()
    install_common_fakes(monkeypatch, redis_client)
    calls = []

    def fake_create(_connection, payload):
        calls.append(payload)
        return {"id": "saved-1", "title": payload["title"]}

    monkeypatch.setattr(analysis_api, "create_saved_analysis", fake_create)

    body = analysis_api.create_saved_analysis_item({"title": "저장"})

    assert calls == [{"title": "저장"}]
    assert body["saved"]["id"] == "saved-1"


def test_get_saved_analysis_item_returns_404(monkeypatch) -> None:
    redis_client = DictRedis()
    install_common_fakes(monkeypatch, redis_client)
    monkeypatch.setattr(analysis_api, "get_saved_analysis", lambda *_args: None)

    with pytest.raises(HTTPException) as exc_info:
        analysis_api.get_saved_analysis_item("00000000-0000-0000-0000-000000000001")

    assert exc_info.value.status_code == 404

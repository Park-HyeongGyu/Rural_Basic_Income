from __future__ import annotations

from typing import Any

import pytest
from fastapi import HTTPException

from rural_basic_income.web.api import info as info_api
from rural_basic_income.web.main import create_app


class FakeConnection:
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        return None


class FakeEngine:
    def connect(self):
        return FakeConnection()

    def begin(self):
        return FakeConnection()


def install_fake_engine(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(info_api, "get_engine", lambda: FakeEngine())


def test_list_info_items(monkeypatch: pytest.MonkeyPatch) -> None:
    install_fake_engine(monkeypatch)
    monkeypatch.setattr(
        info_api,
        "list_info_posts",
        lambda _connection: (
            {
                "id": 1,
                "title": "공지",
                "created_at": "2026-08-24T00:00:00+00:00",
            },
        ),
    )

    body = info_api.list_info_items()

    assert body["posts"][0]["title"] == "공지"


def test_create_info_item(monkeypatch: pytest.MonkeyPatch) -> None:
    install_fake_engine(monkeypatch)
    calls: list[dict[str, Any]] = []

    def fake_create(_connection, payload):
        calls.append(payload)
        return {"id": 1, "title": payload["title"], "body_html": "<p>본문</p>"}

    monkeypatch.setattr(info_api, "create_info_post", fake_create)

    body = info_api.create_info_item({"title": "새 글", "body_markdown": "본문"})

    assert calls == [{"title": "새 글", "body_markdown": "본문"}]
    assert body["post"]["id"] == 1


def test_get_info_item_returns_404(monkeypatch: pytest.MonkeyPatch) -> None:
    install_fake_engine(monkeypatch)
    monkeypatch.setattr(info_api, "get_info_post", lambda *_args: None)

    with pytest.raises(HTTPException) as exc_info:
        info_api.get_info_item(404)

    assert exc_info.value.status_code == 404


def test_info_routes_are_registered_without_mutation_routes() -> None:
    methods_by_path = {}
    for route in create_app().routes:
        if hasattr(route, "path") and hasattr(route, "methods"):
            methods_by_path.setdefault(route.path, set()).update(route.methods or set())
        if hasattr(route, "original_router"):
            for child in route.original_router.routes:
                methods_by_path.setdefault(child.path, set()).update(child.methods or set())

    assert "/api/info" in methods_by_path
    assert {"GET", "POST"}.issubset(methods_by_path["/api/info"])
    assert "/api/info/{info_id}" in methods_by_path
    assert "GET" in methods_by_path["/api/info/{info_id}"]
    assert "DELETE" not in methods_by_path["/api/info/{info_id}"]
    assert "PATCH" not in methods_by_path["/api/info/{info_id}"]
    assert "PUT" not in methods_by_path["/api/info/{info_id}"]

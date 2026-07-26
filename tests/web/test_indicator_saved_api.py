from __future__ import annotations

import pytest
from fastapi import HTTPException

from rural_basic_income.web.api import data as data_api
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
    monkeypatch.setattr(data_api, "get_engine", lambda: FakeEngine())


def test_list_saved_indicator_items(monkeypatch: pytest.MonkeyPatch) -> None:
    install_fake_engine(monkeypatch)
    monkeypatch.setattr(
        data_api,
        "list_saved_indicators",
        lambda _connection: (
            {
                "id": "indicator-1",
                "title": "인구 지표",
                "summary": {"table": "clean_population"},
            },
        ),
    )

    body = data_api.list_saved_indicator_items()

    assert body["saved"][0]["title"] == "인구 지표"


def test_create_saved_indicator_item(monkeypatch: pytest.MonkeyPatch) -> None:
    install_fake_engine(monkeypatch)
    calls = []

    def fake_create(_connection, payload):
        calls.append(payload)
        return {"id": "indicator-1", "title": payload["title"]}

    monkeypatch.setattr(data_api, "create_saved_indicator", fake_create)

    body = data_api.create_saved_indicator_item({"title": "저장"})

    assert calls == [{"title": "저장"}]
    assert body["saved"]["id"] == "indicator-1"


def test_get_saved_indicator_item_returns_404(monkeypatch: pytest.MonkeyPatch) -> None:
    install_fake_engine(monkeypatch)
    monkeypatch.setattr(data_api, "get_saved_indicator", lambda *_args: None)

    with pytest.raises(HTTPException) as exc_info:
        data_api.get_saved_indicator_item("00000000-0000-0000-0000-000000000001")

    assert exc_info.value.status_code == 404


def test_indicator_saved_routes_are_registered() -> None:
    paths = set()
    for route in create_app().routes:
        if hasattr(route, "path"):
            paths.add(route.path)
        if hasattr(route, "original_router"):
            paths.update(child.path for child in route.original_router.routes)

    assert "/api/indicators/saved" in paths
    assert "/api/indicators/saved/{saved_id}" in paths

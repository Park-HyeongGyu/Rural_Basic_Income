import pytest
from fastapi import HTTPException
from fastapi.routing import APIRoute

from rural_basic_income.db.connection import DatabaseUnavailable
import rural_basic_income.web.main as web_main
from rural_basic_income.web.main import create_app, live_health, ready_health


def test_live_health_payload() -> None:
    assert live_health() == {"status": "ok"}


def test_live_health_route_is_registered() -> None:
    app = create_app()
    routes = [
        route
        for route in app.routes
        if isinstance(route, APIRoute) and route.path == "/health/live"
    ]

    assert len(routes) == 1
    assert routes[0].methods == {"GET"}
    assert routes[0].endpoint is live_health


def test_ready_health_payload(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(web_main, "assert_database_ready", lambda: None)

    assert ready_health() == {"status": "ready"}


def test_ready_health_returns_503_when_database_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail_database_check() -> None:
        raise DatabaseUnavailable("database unavailable")

    monkeypatch.setattr(web_main, "assert_database_ready", fail_database_check)

    with pytest.raises(HTTPException) as exc_info:
        ready_health()

    assert exc_info.value.status_code == 503
    assert exc_info.value.detail == {
        "status": "not_ready",
        "reason": "database unavailable",
    }


def test_ready_health_route_is_registered() -> None:
    app = create_app()
    routes = [
        route
        for route in app.routes
        if isinstance(route, APIRoute) and route.path == "/health/ready"
    ]

    assert len(routes) == 1
    assert routes[0].methods == {"GET"}
    assert routes[0].endpoint is ready_health

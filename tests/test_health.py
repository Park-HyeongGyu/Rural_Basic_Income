from fastapi.routing import APIRoute

from rural_basic_income.web.main import create_app, live_health


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

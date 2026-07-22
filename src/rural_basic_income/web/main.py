from fastapi import FastAPI, HTTPException, status

from rural_basic_income import __version__
from rural_basic_income.db.connection import (
    DatabaseUnavailable,
    assert_database_ready,
)
from rural_basic_income.web.api.data import router as data_router


def live_health() -> dict[str, str]:
    return {"status": "ok"}


def ready_health() -> dict[str, str]:
    try:
        assert_database_ready()
    except DatabaseUnavailable as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"status": "not_ready", "reason": str(exc)},
        ) from exc

    return {"status": "ready"}


def create_app() -> FastAPI:
    app = FastAPI(
        title="Rural Basic Income Web",
        version=__version__,
    )

    app.add_api_route(
        "/health/live",
        live_health,
        methods=["GET"],
        tags=["health"],
    )
    app.add_api_route(
        "/health/ready",
        ready_health,
        methods=["GET"],
        tags=["health"],
    )
    app.include_router(data_router)

    return app


app = create_app()

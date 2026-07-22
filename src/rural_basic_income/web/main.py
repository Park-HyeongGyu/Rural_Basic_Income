from fastapi import FastAPI

from rural_basic_income import __version__


def live_health() -> dict[str, str]:
    return {"status": "ok"}


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

    return app


app = create_app()

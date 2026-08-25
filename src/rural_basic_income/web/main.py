from pathlib import Path
from functools import lru_cache
from hashlib import sha256

from fastapi import FastAPI, HTTPException, Request, status
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from rural_basic_income import __version__
from rural_basic_income.db.connection import (
    DatabaseUnavailable,
    assert_database_ready,
)
from rural_basic_income.web.api.analysis import router as analysis_router
from rural_basic_income.web.api.data import router as data_router
from rural_basic_income.web.api.info import router as info_router

WEB_DIR = Path(__file__).resolve().parent
STATIC_DIR = WEB_DIR / "static"
TEMPLATES_DIR = WEB_DIR / "templates"
templates = Jinja2Templates(directory=TEMPLATES_DIR)
STATIC_ASSETS = (
    "styles.css",
    "line_graph.js",
    "app.js",
    "analysis.js",
    "analysis_map.js",
    "info.js",
    "maps/sigungu_2023_4q.json",
    "maps/treatment_regions.json",
)


@lru_cache
def static_asset_versions() -> dict[str, str]:
    versions: dict[str, str] = {}
    for asset_name in STATIC_ASSETS:
        asset_path = STATIC_DIR / asset_name
        try:
            versions[asset_name] = sha256(asset_path.read_bytes()).hexdigest()[:12]
        except FileNotFoundError:
            versions[asset_name] = __version__
    return versions


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


def index(request: Request) -> HTMLResponse:
    return templates.TemplateResponse(
        request,
        "index.html",
        {
            "app_version": __version__,
            "static_versions": static_asset_versions(),
        },
    )


def create_app() -> FastAPI:
    app = FastAPI(
        title="Rural Basic Income Web",
        version=__version__,
    )

    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
    app.add_api_route(
        "/",
        index,
        methods=["GET"],
        response_class=HTMLResponse,
        include_in_schema=False,
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
    app.include_router(analysis_router)
    app.include_router(info_router)

    return app


app = create_app()

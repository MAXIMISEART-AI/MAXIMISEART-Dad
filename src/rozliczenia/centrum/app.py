"""Aplikacja HTTP Centrum rozliczeń: API pod ``/api`` i zbudowany frontend pod ``/``.

Każda grupa zasobów ma własny router (``settings_router``, ``periods_router``,
``configuration_router``);
``create_app`` składa je, pilnuje nagłówków ``Host`` i ``Origin`` (ADR 0004) i
zamienia odmowy (``contract.Refusal``) na bezpieczne odpowiedzi ``Problem``.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, MutableMapping
from datetime import date
from pathlib import Path
from typing import Any, Final
from urllib.parse import urlsplit

from fastapi import FastAPI, Request, Response
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from rozliczenia.centrum.configuration import ConfigurationFiles, configuration_router
from rozliczenia.centrum.contract import Health, Problem, Refusal
from rozliczenia.centrum.metrics import MetricsFiles, metrics_router
from rozliczenia.centrum.period_board import periods_router
from rozliczenia.centrum.platform import Platform
from rozliczenia.centrum.settings import SettingsStore, settings_router
from rozliczenia.centrum.version import tool_version

SERVICE: Final = "centrum-rozliczen"
STATIC_DIRECTORY = Path(__file__).resolve().parent / "static"
_LOCAL_HOSTNAMES = frozenset({"127.0.0.1", "localhost"})
_SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})


def create_app(
    *,
    settings_path: Path,
    platform: Platform,
    today: Callable[[], date] = date.today,
    metrics_files: MetricsFiles | None = None,
    configuration_files: ConfigurationFiles | None = None,
) -> FastAPI:
    # Bez /docs i /openapi.json: kontrakt eksportuje tools/export_openapi.py, a Swagger ładowałby skrypty z sieci.
    app = FastAPI(title="Centrum rozliczeń", version="kontrakt", docs_url=None, redoc_url=None, openapi_url=None)

    @app.middleware("http")
    async def only_local_browser(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        host = request.headers.get("host", "")
        if urlsplit(f"//{host}").hostname not in _LOCAL_HOSTNAMES:
            return _problem(403, "Centrum rozliczeń odpowiada tylko na adres tego komputera.")
        if request.method not in _SAFE_METHODS and request.headers.get("origin") != f"http://{host}":
            return _problem(403, "Tę akcję można wykonać tylko z karty Centrum rozliczeń.")
        return await call_next(request)

    @app.exception_handler(Refusal)
    async def refused(request: Request, refusal: Refusal) -> Response:
        return _problem(refusal.status_code, refusal.message)

    @app.get("/api/health", operation_id="getHealth")
    def health() -> Health:
        return Health(service=SERVICE, version=tool_version())

    store = SettingsStore(settings_path)
    app.include_router(settings_router(store, platform))
    app.include_router(periods_router(store, platform, today))
    app.include_router(metrics_router(metrics_files or MetricsFiles.of_cli(), today))
    app.include_router(configuration_router(configuration_files or ConfigurationFiles.default()))
    if STATIC_DIRECTORY.is_dir():  # bez buildu (np. świeży katalog roboczy frontendu) działa samo API
        app.mount("/", _Frontend(directory=STATIC_DIRECTORY, html=True), name="frontend")
    return app


def _problem(status_code: int, message: str) -> Response:
    return JSONResponse(Problem(message=message).model_dump(), status_code=status_code)


class _Frontend(StaticFiles):
    """Zbudowany frontend: pliki z hashem w nazwie są stałe, ``index.html`` zawsze świeży po ``git pull``."""

    async def get_response(self, path: str, scope: MutableMapping[str, Any]) -> Response:
        response = await super().get_response(path, scope)
        immutable = path.startswith("assets/")
        response.headers["Cache-Control"] = "public, max-age=31536000, immutable" if immutable else "no-cache"
        return response

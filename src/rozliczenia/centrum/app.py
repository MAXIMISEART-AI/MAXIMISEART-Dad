"""Aplikacja HTTP Centrum rozliczeń: API pod ``/api`` i zbudowany frontend pod ``/``.

Każda grupa zasobów ma własny router (``settings_router``, ``periods_router``,
``runs_router``, ``repair_router``, ``metrics_router``, ``configuration_router``,
``tool_update_router``, ``shutdown_router``, ``timing_router``);
``create_app`` składa je, pilnuje nagłówków ``Host`` i ``Origin`` (ADR 0004),
zamienia odmowy (``contract.Refusal``) i folder okresów, którego nie da się odczytać, na bezpieczne
odpowiedzi ``Problem``,
nieoczekiwany wyjątek na wpis w dzienniku Centrum i odpowiedź bez treści wyjątku,
a każdej odpowiedzi API dodaje czas obsługi w ``Server-Timing`` (``timing``).
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Awaitable, Callable, MutableMapping
from contextlib import asynccontextmanager
from datetime import date
from pathlib import Path
import time
from typing import Any
import uuid
from urllib.parse import urlsplit

from fastapi import FastAPI, Request, Response
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from rozliczenia.centrum.cloud_files import CloudFiles
from rozliczenia.centrum.configuration import ConfigurationFiles, configuration_router
from rozliczenia.centrum.contract import Health, Problem, Refusal
from rozliczenia.centrum.diagnosis import Surroundings, diagnose
from rozliczenia.centrum.log import CentrumLog
from rozliczenia.centrum.metrics import MetricsFiles, metrics_router
from rozliczenia.centrum.period_board import periods_router
from rozliczenia.centrum.platform import Platform
from rozliczenia.centrum.report_box import GitHubReportBox, ReportBox
from rozliczenia.centrum.reports import Reports, repair_router
from rozliczenia.centrum.preparation_run import PreparationEntry
from rozliczenia.centrum.run_origins import CENTRUM_RUNS_FILE, CentrumRuns
from rozliczenia.centrum.runs import RunHost, runs_router
from rozliczenia.centrum.settings import settings_router
from rozliczenia.settings import SettingsStore
from rozliczenia.centrum.settlement_run import SettlementEntry
from rozliczenia.centrum.shutdown import Shutdown, shutdown_router
from rozliczenia.centrum.stops import Stops
from rozliczenia.centrum.timing import server_timing, timing_router
from rozliczenia.centrum.tool_freshness import ToolFreshness
from rozliczenia.centrum import restart_guardian
from rozliczenia.centrum.tool_update import RESULT_FILE, ToolClone
from rozliczenia.centrum.tool_updates import GuardianLauncher, ToolUpdates, tool_update_router
from rozliczenia.centrum.version import SERVICE, short_commit
from rozliczenia.period_folder import PeriodFolderInaccessible

STATIC_DIRECTORY = Path(__file__).resolve().parent / "static"
_LOCAL_HOSTNAMES = frozenset({"127.0.0.1", "localhost"})
_SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})


def create_app(
    *,
    settings_path: Path,
    platform: Platform,
    log: CentrumLog,
    shutdown: Shutdown,
    today: Callable[[], date] = date.today,
    metrics_files: MetricsFiles | None = None,
    configuration_files: ConfigurationFiles | None = None,
    tool_freshness: ToolFreshness | None = None,
    cloud_files: CloudFiles | None = None,
    report_box: ReportBox | None = None,
    clock: Callable[[], float] = time.monotonic,
    tool_update: ToolClone | None = None,
    guardian: GuardianLauncher | None = None,
) -> FastAPI:
    @asynccontextmanager
    async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
        # Powiadomienie o naprawie: pierwsze pytanie skrzynki przy starcie, nie dopiero przy wejściu na Okresy.
        reports.check_repairs_in_background()
        yield

    # Bez /docs i /openapi.json: kontrakt eksportuje tools/export_openapi.py, a Swagger ładowałby skrypty z sieci.
    app = FastAPI(
        title="Centrum rozliczeń",
        version="kontrakt",
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
        lifespan=lifespan,
    )

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

    @app.middleware("http")
    async def unexpected_failure(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        try:
            return await call_next(request)
        except Exception as failure:  # noqa: BLE001 - granica API: typ wyjątku trafia do dziennika Centrum
            route = request.scope.get("route")
            log.unexpected_failure(failure, where=f"{request.method} {getattr(route, 'path', 'poza API')}")
            return _problem(500, "W Centrum rozliczeń wystąpił nieoczekiwany błąd. Odśwież kartę i spróbuj ponownie.")

    # Ostatni dodany middleware jest zewnętrzny: czas obejmuje też odmowy Host/Origin i nieoczekiwane wyjątki.
    app.middleware("http")(server_timing)

    @app.exception_handler(Refusal)
    async def refused(request: Request, refusal: Refusal) -> Response:
        return _problem(refusal.status_code, refusal.message)

    @app.exception_handler(PeriodFolderInaccessible)
    async def inaccessible_folder(request: Request, inaccessible: PeriodFolderInaccessible) -> Response:
        return _problem(
            500,
            f"Nie udało się odczytać folderu {inaccessible.folder.name}. "
            "Sprawdź, czy otwiera się w Eksploratorze plików i czy OneDrive działa, potem odśwież kartę.",
        )

    # Każdy start Centrum ma własny identyfikator: karta po aktualizacji rozpozna po nim nowe Centrum.
    instance = uuid.uuid4().hex

    @app.get("/api/health", operation_id="getHealth")
    def health() -> Health:
        return Health(service=SERVICE, commit=_short(surroundings.tool_freshness.local()), instance=instance)

    store = SettingsStore(settings_path)
    app.include_router(settings_router(store, platform))
    app.include_router(periods_router(store, platform, today))
    metrics = metrics_files or MetricsFiles.default()
    configuration = configuration_files or ConfigurationFiles.default()
    # Uruchomienia z Centrum we własnym dzienniku obok ustawień; schemat metryk się nie zmienia.
    centrum_runs = CentrumRuns(settings_path.parent / CENTRUM_RUNS_FILE)
    # Diagnoza: commit `main` z GitHuba i atrybuty OneDrive to granice komputera taty, podstawiane w testach.
    surroundings = Surroundings(tool_freshness or ToolFreshness.of_system(), cloud_files or CloudFiles.of_system())
    # Zgłoszenia do Maksa: skrzynka obok platformy, klucz i stan wysłanych obok Ustawień taty (ADR 0007).
    reports = Reports(
        settings_path.parent, report_box or GitHubReportBox(), log, surroundings.tool_freshness.local, clock=clock
    )
    # Jedno Uruchomienie procesu albo Aktualizacja narzędzia naraz; w ich trakcie zamknięcie Centrum jest odrzucone.
    stops = Stops(
        reports,
        lambda process, period: diagnose(
            process, period, settings=store.load(), configuration=configuration, log=log, surroundings=surroundings
        ),
        log,
    )
    runs = RunHost(log, centrum_runs, stops)
    shutdown.refuse_while(runs.shutdown_refusal)
    # Klon narzędzia, które Centrum aktualizuje (ADR 0009); w testach klon z lokalnym „origin”. Po sukcesie
    # opiekun ponownego startu zostawia wynik obok Ustawień taty, a to Centrum odczytuje go teraz, raz.
    updates = ToolUpdates(
        lambda: tool_update or ToolClone.of_system(),
        runs,
        log,
        surroundings.tool_freshness.local,
        reports,
        shutdown=shutdown,
        guardian=guardian or (lambda copy, restart: restart_guardian.launch(copy, restart)),
        result_file=settings_path.parent / RESULT_FILE,
    )
    preparation = PreparationEntry(store, configuration, metrics.preparation, today)
    settlement = SettlementEntry(store, configuration, metrics.settlement, today)
    app.include_router(runs_router(runs, [preparation, settlement]))
    app.include_router(repair_router(reports))
    app.include_router(metrics_router(metrics, today, centrum_runs))
    app.include_router(configuration_router(configuration, surroundings.tool_freshness, reports.key_state, clock=clock))
    app.include_router(tool_update_router(updates))
    app.include_router(shutdown_router(shutdown))
    app.include_router(timing_router(log))
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


def _short(commit: str | None) -> str | None:
    return None if commit is None else short_commit(commit)

"""Start Centrum rozliczeń: skrót „Centrum rozliczeń” (``pythonw``, bez konsoli) albo launcher z konsolą.

Jedno Centrum na komputerze: gdy port jest zajęty, ``health`` rozstrzyga, czy
to własne Centrum tej samej wersji (wtedy tylko otwiera kartę), Centrum innej
wersji, czy inny program. Każdy błąd startu kończy się komunikatem w trzech
częściach: bez konsoli w natywnym okienku, z konsolą w konsoli, a fakt trafia
do dziennika Centrum. Przy imporcie moduł używa tylko biblioteki
standardowej, więc brak FastAPI albo uvicorn też staje się takim komunikatem.
"""

from __future__ import annotations

import argparse
from collections.abc import Sequence
import json
from pathlib import Path
import urllib.request
import webbrowser

from rozliczenia.centrum import start_problems
from rozliczenia.centrum.log import CentrumLog
from rozliczenia.centrum.platform import has_console, show_start_problem
from rozliczenia.centrum.start_problems import StartProblem
from rozliczenia.centrum.version import SERVICE

DEFAULT_PORT = 47811
LOG_PATH = Path(__file__).resolve().parents[3] / "logs" / "centrum-rozliczen.log"
_HEALTH_TIMEOUT_S = 5  # drugie kliknięcie skrótu może trafić na Centrum, które jeszcze startuje


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Uruchamia Centrum rozliczeń w przeglądarce.")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT, help="Port na 127.0.0.1.")
    parser.add_argument("--no-browser", action="store_true", help="Nie otwieraj karty w przeglądarce.")
    args = parser.parse_args(argv)
    log = CentrumLog(LOG_PATH)
    try:
        return _start(args.port, log, browser=not args.no_browser)
    except Exception as failure:
        log.unexpected_failure(failure, where="start")
        return _refuse(start_problems.unexpected_start_failure(), args.port, log)


def _start(port: int, log: CentrumLog, *, browser: bool) -> int:
    def open_tab(url: str) -> None:
        if browser:
            webbrowser.open(url)

    try:
        from rozliczenia.centrum.app import create_app
        from rozliczenia.centrum.platform import system_platform
        from rozliczenia.centrum.server import listen_locally, serve
        from rozliczenia.centrum.settings import default_settings_path
        from rozliczenia.centrum.shutdown import Shutdown
        from rozliczenia.centrum.version import tool_version
    except ModuleNotFoundError as missing:
        return _refuse(start_problems.missing_library(missing.name or "?"), port, log)

    url = f"http://127.0.0.1:{port}/"
    try:
        listener = listen_locally(port)
    except OSError:
        running = _running_centrum_version(url)
        if running == tool_version():
            log.already_running(port=port)
            _say(f"Centrum rozliczeń już działa: {url}")
            open_tab(url)
            return 0
        if running is None:
            return _refuse(start_problems.port_taken(port), port, log)
        open_tab(url)  # tata widzi starą kartę z przyciskiem „Zamknij Centrum rozliczeń”
        return _refuse(start_problems.other_version_running(port, running), port, log)

    def announce(address: str) -> None:
        _say(f"Centrum rozliczeń działa: {address}")
        open_tab(address)

    shutdown = Shutdown(log)
    app = create_app(settings_path=default_settings_path(), platform=system_platform(), log=log, shutdown=shutdown)
    return serve(app, listener=listener, on_ready=announce, shutdown=shutdown, log=log)


def _running_centrum_version(url: str) -> str | None:
    """Wersja Centrum, które odpowiada na tym adresie; ``None``, gdy odpowiada coś innego albo nic."""

    direct = urllib.request.build_opener(urllib.request.ProxyHandler({}))  # serwer proxy nie widzi 127.0.0.1 taty
    try:
        with direct.open(url + "api/health", timeout=_HEALTH_TIMEOUT_S) as response:
            health = json.load(response)
    except (OSError, ValueError):
        return None
    if not isinstance(health, dict) or health.get("service") != SERVICE:
        return None
    version = health.get("version")
    return version if isinstance(version, str) else None


def _refuse(problem: StartProblem, port: int, log: CentrumLog) -> int:
    log.start_failed(problem.code, port=port)
    if has_console():
        print(problem.text, flush=True)
    else:
        show_start_problem(start_problems.TITLE, problem.text)
    return 1


def _say(line: str) -> None:
    if has_console():
        print(line, flush=True)


"""Start Centrum rozliczeń: skrót „Centrum rozliczeń” (``pythonw``, bez konsoli) albo ``run_centrum.py`` z konsolą.

Jedno Centrum na komputerze: gdy port jest zajęty, ``health`` rozstrzyga, czy
to własne Centrum tej samej wersji (wtedy tylko otwiera kartę), Centrum innej
wersji, czy inny program. Każdy błąd startu kończy się komunikatem w trzech
częściach: bez konsoli w natywnym okienku, z konsolą w konsoli, a fakt trafia
do dziennika Centrum. Ponowny start po Aktualizacji narzędzia (``--bez-okienek``)
nie pokazuje okienka, tylko zapisuje fakt w dzienniku: tata widzi wtedy jeden
Komunikat, w karcie. Przy imporcie moduł używa tylko biblioteki
standardowej, więc brak FastAPI albo uvicorn też staje się takim komunikatem.

Skrót, który zajmie port i zastanie dziennik „Aktualizacja w toku”, kończy
Aktualizację narzędzia przerwaną wyłączeniem komputera: cofa klon do wersji
sprzed niej, zostawia dla karty wynik porażki nieoczekiwanej i startuje od
nowa w cofniętej wersji. Wtedy jeszcze nie wczytał niczego spoza biblioteki
standardowej, więc nowa wersja bez swoich bibliotek też da się cofnąć. Nie
cofa, dopóki opiekun ponownego startu może jeszcze kończyć aktualizację, ani
przy starcie nowej wersji przez samego opiekuna (``--bez-okienek``).
"""

from __future__ import annotations

import argparse
from collections.abc import Callable, Sequence
import functools
import json
import os
import socket
import subprocess
import sys
import time
import urllib.request
import webbrowser

from rozliczenia import TOOL_ROOT
from rozliczenia.centrum import start_problems
from rozliczenia.centrum.log import CentrumLog
from rozliczenia.centrum.platform import has_console, show_start_problem
from rozliczenia.centrum.tool_update import (
    RESULT_FILE,
    UNEXPECTED,
    InterruptedUpdate,
    ToolClone,
    UpdateResult,
    write_result,
)
from rozliczenia.centrum.version import SERVICE, tool_version
from rozliczenia.message import Message

DEFAULT_PORT = 47811
LOG_PATH = TOOL_ROOT / "logs" / "centrum-rozliczen.log"
_HEALTH_TIMEOUT_S = 5  # drugie kliknięcie skrótu może trafić na Centrum, które jeszcze startuje
_HOST = "127.0.0.1"  # wyłącznie ten komputer (ADR 0004)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Uruchamia Centrum rozliczeń w przeglądarce.")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT, help="Port na 127.0.0.1.")
    parser.add_argument("--no-browser", action="store_true", help="Nie otwieraj karty w przeglądarce.")
    parser.add_argument(
        "--bez-okienek",
        action="store_true",
        help="Błąd startu tylko do dziennika Centrum, bez natywnego okienka (ponowny start po aktualizacji).",
    )
    args = parser.parse_args(argv)
    log = CentrumLog(LOG_PATH)
    refuse = functools.partial(_refuse, port=args.port, log=log, dialog=not args.bez_okienek)
    restart_from_disk = [sys.executable, str(TOOL_ROOT / "run_centrum.py"), *(sys.argv[1:] if argv is None else argv)]
    try:
        return _start(
            args.port,
            log,
            refuse,
            browser=not args.no_browser,
            started_by_guardian=args.bez_okienek,
            restart_from_disk=restart_from_disk,
        )
    except Exception as failure:  # noqa: BLE001 - granica startu: typ wyjątku trafia do dziennika Centrum
        log.unexpected_failure(failure, where="start")
        return refuse(start_problems.unexpected_start_failure())


def _start(
    port: int,
    log: CentrumLog,
    refuse: Callable[[Message], int],
    *,
    browser: bool,
    started_by_guardian: bool,
    restart_from_disk: list[str],
) -> int:
    def open_tab(url: str) -> None:
        if browser:
            webbrowser.open(url)

    url = f"http://{_HOST}:{port}/"
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
            return refuse(start_problems.port_taken(port))
        open_tab(url)  # tata widzi starą kartę z przyciskiem „Zamknij Centrum rozliczeń”
        return refuse(start_problems.other_version_running(port, running))

    try:
        interrupted = None if started_by_guardian else ToolClone(TOOL_ROOT).interrupted_update()
        guardian_may_run = interrupted is not None and interrupted.guardian_may_run(time.time())
        if interrupted is not None and not guardian_may_run:
            _roll_back(interrupted)
    except BaseException:
        listener.close()
        raise
    if interrupted is not None:
        listener.close()
        if guardian_may_run:
            return refuse(start_problems.update_finishing())
        # Ten proces ma w pamięci moduły wersji, którą właśnie cofnął: Centrum startuje od nowa z dysku.
        return subprocess.call(restart_from_disk)

    try:
        from rozliczenia.centrum.app import create_app
        from rozliczenia.centrum.platform import system_platform
        from rozliczenia.centrum.server import serve
        from rozliczenia.settings import default_settings_path
        from rozliczenia.centrum.shutdown import Shutdown
    except ModuleNotFoundError as missing:
        listener.close()
        return refuse(start_problems.missing_library(missing.name or "?"))

    def announce(address: str) -> None:
        _say(f"Centrum rozliczeń działa: {address}")
        open_tab(address)

    shutdown = Shutdown(log)
    app = create_app(settings_path=default_settings_path(), platform=system_platform(), log=log, shutdown=shutdown)
    return serve(app, listener=listener, on_ready=announce, shutdown=shutdown, log=log)


def listen_locally(port: int) -> socket.socket:
    """Zajmuje port na ``127.0.0.1``; ``OSError``, gdy port ma już inny program albo inne Centrum."""

    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        if os.name != "nt":  # na Windows SO_REUSEADDR pozwoliłby przejąć port działającego programu
            listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        listener.bind((_HOST, port))
        listener.listen()  # kolejne uruchomienie czeka na health, zamiast dostać odmowę połączenia
    except OSError:
        listener.close()
        raise
    return listener


def _roll_back(interrupted: InterruptedUpdate) -> None:
    """Cofa przerwaną Aktualizację narzędzia; każda porażka to wyjątek, a dziennik zostaje na następny start.

    Plik wyniku od opiekuna mógł już mówić „ok”, a karta cofniętej wersji ma
    pokazać porażkę.
    """

    ToolClone(TOOL_ROOT).roll_back()
    write_result(TOOL_ROOT / "config" / RESULT_FILE, UpdateResult(UNEXPECTED, interrupted.before, interrupted.after))


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


def _refuse(problem: Message, *, port: int, log: CentrumLog, dialog: bool) -> int:
    """Komunikat startu w konsoli albo, bez konsoli, w natywnym okienku (``dialog``); fakt zawsze w dzienniku."""

    log.start_failed(problem.code, port=port)
    if has_console():
        print(problem.text, flush=True)
    elif dialog:
        show_start_problem(start_problems.TITLE, problem.text)
    return 1


def _say(line: str) -> None:
    if has_console():
        print(line, flush=True)


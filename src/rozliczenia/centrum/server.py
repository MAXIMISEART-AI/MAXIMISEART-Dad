"""Serwer Centrum rozliczeń: uvicorn na ``127.0.0.1`` do zamknięcia z karty Centrum albo Ctrl+C."""

from __future__ import annotations

from collections.abc import Callable
import logging
import socket
import threading

import uvicorn
from fastapi import FastAPI
from uvicorn.config import LOGGING_CONFIG

from rozliczenia.centrum.log import CentrumLog
from rozliczenia.centrum.platform import has_console
from rozliczenia.centrum.shutdown import Shutdown
from rozliczenia.centrum.version import tool_version

HOST = "127.0.0.1"  # wyłącznie ten komputer (ADR 0004)
_GRACEFUL_SHUTDOWN_S = 5  # otwarte połączenia (np. strumień postępu) nie wstrzymują zamknięcia dłużej


def serve(
    app: FastAPI,
    *,
    listener: socket.socket,
    on_ready: Callable[[str], None],
    shutdown: Shutdown,
    log: CentrumLog,
) -> int:
    """Obsługuje żądania do zamknięcia; ``on_ready`` dostaje adres, gdy serwer już odpowiada."""

    port = int(listener.getsockname()[1])
    url = f"http://{HOST}:{port}/"
    console = has_console()
    if not console:
        _silence_uvicorn()
    config = uvicorn.Config(
        app,
        log_level="info",
        access_log=False,
        timeout_graceful_shutdown=_GRACEFUL_SHUTDOWN_S,
        log_config=LOGGING_CONFIG if console else None,
    )

    def started() -> None:
        log.started(port=port, version=tool_version(), console=console)
        threading.Thread(target=on_ready, args=(url,), name="centrum-gotowosc", daemon=True).start()

    server = _Server(config, started=started)

    def stop_when_asked() -> None:
        shutdown.wait()
        server.should_exit = True

    threading.Thread(target=stop_when_asked, name="centrum-zamkniecie", daemon=True).start()
    try:
        server.run(sockets=[listener])
    except Exception as failure:  # noqa: BLE001 - granica serwera: typ wyjątku trafia do dziennika Centrum
        log.unexpected_failure(failure, where="serwer")
        return 1
    finally:
        listener.close()
        if server.started:
            log.stopped(port=port)
    return 0 if server.started else 1


class _Server(uvicorn.Server):
    """Uvicorn, który zgłasza gotowość zaraz po zajęciu portu, zanim obsłuży pierwsze żądanie."""

    def __init__(self, config: uvicorn.Config, *, started: Callable[[], None]) -> None:
        super().__init__(config)
        self._started = started

    async def startup(self, sockets: list[socket.socket] | None = None) -> None:
        await super().startup(sockets=sockets)
        if self.started:
            self._started()


def _silence_uvicorn() -> None:
    """Pod ``pythonw`` nie ma ``sys.stdout`` ani ``sys.stderr``: logi uvicorn nie mają dokąd trafić.

    Domyślna konfiguracja logów uvicorn pyta ``sys.stdout.isatty()`` i bez konsoli
    przerywa start. Bezpieczne fakty i tak trafiają do dziennika Centrum.
    """

    uvicorn_logger = logging.getLogger("uvicorn")
    uvicorn_logger.addHandler(logging.NullHandler())
    uvicorn_logger.propagate = False

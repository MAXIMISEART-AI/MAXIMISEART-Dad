"""Start Centrum rozliczeń: serwer na ``127.0.0.1`` i otwarcie karty w przeglądarce po gotowości."""

from __future__ import annotations

import argparse
import threading
import time
import webbrowser
from collections.abc import Callable, Sequence

import uvicorn
from fastapi import FastAPI

from rozliczenia.centrum.app import create_app
from rozliczenia.centrum.platform import system_platform
from rozliczenia.centrum.settings import default_settings_path

HOST = "127.0.0.1"  # wyłącznie ten komputer (ADR 0004)
DEFAULT_PORT = 47811


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Uruchamia Centrum rozliczeń w przeglądarce.")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT, help="Port na 127.0.0.1.")
    parser.add_argument("--no-browser", action="store_true", help="Nie otwieraj karty w przeglądarce.")
    args = parser.parse_args(argv)
    app = create_app(settings_path=default_settings_path(), platform=system_platform())

    def announce(url: str) -> None:
        print(f"Centrum rozliczeń działa: {url}", flush=True)
        if not args.no_browser:
            webbrowser.open(url)

    return serve(app, port=args.port, on_ready=announce)


def serve(app: FastAPI, *, port: int, on_ready: Callable[[str], None]) -> int:
    """Obsługuje żądania do zamknięcia (Ctrl+C); ``on_ready`` dostaje adres, gdy port jest już zajęty przez serwer."""

    server = uvicorn.Server(uvicorn.Config(app, host=HOST, port=port, log_level="info", access_log=False))

    def call_when_ready() -> None:
        while not server.started:
            if server.should_exit:
                return
            time.sleep(0.05)
        on_ready(f"http://{HOST}:{port}/")

    threading.Thread(target=call_when_ready, name="centrum-gotowosc", daemon=True).start()
    server.run()
    return 0 if server.started else 1

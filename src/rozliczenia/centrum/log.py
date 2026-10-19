"""Dziennik Centrum: lokalny plik z bezpiecznymi faktami o pracy serwera.

Każdy wpis to jedna linia: czas, nazwa zdarzenia i fakty ``klucz=wartość``.
Do dziennika trafiają tylko fakty wybrane tutaj (port, wersja, kod komunikatu,
nazwa typu wyjątku), nigdy tekst wyjątku, ścieżki z folderu okresów ani treść
wierszy (ADR 0004), więc można go przekazać osobie utrzymującej narzędzie.
Moduł używa tylko biblioteki standardowej, bo zapisuje też błędy startu, gdy
brakuje zależności.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
import threading


class CentrumLog:
    def __init__(self, path: Path) -> None:
        self._path = path
        self._lock = threading.Lock()

    def started(self, *, port: int, version: str, console: bool) -> None:
        self._write("start", port=port, wersja=version, konsola="tak" if console else "nie")

    def already_running(self, *, port: int) -> None:
        """Ponowne uruchomienie trafiło na działające Centrum tej samej wersji i tylko otworzyło kartę."""

        self._write("juz-dziala", port=port)

    def start_failed(self, code: str, *, port: int, **facts: str) -> None:
        self._write("blad-startu", kod=code, port=port, **facts)

    def shutdown_requested(self) -> None:
        self._write("zamkniecie", z="karta Centrum")

    def stopped(self, *, port: int) -> None:
        self._write("stop", port=port)

    def unexpected_failure(self, failure: BaseException, *, where: str) -> None:
        """Nieoczekiwany wyjątek: tylko nazwa typu i miejsce (np. trasa API), bez tekstu wyjątku."""

        self._write("nieoczekiwany-wyjatek", typ=type(failure).__name__, miejsce=where)

    def _write(self, event: str, **facts: str | int) -> None:
        moment = datetime.now().astimezone().isoformat(timespec="seconds")
        line = " ".join([moment, event, *(f"{key}={_quoted(value)}" for key, value in facts.items())])
        try:
            with self._lock:
                self._path.parent.mkdir(parents=True, exist_ok=True)
                with self._path.open("a", encoding="utf-8") as log:
                    log.write(line + "\n")
        except OSError:
            pass  # dziennik pomaga przy wsparciu; jego brak nie może zatrzymać Centrum


def _quoted(value: str | int) -> str:
    text = str(value)
    return f'"{text}"' if " " in text else text

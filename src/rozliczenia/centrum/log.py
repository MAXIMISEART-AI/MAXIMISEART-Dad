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

    def run_started(self, *, process: str, mode: str, period: str) -> None:
        """Początek Uruchomienia procesu z Centrum: klucz procesu, tryb i token okresu."""

        self._write("uruchomienie-start", proces=process, tryb=mode, okres=period)

    def run_finished(self, *, process: str, mode: str, period: str, result: str, ending: str) -> None:
        """Koniec Uruchomienia procesu z Centrum: wynik i sposób zakończenia, bez linii komunikatu."""

        self._write("uruchomienie-koniec", proces=process, tryb=mode, okres=period, wynik=result, koniec=ending)

    def unexpected_failure(self, failure: BaseException, *, where: str) -> None:
        """Nieoczekiwany wyjątek: tylko nazwa typu i miejsce (np. trasa API), bez tekstu wyjątku."""

        self._write("nieoczekiwany-wyjatek", typ=type(failure).__name__, miejsce=where)

    def diagnosed(self, *, process: str, period: str, cause: str) -> None:
        """Diagnoza Zatrzymania: klucz procesu, token okresu i kod Komunikatu wyjaśnienia."""

        self._write("diagnoza", proces=process, okres=period, przyczyna=cause)

    def report_sent(self, *, process: str, period: str, number: int) -> None:
        """Zgłoszenie do Maksa przyjęte przez skrzynkę Zgłoszeń jako issue ``number``; bez treści i klucza."""

        self._write("zgloszenie-wyslane", proces=process, okres=period, numer=number)

    def report_saved(self, *, process: str, period: str, code: str) -> None:
        """Zgłoszenia nie wysłano i czeka w pliku; ``code`` to kod Komunikatu przyczyny."""

        self._write("zgloszenie-zapisane", proces=process, okres=period, kod=code)

    def recent(self, limit: int) -> list[str]:
        """Najwyżej ``limit`` ostatnich wpisów od ostatniego startu Centrum; brak dziennika to brak wpisów."""

        try:
            with self._lock:
                lines = self._path.read_text(encoding="utf-8").splitlines()
        except OSError:
            return []
        starts = [index for index, line in enumerate(lines) if event_of(line) == "start"]
        session = lines[starts[-1] :] if starts else lines
        return session[-limit:]

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


def event_of(line: str) -> str:
    """Nazwa zdarzenia wpisu dziennika (drugie pole po czasie)."""

    fields = line.split(" ", 2)
    return fields[1] if len(fields) > 1 else ""


def _quoted(value: str | int) -> str:
    text = str(value)
    return f'"{text}"' if " " in text else text

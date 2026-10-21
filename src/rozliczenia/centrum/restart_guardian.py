"""Opiekun ponownego startu: po udanej Aktualizacji narzędzia uruchamia Centrum rozliczeń w nowej wersji (ADR 0009).

Centrum kopiuje ten moduł razem z ``tool_update`` do swojego katalogu
tymczasowego, zanim zmieni klon (``prepare``). Po sukcesie uruchamia opiekuna
odłączonym procesem bez konsoli (``launch``) i samo się zamyka. Opiekun działa
z kopii sprzed aktualizacji i używa tylko biblioteki standardowej (``main``):
zapisuje wynik aktualizacji obok Ustawień taty, czeka na zwolnienie portu,
startuje nową wersję jak skrót, tylko bez karty i bez okienek, i czeka, aż
odpowie w nowym commicie. Na końcu usuwa katalog tymczasowy aktualizacji.
"""

from __future__ import annotations

import argparse
from collections.abc import Sequence
from dataclasses import dataclass
import json
import os
from pathlib import Path
import shutil
import socket
import subprocess
import sys
import time
import urllib.request
from typing import Final

from rozliczenia.centrum.tool_update import UPDATED, UpdateResult, write_result

# Tyle czekają: stare Centrum na zamknięcie (otwarte połączenia karty do 5 s) i nowa wersja na pierwszą odpowiedź.
PORT_TIMEOUT_S: Final = 60.0
START_TIMEOUT_S: Final = 60.0
_POLL_S: Final = 0.2
_HOST: Final = "127.0.0.1"
_SERVICE: Final = "centrum-rozliczen"
_SOURCE: Final = Path(__file__).resolve().parents[2]
# Pakiet-szkielet kopii: tylko moduły bez bibliotek narzędzia, które opiekun importuje.
_COPIED: Final = (
    "rozliczenia/__init__.py",
    "rozliczenia/centrum/__init__.py",
    "rozliczenia/centrum/tool_update.py",
    "rozliczenia/centrum/restart_guardian.py",
)
_BOOT: Final = (
    "import sys; sys.path.insert(0, sys.argv[1]); "
    "from rozliczenia.centrum.restart_guardian import main; raise SystemExit(main(sys.argv[2:]))"
)
# Windows: proces bez konsoli, który przeżyje zamknięcie Centrum; gdzie indziej robi to osobna sesja.
_DETACHED: Final = getattr(subprocess, "DETACHED_PROCESS", 0) | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)


@dataclass(frozen=True)
class Restart:
    """Ponowny start po udanej aktualizacji.

    ``root`` to katalog narzędzia, ``result`` plik wyniku obok Ustawień taty,
    ``work`` katalog tymczasowy aktualizacji (kopia opiekuna i plików taty).
    """

    port: int
    before: str | None
    after: str
    root: Path
    result: Path
    installed: bool
    work: Path

    def arguments(self) -> list[str]:
        return [
            "--port",
            str(self.port),
            "--before",
            self.before or "",
            "--after",
            self.after,
            "--root",
            str(self.root),
            "--result",
            str(self.result),
            "--work",
            str(self.work),
            *(["--installed"] if self.installed else []),
        ]

    @classmethod
    def of_arguments(cls, argv: Sequence[str]) -> Restart:
        parser = argparse.ArgumentParser(description="Opiekun ponownego startu Centrum rozliczeń.")
        parser.add_argument("--port", type=int, required=True)
        parser.add_argument("--before", required=True)
        parser.add_argument("--after", required=True)
        parser.add_argument("--root", type=Path, required=True)
        parser.add_argument("--result", type=Path, required=True)
        parser.add_argument("--work", type=Path, required=True)
        parser.add_argument("--installed", action="store_true")
        args = parser.parse_args(argv)
        return cls(args.port, args.before or None, args.after, args.root, args.result, args.installed, args.work)


def prepare(work: Path) -> Path:
    """Kopiuje opiekuna z tej wersji narzędzia do ``work``, zanim aktualizacja zmieni klon; zwraca katalog kopii."""

    copy = work / "opiekun"
    for name in _COPIED:
        (copy / name).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(_SOURCE / name, copy / name)
    return copy


def launch(copy: Path, restart: Restart) -> subprocess.Popen[bytes]:
    """Uruchamia opiekuna z kopii ``copy`` odłączonym procesem bez konsoli, który przeżyje zamknięcie Centrum."""

    # -I: ani katalog roboczy, ani PYTHONPATH nie podsuną modułów spoza kopii; -B: kopia bez __pycache__.
    return _detached([_windowless_python(), "-I", "-B", "-c", _BOOT, str(copy), *restart.arguments()], restart.root)


def main(argv: Sequence[str]) -> int:
    restart = Restart.of_arguments(argv)
    # Nowe Centrum czyta wynik raz przy starcie, więc plik musi być gotowy, zanim ono wystartuje.
    write_result(restart.result, UpdateResult(UPDATED, restart.before, restart.after, restart.installed))
    if not _port_released(restart.port):
        return 1
    centrum = _detached(
        [
            sys.executable,
            str(restart.root / "run_centrum.py"),
            "--port",
            str(restart.port),
            "--no-browser",
            "--bez-okienek",
        ],
        restart.root,
    )
    if not _answers(centrum, restart.port, restart.after):
        return 1
    shutil.rmtree(restart.work, ignore_errors=True)
    return 0


def _windowless_python() -> str:
    """``pythonw.exe`` obok tego Pythona w Windows (bez okna konsoli, jak skrót); gdzie indziej ten sam Python."""

    windowless = Path(sys.executable).with_name("pythonw.exe")
    return str(windowless) if os.name == "nt" and windowless.is_file() else sys.executable


def _detached(command: list[str], cwd: Path) -> subprocess.Popen[bytes]:
    environment = {name: value for name, value in os.environ.items() if name != "PYTHONPATH"}
    return subprocess.Popen(
        command,
        cwd=cwd,
        env=environment,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        creationflags=_DETACHED,
        start_new_session=os.name != "nt",
    )


def _port_released(port: int) -> bool:
    """Czy stare Centrum zwolniło port w ``PORT_TIMEOUT_S`` (zajęcie go tak jak ``server.listen_locally``)."""

    deadline = time.monotonic() + PORT_TIMEOUT_S
    while True:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
            if os.name != "nt":
                probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            try:
                probe.bind((_HOST, port))
            except OSError:
                pass
            else:
                return True
        if time.monotonic() > deadline:
            return False
        time.sleep(_POLL_S)


def _answers(centrum: subprocess.Popen[bytes], port: int, commit: str) -> bool:
    """Czy nowe Centrum odpowiada w ``START_TIMEOUT_S`` jako Centrum rozliczeń w commicie ``commit``."""

    direct = urllib.request.build_opener(urllib.request.ProxyHandler({}))  # serwer proxy nie widzi 127.0.0.1 taty
    deadline = time.monotonic() + START_TIMEOUT_S
    while centrum.poll() is None and time.monotonic() < deadline:
        try:
            with direct.open(f"http://{_HOST}:{port}/api/health", timeout=2) as response:
                health = json.load(response)
        except (OSError, ValueError):
            health = None
        if isinstance(health, dict) and health.get("service") == _SERVICE and health.get("commit") == commit:
            return True
        time.sleep(_POLL_S)
    return False

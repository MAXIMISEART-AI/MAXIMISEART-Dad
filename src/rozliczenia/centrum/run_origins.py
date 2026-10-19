"""Które Uruchomienia procesu z plików metryk wystartowały z Centrum rozliczeń.

Schemat metryk się nie zmienia (CLI i Centrum dopisują te same rekordy), więc
Centrum zapisuje we własnym lokalnym pliku obok ustawień, poza gitem, proces i
dokładny ``started_at`` rekordu metryk, który dopisało jego Uruchomienie.
Metryki porównują po tej parze; reszta historii to launchery ``.cmd``.

Plik ma tylko bezpieczne fakty (proces i czas startu). Jego brak, uszkodzenie
albo nieudany zapis oznacza tylko, że Uruchomienie pokaże się jako ``.cmd``:
nigdy nie zmienia wyniku Uruchomienia ani metryk.
"""

from __future__ import annotations

import json
import threading
from datetime import datetime
from pathlib import Path
from typing import Final

from rozliczenia.centrum import contract
from rozliczenia.telemetry import MetricsStore

CENTRUM_RUNS_FILE: Final = "centrum-uruchomienia.jsonl"


class CentrumRuns:
    def __init__(self, path: Path) -> None:
        self._path = path
        self._lock = threading.Lock()

    def remember(self, process: contract.ProcessKey, metrics: MetricsStore, since: datetime, until: datetime) -> None:
        """Zapamiętuje rekordy metryk ``process``, które zaczęły się między ``since`` a ``until`` (czasy UTC).

        Centrum prowadzi jedno Uruchomienie naraz, więc w tym oknie jest jego rekord.
        Uruchomienie z ``.cmd`` w tym samym czasie też zostałoby oznaczone; to rzadkie i tylko kosmetyczne.
        """

        try:
            started = [
                record["started_at"]
                for record in metrics.read()
                if since <= datetime.fromisoformat(record["started_at"]) <= until
            ]
            if not started:
                return
            lines = "".join(json.dumps({"process": process, "started_at": value}) + "\n" for value in started)
            with self._lock:
                self._path.parent.mkdir(parents=True, exist_ok=True)
                with self._path.open("a", encoding="utf-8") as log:
                    log.write(lines)
        except (OSError, UnicodeError, ValueError):
            return

    def started(self) -> frozenset[tuple[str, str]]:
        """Pary (proces, ``started_at`` rekordu metryk) Uruchomień z Centrum; niepoprawne linie są pomijane."""

        try:
            text = self._path.read_text(encoding="utf-8")
        except (OSError, UnicodeError):
            return frozenset()
        pairs = set()
        for line in text.splitlines():
            try:
                entry = json.loads(line)
            except ValueError:
                continue
            if isinstance(entry, dict) and isinstance(entry.get("process"), str) and isinstance(
                entry.get("started_at"), str
            ):
                pairs.add((entry["process"], entry["started_at"]))
        return frozenset(pairs)

"""Karty Uruchomień z Logów Uruchomienia (ADR 0017): ostatnie Uruchomienie po starcie Centrum i karta wiersza Historii.

Przy każdym starcie Uruchomienia Centrum zapisuje jego bezpieczne fakty (identyfikator, proces, tryb, okres, start)
w jednym pliku obok dziennika, ``ostatnie-uruchomienie.json``, nadpisywanym przy następnym starcie i nigdy
nieusuwanym. Po starcie Centrum ostatnie Uruchomienie to ten start: gdy ma plik Logów, jego karta wraca z Logów;
gdy go nie ma, to Urwane Uruchomienie (Centrum zamknęło się w jego trakcie), bo Logi powstają przed końcem każdego
Uruchomienia, także przy Zatrzymaniu. Na końcu Uruchomienia ten moduł niczego nie zapisuje, więc nie ma kolejności względem działań po wyniku.

Karta z Logów niesie tylko to, co w nich jest: Komunikaty w trzech częściach, podsumowanie, etapy, sposób
zakończenia i Rodzaj Zatrzymania. Tytuł i akcję wylicza ta sama reguła co na żywo (``runs.verdict``), a tytuł
procesu i Gotowość jego deklaracja. Diagnozy i Zgłoszenia nie ma: żyją tylko przy Zatrzymaniu bieżącego
Uruchomienia tej pracy Centrum. Plik startu ma te same fakty co linia ``uruchomienie-start`` dziennika Centrum i
identyfikator Uruchomienia, więc reguła prywatności Logów obowiązuje bez zmian.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime
from pathlib import Path
import re
from typing import Final, Literal, TypeVar

from fastapi import APIRouter
from pydantic import BaseModel, ConfigDict

from rozliczenia.centrum import contract
from rozliczenia.centrum.atomic_file import replace_atomically
from rozliczenia.centrum.intermax_run import IntermaxEntry
from rozliczenia.centrum.run_logs import RunLog
from rozliczenia.centrum.preparation_run import PreparationEntry
from rozliczenia.centrum.runs import verdict
from rozliczenia.centrum.settlement_run import SettlementEntry

LAST_STARTED_FILE: Final = "ostatnie-uruchomienie.json"
# Identyfikator Uruchomienia z Centrum (``uuid4().hex``); inny nie ma Logów, więc nie dotyka dysku.
_RUN_ID: Final = re.compile(r"[0-9a-f]{32}")

_INTERRUPTED: Final = "Centrum rozliczeń zamknęło się w trakcie tego Uruchomienia, więc nie ma jego wyniku."
_PREVIEW_ADVICE: Final = "Podgląd niczego nie zapisał. Uruchom go ponownie."
_WRITE_ADVICE: Final = "Uruchom ponownie. Pliki okresu, które zdążyły powstać, Centrum zostawi i powie, co z nimi zrobić."

ModelT = TypeVar("ModelT", bound=BaseModel)


class StartedRun(BaseModel):
    """Plik ostatniego startu (schemat 1): te same fakty co nagłówek Logów Uruchomienia."""

    model_config = ConfigDict(extra="forbid")

    schema_version: Literal[1]
    run_id: str
    process: contract.ProcessKey
    mode: Literal["podgląd", "zapis"]
    period: str
    started_at: datetime


class RunCards:
    """Karty Uruchomień z dysku: ostatnie Uruchomienie sprzed startu Centrum i karta po identyfikatorze.

    ``logs`` to katalog Logów Uruchomienia, ``last_started`` plik ostatniego startu, a ``entries`` procesy Centrum,
    z których karta bierze tytuł procesu i deklarację procesu (Gotowość, tytuł wyniku po zapisie), jak przy starcie.
    """

    def __init__(
        self,
        logs: Path,
        last_started: Path,
        entries: Mapping[contract.ProcessKey, PreparationEntry | SettlementEntry | IntermaxEntry],
    ) -> None:
        self._logs = logs
        self._last_started = last_started
        self._entries = entries

    def run_started(self, info: contract.RunInfo, started_at: datetime) -> None:
        started = StartedRun(
            schema_version=1,
            run_id=info.id,
            process=info.process,
            mode="podgląd" if info.dry_run else "zapis",
            period=info.period,
            started_at=started_at,
        )
        replace_atomically(self._last_started, started.model_dump_json(indent=2) + "\n")

    def last(self) -> contract.PastRun | None:
        """Ostatnie Uruchomienie sprzed tego startu Centrum; ``None``: żadnego albo nie da się go odczytać."""

        started = _read(self._last_started, StartedRun)
        if started is None:
            return None
        path = self._logged(started.run_id)
        if path is None:
            return self._interrupted(started)
        record = _read(path, RunLog)
        # Logi są, ale nieczytelne: wynik był, tylko go nie znamy, więc to nie jest Urwane Uruchomienie.
        return None if record is None else self._restored(record)

    def card(self, run_id: str) -> contract.RunCard:
        """Karta Uruchomienia ``run_id`` z jego Logów; ``missing`` bez pliku Logów albo z plikiem, którego nie da się odczytać."""

        path = self._logged(run_id) if _RUN_ID.fullmatch(run_id) else None
        record = None if path is None else _read(path, RunLog)
        return contract.RunCardMissing(state="missing") if record is None else self._restored(record)

    def latest(self, process: contract.ProcessKey) -> contract.RunRestored | None:
        """Karta ostatniego Uruchomienia procesu ``process`` z Logów; ``None``: żadnego albo nie da się go odczytać.

        Nazwa pliku Logów zaczyna się sekundą startu w UTC, a po niej stoi klucz procesu, więc ostatnie pliki procesu
        są ostatnie w kolejności nazw; z tych z tej samej sekundy wygrywa późniejszy start w Logach.
        """

        try:
            names = sorted(path.name for path in self._logs.iterdir() if f"-{process}-" in path.name)
        except OSError:
            return None
        second = names[-1][:16] if names else None
        records = [_read(self._logs / name, RunLog) for name in names if name[:16] == second]
        read = [record for record in records if record is not None]
        return self._restored(max(read, key=lambda record: record.started_at)) if read else None

    def _logged(self, run_id: str) -> Path | None:
        """Plik Logów Uruchomienia ``run_id`` (nazwa kończy się identyfikatorem); ``None`` bez pliku albo katalogu."""

        suffix = f"-{run_id}.json"
        try:
            return next((path for path in self._logs.iterdir() if path.name.endswith(suffix)), None)
        except OSError:
            return None

    def _info(self, run_id: str, process: contract.ProcessKey, mode: str, period: str) -> contract.RunInfo:
        return contract.RunInfo(
            id=run_id,
            process=process,
            title=self._entries[process].process.name,
            period=period,
            dry_run=mode == "podgląd",
            confirms_readiness=self._entries[process].view.confirms_readiness,
            register_name=self._entries[process].view.register_name,
        )

    def _restored(self, record: RunLog) -> contract.RunRestored:
        info = self._info(record.run_id, record.process, record.mode, record.period)
        headline, next_action = verdict(
            ending=record.ending,
            stop_kind=record.stop_kind,
            result=record.result,
            dry_run=info.dry_run,
            view=self._entries[info.process].view,
        )
        messages = {
            kind: [
                contract.Message(what=message.what, where=message.where, action=message.action)
                for message in record.messages
                if message.kind == kind
            ]
            for kind in ("stop", "warning")
        }
        return contract.RunRestored(
            state="restored",
            run=info,
            started_at=record.started_at,
            phases=record.phases,
            result=contract.LoggedOutcome(
                result=record.result,
                headline=headline,
                ending=record.ending,
                next_action=next_action,
                stop_kind=record.stop_kind,
                stops=messages["stop"],
                warnings=messages["warning"],
                technical_notes=record.technical_notes,
                summary=record.summary,
            ),
        )

    def _interrupted(self, started: StartedRun) -> contract.RunInterrupted:
        info = self._info(started.run_id, started.process, started.mode, started.period)
        return contract.RunInterrupted(
            state="interrupted",
            run=info,
            started_at=started.started_at,
            advice=contract.Message(
                what=_INTERRUPTED,
                where=f"{info.title}, okres {info.period}",
                action=_PREVIEW_ADVICE if info.dry_run else _WRITE_ADVICE,
            ),
        )


def _read(path: Path, model: type[ModelT]) -> ModelT | None:
    """Model z pliku JSON; ``None``, gdy pliku nie ma albo nie da się go odczytać (zły JSON, schemat, kodowanie)."""

    try:
        return model.model_validate_json(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def run_cards_router(cards: RunCards) -> APIRouter:
    router = APIRouter(prefix="/api/runs", tags=["uruchomienia"])

    # Brak karty to zwykła odpowiedź, nie 404: przeglądarka nie odróżniłaby go od porażki odczytu.
    @router.get("/{run_id}/card", operation_id="getRunCard")
    def card(run_id: str) -> contract.RunCard:
        return cards.card(run_id)

    return router

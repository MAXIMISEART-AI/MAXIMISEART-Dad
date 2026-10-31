"""Uporządkowanie INTERMAX z Centrum rozliczeń: karta poza okresami, wejście procesu z Ustawień taty i start.

INTERMAX to Rejestr zleceń z Ustawień taty, a Kopie INTERMAX trafiają do folderu narzędzia. Proces nie należy do
okresu: okres Uruchomienia to okres dzisiejszej daty z zegara procesu, ustalony przy starcie (ADR 0019), więc
Logi Uruchomienia trafiają do Skrzynki Zgłoszeń przy tym okresie, także przy Zatrzymaniu przed odczytem.

Konfiguracja wymienia Kopie INTERMAX z tego folderu i przywraca wybraną (``intermax_restore.restore``). Przywrócenie
zajmuje w ``RunHost`` miejsce „jedno naraz”, bo podmienia INTERMAX, więc nie biegnie obok Uporządkowania INTERMAX.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Final

from fastapi import APIRouter

from rozliczenia.centrum import contract
from rozliczenia.centrum.catalog import INTERMAX
from rozliczenia.centrum.configuration import InputWorkbook, open_in_excel
from rozliczenia.centrum.processes import Processes
from rozliczenia.centrum.runs import PreparedRun, RunHost
from rozliczenia import intermax_copies, intermax_messages, intermax_restore
from rozliczenia.intermax_copies import Copy
from rozliczenia.intermax_replace import Disk, Waiting
from rozliczenia.intermax_process import OrderingInputs
from rozliczenia.message import StopError
from rozliczenia.settings import Settings, SettingsStore

_VIEW: Final = INTERMAX.view


@dataclass(frozen=True)
class IntermaxEntry:
    """Adapter startu Uporządkowania INTERMAX: rdzenie procesów, folder Kopii INTERMAX i zegar procesu.

    ``waiting``: zegar Centrum i jego przerwa dla krótkiej ponownej próby podmiany, której odmawia OneDrive, a
    ``disk`` kroki podmiany INTERMAX na dysku, te same dla Uporządkowania i przywrócenia Kopii.
    """

    store: SettingsStore
    processes: Processes
    copies_directory: Path
    now: Callable[[], datetime]
    waiting: Waiting
    disk: Disk

    @property
    def key(self) -> contract.ProcessKey:
        return INTERMAX.key

    def setup(self, last: contract.RunRestored | None) -> contract.IntermaxSetup:
        """Karta przed startem z ostatnim Uporządkowaniem INTERMAX ``last`` z Logów Uruchomienia."""

        settings = self.store.load()
        register = settings.register
        return contract.IntermaxSetup(
            title=INTERMAX.title,
            reminder=_VIEW.reminder,
            blocker=INTERMAX.settings_blocker(settings),
            open_in_excel=[] if register is None else open_in_excel([InputWorkbook("INTERMAX", register, "data_file")]),
            last=last,
        )

    def prepare(self) -> PreparedRun[Any, Any]:
        """Wejście procesu z Ustawień taty; ``contract.Refusal``, gdy Rejestr zleceń nie jest wskazany."""

        register = _register(self.store.load())
        inputs = OrderingInputs(register, self.copies_directory, now=self.now, waiting=self.waiting, disk=self.disk)
        return PreparedRun(
            declaration=INTERMAX, period=inputs.period, process=INTERMAX.core(self.processes), inputs=inputs
        )

    def copies(self) -> contract.IntermaxCopies:
        """Kopie INTERMAX od najnowszej albo Komunikat, gdy folderu Kopii nie da się odczytać."""

        try:
            listed = intermax_copies.listed(self.copies_directory)
        except OSError:
            problem = intermax_messages.copies_unreadable(self.copies_directory)
            return contract.IntermaxCopies(copies=[], problem=contract.Message.of(problem))
        return contract.IntermaxCopies(copies=[_copy(copy) for copy in listed], problem=None)

    def restore(self, name: str) -> contract.IntermaxRestore:
        """Przywraca Kopię INTERMAX ``name`` do INTERMAX z Ustawień taty; ``contract.Refusal``, gdy go nie wskazano."""

        register = _register(self.store.load())
        try:
            restored = intermax_restore.restore(
                name, register, self.copies_directory, now=self.now, waiting=self.waiting, disk=self.disk
            )
        except StopError as stop:
            return contract.IntermaxRestoreRefused(state="refused", message=contract.Message.of(stop.message))
        return contract.IntermaxRestored(
            state="restored",
            restored=_copy(restored.restored),
            previous=_copy(restored.previous),
            warnings=[contract.Message.of(warning) for warning in restored.warnings],
        )


def _copy(copy: Copy) -> contract.IntermaxCopy:
    return contract.IntermaxCopy(
        name=copy.path.name, taken_at=copy.moment.astimezone(timezone.utc), before=copy.before
    )


def _register(settings: Settings) -> Path:
    return INTERMAX.required_paths(settings)["register"]


def intermax_router(
    host: RunHost, entry: IntermaxEntry, last: Callable[[], contract.RunRestored | None]
) -> APIRouter:
    router = APIRouter(prefix="/api/intermax", tags=["uruchomienia"])

    @router.get("", operation_id="getIntermaxSetup")
    def setup() -> contract.IntermaxSetup:
        return entry.setup(last())

    @router.post("/run", operation_id="startIntermax", responses=contract.NOT_FOUND_OR_CONFLICT)
    def start() -> contract.RunView:
        return host.start(entry.prepare())

    return router


def intermax_copies_router(host: RunHost, entry: IntermaxEntry) -> APIRouter:
    """Kopie INTERMAX w Konfiguracji: lista od najnowszej i przywrócenie wybranej."""

    router = APIRouter(prefix="/api/intermax/copies", tags=["konfiguracja"])

    @router.get("", operation_id="getIntermaxCopies")
    def copies() -> contract.IntermaxCopies:
        return entry.copies()

    @router.post("/restore", operation_id="restoreIntermaxCopy", responses={409: {"model": contract.Problem}})
    def restore(request: contract.IntermaxRestoreRequest) -> contract.IntermaxRestore:
        host.begin_restore()
        try:
            return entry.restore(request.name)
        finally:
            host.end_restore()

    return router

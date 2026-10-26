"""Uporządkowanie INTERMAX z Centrum rozliczeń: karta poza okresami, wejście procesu z Ustawień taty i start.

INTERMAX to Rejestr zleceń z Ustawień taty, a Kopie INTERMAX trafiają do folderu narzędzia. Proces nie należy do
okresu: okres Uruchomienia to okres dzisiejszej daty z zegara procesu, ustalony przy starcie (ADR 0019), więc
Logi Uruchomienia trafiają do Skrzynki Zgłoszeń przy tym okresie, także przy Zatrzymaniu przed odczytem.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Final

from fastapi import APIRouter

from rozliczenia.centrum import contract, run_view
from rozliczenia.centrum.configuration import InputWorkbook, open_in_excel
from rozliczenia.centrum.runs import PreparedRun, RunHost
from rozliczenia.intermax_file import Waiting
from rozliczenia.intermax_ordering import OrderingSummary
from rozliczenia.intermax_process import OrderingInputs
from rozliczenia.process_run import Process
from rozliczenia.settings import Settings, SettingsStore

_KEY: Final[contract.ProcessKey] = "intermax"
_VIEW: Final = run_view.INTERMAX
_NO_REGISTER: Final = "Najpierw wskaż INTERMAX."


@dataclass(frozen=True)
class IntermaxEntry:
    """Uporządkowanie INTERMAX jako proces uruchamiany z Centrum: rdzeń, folder Kopii INTERMAX i zegar procesu.

    ``waiting``: zegar Centrum i jego przerwa dla krótkiej ponownej próby podmiany, której odmawia OneDrive.
    """

    store: SettingsStore
    process: Process[OrderingInputs, OrderingSummary]
    copies_directory: Path
    now: Callable[[], datetime]
    waiting: Waiting

    @property
    def key(self) -> contract.ProcessKey:
        return _KEY

    @property
    def view(self) -> run_view.ProcessView[Any, Any]:
        return _VIEW

    def setup(self, last: contract.RunRestored | None) -> contract.IntermaxSetup:
        """Karta przed startem z ostatnim Uporządkowaniem INTERMAX ``last`` z Logów Uruchomienia."""

        register = self.store.load().register
        return contract.IntermaxSetup(
            title=self.process.name,
            reminder=_VIEW.reminder,
            blocker=None if register is not None else _NO_REGISTER,
            open_in_excel=[] if register is None else open_in_excel([InputWorkbook("INTERMAX", register, "data_file")]),
            last=last,
        )

    def prepare(self) -> PreparedRun[Any, Any]:
        """Wejście procesu z Ustawień taty; ``contract.Refusal``, gdy Rejestr zleceń nie jest wskazany."""

        register = _register(self.store.load())
        inputs = OrderingInputs(register, self.copies_directory, now=self.now, waiting=self.waiting)
        return PreparedRun(key=_KEY, period=inputs.period, process=self.process, inputs=inputs, view=self.view)


def _register(settings: Settings) -> Path:
    if settings.register is None:
        raise contract.Refusal(409, _NO_REGISTER)
    return settings.register


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

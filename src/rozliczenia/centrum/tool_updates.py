"""Aktualizacja narzędzia z Centrum rozliczeń: akcja karty, krok i wynik dla przeglądarki (ADR 0009).

Samą aktualizację robi ``tool_update.ToolClone.update``; ten moduł prowadzi ją
w Centrum. Zajmuje miejsce „jedno naraz” w ``RunHost`` (odmowy 409 w trakcie
Uruchomienia procesu albo innej aktualizacji), odpowiada od razu i prowadzi
aktualizację w osobnym wątku, a karta odczytuje krok i wynik. Dziennik Centrum
dostaje start i koniec z commitem przed i po, bez ścieżek i bez wyjścia Gita.
Każdą porażkę, której ``tool_update`` nie przewidział, karta widzi jako
Komunikat nieoczekiwanej porażki, a dziennik tylko nazwę typu wyjątku.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
import shutil
import tempfile
import threading

from fastapi import APIRouter

from rozliczenia.centrum import contract, update_messages
from rozliczenia.centrum.log import CentrumLog
from rozliczenia.centrum.runs import RunHost
from rozliczenia.centrum.tool_freshness import CommitSource
from rozliczenia.centrum.tool_update import UNEXPECTED, UP_TO_DATE, UPDATED, Step, ToolClone, UpdateResult


class ToolUpdates:
    """Aktualizacja narzędzia tego Centrum: najwyżej jedna naraz, a po niej jej wynik.

    ``clone`` daje klon narzędzia przy każdym kliknięciu, nie przy starcie
    Centrum (test bez podstawionego klonu kończy się dopiero na akcji), a
    ``commit`` to commit narzędzia przed aktualizacją, tak jak widzi go Diagnoza.
    """

    def __init__(self, clone: Callable[[], ToolClone], runs: RunHost, log: CentrumLog, commit: CommitSource) -> None:
        self._clone = clone
        self._runs = runs
        self._log = log
        self._commit = commit
        self._lock = threading.Lock()
        self._view: contract.ToolUpdate = contract.ToolUpdateIdle(state="idle")

    def current(self) -> contract.ToolUpdate:
        with self._lock:
            return self._view

    def start(self) -> contract.ToolUpdate:
        """Zaczyna aktualizację w tle i od razu zwraca jej pierwszy krok; ``contract.Refusal``, gdy coś trwa."""

        clone = self._clone()
        self._runs.begin_update()
        before = self._commit()
        self._log.update_started(before=before)
        first = contract.ToolUpdateRunning(state="running", step="fetching")
        with self._lock:
            self._view = first
        threading.Thread(target=self._update, args=(clone, before), name="aktualizacja-narzedzia", daemon=True).start()
        return first

    def _update(self, clone: ToolClone, before: str | None) -> None:
        try:
            result = self._result(clone, before)
            self._log.update_finished(
                result=result.code, before=result.before, after=result.after, installed=result.installed
            )
            with self._lock:
                self._view = _view_of(result)
        finally:
            self._runs.end_update()

    def _result(self, clone: ToolClone, before: str | None) -> UpdateResult:
        try:
            backup = Path(tempfile.mkdtemp(prefix="centrum-aktualizacja-"))
            try:
                return clone.update(backup, self._show_step)
            finally:
                shutil.rmtree(backup, ignore_errors=True)
        except Exception as failure:  # noqa: BLE001 - granica wątku: typ wyjątku trafia do dziennika Centrum
            self._log.unexpected_failure(failure, where="aktualizacja narzędzia")
            return UpdateResult(UNEXPECTED, before, None)

    def _show_step(self, step: Step) -> None:
        with self._lock:
            self._view = contract.ToolUpdateRunning(state="running", step=step)


def _view_of(result: UpdateResult) -> contract.ToolUpdate:
    if result.code == UPDATED and result.after is not None:
        return contract.ToolUpdateUpdated(state="updated", commit=result.after[:7])
    if result.code == UP_TO_DATE:
        return contract.ToolUpdateUpToDate(state="up_to_date")
    message = update_messages.message_of(result.code)
    return contract.ToolUpdateFailed(state="failed", message=contract.Message.of(message))


def tool_update_router(updates: ToolUpdates) -> APIRouter:
    router = APIRouter(prefix="/api/tool-update", tags=["aktualizacja"])

    @router.post("", operation_id="startToolUpdate", status_code=202, responses={409: {"model": contract.Problem}})
    def start() -> contract.ToolUpdate:
        return updates.start()

    @router.get("", operation_id="getToolUpdate")
    def current() -> contract.ToolUpdate:
        return updates.current()

    return router

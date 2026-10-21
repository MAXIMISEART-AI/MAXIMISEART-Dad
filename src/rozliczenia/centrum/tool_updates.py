"""Aktualizacja narzędzia z Centrum rozliczeń: akcja karty, krok i wynik dla przeglądarki (ADR 0009).

Samą aktualizację robi ``tool_update.ToolClone.update``; ten moduł prowadzi ją
w Centrum. Zajmuje miejsce „jedno naraz” w ``RunHost`` (odmowy 409 w trakcie
Uruchomienia procesu albo innej aktualizacji), odpowiada od razu i prowadzi
aktualizację w osobnym wątku, a karta odczytuje krok i wynik. Dziennik Centrum
dostaje start i koniec z commitem przed i po, bez ścieżek i bez wyjścia Gita.
Każdą porażkę, której ``tool_update`` nie przewidział, karta widzi jako
Komunikat nieoczekiwanej porażki, a dziennik tylko nazwę typu wyjątku. Przy
każdej porażce karta dostaje też Zgłoszenie do Maksa z faktami dziennika.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import replace
from pathlib import Path
import shutil
import tempfile
import threading

from fastapi import APIRouter

from rozliczenia.centrum import contract, update_messages
from rozliczenia.centrum.log import CentrumLog
from rozliczenia.centrum.reports import Reports
from rozliczenia.centrum.runs import RunHost
from rozliczenia.centrum.tool_freshness import CommitSource
from rozliczenia.centrum.tool_update import (
    LIBRARIES_FAILED,
    NO_CONNECTION,
    UNEXPECTED,
    UP_TO_DATE,
    UPDATED,
    Step,
    ToolClone,
    UpdateResult,
)

# Porażki, po których tata sam klika „Zaktualizuj narzędzie” jeszcze raz; każdą inną przejmuje Maks.
_RETRIED_BY_TATA = frozenset({NO_CONNECTION, LIBRARIES_FAILED, UNEXPECTED})


class ToolUpdates:
    """Aktualizacja narzędzia tego Centrum: najwyżej jedna naraz, a po niej jej wynik.

    ``clone`` daje klon narzędzia przy każdym kliknięciu, nie przy starcie
    Centrum (test bez podstawionego klonu kończy się dopiero na akcji), a
    ``commit`` to commit narzędzia przed aktualizacją, tak jak widzi go Diagnoza.
    ``reports`` przygotowuje i wysyła Zgłoszenie nieudanej aktualizacji.
    """

    def __init__(
        self, clone: Callable[[], ToolClone], runs: RunHost, log: CentrumLog, commit: CommitSource, reports: Reports
    ) -> None:
        self._clone = clone
        self._runs = runs
        self._log = log
        self._reports = reports
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
            if result.before is None:  # bez Gita commit zna tylko Centrum
                result = replace(result, before=before)
            self._log.update_finished(
                result=result.code, before=result.before, after=result.after, installed=result.installed
            )
            view = _view_of(result) or self._failed(result)
            with self._lock:
                self._view = view
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

    def _failed(self, result: UpdateResult) -> contract.ToolUpdateFailed:
        """Komunikat porażki z podglądem Zgłoszenia; wpis ``aktualizacja-koniec`` jest już w dzienniku."""

        message = update_messages.message_of(result.code)
        draft, report = self._reports.draft_update(result, message)
        return contract.ToolUpdateFailed(
            state="failed",
            message=contract.Message.of(message),
            next_action="retry" if message.code in _RETRIED_BY_TATA else "report",
            report=report,
            draft=draft,
        )

    def send_report(self) -> contract.ReportState:
        """„Wyślij do Maksa” przy nieudanej aktualizacji; ``contract.Refusal``, gdy ostatnia aktualizacja nie zawiodła."""

        with self._lock:
            failed = self._view
        if not isinstance(failed, contract.ToolUpdateFailed):
            raise contract.Refusal(409, "Zgłoszenie powstaje po nieudanej aktualizacji narzędzia.")
        state = self._reports.send_update()
        with self._lock:
            if self._view is failed:
                self._view = failed.model_copy(update={"report": state})
        return state

    def _show_step(self, step: Step) -> None:
        with self._lock:
            self._view = contract.ToolUpdateRunning(state="running", step=step)


def _view_of(result: UpdateResult) -> contract.ToolUpdate | None:
    """Widok udanej aktualizacji albo ``None`` przy porażce."""

    if result.code == UPDATED and result.after is not None:
        return contract.ToolUpdateUpdated(state="updated", commit=result.after[:7])
    if result.code == UP_TO_DATE:
        return contract.ToolUpdateUpToDate(state="up_to_date")
    return None


def tool_update_router(updates: ToolUpdates) -> APIRouter:
    router = APIRouter(prefix="/api/tool-update", tags=["aktualizacja"])

    @router.post("", operation_id="startToolUpdate", status_code=202, responses={409: {"model": contract.Problem}})
    def start() -> contract.ToolUpdate:
        return updates.start()

    @router.get("", operation_id="getToolUpdate")
    def current() -> contract.ToolUpdate:
        return updates.current()

    @router.post("/report", operation_id="reportToolUpdate", responses={409: {"model": contract.Problem}})
    def send_report() -> contract.ReportState:
        return updates.send_report()

    return router

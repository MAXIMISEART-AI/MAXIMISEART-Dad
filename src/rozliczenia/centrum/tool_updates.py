"""Aktualizacja narzędzia z Centrum rozliczeń: akcja karty, krok i wynik dla przeglądarki (ADR 0009).

Samą aktualizację robi ``tool_update.ToolClone.update``; ten moduł prowadzi ją
w Centrum. Zajmuje miejsce „jedno naraz” w ``RunHost`` (odmowy 409 w trakcie
Uruchomienia procesu albo innej aktualizacji), odpowiada od razu i prowadzi
aktualizację w osobnym wątku, a karta odczytuje krok i wynik. Dziennik Centrum
dostaje start i koniec z commitem przed i po, bez ścieżek i bez wyjścia Gita.
Po udanej aktualizacji Centrum zamyka się, a opiekun ponownego startu
(``restart_guardian``) uruchamia nową wersję; koniec aktualizacji zapisuje
wtedy w dzienniku nowe Centrum, z pliku wyniku od opiekuna. Gdy opiekun nie
wystartuje, klon wraca do wersji sprzed kliknięcia, a Centrum działa dalej.
Każdą porażkę, której ``tool_update`` nie przewidział, karta widzi jako Komunikat
nieoczekiwanej porażki, a dziennik tylko nazwę typu wyjątku. Przy każdej
porażce karta dostaje też Zgłoszenie do Maksa z faktami dziennika.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import replace
from pathlib import Path
import shutil
import tempfile
import threading

from fastapi import APIRouter, Request

from rozliczenia.centrum import contract, restart_guardian, update_messages
from rozliczenia.centrum.log import CentrumLog
from rozliczenia.centrum.reports import NO_FAILED_UPDATE, Reports
from rozliczenia.centrum.restart_guardian import Restart
from rozliczenia.centrum.runs import RunHost
from rozliczenia.centrum.shutdown import Shutdown
from rozliczenia.centrum.tool_freshness import CommitSource
from rozliczenia.centrum.tool_update import (
    LIBRARIES_FAILED,
    NO_CONNECTION,
    UNEXPECTED,
    UP_TO_DATE,
    ROLLBACK_FAILED,
    UPDATED,
    Step,
    ToolClone,
    UpdateResult,
    read_result,
)

# Porażki, po których tata sam klika „Zaktualizuj narzędzie” jeszcze raz; każdą inną przejmuje Maks.
_RETRIED_BY_TATA = frozenset({NO_CONNECTION, LIBRARIES_FAILED, UNEXPECTED})

GuardianLauncher = Callable[[Path, Restart], object]
"""Uruchamia opiekuna ponownego startu z kopii (``restart_guardian.launch``); w testach podstawiany."""


class ToolUpdates:
    """Aktualizacja narzędzia tego Centrum: najwyżej jedna naraz, a po niej jej wynik.

    ``clone`` daje klon narzędzia przy każdym kliknięciu, nie przy starcie
    Centrum (test bez podstawionego klonu kończy się dopiero na akcji), a
    ``commit`` to commit narzędzia przed aktualizacją, tak jak widzi go Diagnoza.

    Po udanej aktualizacji Centrum uruchamia opiekuna ponownego startu
    (``guardian``) i zamyka się (``shutdown``); miejsca „jedno naraz” już nie
    zwalnia. Opiekun zostawia wynik w ``result_file``, a nowe Centrum odczytuje
    go raz przy starcie: zapisuje koniec aktualizacji w dzienniku, usuwa plik i
    pokazuje wynik karcie. ``reports`` przygotowuje i wysyła Zgłoszenie nieudanej
    aktualizacji.
    """

    def __init__(
        self,
        clone: Callable[[], ToolClone],
        runs: RunHost,
        log: CentrumLog,
        commit: CommitSource,
        reports: Reports,
        *,
        shutdown: Shutdown,
        guardian: GuardianLauncher,
        result_file: Path,
    ) -> None:
        self._clone = clone
        self._runs = runs
        self._log = log
        self._reports = reports
        self._commit = commit
        self._shutdown = shutdown
        self._guardian = guardian
        self._result_file = result_file
        self._lock = threading.Lock()
        self._view: contract.ToolUpdate = contract.ToolUpdateIdle(state="idle")
        self._after_restart()

    def current(self) -> contract.ToolUpdate:
        with self._lock:
            return self._view

    def start(self, port: int) -> contract.ToolUpdate:
        """Zaczyna aktualizację w tle i od razu zwraca jej pierwszy krok; ``contract.Refusal``, gdy coś trwa.

        ``port`` to port tego Centrum: na nim opiekun startuje nową wersję.
        """

        clone = self._clone()
        self._runs.begin_update()
        before = self._commit()
        self._log.update_started(before=before)
        first = contract.ToolUpdateRunning(state="running", step="fetching")
        with self._lock:
            self._view = first
        threading.Thread(
            target=self._update, args=(clone, before, port), name="aktualizacja-narzedzia", daemon=True
        ).start()
        return first

    def _after_restart(self) -> None:
        """Wynik od opiekuna ponownego startu: do dziennika i do karty, raz, bez czekania na sieć.

        Po porażce (np. cofnięcie nowej wersji) skrzynkę Zgłoszeń pyta osobny wątek: start Centrum na nią nie czeka.
        """

        result = read_result(self._result_file)
        if result is None:
            return
        self._finished(result)
        try:
            self._result_file.unlink(missing_ok=True)
        except OSError:
            pass  # wynik i tak jest już w dzienniku; plik zostaje do następnego startu
        view = _view_of(result)
        if view is not None:
            self._view = view
            return
        failed = self._failed(result)
        self._view = failed
        threading.Thread(
            target=self._ask_box_after_restart, args=(failed,), name="zgloszenie-aktualizacji", daemon=True
        ).start()

    def _ask_box_after_restart(self, failed: contract.ToolUpdateFailed) -> None:
        try:
            state = self._reports.update_report_state()
        except Exception as failure:  # noqa: BLE001 - granica wątku: typ wyjątku trafia do dziennika Centrum
            self._log.unexpected_failure(failure, where="stan Zgłoszenia aktualizacji przy starcie")
            return
        with self._lock:
            if self._view is failed:  # karta mogła już wysłać Zgłoszenie
                self._view = failed.model_copy(update={"report": state})

    def _update(self, clone: ToolClone, before: str | None, port: int) -> None:
        work = Path(tempfile.mkdtemp(prefix="centrum-aktualizacja-"))
        restarting = False
        try:
            result, guardian = self._result(clone, before, work)
            if result.before is None:  # bez Gita commit zna tylko Centrum
                result = replace(result, before=before)
            if result.code == UPDATED and result.after is not None and guardian is not None:
                restart = Restart(
                    port, result.before, result.after, clone.root, self._result_file, result.installed, work
                )
                restarting = self._restart(clone, restart, guardian)
                if not restarting:
                    result = self._moved_back(clone, result)
            if not restarting:
                self._finished(result)
                view = _view_of(result) or self._failed(result).model_copy(
                    update={"report": self._reports.update_report_state()}
                )
                with self._lock:
                    self._view = view
        finally:
            if not restarting:
                shutil.rmtree(work, ignore_errors=True)
                self._runs.end_update()

    def _result(self, clone: ToolClone, before: str | None, work: Path) -> tuple[UpdateResult, Path | None]:
        try:
            # Opiekun działa z kopii sprzed aktualizacji, więc kopia powstaje, zanim klon się zmieni.
            guardian = restart_guardian.prepare(work)
            return clone.update(self._show_step), guardian
        except Exception as failure:  # noqa: BLE001 - granica wątku: typ wyjątku trafia do dziennika Centrum
            self._log.unexpected_failure(failure, where="aktualizacja narzędzia")
            return UpdateResult(UNEXPECTED, before, None), None

    def _restart(self, clone: ToolClone, restart: Restart, guardian: Path) -> bool:
        """Uruchamia opiekuna i zamyka Centrum; ``False``, gdy opiekun nie wystartował (Centrum działa dalej)."""

        try:
            clone.lease_to_guardian()
            with self._lock:
                self._view = contract.ToolUpdateRunning(state="running", step="restarting")
            self._guardian(guardian, restart)
        except Exception as failure:  # noqa: BLE001 - granica wątku: typ wyjątku trafia do dziennika Centrum
            self._log.unexpected_failure(failure, where="ponowny start po aktualizacji")
            return False
        self._shutdown.close_for_update()
        return True

    def _moved_back(self, clone: ToolClone, result: UpdateResult) -> UpdateResult:
        """Bez opiekuna nowa wersja nie wystartuje, a stary kod działałby na nowych plikach: klon wraca sprzed kliknięcia.

        Wynik to porażka nieoczekiwana, a gdy nie uda się cofnięcie, porażka cofnięcia.
        """

        try:
            clone.roll_back()
        except Exception as failure:  # noqa: BLE001 - granica wątku: typ wyjątku trafia do dziennika Centrum
            self._log.unexpected_failure(failure, where="cofnięcie aktualizacji")
            return replace(result, code=ROLLBACK_FAILED)
        return replace(result, code=UNEXPECTED)

    def _finished(self, result: UpdateResult) -> None:
        self._log.update_finished(
            result=result.code, before=result.before, after=result.after, installed=result.installed
        )

    def _failed(self, result: UpdateResult) -> contract.ToolUpdateFailed:
        """Komunikat porażki z podglądem Zgłoszenia i ostatnim znanym stanem; ``aktualizacja-koniec`` jest już w dzienniku."""

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
            raise contract.Refusal(409, NO_FAILED_UPDATE)
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

    if result.code == UPDATED:
        return contract.ToolUpdateUpdated(state="updated")
    if result.code == UP_TO_DATE:
        return contract.ToolUpdateUpToDate(state="up_to_date")
    return None


def tool_update_router(updates: ToolUpdates) -> APIRouter:
    router = APIRouter(prefix="/api/tool-update", tags=["aktualizacja"])

    @router.post("", operation_id="startToolUpdate", status_code=202, responses={409: {"model": contract.Problem}})
    def start(request: Request) -> contract.ToolUpdate:
        server = request.scope.get("server")
        return updates.start(int(server[1]) if server else 0)

    @router.get("", operation_id="getToolUpdate")
    def current() -> contract.ToolUpdate:
        return updates.current()

    @router.post("/report", operation_id="reportToolUpdate", responses={409: {"model": contract.Problem}})
    def send_report() -> contract.ReportState:
        return updates.send_report()

    return router

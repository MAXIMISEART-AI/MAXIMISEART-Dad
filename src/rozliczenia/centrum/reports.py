"""Zgłoszenie do Maksa: treść z Zatrzymania i Diagnozy, wysyłka do skrzynki Zgłoszeń i stan na tym komputerze.

Treść Zgłoszenia powstaje tylko tutaj (``report_of``), z tych samych
bezpiecznych faktów co Komunikat i Diagnoza: Komunikat z kodem i trzema
częściami, proces, okres i tryb, wersja i commit narzędzia, wynik każdego
sprawdzenia Diagnozy i ostatnie wpisy dziennika Centrum, a przy nieoczekiwanym
wyjątku jego typ i ślad wywołań w kodzie narzędzia. Ścieżki są już skrócone w
Komunikatach, szczegółach sprawdzeń i ramkach śladu; treści wierszy, treści
wyjątków ani klucza Zgłoszenie nie ma (ADR 0007).

Diagnoza zostawia treść Zgłoszenia jako podgląd dla swojego Uruchomienia
(``Reports.draft``), a „Wyślij do Maksa” wysyła dokładnie ten podgląd.
"""

from __future__ import annotations

import json
import threading
from collections.abc import Callable, Mapping
from dataclasses import asdict, dataclass, replace
from pathlib import Path
from typing import TYPE_CHECKING, Final

from fastapi import APIRouter

from rozliczenia.call_trace import CallTrace
from rozliczenia.centrum import contract, report_messages
from rozliczenia.centrum.deadline import within
from rozliczenia.centrum.log import CentrumLog
from rozliczenia.centrum.report_box import (
    IssueState,
    Refused,
    Report,
    ReportBox,
    SendOutcome,
    Sent,
    Unreachable,
    fingerprint_line,
)
from rozliczenia.centrum.runs import RunHost, StoppedRun
from rozliczenia.centrum.stops import ProblemFingerprint
from rozliczenia.centrum.tool_freshness import CommitSource
from rozliczenia.centrum.version import tool_version

if TYPE_CHECKING:
    from rozliczenia.centrum.diagnosis import Diagnosis

REPORT_KEY_FILE: Final = "zgloszenia-klucz.txt"
UNSENT_DIRECTORY: Final = "zgloszenia"
SENT_REPORTS_FILE: Final = "zgloszenia-wyslane.json"
# Skrzynkę Zgłoszeń o stan wysłanych Zgłoszeń Centrum pyta najwyżej raz na 10 minut.
STATES_INTERVAL_S: Final = 10 * 60
# Diagnoza czeka na odpowiedź skrzynki o otwarte Zgłoszenie najwyżej tyle, co na commit `main`.
SEARCH_DEADLINE_S: Final = 3.0

_MODES: Final = {True: "DRY-RUN", False: "RUN"}
_CHECK_STATES: Final = {"passed": "przeszło", "failed": "nie przeszło", "not_checked": "nie sprawdzono"}


def report_of(diagnosis: Diagnosis, *, commit: str | None, previous: int | None = None) -> Report:
    """Zgłoszenie Zatrzymania z wynikiem Diagnozy; tytuł to kod Komunikatu i „Co się stało”.

    ``previous`` to numer wcześniejszego Zgłoszenia tego samego problemu, które Maks już zamknął.
    """

    stopped = diagnosis.stopped
    info, message = stopped.info, stopped.stop.message
    fingerprint = ProblemFingerprint.of(info.process, message).digest
    explanation = diagnosis.explanation
    lines = [
        "Zgłoszenie z Centrum rozliczeń.",
        "",
        "## Komunikat",
        "",
        f"- Kod: {message.code}",
        f"- Co się stało: {message.what}",
        f"- Gdzie: {message.where}",
        f"- Co zrobić: {message.action}",
        "",
        "## Uruchomienie procesu",
        "",
        f"- Proces: {info.title}",
        f"- Okres: {info.period}",
        f"- Tryb: {_MODES[info.dry_run]}",
        "",
        *_trace_lines(stopped.stop.trace),
        "## Narzędzie",
        "",
        f"- Wersja: {tool_version()}",
        f"- Commit: {commit or 'nieznany'}",
        fingerprint_line(fingerprint),
        *([] if previous is None else [f"- Poprzednie Zgłoszenie: #{previous}"]),
        "",
        "## Diagnoza",
        "",
        f"Wyjaśnienie: {explanation.code} · {explanation.what}",
        "",
        "| Sprawdzenie | Wynik | Szczegóły |",
        "| --- | --- | --- |",
        *(
            f"| {_cell(check.label)} | {_CHECK_STATES[check.state]} | {_cell(check.detail)} |"
            for check in diagnosis.checks
        ),
        "",
        "## Dziennik Centrum rozliczeń",
        "",
        "```text",
        *diagnosis.log_entries,
        "```",
    ]
    return Report(title=f"{message.code}: {message.what}", body="\n".join(lines) + "\n", fingerprint=fingerprint)


def _trace_lines(trace: CallTrace | None) -> list[str]:
    """Sekcja śladu wywołań nieoczekiwanego wyjątku: typ i ramki kodu narzędzia, bez treści wyjątku."""

    if trace is None:
        return []
    return [
        "## Ślad wywołań",
        "",
        f"- Wyjątek: {trace.exception_type}",
        "",
        "```text",
        *(f"{frame.file}:{frame.line} w {frame.function}" for frame in trace.frames),
        "```",
        "",
    ]


def _cell(text: str) -> str:
    return text.replace("|", "\\|")


@dataclass(frozen=True)
class SentReport:
    """Wysłane Zgłoszenie w lokalnym stanie: odcisk problemu, numer issue i commit narzędzia przy wysyłce.

    ``state`` to ostatni znany stan issue w skrzynce Zgłoszeń; dopóki skrzynka nie powie inaczej, ``open``.
    """

    fingerprint: str
    number: int
    commit: str | None
    state: IssueState = "open"


class SentReports:
    """Lokalny plik wysłanych Zgłoszeń obok Ustawień taty, poza Gitem.

    Potwierdzenie wysłania przetrwa odświeżenie karty i restart Centrum, a commit
    mówi, z jakiej wersji narzędzia wysłano Zgłoszenie. Brak albo uszkodzenie
    pliku to brak wysłanych Zgłoszeń; nieudany zapis zostawia Zgłoszenie wysłanym
    do końca pracy Centrum.
    """

    def __init__(self, path: Path, log: CentrumLog) -> None:
        self._path = path
        self._log = log
        self._remembered: list[SentReport] = []

    def all(self) -> list[SentReport]:
        stored = self._read()
        known = {sent.number for sent in stored}
        return stored + [sent for sent in self._remembered if sent.number not in known]

    def find(self, fingerprint: str) -> SentReport | None:
        """Ostatnio wysłane Zgłoszenie problemu ``fingerprint``."""

        return next((sent for sent in reversed(self.all()) if sent.fingerprint == fingerprint), None)

    def add(self, sent: SentReport) -> None:
        reports = [*self.all(), sent]
        self._remembered.append(sent)
        self._write(reports)

    def mark(self, states: Mapping[int, IssueState]) -> None:
        """Zapamiętuje stan issue ze skrzynki Zgłoszeń przy wysłanych Zgłoszeniach o tych numerach."""

        def marked(sent: SentReport) -> SentReport:
            return replace(sent, state=states.get(sent.number, sent.state))

        self._remembered = [marked(sent) for sent in self._remembered]
        self._write([marked(sent) for sent in self.all()])

    def _write(self, reports: list[SentReport]) -> None:
        temporary = self._path.with_name(self._path.name + ".tmp")
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            temporary.write_text(json.dumps([asdict(report) for report in reports], indent=2) + "\n", encoding="utf-8")
            temporary.replace(self._path)
        except OSError as failure:
            self._log.unexpected_failure(failure, where="stan wysłanych Zgłoszeń")

    def _read(self) -> list[SentReport]:
        try:
            entries = json.loads(self._path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, ValueError):
            return []
        if not isinstance(entries, list):
            return []
        return [
            SentReport(entry["fingerprint"], entry["number"], entry.get("commit"), entry.get("state", "open"))
            for entry in entries
            if isinstance(entry, dict)
            and isinstance(entry.get("fingerprint"), str)
            and isinstance(entry.get("number"), int)
            and isinstance(entry.get("commit"), str | None)
            and entry.get("state", "open") in ("open", "closed")
        ]


@dataclass(frozen=True)
class _Draft:
    """Zgłoszenie z ostatniej Diagnozy, jego Uruchomienie i nazwa pliku na wypadek nieudanej wysyłki."""

    run_id: str
    report: Report
    file_name: str


class Reports:
    """Zgłoszenia z tego komputera: podgląd z ostatniej Diagnozy, jego wysyłka i stan wysłanych.

    Klucz, stan wysłanych i niewysłane Zgłoszenia leżą w katalogu konfiguracji
    obok Ustawień taty, poza Gitem. Jeden problem ma jedno otwarte Zgłoszenie:
    Diagnoza i wysyłka pytają skrzynkę o otwarte Zgłoszenie z tym samym odciskiem,
    a gdy jest, nowe nie powstaje. Bez odpowiedzi skrzynki (brak klucza albo
    sieci) problem wysłany z tego komputera czeka na naprawę.
    """

    def __init__(
        self,
        config_directory: Path,
        box: ReportBox,
        log: CentrumLog,
        commit: CommitSource,
        *,
        clock: Callable[[], float],
    ) -> None:
        self._commit = commit
        self._clock = clock
        self._states_asked_at: float | None = None  # od startu Centrum skrzynka nie była jeszcze pytana
        self._key_file = config_directory / REPORT_KEY_FILE
        self._unsent = config_directory / UNSENT_DIRECTORY
        self._sent = SentReports(config_directory / SENT_REPORTS_FILE, log)
        self._box = box
        self._log = log
        self._lock = threading.Lock()
        self._draft: _Draft | None = None
        self._sent_runs: set[str] = set()
        # Ostatnia odpowiedź skrzynki w tej pracy Centrum: odcisk problemu → numer otwartego Zgłoszenia albo None.
        self._open: dict[str, int | None] = {}

    def state(self, fingerprint: ProblemFingerprint) -> contract.ReportState:
        """Stan Zgłoszenia problemu przy wyniku Uruchomienia: czeka na naprawę albo gotowe do wysłania."""

        return self._state_of(fingerprint.digest)

    def draft(self, diagnosis: Diagnosis) -> tuple[contract.ReportDraft, contract.ReportState]:
        """Zgłoszenie z Diagnozy, które wyśle „Wyślij do Maksa” w tym Uruchomieniu, i stan po pytaniu skrzynki.

        Gdy ten problem był już zgłoszony z tego komputera, Zgłoszenie ma odnośnik do ostatniego z nich.
        """

        stopped = diagnosis.stopped
        info = stopped.info
        fingerprint = ProblemFingerprint.of(info.process, stopped.stop.message).digest
        self._ask_box(fingerprint)
        previous = self._sent.find(fingerprint)
        report = report_of(diagnosis, commit=self._commit(), previous=previous.number if previous else None)
        file_name = f"Zgłoszenie {stopped.stop.message.code} {info.period}.md"
        with self._lock:
            self._draft = _Draft(info.id, report, file_name)
            state = contract.ReportSent(state="sent") if info.id in self._sent_runs else self._state_of(fingerprint)
        return contract.ReportDraft(title=report.title, body=report.body), state

    def send(self, stopped: StoppedRun) -> contract.ReportState:
        """Wysyła podgląd z Diagnozy ``stopped``, chyba że skrzynka ma już otwarte Zgłoszenie tego problemu.

        Gdy się nie uda, zapisuje Zgłoszenie w pliku i mówi, co dalej.
        """

        info = stopped.info
        with self._lock:
            draft = self._draft
            if draft is None or draft.run_id != info.id:
                raise contract.Refusal(409, "Zgłoszenie powstaje z Diagnozy. Najpierw kliknij „Diagnoza”.")
            if info.id in self._sent_runs:
                return contract.ReportSent(state="sent")
            key = self._key()
            outcome: SendOutcome | None = None
            if key is not None:
                found = self._box.find_open(draft.report.fingerprint, key=key)
                if isinstance(found, int):
                    self._open[draft.report.fingerprint] = found
                    self._log.report_waiting(process=info.process, period=info.period, number=found)
                    return contract.ReportWaiting(state="waiting")
                outcome = self._box.send(draft.report, key=key) if found is None else found
            saved = self._unsent / draft.file_name
            if isinstance(outcome, Sent):
                self._sent.add(SentReport(draft.report.fingerprint, outcome.number, self._commit()))
                self._open[draft.report.fingerprint] = outcome.number
                self._sent_runs.add(info.id)
                saved.unlink(missing_ok=True)
                self._log.report_sent(process=info.process, period=info.period, number=outcome.number)
                return contract.ReportSent(state="sent")
            saved.parent.mkdir(parents=True, exist_ok=True)
            saved.write_text(f"# {draft.report.title}\n\n{draft.report.body}", encoding="utf-8")
        message = (
            report_messages.key_missing(saved)
            if outcome is None
            else report_messages.key_refused(saved)
            if isinstance(outcome, Refused)
            else report_messages.box_unreachable(saved)
        )
        self._log.report_saved(process=info.process, period=info.period, code=message.code)
        return contract.ReportSaved(state="saved", message=contract.Message.of(message))

    def repair_notice(self) -> contract.RepairNotice:
        """Czy Maks zamknął Zgłoszenie wysłane z wersji narzędzia, która nadal tu działa.

        Gdy od startu Centrum skrzynki nie pytano albo minęło ``STATES_INTERVAL_S``,
        Centrum pyta ją o stan otwartych Zgłoszeń z tej wersji; porażka zapytania
        przechodzi po cichu i zostaje ostatni znany stan. Po aktualizacji narzędzia
        commit jest inny, więc powiadomienie znika samo.
        """

        commit = self._commit()
        if commit is None:
            return contract.RepairNotice(repaired=False)
        with self._lock:
            waiting = [sent.number for sent in self._sent.all() if sent.commit == commit and sent.state == "open"]
            key = self._key()
            now = self._clock()
            due = self._states_asked_at is None or now - self._states_asked_at >= STATES_INTERVAL_S
            if waiting and key is not None and due:
                self._states_asked_at = now
                states = self._box.states(waiting, key=key)
                if not isinstance(states, Refused | Unreachable):
                    self._sent.mark(states)
            repaired = any(sent.commit == commit and sent.state == "closed" for sent in self._sent.all())
        return contract.RepairNotice(repaired=repaired)

    def _ask_box(self, fingerprint: str) -> None:
        """Pyta skrzynkę o otwarte Zgłoszenie problemu; bez klucza albo odpowiedzi zostaje to, co już wiadomo.

        Brak odpowiedzi w ``SEARCH_DEADLINE_S`` to brak odpowiedzi: Diagnoza zostaje krótka bez sieci, a
        wysyłka i tak pyta skrzynkę, zanim założy Zgłoszenie.
        """

        key = self._key()
        if key is None:
            return
        box = self._box
        answer = within(SEARCH_DEADLINE_S, lambda: (box.find_open(fingerprint, key=key),), name="skrzynka-szukaj")
        if answer is None:
            return
        [found] = answer
        if found is None or isinstance(found, int):
            with self._lock:
                self._open[fingerprint] = found

    def _state_of(self, fingerprint: str) -> contract.ReportState:
        """Odpowiedź skrzynki z tej pracy Centrum, a bez niej ostatni znany stan wysłanego Zgłoszenia.

        Zgłoszenie, o którym wiadomo, że Maks je zamknął, nie czeka na naprawę.
        """

        if fingerprint in self._open:
            waiting = self._open[fingerprint] is not None
        else:
            sent = self._sent.find(fingerprint)
            waiting = sent is not None and sent.state == "open"
        return contract.ReportWaiting(state="waiting") if waiting else contract.ReportReady(state="ready")

    def key_state(self) -> contract.ReportKeyState:
        return "ready" if self._key() is not None else "missing_key"

    def _key(self) -> str | None:
        """Klucz do Zgłoszeń z lokalnego pliku; ``None``, gdy pliku nie ma albo jest pusty."""

        try:
            key = self._key_file.read_text(encoding="utf-8").strip()
        except (OSError, UnicodeError):
            return None
        return key or None




def reports_router(host: RunHost, reports: Reports) -> APIRouter:
    router = APIRouter(prefix="/api/runs", tags=["uruchomienia"])

    @router.post("/{run_id}/report", operation_id="reportRun", responses=contract.NOT_FOUND_OR_CONFLICT)
    def send_report(run_id: str) -> contract.ReportState:
        state = reports.send(host.stopped(run_id))
        host.show_report(run_id, state)
        return state

    return router


def repair_router(reports: Reports) -> APIRouter:
    router = APIRouter(prefix="/api/reports", tags=["zgloszenia"])

    @router.get("/repair", operation_id="getRepairNotice")
    def repair_notice() -> contract.RepairNotice:
        return reports.repair_notice()

    return router

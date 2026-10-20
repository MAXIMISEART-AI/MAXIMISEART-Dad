"""Zgłoszenie do Maksa: treść z Zatrzymania i Diagnozy, wysyłka do skrzynki Zgłoszeń i stan na tym komputerze.

Treść Zgłoszenia powstaje tylko tutaj (``report_of``), z tych samych
bezpiecznych faktów co Komunikat i Diagnoza: Komunikat z kodem i trzema
częściami, proces, okres i tryb, wersja i commit narzędzia, wynik każdego
sprawdzenia Diagnozy i ostatnie wpisy dziennika Centrum. Ścieżki są już
skrócone w Komunikatach i szczegółach sprawdzeń; treści wierszy, treści
wyjątków ani klucza Zgłoszenie nie ma (ADR 0007).

Diagnoza zostawia treść Zgłoszenia jako podgląd dla swojego Uruchomienia
(``Reports.draft``), a „Wyślij do Maksa” wysyła dokładnie ten podgląd.
"""

from __future__ import annotations

import json
import threading
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Final

from fastapi import APIRouter

from rozliczenia.centrum import contract, report_messages
from rozliczenia.centrum.log import CentrumLog
from rozliczenia.centrum.report_box import Refused, Report, ReportBox, Sent
from rozliczenia.centrum.runs import RunHost, StoppedRun
from rozliczenia.centrum.stops import ProblemFingerprint
from rozliczenia.centrum.tool_freshness import CommitSource
from rozliczenia.centrum.version import tool_version

if TYPE_CHECKING:
    from rozliczenia.centrum.diagnosis import Diagnosis

REPORT_KEY_FILE: Final = "zgloszenia-klucz.txt"
UNSENT_DIRECTORY: Final = "zgloszenia"
SENT_REPORTS_FILE: Final = "zgloszenia-wyslane.json"

_MODES: Final = {True: "DRY-RUN", False: "RUN"}
_CHECK_STATES: Final = {"passed": "przeszło", "failed": "nie przeszło", "not_checked": "nie sprawdzono"}


def report_of(diagnosis: Diagnosis, *, commit: str | None) -> Report:
    """Zgłoszenie Zatrzymania z wynikiem Diagnozy; tytuł to kod Komunikatu i „Co się stało”."""

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
        "## Narzędzie",
        "",
        f"- Wersja: {tool_version()}",
        f"- Commit: {commit or 'nieznany'}",
        f"- Odcisk problemu: {fingerprint}",
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


def _cell(text: str) -> str:
    return text.replace("|", "\\|")


@dataclass(frozen=True)
class SentReport:
    """Wysłane Zgłoszenie w lokalnym stanie: odcisk problemu, numer issue i commit narzędzia przy wysyłce."""

    fingerprint: str
    number: int
    commit: str | None


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
        known = {sent.fingerprint for sent in stored}
        return stored + [sent for sent in self._remembered if sent.fingerprint not in known]

    def find(self, fingerprint: str) -> SentReport | None:
        return next((sent for sent in self.all() if sent.fingerprint == fingerprint), None)

    def add(self, sent: SentReport) -> None:
        reports = [*self.all(), sent]
        self._remembered.append(sent)
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
            SentReport(entry["fingerprint"], entry["number"], entry.get("commit"))
            for entry in entries
            if isinstance(entry, dict)
            and isinstance(entry.get("fingerprint"), str)
            and isinstance(entry.get("number"), int)
            and isinstance(entry.get("commit"), str | None)
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
    obok Ustawień taty, poza Gitem. Jeden problem wysyła się raz: Zgłoszenie z
    odciskiem, który jest już w stanie wysłanych, nie trafia drugi raz do skrzynki.
    """

    def __init__(self, config_directory: Path, box: ReportBox, log: CentrumLog, commit: CommitSource) -> None:
        self._commit = commit
        self._key_file = config_directory / REPORT_KEY_FILE
        self._unsent = config_directory / UNSENT_DIRECTORY
        self._sent = SentReports(config_directory / SENT_REPORTS_FILE, log)
        self._box = box
        self._log = log
        self._lock = threading.Lock()
        self._draft: _Draft | None = None

    def state(self, fingerprint: ProblemFingerprint) -> contract.ReportState:
        """Stan Zgłoszenia problemu przy wyniku Uruchomienia: wysłane z tego komputera albo gotowe do wysłania."""

        if self._sent.find(fingerprint.digest) is not None:
            return contract.ReportSent(state="sent")
        return contract.ReportReady(state="ready")

    def draft(self, diagnosis: Diagnosis) -> contract.ReportDraft:
        """Zapamiętuje Zgłoszenie z Diagnozy jako to, które wyśle „Wyślij do Maksa” w tym Uruchomieniu."""

        report = report_of(diagnosis, commit=self._commit())
        info = diagnosis.stopped.info
        file_name = f"Zgłoszenie {diagnosis.stopped.stop.message.code} {info.period}.md"
        with self._lock:
            self._draft = _Draft(info.id, report, file_name)
        return contract.ReportDraft(title=report.title, body=report.body)

    def send(self, stopped: StoppedRun) -> contract.ReportState:
        """Wysyła podgląd z Diagnozy ``stopped``; gdy się nie uda, zapisuje go w pliku i mówi, co dalej."""

        info = stopped.info
        with self._lock:
            draft = self._draft
            if draft is None or draft.run_id != info.id:
                raise contract.Refusal(409, "Zgłoszenie powstaje z Diagnozy. Najpierw kliknij „Diagnoza”.")
            if self._sent.find(draft.report.fingerprint) is not None:
                return contract.ReportSent(state="sent")
            key = self._key()
            outcome = self._box.send(draft.report, key=key) if key is not None else None
            saved = self._unsent / draft.file_name
            if isinstance(outcome, Sent):
                self._sent.add(SentReport(draft.report.fingerprint, outcome.number, self._commit()))
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

    def key_state(self) -> contract.ReportKeyState:
        return "ready" if self._key() is not None else "missing_key"

    def _key(self) -> str | None:
        """Klucz do Zgłoszeń z lokalnego pliku; ``None``, gdy pliku nie ma albo jest pusty."""

        try:
            key = self._key_file.read_text(encoding="utf-8").strip()
        except (OSError, UnicodeError):
            return None
        return key or None


_PROBLEMS: dict[int | str, dict[str, object]] = {404: {"model": contract.Problem}, 409: {"model": contract.Problem}}


def reports_router(host: RunHost, reports: Reports) -> APIRouter:
    router = APIRouter(prefix="/api/runs", tags=["uruchomienia"])

    @router.post("/{run_id}/report", operation_id="reportRun", responses=_PROBLEMS)
    def send_report(run_id: str) -> contract.ReportState:
        state = reports.send(host.stopped(run_id))
        host.show_report(run_id, state)
        return state

    return router

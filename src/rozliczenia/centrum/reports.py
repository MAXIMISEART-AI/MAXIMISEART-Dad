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
Nieudana Aktualizacja narzędzia zostawia swój podgląd (``Reports.draft_update``)
z tymi samymi faktami co dziennik Centrum: kod Komunikatu, commit przed i po,
czy instalowano biblioteki, wersja narzędzia i ostatnie wpisy dziennika, bez
ścieżek i bez wyjścia Gita.
"""

from __future__ import annotations

import json
import threading
from collections.abc import Callable, Mapping
from contextlib import suppress
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
from rozliczenia.centrum.tool_update import UpdateResult
from rozliczenia.centrum.version import tool_version
from rozliczenia.message import Message

if TYPE_CHECKING:
    from rozliczenia.centrum.diagnosis import Diagnosis

REPORT_KEY_FILE: Final = "zgloszenia-klucz.txt"
UNSENT_DIRECTORY: Final = "zgloszenia"
SENT_REPORTS_FILE: Final = "zgloszenia-wyslane.json"
# Skrzynkę Zgłoszeń o stan wysłanych Zgłoszeń Centrum pyta najwyżej raz na 10 minut.
STATES_INTERVAL_S: Final = 10 * 60
# Diagnoza czeka na odpowiedź skrzynki o otwarte Zgłoszenie najwyżej tyle, co na commit `main`.
SEARCH_DEADLINE_S: Final = 3.0

# Zgłoszenie nieudanej Aktualizacji narzędzia ma tyle ostatnich wpisów dziennika co Zgłoszenie z Diagnozy.
_UPDATE_LOG_ENTRIES: Final = 20
# Podgląd Zgłoszenia aktualizacji jest jeden na Centrum, jak sama aktualizacja.
_UPDATE_KEY: Final = "aktualizacja-narzedzia"
# Odmowa „Wyślij do Maksa”, gdy ostatnia Aktualizacja narzędzia nie zawiodła.
NO_FAILED_UPDATE: Final = "Zgłoszenie powstaje po nieudanej aktualizacji narzędzia."

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
        *_message_lines(message),
        "## Uruchomienie procesu",
        "",
        f"- Proces: {info.title}",
        f"- Okres: {info.period}",
        f"- Tryb: {_MODES[info.dry_run]}",
        "",
        *_trace_lines(stopped.stop.trace),
        *_tool_lines(fingerprint, previous, commit=f"- Commit: {commit or 'nieznany'}"),
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
    return _report(message, lines, fingerprint)


def update_report_of(
    result: UpdateResult, message: Message, *, log_entries: list[str], previous: int | None = None
) -> Report:
    """Zgłoszenie nieudanej Aktualizacji narzędzia: Komunikat i fakty wpisu ``aktualizacja-koniec`` dziennika."""

    fingerprint = ProblemFingerprint.of_tool_update(message).digest
    lines = [
        *_message_lines(message),
        "## Aktualizacja narzędzia",
        "",
        f"- Wynik: {result.code}",
        f"- Commit przed: {result.before or 'nieznany'}",
        f"- Commit po: {result.after or 'brak'}",
        f"- Biblioteki instalowane: {'tak' if result.installed else 'nie'}",
        "",
        *_tool_lines(fingerprint, previous),
        "## Dziennik Centrum rozliczeń",
        "",
        "```text",
        *log_entries,
        "```",
    ]
    return _report(message, lines, fingerprint)


def _message_lines(message: Message) -> list[str]:
    """Początek każdego Zgłoszenia: Komunikat z kodem i trzema częściami."""

    return [
        "Zgłoszenie z Centrum rozliczeń.",
        "",
        "## Komunikat",
        "",
        f"- Kod: {message.code}",
        f"- Co się stało: {message.what}",
        f"- Gdzie: {message.where}",
        f"- Co zrobić: {message.action}",
        "",
    ]


def _tool_lines(fingerprint: str, previous: int | None, *, commit: str | None = None) -> list[str]:
    """Sekcja narzędzia: wersja, ``commit`` (gotowy wiersz, jeśli jest), odcisk problemu i poprzednie Zgłoszenie."""

    return [
        "## Narzędzie",
        "",
        f"- Wersja: {tool_version()}",
        *([] if commit is None else [commit]),
        fingerprint_line(fingerprint),
        *([] if previous is None else [f"- Poprzednie Zgłoszenie: #{previous}"]),
        "",
    ]


def _report(message: Message, lines: list[str], fingerprint: str) -> Report:
    """Zgłoszenie z tytułem z kodu i „Co się stało” Komunikatu."""

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


def _replace_atomically(path: Path, text: str) -> None:
    """Zapisuje ``text`` jako ``path`` przez plik tymczasowy w tym samym folderze.

    Nieudany zapis (``OSError``) nie zostawia pustego ani urwanego pliku i nie niszczy poprzedniej treści.
    """

    temporary = path.with_name(path.name + ".tmp")
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        temporary.write_text(text, encoding="utf-8")
        temporary.replace(path)
    except OSError:
        with suppress(OSError):
            temporary.unlink(missing_ok=True)
        raise


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
        try:
            _replace_atomically(self._path, json.dumps([asdict(report) for report in reports], indent=2) + "\n")
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
class _ReportLog:
    """Wpisy dziennika Centrum o wysyłce jednego podglądu: z Uruchomienia albo z Aktualizacji narzędzia."""

    sent: Callable[[int], None]
    waiting: Callable[[int], None]
    saved: Callable[[str], None]
    not_saved: Callable[[str], None]

    @classmethod
    def of_run(cls, log: CentrumLog, process: str, period: str) -> _ReportLog:
        return cls(
            sent=lambda number: log.report_sent(process=process, period=period, number=number),
            waiting=lambda number: log.report_waiting(process=process, period=period, number=number),
            saved=lambda code: log.report_saved(process=process, period=period, code=code),
            not_saved=lambda cause: log.report_not_saved(process=process, period=period, cause=cause),
        )

    @classmethod
    def of_update(cls, log: CentrumLog) -> _ReportLog:
        return cls(
            sent=lambda number: log.update_report_sent(number=number),
            waiting=lambda number: log.update_report_waiting(number=number),
            saved=lambda code: log.update_report_saved(code=code),
            not_saved=lambda cause: log.update_report_not_saved(cause=cause),
        )


@dataclass(frozen=True)
class _Draft:
    """Podgląd Zgłoszenia, jego wpisy w dzienniku i nazwa pliku na wypadek nieudanej wysyłki.

    ``key`` to Uruchomienie (jego identyfikator) albo Aktualizacja narzędzia.
    """

    key: str
    report: Report
    file_name: str
    logged: _ReportLog


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
        # Blokada chroni tylko stan w pamięci i pliki stanu; pytania do skrzynki idą bez niej.
        self._lock = threading.Lock()
        self._changed = threading.Condition(self._lock)
        self._draft: _Draft | None = None  # z ostatniej Diagnozy
        self._update_draft: _Draft | None = None  # z ostatniej nieudanej Aktualizacji narzędzia
        self._sent_drafts: set[str] = set()  # ``_Draft.key`` podglądów wysłanych w tej pracy Centrum
        self._sending: set[str] = set()  # ``_Draft.key`` podglądów, które właśnie idą do skrzynki
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
            self._draft = _Draft(info.id, report, file_name, _ReportLog.of_run(self._log, info.process, info.period))
            state = contract.ReportSent(state="sent") if info.id in self._sent_drafts else self._state_of(fingerprint)
        return contract.ReportDraft(title=report.title, body=report.body), state

    def draft_update(self, result: UpdateResult, message: Message) -> tuple[contract.ReportDraft, contract.ReportState]:
        """Zgłoszenie nieudanej Aktualizacji narzędzia, które wyśle „Wyślij do Maksa”, i ostatni znany stan.

        Skrzynki nie pyta (start Centrum po cofnięciu nie czeka na sieć); pyta ją ``update_report_state``.
        Wpis ``aktualizacja-koniec`` jest już w dzienniku, więc Zgłoszenie ma go wśród ostatnich wpisów.
        """

        fingerprint = ProblemFingerprint.of_tool_update(message).digest
        previous = self._sent.find(fingerprint)
        report = update_report_of(
            result,
            message,
            log_entries=self._log.recent(_UPDATE_LOG_ENTRIES),
            previous=previous.number if previous else None,
        )
        with self._lock:
            self._update_draft = _Draft(
                _UPDATE_KEY, report, f"Zgłoszenie {message.code} aktualizacja.md", _ReportLog.of_update(self._log)
            )
            self._sent_drafts.discard(_UPDATE_KEY)  # nowa porażka: jej Zgłoszenie jeszcze nie wyszło
            state = self._state_of(fingerprint)
        return contract.ReportDraft(title=report.title, body=report.body), state

    def update_report_state(self) -> contract.ReportState:
        """Stan Zgłoszenia ostatniej nieudanej Aktualizacji narzędzia po pytaniu skrzynki (``_ask_box``)."""

        with self._lock:
            draft = self._update_draft
        if draft is None:
            return contract.ReportReady(state="ready")
        self._ask_box(draft.report.fingerprint)
        with self._lock:
            if _UPDATE_KEY in self._sent_drafts:
                return contract.ReportSent(state="sent")
            return self._state_of(draft.report.fingerprint)

    def send(self, stopped: StoppedRun) -> contract.ReportState:
        """Wysyła podgląd z Diagnozy ``stopped``, chyba że skrzynka ma już otwarte Zgłoszenie tego problemu.

        Gdy się nie uda, zapisuje Zgłoszenie w pliku i mówi, co dalej.
        """

        return self._send(
            stopped.info.id, lambda: self._draft, "Zgłoszenie powstaje z Diagnozy. Najpierw kliknij „Diagnoza”."
        )

    def send_update(self) -> contract.ReportState:
        """Wysyła podgląd z ostatniej nieudanej Aktualizacji narzędzia, tak samo jak ``send``."""

        return self._send(_UPDATE_KEY, lambda: self._update_draft, NO_FAILED_UPDATE)

    def _send(self, key: str, current: Callable[[], _Draft | None], refusal: str) -> contract.ReportState:
        """Wysyła podgląd ``current()`` o kluczu ``key`` najwyżej raz; bez takiego podglądu odmowa ``refusal``."""

        with self._changed:
            while key in self._sending:  # drugie kliknięcie czeka na wynik pierwszego
                self._changed.wait()
            draft = current()
            if draft is None or draft.key != key:
                raise contract.Refusal(409, refusal)
            if key in self._sent_drafts:
                return contract.ReportSent(state="sent")
            self._sending.add(key)
        try:
            return self._deliver(draft)
        finally:
            with self._changed:
                self._sending.discard(key)
                self._changed.notify_all()

    def _deliver(self, draft: _Draft) -> contract.ReportState:
        """Wysyła ``draft``, gdy skrzynka nie ma otwartego Zgłoszenia tego problemu; inaczej zapisuje plik."""

        key = self._key()
        outcome: SendOutcome | None = None
        if key is not None:
            found = self._box.find_open(draft.report.fingerprint, key=key)
            if isinstance(found, int):
                with self._lock:
                    self._open[draft.report.fingerprint] = found
                draft.logged.waiting(found)
                return contract.ReportWaiting(state="waiting")
            outcome = self._box.send(draft.report, key=key) if found is None else found
        saved = self._unsent / draft.file_name
        if isinstance(outcome, Sent):
            with self._lock:
                self._sent.add(SentReport(draft.report.fingerprint, outcome.number, self._commit()))
                self._open[draft.report.fingerprint] = outcome.number
                self._sent_drafts.add(draft.key)
            draft.logged.sent(outcome.number)
            try:
                saved.unlink(missing_ok=True)
            except OSError as failure:  # np. plik otwarty w Windows: zostaje w folderze, Zgłoszenie i tak wysłane
                self._log.unexpected_failure(failure, where="usunięcie niewysłanego Zgłoszenia")
            return contract.ReportSent(state="sent")
        unsent = (
            report_messages.key_missing(saved)
            if outcome is None
            else report_messages.key_refused(saved)
            if isinstance(outcome, Refused)
            else report_messages.box_unreachable(saved)
        )
        try:
            _replace_atomically(saved, f"# {draft.report.title}\n\n{draft.report.body}")
        except OSError as failure:  # np. folder Zgłoszeń niedostępny: treść zostaje tylko w podglądzie Diagnozy
            self._log.unexpected_failure(failure, where="zapis niewysłanego Zgłoszenia")
            draft.logged.not_saved(unsent.code)
            message = report_messages.not_saved(self._unsent)
            return contract.ReportSaved(state="saved", message=contract.Message.of(message))
        draft.logged.saved(unsent.code)
        return contract.ReportSaved(state="saved", message=contract.Message.of(unsent))

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
        key = self._key()
        with self._lock:
            waiting = [sent.number for sent in self._sent.all() if sent.commit == commit and sent.state == "open"]
            now = self._clock()
            due = self._states_asked_at is None or now - self._states_asked_at >= STATES_INTERVAL_S
            ask = bool(waiting) and key is not None and due
            if ask:
                self._states_asked_at = now  # rezerwuje pytanie: równoległy odczyt nie pyta drugi raz
        if ask and key is not None:
            states = self._box.states(waiting, key=key)
            if not isinstance(states, Refused | Unreachable):
                with self._lock:
                    self._sent.mark(states)
        with self._lock:
            repaired = any(sent.commit == commit and sent.state == "closed" for sent in self._sent.all())
        return contract.RepairNotice(repaired=repaired)

    def check_repairs_in_background(self) -> None:
        """Przy starcie Centrum pierwsze pytanie o stan wysłanych Zgłoszeń, w tle, żeby start nie czekał na sieć."""

        threading.Thread(target=self._check_repairs, name="zgloszenia-przy-starcie", daemon=True).start()

    def _check_repairs(self) -> None:
        try:
            self.repair_notice()
        except Exception as failure:  # noqa: BLE001 - granica wątku startu: typ wyjątku trafia do dziennika Centrum
            self._log.unexpected_failure(failure, where="stan Zgłoszeń przy starcie")

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
            key = self._key_file.read_text(encoding="utf-8-sig").strip()  # Notatnik i PowerShell 5.1 dopisują BOM
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

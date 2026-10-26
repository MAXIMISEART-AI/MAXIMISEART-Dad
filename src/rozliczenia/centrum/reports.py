"""Zgłoszenie do Maksa: treść, wysyłka do skrzynki Zgłoszeń i stan na tym komputerze.

Treść Zgłoszenia powstaje tylko tutaj, z tych samych bezpiecznych faktów co
Komunikat. Zgłoszenie Zatrzymania (``StopReport``) ma Komunikat z kodem i
trzema częściami, proces, okres i tryb, odnośnik do Logów Uruchomienia, commit
narzędzia, wynik każdego sprawdzenia Diagnozy i ostatnie wpisy dziennika
Centrum, a przy nieoczekiwanym wyjątku jego typ i ślad wywołań w kodzie
narzędzia. Zgłoszenie nieudanej Aktualizacji narzędzia (``UpdateReport``) ma
te same fakty co dziennik Centrum:
kod Komunikatu, commit przed i po, czy instalowano biblioteki i ostatnie wpisy
dziennika, bez ścieżek i bez wyjścia Gita. Ścieżki są już skrócone w
Komunikatach, szczegółach sprawdzeń i ramkach śladu; treści wierszy, treści
wyjątków ani klucza Zgłoszenie nie ma (ADR 0007).

Źródło Zgłoszenia (Zatrzymanie w ``stops``, nieudana Aktualizacja narzędzia w
``tool_updates``) trzyma jego uchwyt (``ReportHandle``): uchwyt zamraża podgląd,
a „Wyślij do Maksa” wysyła dokładnie ten podgląd, najwyżej raz na uchwyt.
"""

from __future__ import annotations

import codecs
import threading
from collections.abc import Callable
from dataclasses import astuple, dataclass
from datetime import datetime, timezone
import hashlib
from pathlib import Path
from typing import Final, Literal

from rozliczenia.call_trace import CallTrace
from rozliczenia.centrum import contract, report_messages
from rozliczenia.centrum.atomic_file import replace_atomically
from rozliczenia.centrum.dad_cases import REPORT, Case, DadCases
from rozliczenia.centrum.deadline import within
from rozliczenia.centrum.diagnosis import Diagnosis
from rozliczenia.centrum.log import CentrumLog
from rozliczenia.centrum.report_box import FindOutcome, Refused, ReportBox, SendOutcome, Sent, find_issue
from rozliczenia.centrum.tool_freshness import CommitSource
from rozliczenia.centrum.tool_update import UpdateResult
from rozliczenia.message import Message
from rozliczenia.process_run import Stop

REPORT_KEY_FILE: Final = "zgloszenia-klucz.txt"
UNSENT_DIRECTORY: Final = "zgloszenia"
# Podgląd Zgłoszenia czeka w tle na odpowiedź skrzynki o otwarte Zgłoszenie najwyżej tyle, co Diagnoza na commit `main`.
SEARCH_DEADLINE_S: Final = 3.0

# Zgłoszenie nieudanej Aktualizacji narzędzia ma tyle ostatnich wpisów dziennika co Zgłoszenie z Diagnozy.
_UPDATE_LOG_ENTRIES: Final = 20

_CHECK_STATES: Final = {"passed": "przeszło", "failed": "nie przeszło", "not_checked": "nie sprawdzono"}


@dataclass(frozen=True)
class Report:
    """Zgłoszenie: tytuł (kod i „Co się stało”), treść Markdown, odcisk problemu, po którym je rozpoznać, i samo
    „Co się stało”, którym Powiadomienie nazywa Zgłoszenie."""

    title: str
    body: str
    fingerprint: str
    what: str


@dataclass(frozen=True)
class ProblemFingerprint:
    """Odcisk problemu: proces (albo Aktualizacja narzędzia), kod Komunikatu i jego trzy części.

    Kody są unikalne tylko w katalogu procesu, więc odcisk zawiera proces.
    """

    process: contract.ProcessKey | Literal["tool_update"]
    code: str
    what: str
    where: str
    action: str

    @classmethod
    def of(cls, process: contract.ProcessKey, message: Message) -> ProblemFingerprint:
        return cls(process, message.code, message.what, message.where, message.action)

    @classmethod
    def of_tool_update(cls, message: Message) -> ProblemFingerprint:
        """Odcisk problemu nieudanej Aktualizacji narzędzia: jej kody są unikalne w jej własnym katalogu."""

        return cls("tool_update", message.code, message.what, message.where, message.action)

    @property
    def digest(self) -> str:
        """Stały skrót odcisku do Zgłoszenia i lokalnego stanu wysłanych; bez treści Komunikatu."""

        return hashlib.sha256("\x1f".join(astuple(self)).encode("utf-8")).hexdigest()[:16]


@dataclass(frozen=True)
class StopReport:
    """Zgłoszenie Zatrzymania z Diagnozy.

    ``logs``: adres komentarza Logów Uruchomienia w Skrzynce Zgłoszeń z chwili Diagnozy; ``None``: Logi nie były
    jeszcze w Skrzynce (zwykle czekały w kolejce). Ustalony przy Diagnozie, więc wysłane Zgłoszenie jest dokładnie
    podglądem, który widział tata.
    """

    run: contract.RunInfo
    stop: Stop
    fingerprint: ProblemFingerprint
    diagnosis: Diagnosis
    logs: str | None

    @property
    def file_name(self) -> str:
        return f"Zgłoszenie {self.stop.message.code} {self.run.period}.md"

    def logged(self, log: CentrumLog) -> _ReportLog:
        return _ReportLog.of_run(log, self.run.process, self.run.period)

    def report(self, *, commit: str | None, previous: int | None) -> Report:
        run, message, diagnosis = self.run, self.stop.message, self.diagnosis
        fingerprint = self.fingerprint.digest
        explanation = diagnosis.explanation
        lines = [
            *_message_lines(message),
            "## Uruchomienie procesu",
            "",
            f"- Proces: {run.title}",
            f"- Okres: {run.period}",
            f"- Tryb: {run.mode}",
            f"- Logi: {self.logs or f'jeszcze niewysłane, Uruchomienie {run.id}'}",
            "",
            *_trace_lines(self.stop.trace),
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


@dataclass(frozen=True)
class UpdateReport:
    """Zgłoszenie nieudanej Aktualizacji narzędzia: Komunikat i fakty wpisu ``aktualizacja-koniec`` dziennika."""

    result: UpdateResult
    message: Message
    log_entries: tuple[str, ...]
    fingerprint: ProblemFingerprint

    @classmethod
    def of(cls, result: UpdateResult, message: Message, log: CentrumLog) -> UpdateReport:
        return cls(result, message, tuple(log.recent(_UPDATE_LOG_ENTRIES)), ProblemFingerprint.of_tool_update(message))

    @property
    def file_name(self) -> str:
        return f"Zgłoszenie {self.message.code} aktualizacja.md"

    def logged(self, log: CentrumLog) -> _ReportLog:
        return _ReportLog.of_update(log)

    def report(self, *, commit: str | None, previous: int | None) -> Report:
        result, fingerprint = self.result, self.fingerprint.digest
        lines = [
            *_message_lines(self.message),
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
            *self.log_entries,
            "```",
        ]
        return _report(self.message, lines, fingerprint)


def fingerprint_line(fingerprint: str) -> str:
    """Wiersz treści Zgłoszenia z odciskiem problemu, po którym Centrum znajduje otwarte Zgłoszenie w skrzynce."""

    return f"- Odcisk problemu: {fingerprint}"


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
    """Sekcja narzędzia: ``commit`` (gotowy wiersz, jeśli jest), odcisk problemu i poprzednie Zgłoszenie."""

    return [
        "## Narzędzie",
        "",
        *([] if commit is None else [commit]),
        fingerprint_line(fingerprint),
        *([] if previous is None else [f"- Poprzednie Zgłoszenie: #{previous}"]),
        "",
    ]


def _report(message: Message, lines: list[str], fingerprint: str) -> Report:
    """Zgłoszenie z tytułem z kodu i „Co się stało” Komunikatu."""

    return Report(
        title=f"{message.code}: {message.what}", body="\n".join(lines) + "\n", fingerprint=fingerprint, what=message.what
    )


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
class _Preview:
    """Zamrożony podgląd Zgłoszenia, jego wpisy w dzienniku i nazwa pliku na wypadek nieudanej wysyłki."""

    report: Report
    file_name: str
    logged: _ReportLog

    @property
    def view(self) -> contract.ReportDraft:
        return contract.ReportDraft(title=self.report.title, body=self.report.body)


ReportShown = Callable[[contract.ReportState], None]
"""Właściciel Zgłoszenia, który pokazuje każdy jego nowy stan (np. karta Uruchomienia przez ``RunHost``)."""


class NoPreview(Exception):
    """„Wyślij do Maksa” przed pierwszym podglądem: nie ma czego wysłać."""


class ReportHandle:
    """Zgłoszenie jednego problemu z jednego źródła (Zatrzymanie, nieudana Aktualizacja narzędzia), od podglądu do wysyłki.

    ``prepare`` zamraża podgląd i pyta skrzynkę Zgłoszeń w tle o otwarte Zgłoszenie tego problemu, a ``send``
    wysyła ostatni podgląd najwyżej raz; drugie kliknięcie w trakcie wysyłki czeka na jej wynik. Po każdej
    odpowiedzi skrzynki i każdej wysyłce nowy stan dostaje ``shown`` właściciela. Odpowiedź na pytanie sprzed
    wysyłki przepada, bo stan to już wynik wysyłki. ``shown`` biegnie pod blokadą uchwytu, więc dostaje stany w
    kolejności ich zmian, i nie woła uchwytu. Właściciel, który pokazuje stan dopiero po odpowiedzi skrzynki,
    czeka na nią przez ``wait_for_box``.
    """

    def __init__(self, reports: Reports, fingerprint: str, shown: ReportShown | None) -> None:
        self._reports = reports
        self._fingerprint = fingerprint
        self._shown = shown
        self._changed = threading.Condition()
        self._state = reports._state_of(fingerprint)
        self._preview: _Preview | None = None
        self._asking: threading.Thread | None = None
        self._sends = 0  # wysyłki zaczęte do tej pory: odpowiedź skrzynki na pytanie sprzed wysyłki przepada
        self._sending = False

    @property
    def state(self) -> contract.ReportState:
        """Ostatni znany stan: czeka na naprawę, gotowe do wysłania, wysłane albo zapisane w pliku."""

        with self._changed:
            return self._state

    def prepare(self, source: StopReport | UpdateReport) -> contract.ReportDraft:
        """Nowy podgląd ``source``, który wyśle ``send``; nie czeka na skrzynkę i niczego nie zapisuje.

        Gdy ten problem był już zgłoszony z tego komputera, Zgłoszenie ma odnośnik do ostatniego z nich.
        """

        preview = self._reports._preview(source)
        with self._changed:
            self._preview = preview
            asking = self._asking = threading.Thread(
                target=self._ask, args=(self._sends,), name="zgloszenie-skrzynka", daemon=True
            )
        asking.start()
        return preview.view

    def wait_for_box(self) -> None:
        """Czeka na odpowiedź skrzynki na pytanie z ostatniego ``prepare``, najwyżej termin szukania w skrzynce."""

        with self._changed:
            asking = self._asking
        if asking is not None:
            asking.join()

    def _ask(self, sends: int) -> None:
        self._reports._ask_box(self._fingerprint)
        with self._changed:
            if sends == self._sends:
                self._show(self._state if self._sent else self._reports._state_of(self._fingerprint))

    def send(self) -> contract.ReportState:
        """Wysyła ostatni podgląd, chyba że już wysłany albo skrzynka ma otwarte Zgłoszenie tego problemu.

        Gdy wysyłka się nie uda, zapisuje Zgłoszenie w pliku i mówi, co dalej. ``NoPreview``, gdy podglądu nie ma.
        """

        with self._changed:
            while self._sending:
                self._changed.wait()
            preview = self._preview
            if preview is None:
                raise NoPreview
            if self._sent:
                return self._state
            self._sending = True
            self._sends += 1
        state: contract.ReportState | None = None
        try:
            state = self._reports._deliver(preview)
            return state
        finally:
            with self._changed:
                self._sending = False
                if state is not None:
                    self._show(state)
                self._changed.notify_all()

    @property
    def _sent(self) -> bool:
        return isinstance(self._state, contract.ReportSent)

    def _show(self, state: contract.ReportState) -> None:
        self._state = state
        if self._shown is not None:
            self._shown(state)


class Reports:
    """Zgłoszenia z tego komputera: uchwyt Zgłoszenia każdego źródła, wysyłka i stan wysłanych.

    Klucz i niewysłane Zgłoszenia leżą w katalogu konfiguracji obok Ustawień
    taty, poza Gitem, a wysłane są Sprawami taty. Jeden problem ma jedno otwarte Zgłoszenie:
    podgląd i wysyłka pytają skrzynkę o otwarte Zgłoszenie z tym samym odciskiem,
    a gdy jest, nowe nie powstaje. Bez odpowiedzi skrzynki (brak klucza albo
    sieci) problem wysłany z tego komputera czeka na naprawę.
    """

    def __init__(
        self,
        config_directory: Path,
        box: ReportBox,
        log: CentrumLog,
        commit: CommitSource,
        cases: DadCases,
        *,
        search_deadline_s: float,
    ) -> None:
        self._commit = commit
        self._search_deadline_s = search_deadline_s
        self._config_directory = config_directory
        self._unsent = config_directory / UNSENT_DIRECTORY
        self._cases = cases
        self._box = box
        self._log = log
        # Blokada chroni tylko stan w pamięci; pytania do skrzynki idą bez niej.
        self._lock = threading.Lock()
        # Ostatnia odpowiedź skrzynki w tej pracy Centrum: odcisk problemu → numer otwartego Zgłoszenia albo None.
        self._open: dict[str, int | None] = {}

    def handle(self, fingerprint: ProblemFingerprint, *, shown: ReportShown | None = None) -> ReportHandle:
        """Uchwyt Zgłoszenia problemu ``fingerprint`` bez podglądu; stan bez pytania skrzynki.

        ``shown`` dostaje każdy nowy stan; właściciel, który czyta ``ReportHandle.state`` sam, go nie podaje.
        """

        return ReportHandle(self, fingerprint.digest, shown)

    def _preview(self, source: StopReport | UpdateReport) -> _Preview:
        fingerprint = source.fingerprint.digest
        previous = self._cases.find(REPORT, fingerprint)
        report = source.report(commit=self._commit(), previous=previous.number if previous else None)
        return _Preview(report, source.file_name, source.logged(self._log))

    def _deliver(self, preview: _Preview) -> contract.ReportState:
        """Wysyła ``preview``, gdy skrzynka nie ma otwartego Zgłoszenia tego problemu; inaczej zapisuje plik."""

        key = self._key()
        outcome: SendOutcome | None = None
        if key is not None:
            found = self._find_open(preview.report.fingerprint, key)
            if isinstance(found, int):
                with self._lock:
                    self._open[preview.report.fingerprint] = found
                preview.logged.waiting(found)
                return contract.ReportWaiting(state="waiting")
            outcome = (
                self._box.open_issue(REPORT.label, preview.report.title, preview.report.body, key=key)
                if found is None
                else found
            )
        saved = self._unsent / preview.file_name
        if isinstance(outcome, Sent):
            with self._lock:
                self._cases.add(
                    Case(
                        REPORT,
                        preview.report.fingerprint,
                        preview.report.what,
                        self._commit(),
                        datetime.now(timezone.utc),
                        outcome.number,
                    )
                )
                self._open[preview.report.fingerprint] = outcome.number
            preview.logged.sent(outcome.number)
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
            replace_atomically(saved, f"# {preview.report.title}\n\n{preview.report.body}")
        except OSError as failure:  # np. folder Zgłoszeń niedostępny: treść zostaje tylko w podglądzie Diagnozy
            self._log.unexpected_failure(failure, where="zapis niewysłanego Zgłoszenia")
            preview.logged.not_saved(unsent.code)
            message = report_messages.not_saved(self._unsent)
            return contract.ReportSaved(state="saved", message=contract.Message.of(message))
        preview.logged.saved(unsent.code)
        return contract.ReportSaved(state="saved", message=contract.Message.of(unsent))

    def _ask_box(self, fingerprint: str) -> None:
        """Pyta skrzynkę o otwarte Zgłoszenie problemu; bez klucza albo odpowiedzi zostaje to, co już wiadomo.

        Brak odpowiedzi w ``search_deadline_s`` (u taty ``SEARCH_DEADLINE_S``) to brak odpowiedzi: spóźniona
        przepada, a wysyłka i tak pyta skrzynkę, zanim założy Zgłoszenie.
        """

        key = self._key()
        if key is None:
            return
        answer = within(self._search_deadline_s, lambda: (self._find_open(fingerprint, key),), name="skrzynka-szukaj")
        if answer is None:
            return
        [found] = answer
        if found is None or isinstance(found, int):
            with self._lock:
                self._open[fingerprint] = found

    def _find_open(self, fingerprint: str, key: str) -> FindOutcome:
        return find_issue(self._box, REPORT.label, fingerprint_line(fingerprint), include_closed=False, key=key)

    def _state_of(self, fingerprint: str) -> contract.ReportState:
        """Odpowiedź skrzynki z tej pracy Centrum, a bez niej ostatni znany stan wysłanego Zgłoszenia.

        Zgłoszenie, o którym wiadomo, że Maks je zamknął, nie czeka na naprawę.
        """

        if fingerprint in self._open:
            waiting = self._open[fingerprint] is not None
        else:
            sent = self._cases.find(REPORT, fingerprint)
            waiting = sent is not None and sent.closure is None
        return contract.ReportWaiting(state="waiting") if waiting else contract.ReportReady(state="ready")

    def key_state(self) -> contract.ReportKeyState:
        return "ready" if self._key() is not None else "missing_key"

    def _key(self) -> str | None:
        return read_report_key(self._config_directory)


def read_report_key(config_directory: Path) -> str | None:
    """Klucz do Skrzynki Zgłoszeń z lokalnego pliku; ``None``, gdy pliku nie ma albo jest pusty."""

    try:
        content = (config_directory / REPORT_KEY_FILE).read_bytes()
        # Notatnik dopisuje BOM UTF-8, a ``>`` i ``Out-File`` w PowerShell 5.1 zapisują UTF-16 z BOM.
        encoding = "utf-16" if content.startswith((codecs.BOM_UTF16_LE, codecs.BOM_UTF16_BE)) else "utf-8-sig"
        key = content.decode(encoding).strip()
    except (OSError, UnicodeError):
        return None
    return key or None


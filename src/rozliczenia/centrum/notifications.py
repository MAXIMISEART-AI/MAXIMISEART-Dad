"""Powiadomienia (ADR 0015): co stało się z Uwagami taty i Zgłoszeniami wysłanymi z tego komputera.

Sprawa taty to Uwaga taty (``DadNotes``) albo wysłane Zgłoszenie (``SentReports``); każda pamięta numer issue i
ostatnie znane zamknięcie przez Maksa. Jej stan w Powiadomieniu wynika tylko z tabeli ``_CASE_STATES``: czy czeka w
kolejce, czy issue jest zamknięte i z jakim ``state_reason``. Powiadomienie to sprawa w jednym stanie, więc nowy stan
to nowe Powiadomienie. Nowe są tylko stany, które dał Maks (rozwiązana, przeczytana); wysłanie i czekanie w kolejce
to czynność taty i kropki na dzwonku nie zapala.

Centrum pyta Skrzynkę Zgłoszeń o zamknięcie otwartych spraw przy starcie, w tle, i przy odczycie Powiadomień, gdy od
ostatniego pytania minęło ``CHECK_INTERVAL_S``; bez otwartych spraw albo bez klucza nie pyta. Odczyt czeka na trwające
pytanie najwyżej ``CHECK_WAIT_S`` i odpowiada ostatnim znanym stanem, a spóźniona odpowiedź i tak zapisuje stan. Brak
sieci albo odmowa przechodzą po cichu, bez Komunikatu. Przeczytane Powiadomienia (ich ``id``) leżą w
``config/powiadomienia.json`` poza Gitem i przetrwają restart Centrum.
"""

from __future__ import annotations

import json
import threading
from collections.abc import Callable, Iterable, Mapping
from datetime import datetime
from pathlib import Path
from typing import Final

from fastapi import APIRouter

from rozliczenia.centrum import contract
from rozliczenia.centrum.dad_notes import NOTE_LABEL, DadNote, DadNotes
from rozliczenia.centrum.log import CentrumLog
from rozliczenia.centrum.report_box import REPORT_LABEL, Closure, CloseReason, Label, Refused, ReportBox, Unreachable
from rozliczenia.centrum.atomic_file import replace_atomically
from rozliczenia.centrum.reports import SentReport, SentReports

NOTIFICATIONS_FILE: Final = "powiadomienia.json"
SCHEMA_VERSION: Final = 1
# Skrzynkę Zgłoszeń o stan spraw taty Centrum pyta najwyżej raz na 10 minut.
CHECK_INTERVAL_S: Final = 10 * 60
# Tyle odczyt Powiadomień czeka na trwające pytanie skrzynki, zanim odpowie ostatnim znanym stanem.
CHECK_WAIT_S: Final = 3.0

# (czeka w kolejce, issue zamknięte, state_reason) → stan sprawy. GitHub zamyka issue bez powodu jako ``completed``,
# a duplikat to sprawa przeczytana bez zmian.
_CASE_STATES: Final[Mapping[tuple[bool, bool, CloseReason | None], contract.CaseState]] = {
    (True, False, None): "czeka_na_internet",
    (False, False, None): "wyslana",
    (False, True, "completed"): "rozwiazana",
    (False, True, None): "rozwiazana",
    (False, True, "not_planned"): "przeczytana",
    (False, True, "duplicate"): "przeczytana",
}
# Stany, które dał Maks: tylko one są nowe dla taty, dopóki ich nie zobaczy.
_NEWS: Final[frozenset[contract.CaseState]] = frozenset({"rozwiazana", "przeczytana"})


def case_state(number: int | None, closure: Closure | None) -> contract.CaseState:
    """Stan sprawy taty: ``number`` ``None`` czeka w kolejce, ``closure`` ``None`` to otwarte issue."""

    return _CASE_STATES[(number is None, closure is not None, None if closure is None else closure.reason)]


class ReadNotifications:
    """Przeczytane Powiadomienia w ``config/`` poza Gitem, czytane raz przy starcie Centrum.

    Brak, uszkodzenie albo nieznany schemat pliku to brak przeczytanych. Nieudany zapis trafia do dziennika Centrum,
    a Powiadomienia zostają przeczytane do końca tej pracy Centrum.
    """

    def __init__(self, path: Path, log: CentrumLog) -> None:
        self._path = path
        self._log = log
        self._lock = threading.Lock()
        self._read = self._load()

    def __contains__(self, notification_id: str) -> bool:
        with self._lock:
            return notification_id in self._read

    def add(self, ids: Iterable[str]) -> None:
        with self._lock:
            added = set(ids) - self._read
            if not added:
                return
            self._read |= added
            document = {"schema_version": SCHEMA_VERSION, "przeczytane": sorted(self._read)}
            try:
                replace_atomically(self._path, json.dumps(document, ensure_ascii=False, indent=2) + "\n")
            except OSError as failure:
                self._log.unexpected_failure(failure, where="stan przeczytanych Powiadomień")

    def _load(self) -> set[str]:
        try:
            document = json.loads(self._path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, ValueError):
            return set()
        if not isinstance(document, dict) or document.get("schema_version") != SCHEMA_VERSION:
            return set()
        ids = document.get("przeczytane")
        return {entry for entry in ids if isinstance(entry, str)} if isinstance(ids, list) else set()


class Notifications:
    """Powiadomienia z Uwag taty i wysłanych Zgłoszeń, sprawdzanie ich stanu w skrzynce i przeczytane."""

    def __init__(
        self,
        reports: SentReports,
        notes: DadNotes,
        read: ReadNotifications,
        box: ReportBox,
        key: Callable[[], str | None],
        log: CentrumLog,
        *,
        clock: Callable[[], float],
    ) -> None:
        self._reports = reports
        self._notes = notes
        self._read = read
        self._box = box
        self._key = key
        self._log = log
        self._clock = clock
        self._lock = threading.Lock()
        self._asked_at: float | None = None  # od startu Centrum skrzynka nie była jeszcze pytana
        self._check: threading.Thread | None = None

    def view(self) -> contract.Notifications:
        """Powiadomienia od najnowszego; gdy pora, najpierw pyta skrzynkę (czeka najwyżej ``CHECK_WAIT_S``)."""

        check = self._start_check_if_due()
        if check is not None:
            check.join(CHECK_WAIT_S)
        return self._notifications()

    def mark_read(self, ids: Iterable[str]) -> contract.Notifications:
        """Zapamiętuje Powiadomienia, które tata zobaczył; nie pyta skrzynki."""

        self._read.add(ids)
        return self._notifications()

    def check_in_background(self) -> None:
        """Przy starcie Centrum pierwsze pytanie o stan spraw taty, w tle, żeby start nie czekał na sieć."""

        self._start_check_if_due()

    def _start_check_if_due(self) -> threading.Thread | None:
        """Pytanie skrzynki w tle, gdy pora (trwające też się liczy); ``None``, gdy nie ma na co czekać."""

        key = self._key()
        labels = self._open_labels()
        with self._lock:
            now = self._clock()
            due = self._asked_at is None or now - self._asked_at >= CHECK_INTERVAL_S
            if due and labels and key is not None:
                self._asked_at = now  # rezerwuje pytanie: równoległy odczyt nie pyta drugi raz
                self._check = threading.Thread(
                    target=self._ask, args=(labels, key), name="powiadomienia-skrzynka", daemon=True
                )
                self._check.start()
            return self._check

    def _open_labels(self) -> tuple[Label, ...]:
        """Etykiety, pod którymi tata ma wysłane sprawy, których Maks jeszcze nie zamknął."""

        reports = any(sent.closure is None for sent in self._reports.all())
        notes = any(note.number is not None and note.closure is None for note in self._notes.all())
        return tuple(label for label, open_cases in ((REPORT_LABEL, reports), (NOTE_LABEL, notes)) if open_cases)

    def _ask(self, labels: tuple[Label, ...], key: str) -> None:
        try:
            for label in labels:
                issues = self._box.labelled_issues(label, include_closed=True, key=key)
                if isinstance(issues, Refused | Unreachable):
                    continue
                closures = {issue.number: issue.closure for issue in issues}
                if label == NOTE_LABEL:
                    self._notes.mark(closures)
                else:
                    self._reports.mark(closures)
        except Exception as failure:
            self._log.unexpected_failure(failure, where="stan spraw w Powiadomieniach")

    def _notifications(self) -> contract.Notifications:
        notes = [self._note(note) for note in self._notes.all()]
        reports = [report for report in map(self._report, self._reports.all()) if report is not None]
        items: list[contract.DadNoteNotification | contract.ReportNotification] = [*notes, *reports]
        items.sort(key=lambda item: item.at, reverse=True)
        return contract.Notifications(unread=sum(item.unread for item in items), items=items)

    def _note(self, note: DadNote) -> contract.DadNoteNotification:
        state = case_state(note.number, note.closure)
        notification_id = f"uwaga-{note.id}-{state}"
        return contract.DadNoteNotification(
            kind="uwaga",
            id=notification_id,
            at=_moment(note.closure, note.written_at),
            unread=self._unread(notification_id, state),
            title=note.title,
            state=state,
        )

    def _report(self, sent: SentReport) -> contract.ReportNotification | None:
        """Powiadomienie o wysłanym Zgłoszeniu; wpis sprzed Powiadomień (bez „Co się stało”) go nie daje."""

        if sent.what is None or sent.sent_at is None:
            return None
        state = case_state(sent.number, sent.closure)
        notification_id = f"zgloszenie-{sent.number}-{state}"
        return contract.ReportNotification(
            kind="zgloszenie",
            id=notification_id,
            at=_moment(sent.closure, sent.sent_at),
            unread=self._unread(notification_id, state),
            what=sent.what,
            state=state,
        )

    def _unread(self, notification_id: str, state: contract.CaseState) -> bool:
        return state in _NEWS and notification_id not in self._read


def _moment(closure: Closure | None, sent_at: datetime) -> datetime:
    """Czas stanu sprawy: zamknięcie przez Maksa, a bez niego wysłanie przez tatę."""

    return closure.at if closure is not None and closure.at is not None else sent_at


def notifications_router(notifications: Notifications) -> APIRouter:
    router = APIRouter(prefix="/api/notifications", tags=["powiadomienia"])

    @router.get("", operation_id="getNotifications")
    def get_notifications() -> contract.Notifications:
        return notifications.view()

    @router.post("/read", operation_id="markNotificationsRead")
    def mark_read(read: contract.NotificationsRead) -> contract.Notifications:
        return notifications.mark_read(read.ids)

    return router

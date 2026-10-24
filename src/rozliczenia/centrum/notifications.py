"""Powiadomienia (ADR 0015): co stało się z Uwagami taty i Zgłoszeniami wysłanymi z tego komputera i nowe Wydania.

Sprawa taty to Uwaga taty albo wysłane Zgłoszenie (``DadCases``); jej stan w Powiadomieniu to ``Case.state``.
Powiadomienie to sprawa w jednym stanie, więc nowy stan to nowe Powiadomienie. Nowe są tylko stany, które dał Maks (rozwiązana, przeczytana); wysłanie i czekanie w kolejce
to czynność taty i kropki na dzwonku nie zapala.

Powiadomienie o nowej wersji to opublikowane Wydanie (GitHub Release) o numerze nie wyższym od najnowszego Wydania na
`main`, które wybiera Aktualność narzędzia (ADR 0014): wyższe spoza `main` się nie liczy. Niższego Centrum nie
sprawdza osobno (każde to pytanie do API); Release z notką zakłada tylko narzędzie Wydań, które sprawdza `main`.
Powiadomienie ma notkę „Co nowego”, sprawy wysłane z tego komputera, które rozwiązuje (``release_notes.parse``), a
najnowsze także przycisk Aktualizacji narzędzia, gdy pozwala na to ``offers_update``. Nowe (kropka na dzwonku) jest
tylko Wydanie z przyciskiem, czyli nowsze od wersji taty; starsze Wydania to historia i kropki nie zapalają.

Centrum pyta przy starcie, w tle, i przy odczycie Powiadomień, gdy od ostatniego pytania minęło ``CHECK_INTERVAL_S``:
GitHub o Wydania zawsze, Skrzynkę Zgłoszeń o zamknięcie otwartych spraw tylko przy otwartych sprawach i kluczu.
Najnowsze Wydanie na `main` daje ta sama pamiętana odpowiedź GitHuba co w Konfiguracji, więc obie nie pytają o nie dwa
razy; ta odpowiedź może mieć do 10 minut, więc nowe Wydanie pojawia się najpóźniej po 20 minutach. Odczyt czeka na trwające pytanie najwyżej ``CHECK_WAIT_S`` i odpowiada ostatnim znanym stanem, a spóźniona
odpowiedź i tak zapisuje stan. Brak sieci albo odmowa przechodzą po cichu, bez Komunikatu, z ostatnią znaną
odpowiedzią. Przeczytane Powiadomienia (ich ``id``) leżą w ``config/powiadomienia.json`` poza Gitem i przetrwają
restart Centrum.
"""

from __future__ import annotations

import json
import threading
from collections.abc import Callable, Iterable
from dataclasses import dataclass, replace
from datetime import datetime
from pathlib import Path
from typing import Final

from fastapi import APIRouter

from rozliczenia.centrum import contract
from rozliczenia.centrum.dad_cases import NOTE, Case, DadCases
from rozliczenia.centrum.log import CentrumLog
from rozliczenia.centrum.report_box import Closure, ReportBox
from rozliczenia.centrum.atomic_file import replace_atomically
from rozliczenia.centrum.release_notes import parse
from rozliczenia.centrum.tool_freshness import PublishedRelease, ReleaseSource, ToolFreshness, offers_update
from rozliczenia.centrum.tool_update import Release

NOTIFICATIONS_FILE: Final = "powiadomienia.json"
SCHEMA_VERSION: Final = 1
# Skrzynkę Zgłoszeń o stan spraw taty i GitHub o Wydania Centrum pyta najwyżej raz na 10 minut.
CHECK_INTERVAL_S: Final = 10 * 60
# Tyle odczyt Powiadomień czeka na trwające pytanie skrzynki i GitHuba, zanim odpowie ostatnim znanym stanem.
CHECK_WAIT_S: Final = 3.0

# Stany, które dał Maks: tylko one są nowe dla taty, dopóki ich nie zobaczy.
_NEWS: Final[frozenset[contract.CaseState]] = frozenset({"rozwiazana", "przeczytana"})


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


@dataclass(frozen=True)
class _Releases:
    """Ostatnia odpowiedź GitHuba o Wydaniach: najnowsze Wydanie na `main`, czy Centrum proponuje aktualizację do
    niego, i opublikowane Wydania; brak odpowiedzi zostawia poprzednią."""

    newest: Release | None = None
    offered: bool = False
    published: tuple[PublishedRelease, ...] = ()


class Notifications:
    """Powiadomienia z Uwag taty, wysłanych Zgłoszeń i Wydań, sprawdzanie ich stanu i przeczytane.

    ``release`` to odpowiedź GitHuba o najnowszym Wydaniu, pamiętana wspólnie z Konfiguracją.
    """

    def __init__(
        self,
        cases: DadCases,
        read: ReadNotifications,
        box: ReportBox,
        key: Callable[[], str | None],
        freshness: ToolFreshness,
        release: ReleaseSource,
        log: CentrumLog,
        *,
        clock: Callable[[], float],
    ) -> None:
        self._cases = cases
        self._read = read
        self._box = box
        self._key = key
        self._freshness = freshness
        self._release = release
        self._log = log
        self._clock = clock
        self._lock = threading.Lock()
        self._asked_at: float | None = None  # od startu Centrum nie było jeszcze pytania
        self._check: threading.Thread | None = None
        self._releases = _Releases()

    def view(self) -> contract.Notifications:
        """Powiadomienia od najnowszego; gdy pora, najpierw pyta skrzynkę i GitHub (czeka najwyżej ``CHECK_WAIT_S``)."""

        check = self._start_check_if_due()
        if check is not None:
            check.join(CHECK_WAIT_S)
        return self._notifications()

    def mark_read(self, ids: Iterable[str]) -> contract.Notifications:
        """Zapamiętuje Powiadomienia, które tata zobaczył; nie pyta skrzynki."""

        self._read.add(ids)
        return self._notifications()

    def check_in_background(self) -> None:
        """Przy starcie Centrum pierwsze pytanie o Wydania i stan spraw taty, w tle, żeby start nie czekał na sieć."""

        self._start_check_if_due()

    def _start_check_if_due(self) -> threading.Thread | None:
        """Pytanie skrzynki i GitHuba w tle, gdy pora (trwające też się liczy); ``None``, gdy nie ma na co czekać."""

        key = self._key()
        with self._lock:
            now = self._clock()
            if self._asked_at is None or now - self._asked_at >= CHECK_INTERVAL_S:
                self._asked_at = now  # rezerwuje pytanie: równoległy odczyt nie pyta drugi raz
                self._check = threading.Thread(
                    target=self._ask, args=(key,), name="powiadomienia-sprawdzanie", daemon=True
                )
                self._check.start()
            return self._check

    def _ask(self, key: str | None) -> None:
        if key is not None:
            self._ask_box(key)
        try:
            self._ask_github()
        except Exception as failure:
            self._log.unexpected_failure(failure, where="Wydania w Powiadomieniach")

    def _ask_github(self) -> None:
        """Najnowsze Wydanie na `main` i opublikowane Wydania; to, na co GitHub nie odpowiedział, zostaje bez zmian."""

        answer = self._release()
        published = self._freshness.published()
        known = self._releases
        if answer is not None:
            newest = None if answer.tag is None else Release.of_tag(answer.tag)
            # Commit narzędzia nie zmienia się do końca pracy Centrum, więc ocena zależy tylko od tej odpowiedzi.
            offered = offers_update(self._freshness.judge(lambda: answer))
            known = replace(known, newest=newest, offered=offered)
        if published is not None:
            known = replace(known, published=published)
        self._releases = known

    def _ask_box(self, key: str) -> None:
        try:
            self._cases.ask_box(self._box, key)
        except Exception as failure:
            self._log.unexpected_failure(failure, where="stan spraw w Powiadomieniach")

    def _notifications(self) -> contract.Notifications:
        cases = self._cases.all()
        items: list[contract.DadNoteNotification | contract.ReportNotification | contract.ReleaseNotification] = [
            *(notification for notification in map(self._case, cases) if notification is not None),
            *self._new_versions(cases),
        ]
        items.sort(key=lambda item: item.at, reverse=True)
        return contract.Notifications(unread=sum(item.unread for item in items), items=items)

    def _new_versions(self, cases: list[Case]) -> list[contract.ReleaseNotification]:
        """Opublikowane Wydania nie wyższe od najnowszego na `main`; przycisk ma tylko najnowsze.

        Sprawę z notki Wydania Powiadomienie nazywa tak, jak zna ją tata; sprawy wysłanej z innego komputera nie ma.
        """

        sent = {
            (case.kind.label, case.number): contract.SolvedCase(kind=case.kind.key, title=case.title)
            for case in cases
            if case.title is not None
        }
        known = self._releases
        newest = known.newest
        if newest is None:
            return []
        versions = []
        for published in known.published:
            release = published.release
            if release > newest:
                continue
            notes = parse(published.notes)
            notification_id = f"wydanie-{release.tag}"
            offered = known.offered and release == newest
            versions.append(
                contract.ReleaseNotification(
                    kind="nowa_wersja",
                    id=notification_id,
                    at=published.at,
                    unread=offered and notification_id not in self._read,
                    version=".".join(map(str, release.number)),
                    summary=notes.summary,
                    solved=[sent[case.label, case.number] for case in notes.cases if (case.label, case.number) in sent],
                    update_offered=offered,
                )
            )
        return versions

    def _case(self, case: Case) -> contract.DadNoteNotification | contract.ReportNotification | None:
        """Powiadomienie o sprawie; wpis Zgłoszenia sprzed Powiadomień (bez „Co się stało”) go nie daje."""

        if case.title is None or case.sent_at is None:
            return None
        state, at = case.state, _moment(case.closure, case.sent_at)
        if case.kind == NOTE:
            notification_id = f"uwaga-{case.id}-{state}"
            unread = self._unread(notification_id, state)
            return contract.DadNoteNotification(
                kind="uwaga", id=notification_id, at=at, unread=unread, title=case.title, state=state
            )
        notification_id = f"zgloszenie-{case.number}-{state}"
        unread = self._unread(notification_id, state)
        return contract.ReportNotification(
            kind="zgloszenie", id=notification_id, at=at, unread=unread, what=case.title, state=state
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

"""Uwaga taty (ADR 0015): treść issue, wysyłka przez kolejkę Skrzynki Zgłoszeń i stan Uwag na tym komputerze.

Treść issue powstaje tylko w ``note_issue``: podgląd „Maks dostanie” i wysyłka wołają tę samą funkcję, więc tata
widzi dokładnie to, co dostanie Maks. „Wyślij” zapisuje Uwagę bez numeru issue w ``config/uwagi-taty.json`` (poza
Gitem), kładzie ją w kolejce Skrzynki Zgłoszeń jako osobne issue z etykietą ``uwaga-taty`` i czeka na skrzynkę
najwyżej ``DELIVERY_WAIT_S``. Numer issue dopisuje wątek kolejki, także po następnym starcie Centrum, a zamknięcie
issue przez Maksa sprawdzanie Powiadomień. Plik stanu ma tylko tytuł Uwagi i przypięte Uruchomienie, bez treści.

Uwaga przypięta do Uruchomienia procesu z Centrum niesie w stopce jego proces, okres, tryb, wynik i datę oraz
odnośnik do jego Logów Uruchomienia w Skrzynce. Uruchomienia do wyboru i do przypięcia pochodzą z historii metryk
(``History``). Gdy Logi jeszcze czekają w kolejce, stopka mówi, że są w drodze, a ``with_logs`` wstawia odnośnik
tuż przed wysłaniem Uwagi z kolejki, jeśli Logi zdążyły dojść do skrzynki.
"""

from __future__ import annotations

import json
import threading
import uuid
from collections.abc import Callable, Mapping
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Final, assert_never

from fastapi import APIRouter

from rozliczenia.centrum import contract
from rozliczenia.centrum.atomic_file import replace_atomically
from rozliczenia.centrum.log import CentrumLog
from rozliczenia.centrum.outbox import NewIssue, Outbox, Post
from rozliczenia.centrum.report_box import Closure, Label, closure_json, read_closure
from rozliczenia.centrum.tool_freshness import CommitSource
from rozliczenia.centrum.version import version_label

DAD_NOTES_FILE: Final = "uwagi-taty.json"
NOTE_LABEL: Final[Label] = "uwaga-taty"
SCHEMA_VERSION: Final = 1
# Tyle „Wyślij” czeka na skrzynkę, zanim powie tacie, że Uwaga czeka w kolejce.
DELIVERY_WAIT_S: Final = 5.0
# Tyle najnowszych Uruchomień z Centrum okno Uwagi pokazuje do przypięcia.
RECENT_RUNS: Final = 6
_NOT_QUEUED: Final = "Uwaga się nie zapisała i nie pójdzie do Maksa. Spróbuj wysłać ją jeszcze raz."
_UNKNOWN_RUN: Final = (
    "Tego Uruchomienia nie ma już w historii Centrum rozliczeń. Wybierz inne Uruchomienie albo wyślij Uwagę ogólną."
)
_NO_HISTORY: Final = "Nie udało się odczytać historii Uruchomień. Odśwież kartę albo wyślij Uwagę ogólną."
_MODE_WORDS: Final[dict[contract.RunMode, str]] = {"DRY-RUN": "podgląd", "RUN": "zapis"}

History = Callable[[], list[contract.ProcessRun]]
"""Uruchomienia procesu z plików metryk od najnowszego (``metrics.read_runs``); ``OSError``: pliki nieczytelne."""
LogsAddress = Callable[[str], str | None]
"""Adres pierwszego komentarza Logów Uruchomienia o tym identyfikatorze w Skrzynce; ``None``: jeszcze ich tam nie ma."""


@dataclass(frozen=True)
class PinnedRun:
    """Uruchomienie z Centrum, do którego tata przypiął Uwagę (``run.run_id`` nie jest ``None``), i adres jego Logów.

    ``logs`` ``None``: Logi Uruchomienia jeszcze nie doszły do Skrzynki Zgłoszeń.
    """

    run: contract.ProcessRun
    logs: str | None


def note_issue(title: str, body: str, commit: str | None, pinned: PinnedRun | None) -> contract.DadNoteDraft:
    """Issue Uwagi taty: jej tytuł, a w treści jej tekst i stopka (bez tekstu sama stopka).

    Stopka Uwagi ogólnej to wersja narzędzia; przypiętej to linia Uruchomienia z wersją i linia jego Logów.
    """

    version = f"wersja narzędzia {version_label(commit)}"
    footer = f"Uwaga ogólna · {version}" if pinned is None else _pinned_footer(pinned, version)
    return contract.DadNoteDraft(title=title, body=f"{body}\n\n{footer}" if body else footer)


def _pinned_footer(pinned: PinnedRun, version: str) -> str:
    run = pinned.run
    started = run.started_at.astimezone()
    facts = (run.process_label, run.period, _MODE_WORDS[run.mode], _result_word(run), f"{started:%d.%m.%Y, %H:%M}")
    return f"Uruchomienie: {' · '.join((*facts, version))}\n{_logs_line(str(run.run_id), pinned.logs)}"


def _result_word(run: contract.ProcessRun) -> str:
    """Wynik słowem jak na karcie Uruchomienia (``RunResultBadge``): błąd to tylko Zatrzymanie „do Maksa”."""

    match run.result:
        case "OK":
            return "OK"
        case "WYMAGA_SPRAWDZENIA":
            return "do sprawdzenia"
        case "BLAD_KRYTYCZNY":
            return "błąd" if run.stop_kind == "for_maks" else "zatrzymano"
        case _:
            assert_never(run.result)


def _logs_line(run_id: str, logs: str | None) -> str:
    """Linia Logów przypiętej Uwagi: odnośnik albo „w drodze”, którą ``with_logs`` zamienia na odnośnik."""

    return f"Logi Uruchomienia: {logs}" if logs is not None else f"Logi Uruchomienia: w drodze (Uruchomienie {run_id})"


@dataclass(frozen=True)
class DadNote:
    """Uwaga taty w lokalnym stanie: tytuł, commit narzędzia i czas „Wyślij”; ``number`` ``None``: czeka w kolejce.

    ``closure`` to ostatnie znane zamknięcie jej issue przez Maksa (``None``: otwarte albo jeszcze nie wysłane).
    Wpisy sprzed #322 nie mają ``run_id``.
    """

    id: str
    title: str
    commit: str | None
    written_at: datetime
    number: int | None
    closure: Closure | None = None
    run_id: str | None = None
    """Uruchomienie, do którego Uwaga jest przypięta; ``None``: Uwaga ogólna."""


class DadNotes:
    """Plik stanu Uwag taty obok Ustawień taty, poza Gitem.

    Piszą do niego wątek zapytania „Wyślij” i wątek kolejki (numer issue), więc każdy odczyt ze zmianą idzie pod
    blokadą. Brak, uszkodzenie albo nieznany schemat pliku to brak Uwag; nieudany zapis trafia do dziennika Centrum,
    a Uwaga i tak idzie do Maksa.
    """

    def __init__(self, path: Path, log: CentrumLog) -> None:
        self._path = path
        self._log = log
        self._lock = threading.Lock()

    def add(self, note: DadNote) -> None:
        with self._lock:
            self._write([*self._read(), note])

    def all(self) -> list[DadNote]:
        with self._lock:
            return self._read()

    def mark(self, closures: Mapping[int, Closure | None]) -> None:
        """Zapamiętuje zamknięcie issue ze skrzynki przy Uwagach o tych numerach."""

        with self._lock:
            notes = self._read()
            self._write(
                [
                    replace(note, closure=closures.get(note.number, note.closure)) if note.number is not None else note
                    for note in notes
                ]
            )

    def forget(self, note_id: str) -> None:
        """Usuwa Uwagę, której kolejka nie przyjęła: tata wyśle ją jeszcze raz jako nową."""

        with self._lock:
            self._write([note for note in self._read() if note.id != note_id])

    def delivered(self, post: Post, number: int) -> None:
        """Dopisuje numer issue Uwadze, którą przyjęła skrzynka; wysyłki innych etykiet pomija."""

        if post.target.label != NOTE_LABEL:
            return
        with self._lock:
            notes = self._read()
            if any(note.id == post.run_id for note in notes):
                self._write([replace(note, number=number) if note.id == post.run_id else note for note in notes])

    def _read(self) -> list[DadNote]:
        try:
            document = json.loads(self._path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, ValueError):
            return []
        if not isinstance(document, dict) or document.get("schema_version") != SCHEMA_VERSION:
            return []
        entries = document.get("uwagi")
        return [note for note in map(_note, entries) if note is not None] if isinstance(entries, list) else []

    def _write(self, notes: list[DadNote]) -> None:
        document = {
            "schema_version": SCHEMA_VERSION,
            "uwagi": [
                {
                    "id": note.id,
                    "title": note.title,
                    "commit": note.commit,
                    "written_at": note.written_at.isoformat(),
                    "number": note.number,
                    "closure": closure_json(note.closure),
                    "run_id": note.run_id,
                }
                for note in notes
            ],
        }
        try:
            replace_atomically(self._path, json.dumps(document, ensure_ascii=False, indent=2) + "\n")
        except OSError as failure:
            self._log.unexpected_failure(failure, where="stan Uwag taty")


def _note(entry: object) -> DadNote | None:
    """Wpis pliku stanu; wpis z polem złego typu albo czasem bez strefy pomija."""

    if not isinstance(entry, dict):
        return None
    note_id, title, commit, written_at, number, run_id = (
        entry.get(name) for name in ("id", "title", "commit", "written_at", "number", "run_id")
    )
    if not (isinstance(note_id, str) and isinstance(title, str) and isinstance(written_at, str)):
        return None
    if not (isinstance(commit, str | None) and isinstance(run_id, str | None)) or not (
        number is None or type(number) is int
    ):
        return None
    try:
        moment = datetime.fromisoformat(written_at)
    except ValueError:
        return None
    if moment.tzinfo is None:
        return None
    return DadNote(note_id, title, commit, moment, number, read_closure(entry.get("closure")), run_id)


def with_logs(post: Post, notes: DadNotes, logs: LogsAddress) -> Post:
    """Wysyłka z kolejki tuż przed wysłaniem (``Outbox`` ``prepare``): przypięta Uwaga dostaje odnośnik do Logów.

    Dotyczy Uwagi, której stopka mówi, że Logi jej Uruchomienia są w drodze, a skrzynka zdążyła je przyjąć. Każda
    inna wysyłka idzie bez zmian, także Uwaga, której Logi dalej czekają.
    """

    if post.target.label != NOTE_LABEL:
        return post
    run_id = next((note.run_id for note in notes.all() if note.id == post.run_id), None)
    if run_id is None or (address := logs(run_id)) is None:
        return post
    first, waiting = post.parts[0], _logs_line(run_id, None)
    if not first.endswith(waiting):
        return post
    return replace(post, parts=(first.removesuffix(waiting) + _logs_line(run_id, address), *post.parts[1:]))


def _history(history: History) -> list[contract.ProcessRun]:
    try:
        return history()
    except OSError:
        raise contract.Refusal(500, _NO_HISTORY) from None


def _pickable(history: list[contract.ProcessRun], selected: str | None) -> list[contract.ProcessRun]:
    """Uruchomienia z Centrum do przypięcia, od najnowszego: ``RECENT_RUNS`` najnowszych i starsze ``selected``.

    ``selected`` to Uruchomienie z karty, z której tata otworzył okno; nieznane jest pomijane.
    """

    own = [run for run in history if run.run_id is not None]
    return own[:RECENT_RUNS] + [run for run in own[RECENT_RUNS:] if run.run_id == selected]


def _pinned(run_id: str | None, history: History, logs: LogsAddress) -> PinnedRun | None:
    """Uruchomienie z historii o tym identyfikatorze i adres jego Logów; nieznane to odmowa 404."""

    if run_id is None:
        return None
    run = next((run for run in _history(history) if run.run_id == run_id), None)
    if run is None:
        raise contract.Refusal(404, _UNKNOWN_RUN)
    return PinnedRun(run, logs(run_id))


def send(
    request: contract.DadNoteRequest, notes: DadNotes, outbox: Outbox, commit: str | None, pinned: PinnedRun | None
) -> contract.DadNoteState:
    """Zapisuje Uwagę, kładzie ją w kolejce i mówi, czy skrzynka przyjęła ją w ``DELIVERY_WAIT_S``.

    Uwaga, której kolejka nie zapisała, to odmowa: inaczej tekst taty przepadłby po cichu.
    """

    issue = note_issue(request.title, request.body, commit, pinned)
    run_id = None if pinned is None else pinned.run.run_id
    note = DadNote(uuid.uuid4().hex, issue.title, commit, datetime.now(timezone.utc), number=None, run_id=run_id)
    notes.add(note)
    queued = outbox.post(
        Post(NewIssue(NOTE_LABEL, issue.title), period=None, run_id=note.id, header=None, parts=(issue.body,))
    )
    if not queued:
        notes.forget(note.id)
        raise contract.Refusal(500, _NOT_QUEUED)
    if outbox.wait_delivered(note.id, NOTE_LABEL, timeout_s=DELIVERY_WAIT_S):
        return contract.DadNoteSent(state="sent")
    return contract.DadNoteWaiting(state="waiting")


def dad_notes_router(
    notes: DadNotes, outbox: Outbox, commit: CommitSource, history: History, logs: LogsAddress
) -> APIRouter:
    router = APIRouter(prefix="/api/dad-notes", tags=["uwagi-taty"])
    refusals: dict[int | str, dict[str, object]] = {status: {"model": contract.Problem} for status in (404, 500)}

    @router.get("/runs", operation_id="getDadNoteRuns", responses={500: {"model": contract.Problem}})
    def runs(selected: str | None = None) -> list[contract.ProcessRun]:
        return _pickable(_history(history), selected)

    @router.post("/draft", operation_id="draftDadNote", responses=refusals)
    def draft(text: contract.DadNoteText) -> contract.DadNoteDraft:
        return note_issue(text.title, text.body, commit(), _pinned(text.run_id, history, logs))

    @router.post("", operation_id="sendDadNote", responses=refusals)
    def send_note(request: contract.DadNoteRequest) -> contract.DadNoteState:
        return send(request, notes, outbox, commit(), _pinned(request.run_id, history, logs))

    return router

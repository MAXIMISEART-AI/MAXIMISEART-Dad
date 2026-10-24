"""Uwaga taty ogólna (ADR 0015): treść issue, wysyłka przez kolejkę Skrzynki Zgłoszeń i stan Uwag na tym komputerze.

Treść issue powstaje tylko w ``note_issue``: podgląd „Maks dostanie” i wysyłka wołają tę samą funkcję, więc tata
widzi dokładnie to, co dostanie Maks. „Wyślij” zapisuje Uwagę bez numeru issue w ``config/uwagi-taty.json`` (poza
Gitem), kładzie ją w kolejce Skrzynki Zgłoszeń jako osobne issue z etykietą ``uwaga-taty`` i czeka na skrzynkę
najwyżej ``DELIVERY_WAIT_S``. Numer issue dopisuje wątek kolejki, także po następnym starcie Centrum, a zamknięcie
issue przez Maksa sprawdzanie Powiadomień. Plik stanu ma tylko tytuł Uwagi, bez treści.
"""

from __future__ import annotations

import json
import threading
import uuid
from collections.abc import Mapping
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Final

from fastapi import APIRouter

from rozliczenia.centrum import contract
from rozliczenia.centrum.atomic_file import replace_atomically
from rozliczenia.centrum.log import CentrumLog
from rozliczenia.centrum.outbox import NewIssue, Outbox, Post
from rozliczenia.centrum.report_box import NOTE_LABEL, Closure, closure_json, read_closure
from rozliczenia.centrum.tool_freshness import CommitSource
from rozliczenia.centrum.version import version_label

DAD_NOTES_FILE: Final = "uwagi-taty.json"
SCHEMA_VERSION: Final = 1
# Tyle „Wyślij” czeka na skrzynkę, zanim powie tacie, że Uwaga czeka w kolejce.
DELIVERY_WAIT_S: Final = 5.0
_NOT_QUEUED: Final = "Uwaga się nie zapisała i nie pójdzie do Maksa. Spróbuj wysłać ją jeszcze raz."


def note_issue(title: str, body: str, commit: str | None) -> contract.DadNoteDraft:
    """Issue Uwagi taty: jej tytuł, a w treści jej tekst i wersja narzędzia (bez tekstu tylko wersja)."""

    footer = f"Uwaga ogólna · wersja narzędzia {version_label(commit)}"
    return contract.DadNoteDraft(title=title, body=f"{body}\n\n{footer}" if body else footer)


@dataclass(frozen=True)
class DadNote:
    """Uwaga taty w lokalnym stanie: tytuł, commit narzędzia i czas „Wyślij”; ``number`` ``None``: czeka w kolejce.

    ``closure`` to ostatnie znane zamknięcie jej issue przez Maksa (``None``: otwarte albo jeszcze nie wysłane).
    """

    id: str
    title: str
    commit: str | None
    written_at: datetime
    number: int | None
    closure: Closure | None = None


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
    note_id, title, commit, written_at, number = (
        entry.get(name) for name in ("id", "title", "commit", "written_at", "number")
    )
    if not (isinstance(note_id, str) and isinstance(title, str) and isinstance(written_at, str)):
        return None
    if not isinstance(commit, str | None) or not (number is None or type(number) is int):
        return None
    try:
        moment = datetime.fromisoformat(written_at)
    except ValueError:
        return None
    if moment.tzinfo is None:
        return None
    return DadNote(note_id, title, commit, moment, number, read_closure(entry.get("closure")))


def send(request: contract.DadNoteRequest, notes: DadNotes, outbox: Outbox, commit: str | None) -> contract.DadNoteState:
    """Zapisuje Uwagę, kładzie ją w kolejce i mówi, czy skrzynka przyjęła ją w ``DELIVERY_WAIT_S``.

    Uwaga, której kolejka nie zapisała, to odmowa: inaczej tekst taty przepadłby po cichu.
    """

    issue = note_issue(request.title, request.body, commit)
    note = DadNote(uuid.uuid4().hex, issue.title, commit, datetime.now(timezone.utc), number=None)
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


def dad_notes_router(notes: DadNotes, outbox: Outbox, commit: CommitSource) -> APIRouter:
    router = APIRouter(prefix="/api/dad-notes", tags=["uwagi-taty"])

    @router.post("/draft", operation_id="draftDadNote")
    def draft(text: contract.DadNoteText) -> contract.DadNoteDraft:
        return note_issue(text.title, text.body, commit())

    @router.post("", operation_id="sendDadNote", responses={500: {"model": contract.Problem}})
    def send_note(request: contract.DadNoteRequest) -> contract.DadNoteState:
        return send(request, notes, outbox, commit())

    return router

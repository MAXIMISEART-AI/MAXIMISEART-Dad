"""Uwaga taty (ADR 0015): treść issue, wysyłka przez kolejkę Skrzynki Zgłoszeń i stan Uwag na tym komputerze.

Treść issue powstaje tylko w ``note_issue``: podgląd „Maks dostanie” i wysyłka wołają tę samą funkcję, więc tata
widzi dokładnie to, co dostanie Maks. „Wyślij” zapisuje Uwagę bez numeru issue jako sprawę taty (``DadCases``),
kładzie ją w kolejce Skrzynki Zgłoszeń jako osobne issue z etykietą ``uwaga-taty`` i czeka na skrzynkę najwyżej
``DELIVERY_WAIT_S``, a gdy jej nie przyjęła, mówi, na co Uwaga czeka (``DadCases.hold``). Numer issue dopisuje wątek kolejki, także po następnym starcie Centrum, a zamknięcie issue przez
Maksa sprawdzanie Powiadomień. Sprawa ma tylko tytuł Uwagi i przypięte Uruchomienie, bez treści.

Uwaga przypięta do Uruchomienia procesu z Centrum niesie w stopce jego proces, okres, tryb, wynik i datę oraz
odnośnik do jego Logów Uruchomienia w Skrzynce. Uruchomienia do wyboru i do przypięcia pochodzą z historii metryk
(``History``). Gdy Logi jeszcze czekają w kolejce, stopka szkicu mówi, że są w drodze, a ``with_logs`` tuż przed
wysłaniem Uwagi z kolejki wstawia odnośnik, jeśli Logi zdążyły dojść do skrzynki, a jeśli nie, mówi, dlaczego ich nie
ma. Logi idą przed Uwagą (starszy plik kolejki), więc Uwaga wychodzi bez nich tylko wtedy, gdy skrzynka odrzuciła ich
treść albo nie było ich w kolejce. Po odrzuconych Logach ``after_delivery`` kładzie w kolejce komentarz do issue
Uwagi, który czeka na te Logi i wychodzi z odnośnikiem, gdy dotrą przy którymś następnym starcie Centrum. Tworzy go
tylko dostarczenie Uwagi, więc każde jej issue dostaje najwyżej jeden taki komentarz, także po ponownym starcie.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from typing import Final, assert_never

from fastapi import APIRouter

from rozliczenia.centrum import contract
from rozliczenia.centrum.dad_cases import NOTE, Case, DadCases
from rozliczenia.centrum.keyed_box import KeyedBox
from rozliczenia.centrum.outbox import DELIVERY_WAIT_S, KnownIssue, NewIssue, Outbox, Post
from rozliczenia.centrum.tool_freshness import CommitSource
from rozliczenia.centrum.version import version_label

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
LogsRejected = Callable[[str], bool]
"""Skrzynka odrzuciła w tej pracy Centrum treść Logów Uruchomienia o tym identyfikatorze (``Outbox.rejected``)."""


@dataclass(frozen=True)
class PinnedRun:
    """Uruchomienie z Centrum, do którego tata przypiął Uwagę, i adres jego Logów.

    ``logs`` ``None``: Logi Uruchomienia jeszcze nie doszły do Skrzynki Zgłoszeń.
    """

    run: contract.PinnableRun
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
    return f"Uruchomienie: {' · '.join((*facts, version))}\n{_logs_line(run.run_id, pinned.logs)}"


def _result_word(run: contract.PinnableRun) -> str:
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
    """Linia Logów przypiętej Uwagi: odnośnik albo „w drodze”, którą ``with_logs`` zamienia na odnośnik.

    Odnośnik to link Markdown: GitHub pokazuje Maksowi sam napis, a „Maks dostanie” pokazuje tacie ten sam napis
    bez adresu prywatnej Skrzynki, którego tata i tak nie otworzy.
    """

    return f"[Logi Uruchomienia]({logs})" if logs is not None else f"Logi Uruchomienia: w drodze (Uruchomienie {run_id})"


def _pinned_run(cases: DadCases, note_id: str) -> str | None:
    """Uruchomienie, do którego przypięta jest Uwaga ``note_id``; ``None``: Uwaga ogólna albo nieznana."""

    note = cases.find(NOTE, note_id)
    return None if note is None else note.run_id


def _sent_logs_line(run_id: str, logs: LogsAddress, rejected: LogsRejected) -> str:
    """Linia Logów przypiętej Uwagi w chwili wysłania: odnośnik albo dlaczego Logów nie ma w Skrzynce."""

    if (address := logs(run_id)) is not None:
        return _logs_line(run_id, address)
    if rejected(run_id):
        return _rejected_logs_line(run_id)
    return f"Logi Uruchomienia: nie powstały albo nie da się ich wysłać (Uruchomienie {run_id})"


def _rejected_logs_line(run_id: str) -> str:
    return (
        f"Logi Uruchomienia: nie dotarły, Skrzynka odrzuciła ich treść (Uruchomienie {run_id}). "
        "Odnośnik przyjdzie w komentarzu, gdy dotrą."
    )


def _logs_arrived(run_id: str, address: str) -> str:
    return f"{_logs_line(run_id, address)} dotarły do Skrzynki po tej Uwadze (Uruchomienie {run_id})."


def _logs_gone(run_id: str) -> str:
    return f"Logi Uruchomienia nie dotrą: Centrum przestało je wysyłać (Uruchomienie {run_id})."


def with_logs(post: Post, cases: DadCases, logs: LogsAddress, rejected: LogsRejected) -> Post | None:
    """Wysyłka z kolejki tuż przed wysłaniem (``Outbox`` ``prepare``): Logi w Uwadze przypiętej do Uruchomienia.

    Uwaga, której stopka mówi, że Logi są w drodze, dostaje odnośnik albo linię, dlaczego Logów nie ma. Komentarz
    z odnośnikiem do issue Uwagi (``run_id`` to Uruchomienie) czeka (``None``), dopóki skrzynka odrzuca Logi w tej
    pracy Centrum, a gdy Logów nie ma ani w Skrzynce, ani w kolejce, idzie z zapisanym tekstem, że nie dotrą. Każda
    inna wysyłka idzie bez zmian.
    """

    if post.target.label != NOTE.label:
        return post
    if isinstance(post.target, KnownIssue):
        if (address := logs(post.run_id)) is not None:
            return replace(post, parts=(_logs_arrived(post.run_id, address),))
        return None if rejected(post.run_id) else post
    run_id = _pinned_run(cases, post.run_id)
    if run_id is None:
        return post
    first, waiting = post.parts[0], _logs_line(run_id, None)
    if not first.endswith(waiting):
        return post
    return replace(post, parts=(first.removesuffix(waiting) + _sent_logs_line(run_id, logs, rejected), *post.parts[1:]))


def after_delivery(post: Post, number: int, cases: DadCases, outbox: Outbox) -> None:
    """Wysyłka przyjęta przez skrzynkę (``Outbox`` ``on_delivered``): Uwaga dostaje numer issue.

    Uwaga, która wyszła przed odrzuconymi Logami swojego Uruchomienia, dostaje w kolejce komentarz z odnośnikiem do
    nich, zanim jej plik dostanie znacznik dostarczenia. Nieudany zapis komentarza zostaje w dzienniku Centrum.
    """

    cases.delivered(post, number)
    if not isinstance(post.target, NewIssue) or post.target.label != NOTE.label:
        return
    run_id = _pinned_run(cases, post.run_id)
    if run_id is not None and post.parts[0].endswith(_rejected_logs_line(run_id)):
        target = KnownIssue(NOTE.label, number)
        outbox.post(Post(target, period=None, run_id=run_id, header=None, parts=(_logs_gone(run_id),)))


def _pinnable(history: History) -> list[contract.PinnableRun]:
    """Uruchomienia z Centrum z historii, od najnowszego; Uruchomienie bez identyfikatora nie ma czego przypiąć."""

    try:
        runs = history()
    except OSError:
        raise contract.Refusal(500, _NO_HISTORY) from None
    return [contract.PinnableRun.model_validate(run, from_attributes=True) for run in runs if run.run_id is not None]


def _pickable(own: list[contract.PinnableRun], selected: str | None) -> list[contract.PinnableRun]:
    """Uruchomienia do wyboru w oknie Uwagi: ``RECENT_RUNS`` najnowszych i starsze ``selected``.

    ``selected`` to Uruchomienie z karty, z której tata otworzył okno; nieznane jest pomijane.
    """

    return own[:RECENT_RUNS] + [run for run in own[RECENT_RUNS:] if run.run_id == selected]


def _pinned(run_id: str | None, history: History, logs: LogsAddress) -> PinnedRun | None:
    """Uruchomienie z historii o tym identyfikatorze i adres jego Logów; nieznane to odmowa 404."""

    if run_id is None:
        return None
    run = next((run for run in _pinnable(history) if run.run_id == run_id), None)
    if run is None:
        raise contract.Refusal(404, _UNKNOWN_RUN)
    return PinnedRun(run, logs(run_id))


def send(
    request: contract.DadNoteRequest,
    cases: DadCases,
    outbox: Outbox,
    box: KeyedBox,
    commit: str | None,
    pinned: PinnedRun | None,
) -> contract.DadNoteState:
    """Zapisuje Uwagę, kładzie ją w kolejce i mówi, czy skrzynka przyjęła ją w ``DELIVERY_WAIT_S``, a jeśli nie, na
    co czeka albo że skrzynka odrzuciła jej treść.

    Uwaga, której kolejka nie zapisała, to odmowa: inaczej tekst taty przepadłby po cichu.
    """

    issue = note_issue(request.title, request.body, commit, pinned)
    run_id = None if pinned is None else pinned.run.run_id
    note = Case(NOTE, uuid.uuid4().hex, issue.title, commit, datetime.now(timezone.utc), number=None, run_id=run_id)
    cases.add(note)
    queued = outbox.post(
        Post(NewIssue(NOTE.label, issue.title), period=None, run_id=note.id, header=None, parts=(issue.body,))
    )
    if not queued:
        cases.forget(NOTE, note.id)
        raise contract.Refusal(500, _NOT_QUEUED)
    if outbox.wait_delivered(note.id, NOTE.label, timeout_s=DELIVERY_WAIT_S):
        return contract.DadNoteSent(state="sent")
    hold = cases.hold(note.id, box)
    if hold == "rejected":
        return contract.DadNoteRejected(state="rejected")
    return contract.DadNoteWaiting(state="waiting", waits_for=hold)


def dad_notes_router(
    cases: DadCases, outbox: Outbox, box: KeyedBox, commit: CommitSource, history: History, logs: LogsAddress
) -> APIRouter:
    router = APIRouter(prefix="/api/dad-notes", tags=["uwagi-taty"])
    refusals: dict[int | str, dict[str, object]] = {status: {"model": contract.Problem} for status in (404, 500)}

    @router.get("/runs", operation_id="getDadNoteRuns", responses={500: {"model": contract.Problem}})
    def runs(selected: str | None = None) -> list[contract.PinnableRun]:
        return _pickable(_pinnable(history), selected)

    @router.post("/draft", operation_id="draftDadNote", responses=refusals)
    def draft(text: contract.DadNoteText) -> contract.DadNoteDraft:
        return note_issue(text.title, text.body, commit(), _pinned(text.run_id, history, logs))

    @router.post("", operation_id="sendDadNote", responses=refusals)
    def send_note(request: contract.DadNoteRequest) -> contract.DadNoteState:
        return send(request, cases, outbox, box, commit(), _pinned(request.run_id, history, logs))

    return router

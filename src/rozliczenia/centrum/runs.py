"""Uruchomienia procesu z Centrum rozliczeń: jedno naraz, w wątku roboczym, z podglądem przez SSE.

Centrum jest rozmówcą rdzenia Uruchomienia procesu (``process_run``) i trzecim
adapterem projekcji postępu (ADR 0002, ADR 0004). Ten moduł nie zna żadnego
procesu: proces podaje gotowe ``PreparedRun`` (tytuł, okres, tryb i funkcję,
która prowadzi Uruchomienie z danym rozmówcą i zwraca wynik dla przeglądarki).

Każda zmiana stanu to nowy niemutowalny widok (``contract.RunView``) z kolejnym
numerem. Strumień SSE wysyła najpierw bieżący widok, potem każdy kolejny, więc
ponowne podłączenie (odświeżenie, nowa karta) zaczyna od bieżącego stanu.
Decyzja taty czeka w stanie ``awaiting_decision``, aż przyjdzie przez API.
"""

from __future__ import annotations

import re
import threading
import uuid
from collections.abc import AsyncIterator, Callable, Mapping, Sequence
from contextlib import AbstractContextManager, nullcontext
from dataclasses import dataclass
from typing import Any, Final, Literal, Protocol

import anyio
from fastapi import APIRouter
from fastapi.responses import StreamingResponse

from rozliczenia.centrum import contract
from rozliczenia.process_run import Finished, Interlocutor, Outcome
from rozliczenia.progress import ProgressNotice, ProgressProjection, ProgressSnapshot

_STREAM_POLL_SECONDS: Final = 0.05
_KEEPALIVE_SECONDS: Final = 15.0
_RECONNECT_MS: Final = 1000
_THREE_PARTS: Final = ("Co się stało: ", "Gdzie: ", "Co zrobić: ")
_COUNT_LINE: Final = re.compile(r"- (?P<label>.+): (?P<count>\d+)")


@dataclass(frozen=True)
class PreparedRun:
    """Uruchomienie procesu gotowe do startu: ``conduct`` prowadzi je z rozmówcą Centrum i zwraca wynik."""

    process: contract.ProcessKey
    title: str
    period: str
    dry_run: bool
    conduct: Callable[[Interlocutor], contract.RunOutcome]


class RunHost:
    """Jedno Uruchomienie procesu naraz w obrębie serwera i jego widoki dla przeglądarki.

    ``in_progress()`` mówi, czy Uruchomienie trwa (także gdy czeka na decyzję
    taty); zamknięcie serwera w tym czasie jest zablokowane.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._sequence = 0
        self._events: list[contract.RunEvent] = [contract.RunEvent(sequence=0, view=contract.RunIdle(state="idle"))]
        self._run: _Run | None = None

    def in_progress(self) -> bool:
        with self._lock:
            return self._run is not None and not self._run.ended

    def current(self) -> contract.RunEvent:
        with self._lock:
            return self._events[-1]

    def events_after(self, sequence: int) -> list[contract.RunEvent]:
        with self._lock:
            return [event for event in self._events if event.sequence > sequence]

    def start(self, prepared: PreparedRun) -> contract.RunView:
        with self._lock:
            if self._run is not None and not self._run.ended:
                running = self._run.info
                raise contract.Refusal(
                    409,
                    f"Trwa już Uruchomienie procesu: {running.title}, okres {running.period}. "
                    "Poczekaj na jego wynik w Uruchomieniach.",
                )
            run = _Run(self, prepared)
            self._run = run
            self._events = []
            self._publish_locked(run.running_view())
            view = self._events[-1].view
        threading.Thread(target=run.work, name=f"uruchomienie-{run.info.id}", daemon=True).start()
        return view

    def decide(self, run_id: str, answer: contract.DecisionAnswer) -> contract.RunView:
        with self._lock:
            run = self._run
            if run is None or run.info.id != run_id:
                raise contract.Refusal(404, "Nie ma takiego Uruchomienia procesu.")
            if not run.awaiting_decision:
                raise contract.Refusal(409, "To Uruchomienie procesu nie czeka na decyzję.")
            run.answer(answer.answer == "continue")
            self._publish_locked(run.running_view())
            return self._events[-1].view

    def publish(self, run: _Run, view: contract.RunView) -> None:
        with self._lock:
            if self._run is run:
                self._publish_locked(view)

    def _publish_locked(self, view: contract.RunView) -> None:
        self._sequence += 1
        self._events.append(contract.RunEvent(sequence=self._sequence, view=view))


class _Run:
    """Jedno Uruchomienie procesu i jednocześnie jego rozmówca w rdzeniu (``Interlocutor``).

    Metody podglądu zamieniają snapshot projekcji na widok i publikują go.
    Wyjątek przy tym oznacza, że podgląd przestał się aktualizować: widok
    dostaje ``progress_stale``, a rdzeń odłącza podgląd bez wpływu na wynik.
    """

    def __init__(self, host: RunHost, prepared: PreparedRun) -> None:
        self._host = host
        self._prepared = prepared
        self.info = contract.RunInfo(
            id=uuid.uuid4().hex,
            process=prepared.process,
            title=prepared.title,
            period=prepared.period,
            dry_run=prepared.dry_run,
        )
        mode = "DRY-RUN" if prepared.dry_run else "RUN"
        self._progress = progress_view(ProgressProjection(mode, prepared.period).snapshot)
        self._notice: contract.ProgressNotice | None = None
        self._stale = False
        self._decided = threading.Event()
        self._consent = False
        self.awaiting_decision = False
        self.ended = False

    def running_view(self) -> contract.RunRunning:
        return contract.RunRunning(
            state="running",
            run=self.info,
            progress=self._progress,
            notice=self._notice,
            progress_stale=self._stale,
        )

    def work(self) -> None:
        try:
            result = self._prepared.conduct(self)
        except Exception:
            result = _unexpected_result(self.info.dry_run)
        self.ended = True
        self._host.publish(
            self,
            contract.RunFinished(
                state="finished", run=self.info, progress=self._progress, progress_stale=self._stale, result=result
            ),
        )

    def answer(self, consent: bool) -> None:
        """Wywoływane przez ``RunHost.decide`` pod blokadą hosta."""

        self._consent = consent
        self.awaiting_decision = False
        self._decided.set()

    # Rozmowa z tatą (Conversation)

    def say(self, *lines: str) -> None:
        """Centrum nie pokazuje luźnych linii w trakcie; wynik ma wszystkie linie końcowe."""

    def ask(self, prompt: str) -> str | None:
        return None

    def confirm(self, lines: Sequence[str], question: str) -> bool:
        self._decided.clear()
        self.awaiting_decision = True
        self._host.publish(
            self,
            contract.RunAwaitingDecision(
                state="awaiting_decision", run=self.info, progress=self._progress, decision=decision(lines, question)
            ),
        )
        self._decided.wait()
        return self._consent

    def paused(self) -> AbstractContextManager[None]:
        return nullcontext()

    # Podgląd postępu (trzeci adapter projekcji)

    def start_progress(self, snapshot: ProgressSnapshot, *, title: str, shows_templates: bool) -> None:
        self._show(snapshot, None)

    def show_progress(self, snapshot: ProgressSnapshot, notice: ProgressNotice) -> None:
        self._show(snapshot, notice)

    def stop_progress(self) -> None:
        """Widok końcowy publikuje ``work`` razem z wynikiem."""

    def _show(self, snapshot: ProgressSnapshot, notice: ProgressNotice | None) -> None:
        try:
            progress = progress_view(snapshot)
            notice_shown = None if notice is None else notice_view(notice)
        except Exception:
            self._stale = True
            self._host.publish(self, self.running_view())
            raise
        if (progress, notice_shown) != (self._progress, self._notice):
            self._progress, self._notice = progress, notice_shown
            self._host.publish(self, self.running_view())


def progress_view(snapshot: ProgressSnapshot) -> contract.Progress:
    return contract.Progress(
        mode="DRY-RUN" if snapshot.mode == "DRY-RUN" else "RUN",
        period=snapshot.period,
        phases=[
            contract.PhaseProgress(
                phase=phase.value, state=state.value, duration_ms=snapshot.phase_durations_ms.get(phase, 0)
            )
            for phase, state in snapshot.phase_states.items()
        ],
        current_phase=None if snapshot.current_phase is None else snapshot.current_phase.value,
        template_total=snapshot.template_total,
        templates_completed=snapshot.templates_completed,
        current_worker=snapshot.current_worker,
        rows=snapshot.rows,
        operation_counts=dict(snapshot.operation_counts),
        recent_operations=[
            contract.OperationProgress(
                worker_name=operation.worker_name,
                status=operation.status,
                rows=operation.rows,
                worker_elapsed_ms=operation.worker_elapsed_ms,
            )
            for operation in snapshot.recent_operations
        ],
        total_elapsed_ms=snapshot.total_elapsed_ms,
        issue_count=snapshot.issue_count,
    )


def notice_view(notice: ProgressNotice) -> contract.ProgressNotice:
    return contract.ProgressNotice(
        kind=notice.kind.value,
        phase=notice.phase.value,
        worker_name=notice.worker_name,
        status=notice.status,
        rows=notice.rows,
        worker_elapsed_ms=notice.worker_elapsed_ms,
        template_index=notice.template_index,
        template_total=notice.template_total,
    )


def messages(lines: Sequence[str]) -> list[contract.RunMessage]:
    """Linie komunikatów z ``Co się stało``/``Gdzie``/``Co zrobić`` w trzech częściach; inna linia to komunikat sam w sobie."""

    found: list[dict[str, str | None]] = []
    for line in lines:
        what, where, action = _THREE_PARTS
        if line.startswith(what):
            found.append({"what": line.removeprefix(what), "where": None, "action": None})
        elif line.startswith(where) and found:
            found[-1]["where"] = line.removeprefix(where)
        elif line.startswith(action) and found:
            found[-1]["action"] = line.removeprefix(action)
        else:
            found.append({"what": line, "where": None, "action": None})
    return [contract.RunMessage.model_validate(message) for message in found]


def decision(lines: Sequence[str], question: str) -> contract.Decision:
    """Linie pytania procesu: tytuł, komunikat w trzech częściach i grupy liczb (``Nagłówek:`` i ``- etykieta: N``)."""

    title: str | None = None
    message_lines: list[str] = []
    groups: list[tuple[str, list[contract.Count]]] = []
    for line in lines:
        count = _COUNT_LINE.fullmatch(line)
        if line.startswith(_THREE_PARTS):
            message_lines.append(line)
        elif count is not None and groups:
            groups[-1][1].append(contract.Count(label=count["label"], count=int(count["count"])))
        elif line.endswith(":"):
            groups.append((line.removesuffix(":"), []))
        elif title is None:
            title = line
    found = messages(message_lines)
    return contract.Decision(
        question=question,
        title=title,
        message=found[0] if found else None,
        count_groups=[contract.CountGroup(title=name, counts=counts) for name, counts in groups],
    )


def run_result(
    outcome: Outcome[Any],
    *,
    dry_run: bool,
    done: str,
    summary: contract.PreparationSummary | None,
    warnings: Sequence[contract.RunMessage],
) -> contract.RunOutcome:
    """Wynik dla przeglądarki z ``Outcome`` rdzenia: linie bez zmian, zatrzymania z linii statusu procesu.

    ``done`` to tytuł wyniku po zapisie, np. „Plik zbiorczy przygotowany”.
    """

    ending = outcome.ending
    finished = isinstance(ending, Finished)
    kind = "finished" if isinstance(ending, Finished) else ending.kind
    next_action: Literal["run", "rerun", "open_period_folder"]
    if finished:
        next_action = "run" if dry_run else "open_period_folder"
        headline = "Podgląd gotowy · nic nie zapisano" if dry_run else done
    else:
        headline = "Zatrzymano" if kind == "stop" else "Błąd"
        # Po błędzie podsumowania przy zapisie pliki już są: nie proponujemy ponownego uruchomienia.
        next_action = "open_period_folder" if kind == "after_engine" and not dry_run else "rerun"
    return contract.RunOutcome(
        result=outcome.result,
        headline=headline,
        ending=kind,
        next_action=next_action,
        status_line=outcome.status_lines[0] if outcome.status_lines else "",
        total_duration_ms=outcome.total_duration_ms,
        stops=[] if finished else messages(outcome.status_lines[1:]),
        warnings=list(warnings),
        notices=list(outcome.notice_lines),
        summary=summary,
        lines=list(outcome.lines),
    )


def _unexpected_result(dry_run: bool) -> contract.RunOutcome:
    """Wynik, gdy nie dało się zbudować widoku wyniku; rdzeń zapisał już metryki."""

    what = "Nie udało się pokazać wyniku Uruchomienia procesu."
    action = "Sprawdź Folder okresu i przekaż ten komunikat osobie utrzymującej narzędzie."
    return contract.RunOutcome(
        result="BLAD_KRYTYCZNY",
        headline="Błąd",
        ending="after_engine",
        next_action="rerun" if dry_run else "open_period_folder",
        status_line="Status końcowy: BŁĄD",
        total_duration_ms=0,
        stops=[contract.RunMessage(what=what, where=None, action=action)],
        warnings=[],
        notices=[],
        summary=None,
        lines=["Status końcowy: BŁĄD", f"Co się stało: {what}", f"Co zrobić: {action}"],
    )


def _sse(event: contract.RunEvent) -> str:
    return f"id: {event.sequence}\ndata: {event.model_dump_json()}\n\n"


async def _event_stream(host: RunHost) -> AsyncIterator[str]:
    current = host.current()
    yield f"retry: {_RECONNECT_MS}\n" + _sse(current)
    seen = current.sequence
    idle = 0.0
    while True:
        await anyio.sleep(_STREAM_POLL_SECONDS)
        events = host.events_after(seen)
        for event in events:
            yield _sse(event)
            seen = event.sequence
        idle = 0.0 if events else idle + _STREAM_POLL_SECONDS
        if idle >= _KEEPALIVE_SECONDS:
            idle = 0.0
            yield ": trwa\n\n"


_PROBLEMS: dict[int | str, dict[str, Any]] = {
    404: {"model": contract.Problem},
    409: {"model": contract.Problem},
}
_STREAM_RESPONSES: dict[int | str, dict[str, Any]] = {
    200: {"description": "Strumień SSE; każde pole `data` to `RunEvent` (JSON).", "model": contract.RunEvent},
}


class ProcessEntry(Protocol):
    """Proces, który Centrum umie uruchomić: co pokazać przed startem i jak przygotować Uruchomienie."""

    @property
    def key(self) -> contract.ProcessKey: ...

    def setup(self) -> contract.ProcessSetup: ...

    def prepare(self, request: contract.RunRequest) -> PreparedRun:
        """Wejście procesu z ustawień i okresu; ``contract.Refusal``, gdy czegoś brakuje."""
        ...


def runs_router(host: RunHost, entries: Sequence[ProcessEntry]) -> APIRouter:
    router = APIRouter(prefix="/api/runs", tags=["uruchomienia"])
    by_key: Mapping[str, ProcessEntry] = {entry.key: entry for entry in entries}

    @router.get("/setup", operation_id="getRunSetup")
    def setup() -> contract.RunSetup:
        return contract.RunSetup(processes=[entry.setup() for entry in entries])

    @router.post("", operation_id="startRun", responses=_PROBLEMS)
    def start(request: contract.RunRequest) -> contract.RunView:
        return host.start(by_key[request.process].prepare(request))

    @router.get("/current", operation_id="getCurrentRun")
    def current() -> contract.RunView:
        return host.current().view

    @router.post("/{run_id}/decision", operation_id="decideRun", responses=_PROBLEMS)
    def decide(run_id: str, answer: contract.DecisionAnswer) -> contract.RunView:
        return host.decide(run_id, answer)

    @router.get("/events", operation_id="streamRunEvents", response_class=StreamingResponse, responses=_STREAM_RESPONSES)
    def events() -> StreamingResponse:
        return StreamingResponse(
            _event_stream(host),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    return router


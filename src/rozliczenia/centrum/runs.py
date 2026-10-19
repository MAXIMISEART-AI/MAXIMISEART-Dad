"""Uruchomienia procesu z Centrum rozliczeń: jedno naraz, w wątku roboczym, z podglądem przez SSE.

Centrum jest rozmówcą rdzenia Uruchomienia procesu (``process_run``) i trzecim
adapterem projekcji postępu (ADR 0002, ADR 0004). Ten moduł nie zna żadnego
procesu: proces podaje gotowe ``PreparedRun`` (opis procesu z CLI, wejście
procesu, plik metryk i sposób pokazania podsumowania), a moduł prowadzi z nim
rdzeń i zamienia wynik na widok dla przeglądarki. Zatrzymania, ostrzeżenia i
decyzja taty przechodzą jako komunikaty w trzech częściach, bez linii terminala.

Każda zmiana stanu to nowy niemutowalny widok (``contract.RunView``) z kolejnym
numerem. Strumień SSE wysyła najpierw bieżący widok, potem każdy kolejny, więc
ponowne podłączenie (odświeżenie, nowa karta) zaczyna od bieżącego stanu.
Decyzja taty czeka w stanie ``awaiting_decision``, aż przyjdzie przez API.
"""

from __future__ import annotations

import threading
import uuid
from collections.abc import AsyncIterator, Callable, Mapping, Sequence
from contextlib import AbstractContextManager, nullcontext
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Final, Generic, Literal, Protocol, TypeVar

import anyio
from fastapi import APIRouter
from fastapi.responses import StreamingResponse

from rozliczenia.centrum import contract
from rozliczenia.centrum.log import CentrumLog
from rozliczenia.centrum.run_origins import CentrumRuns
from rozliczenia.message import Message
from rozliczenia.process_run import (
    Decision,
    Finished,
    Outcome,
    Process,
    ProcessInputs,
    Stop,
    run_process,
)
from rozliczenia.progress import ProgressNotice, ProgressProjection, ProgressSnapshot
from rozliczenia.telemetry import MetricsStore

_STREAM_POLL_SECONDS: Final = 0.05
_KEEPALIVE_SECONDS: Final = 15.0
_RECONNECT_MS: Final = 1000
_CONTINUE_HINT: Final = "przy decyzji wybierz „Kontynuuj”"

InputsT = TypeVar("InputsT", bound=ProcessInputs)
SummaryT = TypeVar("SummaryT")


@dataclass(frozen=True)
class Endings:
    """Komunikaty procesu dla zakończeń bez jego własnego zatrzymania (``Stop.kind`` inny niż ``stop``)."""

    unexpected: Message
    plan_not_shown: Message
    summary_not_shown: Message


@dataclass(frozen=True)
class PreparedRun(Generic[InputsT, SummaryT]):
    """Uruchomienie procesu gotowe do startu: ten sam opis procesu co w CLI i wejście procesu z ustawień.

    ``done`` to tytuł wyniku po zapisie, np. „Plik zbiorczy przygotowany”.
    ``summary`` i ``warnings`` zamieniają podsumowanie silnika na widok dla przeglądarki.
    """

    key: contract.ProcessKey
    title: str
    period: str
    process: Process[InputsT, SummaryT]
    inputs: InputsT
    metrics_path: Path
    done: str
    endings: Endings
    summary: Callable[[SummaryT], contract.PreparationSummary | contract.SettlementSummary]
    warnings: Callable[[SummaryT], Sequence[Message]]

    @property
    def dry_run(self) -> bool:
        return self.inputs.dry_run


class RunHost:
    """Jedno Uruchomienie procesu naraz w obrębie serwera i jego widoki dla przeglądarki.

    ``shutdown_refusal()`` odmawia zamknięcia serwera, gdy Uruchomienie trwa
    (także gdy czeka na decyzję taty). Początek i koniec każdego Uruchomienia
    trafiają do dziennika Centrum jako bezpieczne fakty, a rekord metryk każdego
    Uruchomienia z Centrum do ``CentrumRuns``.
    """

    def __init__(self, log: CentrumLog, centrum_runs: CentrumRuns) -> None:
        self._log = log
        self._centrum_runs = centrum_runs
        self._lock = threading.Lock()
        self._sequence = 0
        self._events: list[contract.RunEvent] = [contract.RunEvent(sequence=0, view=contract.RunIdle(state="idle"))]
        self._run: _Run | None = None

    def shutdown_refusal(self) -> str | None:
        """Dlaczego teraz nie można zamknąć Centrum (``Shutdown.refuse_while``); ``None``, gdy nic nie trwa."""

        with self._lock:
            run = self._run
            if run is None or run.ended:
                return None
            return (
                f"Trwa Uruchomienie procesu: {run.info.title}, okres {run.info.period}. "
                "Poczekaj na jego wynik w Uruchomieniach, potem zamknij Centrum rozliczeń."
            )

    def current(self) -> contract.RunEvent:
        with self._lock:
            return self._events[-1]

    def events_after(self, sequence: int) -> list[contract.RunEvent]:
        with self._lock:
            return [event for event in self._events if event.sequence > sequence]

    def start(self, prepared: PreparedRun[Any, Any]) -> contract.RunView:
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
        self._log.run_started(process=prepared.key, mode=_mode(prepared.dry_run), period=prepared.period)
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

    def remember(self, prepared: PreparedRun[Any, Any], since: datetime) -> None:
        """Zapamiętuje rekord metryk, który dopisało to Uruchomienie, jako Uruchomienie z Centrum."""

        metrics = MetricsStore(prepared.metrics_path, prepared.process.counter_names)
        self._centrum_runs.remember(prepared.key, metrics, since, datetime.now(timezone.utc))

    def failed(self, failure: Exception) -> None:
        """Wyniku Uruchomienia nie dało się pokazać: do dziennika tylko typ wyjątku, bez jego tekstu."""

        self._log.unexpected_failure(failure, where="wynik Uruchomienia procesu")

    def finished(self, run: _Run, result: contract.RunOutcome) -> None:
        info = run.info
        self._log.run_finished(
            process=info.process,
            mode=_mode(info.dry_run),
            period=info.period,
            result=result.result,
            ending=result.ending,
        )

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

    def __init__(self, host: RunHost, prepared: PreparedRun[Any, Any]) -> None:
        self._host = host
        self._prepared = prepared
        self.info = contract.RunInfo(
            id=uuid.uuid4().hex,
            process=prepared.key,
            title=prepared.title,
            period=prepared.period,
            dry_run=prepared.dry_run,
        )
        self._progress = _progress_view(ProgressProjection(_mode(prepared.dry_run), prepared.period).snapshot)
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
        prepared = self._prepared
        try:
            since = datetime.now(timezone.utc)
            outcome = run_process(prepared.process, prepared.inputs, self, metrics_path=prepared.metrics_path)
            self._host.remember(prepared, since)
            result = _run_result(outcome, prepared)
        except Exception as failure:  # noqa: BLE001 - granica wątku Uruchomienia: typ wyjątku trafia do dziennika Centrum
            self._host.failed(failure)
            result = _unexpected_result(prepared.dry_run)
        self._host.finished(self, result)
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

    # Rozmowa z tatą (Conversation). Wejście procesu przychodzi z ustawień, a procesy
    # rozmawiają w trakcie silnika tylko przez decyzję taty (``confirm``); ``say``,
    # ``ask`` i ``paused`` są w protokole dla rozmowy w terminalu.

    @property
    def continue_hint(self) -> str:
        return _CONTINUE_HINT

    def say(self, *lines: str) -> None:
        """Wynik ma wszystkie komunikaty końcowe."""

    def ask(self, prompt: str) -> str | None:
        return None

    def confirm(self, decision: Decision) -> bool:
        self._decided.clear()
        self.awaiting_decision = True
        self._host.publish(
            self,
            contract.RunAwaitingDecision(
                state="awaiting_decision", run=self.info, progress=self._progress, decision=_decision_view(decision)
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
            progress = _progress_view(snapshot)
            notice_shown = None if notice is None else _notice_view(notice)
        except Exception:
            self._stale = True
            self._host.publish(self, self.running_view())
            raise
        if (progress, notice_shown) != (self._progress, self._notice):
            self._progress, self._notice = progress, notice_shown
            self._host.publish(self, self.running_view())


def _mode(dry_run: bool) -> str:
    return "DRY-RUN" if dry_run else "RUN"


def _progress_view(snapshot: ProgressSnapshot) -> contract.Progress:
    counters = snapshot.metric_counters()
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
        counts=contract.TemplateCounts(
            written=counters["written"],
            empty=counters["empty"],
            planned=counters["planned"],
            skipped=counters["skipped"],
        ),
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


def _notice_view(notice: ProgressNotice) -> contract.ProgressNotice:
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


def _decision_view(decision: Decision) -> contract.Decision:
    return contract.Decision(
        question=decision.question,
        title=decision.title,
        message=contract.Message.of(decision.message),
        counts=contract.CountGroup(
            title=decision.counts_title,
            counts=[contract.Count(label=label, count=count) for label, count in decision.counts],
        ),
    )


def _stop_message(stop: Stop, endings: Endings) -> Message:
    if stop.message is not None:
        return stop.message
    if stop.kind == "unexpected":
        return endings.unexpected
    return endings.plan_not_shown if stop.dry_run else endings.summary_not_shown


def _run_result(outcome: Outcome[Any], prepared: PreparedRun[Any, Any]) -> contract.RunOutcome:
    """Wynik dla przeglądarki z ``Outcome`` rdzenia.

    Wynik „Wymaga sprawdzenia” ma własny tytuł, a po podglądzie proponuje
    ponowny podgląd po poprawce zamiast zapisu.
    """

    dry_run = prepared.dry_run
    ending = outcome.ending
    kind: Literal["finished", "stop", "unexpected", "after_engine"]
    next_action: Literal["run", "rerun", "open_period_folder"]
    stops: list[contract.Message] = []
    if not isinstance(ending, Finished):
        kind = ending.kind
        stops = [contract.Message.of(_stop_message(ending, prepared.endings))]
        headline = "Zatrzymano" if kind == "stop" else "Błąd"
        # Po błędzie podsumowania przy zapisie pliki już są: nie proponujemy ponownego uruchomienia.
        next_action = "open_period_folder" if kind == "after_engine" and not dry_run else "rerun"
    elif outcome.result == "WYMAGA_SPRAWDZENIA":
        kind = "finished"
        next_action = "rerun" if dry_run else "open_period_folder"
        headline = "Podgląd wymaga sprawdzenia · nic nie zapisano" if dry_run else f"{prepared.done} · wymaga sprawdzenia"
    else:
        kind = "finished"
        next_action = "run" if dry_run else "open_period_folder"
        headline = "Podgląd gotowy · nic nie zapisano" if dry_run else prepared.done
    summary = outcome.summary
    return contract.RunOutcome(
        result=outcome.result,
        headline=headline,
        ending=kind,
        next_action=next_action,
        total_duration_ms=outcome.total_duration_ms,
        stops=stops,
        warnings=[] if summary is None else [contract.Message.of(warning) for warning in prepared.warnings(summary)],
        notices=list(outcome.notice_lines),
        summary=None if summary is None else prepared.summary(summary),
    )


def _unexpected_result(dry_run: bool) -> contract.RunOutcome:
    """Wynik, gdy nie dało się zbudować widoku wyniku; rdzeń zapisał już metryki."""

    return contract.RunOutcome(
        result="BLAD_KRYTYCZNY",
        headline="Błąd",
        ending="after_engine",
        next_action="rerun" if dry_run else "open_period_folder",
        total_duration_ms=0,
        stops=[
            contract.Message(
                what="Nie udało się pokazać wyniku Uruchomienia procesu.",
                where="Centrum rozliczeń",
                action="Sprawdź Folder okresu i przekaż ten komunikat osobie utrzymującej narzędzie.",
            )
        ],
        warnings=[],
        notices=[],
        summary=None,
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

    def prepare(self, request: contract.RunRequest) -> PreparedRun[Any, Any]:
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


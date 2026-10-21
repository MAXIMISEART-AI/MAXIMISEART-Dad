"""Uruchomienia procesu z Centrum rozliczeń: jedno naraz, w wątku roboczym, z podglądem przez SSE.

Centrum jest rozmówcą rdzenia Uruchomienia procesu (``process_run``) i
podglądem projekcji postępu (ADR 0002, ADR 0004). Ten moduł nie zna żadnego
procesu: proces podaje gotowe ``PreparedRun`` (opis procesu, wejście
procesu, plik metryk i widok Uruchomienia procesu z ``run_view``), a moduł
prowadzi z nim rdzeń i publikuje widoki dla przeglądarki. Widok podsumowania robi rdzeń
w swojej osłonie, więc jego awaria to błąd po silniku z Komunikatem z katalogu
procesu, ten sam wynik co w metrykach. Zatrzymania, ostrzeżenia i decyzja taty
przechodzą jako Komunikaty w trzech częściach.

Każda zmiana stanu to nowy niemutowalny widok (``contract.RunView``) z kolejnym
numerem. Strumień SSE wysyła najpierw bieżący widok, potem każdy kolejny, więc
ponowne podłączenie (odświeżenie, nowa karta) zaczyna od bieżącego stanu.
Decyzja taty czeka w stanie ``awaiting_decision``, aż przyjdzie przez API.
"""

from __future__ import annotations

import threading
import uuid
from collections.abc import AsyncIterator, Callable, Mapping, Sequence
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
from rozliczenia.centrum.run_view import ProcessView
from rozliczenia.centrum.stops import ProblemFingerprint, StopMemory, diagnosis_offer
from rozliczenia.call_trace import CallTrace
from rozliczenia.decision import Decision
from rozliczenia.message import Message
from rozliczenia.process_run import (
    Finished,
    Outcome,
    Process,
    ProcessInputs,
    Stop,
    run_process,
)
from rozliczenia.progress import ProgressProjection, ProgressSnapshot
from rozliczenia.telemetry import MetricsStore

_STREAM_POLL_SECONDS: Final = 0.05
_KEEPALIVE_SECONDS: Final = 15.0
_RECONNECT_MS: Final = 1000
_CONTINUE_HINT: Final = "przy decyzji wybierz „Kontynuuj”"
# Ostatnia siatka adaptera: wyniku nie dało się pokazać, choć rdzeń zapisał już metryki.
_RESULT_NOT_SHOWN: Final = Message(
    code="BLAD_WYNIKU",
    what="Nie udało się pokazać wyniku Uruchomienia procesu.",
    where="Centrum rozliczeń",
    action="Sprawdź Folder okresu i przekaż ten komunikat osobie utrzymującej narzędzie.",
)

InputsT = TypeVar("InputsT", bound=ProcessInputs)
SummaryT = TypeVar("SummaryT")


@dataclass(frozen=True)
class PreparedRun(Generic[InputsT, SummaryT]):
    """Uruchomienie procesu gotowe do startu.

    ``done`` to tytuł wyniku po zapisie, np. „Plik zbiorczy przygotowany”.
    """

    key: contract.ProcessKey
    period: str
    process: Process[InputsT, SummaryT]
    inputs: InputsT
    metrics_path: Path
    done: str
    view: ProcessView[InputsT, SummaryT]

    @property
    def dry_run(self) -> bool:
        return self.inputs.dry_run

    def progress_view(self, snapshot: ProgressSnapshot) -> contract.Progress:
        return self.view.progress(snapshot, dry_run=self.dry_run)

    def summary_view(self, inputs: InputsT, summary: SummaryT) -> _SummaryView:
        return _SummaryView(
            summary=self.view.summary(summary, dry_run=self.dry_run),
            warnings=[contract.Message.of(warning) for warning in self.view.warnings(inputs, summary)],
        )


@dataclass(frozen=True)
class _SummaryView:
    """Podsumowanie i ostrzeżenia zakończonego procesu w kształcie kontraktu."""

    summary: contract.RunSummary
    warnings: list[contract.Message]


@dataclass(frozen=True)
class _StopView:
    """Zatrzymanie w wyniku Uruchomienia: rodzaj, proponowana Diagnoza i stan Zgłoszenia (``None`` bez nich)."""

    kind: contract.StopKind | None
    diagnosis: contract.DiagnosisOffer | None
    report: contract.ReportState | None


@dataclass(frozen=True)
class StoppedRun:
    """Zakończone Uruchomienie procesu z Zatrzymaniem, dla którego Centrum proponuje Diagnozę."""

    info: contract.RunInfo
    stop: Stop


class RunHost:
    """Jedno Uruchomienie procesu naraz w obrębie serwera i jego widoki dla przeglądarki.

    ``shutdown_refusal()`` odmawia zamknięcia serwera, gdy Uruchomienie trwa
    (także gdy czeka na decyzję taty). Początek i koniec każdego Uruchomienia
    trafiają do dziennika Centrum jako bezpieczne fakty, a rekord metryk każdego
    Uruchomienia z Centrum do ``CentrumRuns``. Ostatnie Zatrzymanie każdego procesu
    zostaje w pamięci (``StopMemory``), żeby rozpoznać powtórkę. Przy Zatrzymaniu
    z Diagnozą wynik pokazuje stan Zgłoszenia tego problemu (``report_state``).
    """

    def __init__(
        self,
        log: CentrumLog,
        centrum_runs: CentrumRuns,
        report_state: Callable[[ProblemFingerprint], contract.ReportState],
    ) -> None:
        self._log = log
        self._centrum_runs = centrum_runs
        self._report_state = report_state
        self._stops = StopMemory()
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

    def stopped(self, run_id: str) -> StoppedRun:
        """Bieżące Uruchomienie ``run_id`` z Zatrzymaniem „do Maksa” albo powtórką; inaczej ``contract.Refusal``."""

        with self._lock:
            run = self._run
            if run is None or run.info.id != run_id:
                raise contract.Refusal(404, "Nie ma takiego Uruchomienia procesu.")
            stop, offer = run.stop, run.diagnosis
        if not run.ended or stop is None or offer is None:
            raise contract.Refusal(
                409, "Diagnoza jest przy Zatrzymaniu do Maksa albo przy powtórce tego samego Komunikatu."
            )
        return StoppedRun(run.info, stop)

    def remember(self, prepared: PreparedRun[Any, Any], since: datetime) -> None:
        """Zapamiętuje rekord metryk, który dopisało to Uruchomienie, jako Uruchomienie z Centrum."""

        metrics = MetricsStore(prepared.metrics_path, prepared.process.counter_names)
        self._centrum_runs.remember(prepared.key, metrics, since, datetime.now(timezone.utc))

    def failed(self, failure: Exception) -> None:
        """Wyniku Uruchomienia nie dało się pokazać: do dziennika tylko typ wyjątku, bez jego tekstu."""

        self._log.unexpected_failure(failure, where="wynik Uruchomienia procesu")

    def stop_view(self, run: _Run, stop: Stop | None) -> _StopView:
        """Rodzaj Zatrzymania ``stop``, Diagnoza, którą Centrum z niego proponuje, i stan Zgłoszenia problemu."""

        kind = self._stops.kind(run.info.process, stop)
        offer = diagnosis_offer(stop, kind)
        report = (
            None
            if stop is None or offer is None
            else self._report_state(ProblemFingerprint.of(run.info.process, stop.message))
        )
        return _StopView(kind, offer, report)

    def show_report(self, run_id: str, state: contract.ReportState) -> None:
        """Nowy stan Zgłoszenia w wyniku zakończonego Uruchomienia ``run_id`` dla każdej karty Centrum."""

        with self._lock:
            view = self._events[-1].view
            if isinstance(view, contract.RunFinished) and view.run.id == run_id:
                result = view.result.model_copy(update={"report": state})
                self._publish_locked(view.model_copy(update={"result": result}))

    def finished(self, run: _Run, result: contract.RunOutcome, stop: Stop | None) -> None:
        info = run.info
        self._stops.remember(info.process, stop)
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
            title=prepared.process.name,
            period=prepared.period,
            dry_run=prepared.dry_run,
            confirms_readiness=prepared.view.confirms_readiness,
        )
        self._progress = prepared.progress_view(ProgressProjection().snapshot)
        self._stale = False
        self._decided = threading.Event()
        self._consent = False
        self.awaiting_decision = False
        self.ended = False
        self.stop: Stop | None = None
        self.diagnosis: contract.DiagnosisOffer | None = None

    def running_view(self) -> contract.RunRunning:
        return contract.RunRunning(
            state="running",
            run=self.info,
            progress=self._progress,
            progress_stale=self._stale,
        )

    def work(self) -> None:
        prepared = self._prepared
        stop: Stop | None
        try:
            since = datetime.now(timezone.utc)
            outcome = run_process(
                prepared.process, prepared.inputs, self, view=prepared.summary_view, metrics_path=prepared.metrics_path
            )
            self._host.remember(prepared, since)
            stop = None if isinstance(outcome.ending, Finished) else outcome.ending
            result = _run_result(outcome, prepared, self._host.stop_view(self, stop))
        except Exception as failure:  # noqa: BLE001 - granica wątku Uruchomienia: typ wyjątku trafia do dziennika Centrum
            self._host.failed(failure)
            stop = Stop("after_engine", _RESULT_NOT_SHOWN, CallTrace.of(failure))
            result = _unexpected_result(prepared.dry_run, self._host.stop_view(self, stop))
        self.stop = stop
        self.diagnosis = result.diagnosis
        self._host.finished(self, result, stop)
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

    # Decyzja taty w trakcie silnika (Conversation); wejście procesu przychodzi z ustawień.

    @property
    def continue_hint(self) -> str:
        return _CONTINUE_HINT

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

    # Podgląd postępu. Każde powiadomienie odświeża widok
    # na żywo; przeglądarka dostaje nowy widok tylko wtedy, gdy zmieniło się to, co pokazuje.

    def start_progress(self, snapshot: ProgressSnapshot) -> None:
        self._show(snapshot)

    def show_progress(self, snapshot: ProgressSnapshot) -> None:
        self._show(snapshot)

    def stop_progress(self) -> None:
        """Widok końcowy publikuje ``work`` razem z wynikiem."""

    def _show(self, snapshot: ProgressSnapshot) -> None:
        try:
            progress = self._prepared.progress_view(snapshot)
        except Exception:
            self._stale = True
            self._host.publish(self, self.running_view())
            raise
        if progress != self._progress:
            self._progress = progress
            self._host.publish(self, self.running_view())


def _mode(dry_run: bool) -> str:
    return "DRY-RUN" if dry_run else "RUN"


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


def _run_result(
    outcome: Outcome[_SummaryView],
    prepared: PreparedRun[Any, Any],
    stopped: _StopView,
) -> contract.RunOutcome:
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
        stops = [contract.Message.of(ending.message)]
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
    shown = outcome.view
    return contract.RunOutcome(
        result=outcome.result,
        headline=headline,
        ending=kind,
        next_action=next_action,
        stop_kind=stopped.kind,
        diagnosis=stopped.diagnosis,
        report=stopped.report,
        stops=stops,
        warnings=[] if shown is None else shown.warnings,
        notices=list(outcome.notices),
        summary=None if shown is None else shown.summary,
    )


def _unexpected_result(dry_run: bool, stopped: _StopView) -> contract.RunOutcome:
    """Ostatnia siatka: błąd samego adaptera po zakończeniu rdzenia (np. kontraktu wyniku); rdzeń zapisał już metryki."""

    return contract.RunOutcome(
        result="BLAD_KRYTYCZNY",
        headline="Błąd",
        ending="after_engine",
        next_action="rerun" if dry_run else "open_period_folder",
        stop_kind=stopped.kind,
        diagnosis=stopped.diagnosis,
        report=stopped.report,
        stops=[contract.Message.of(_RESULT_NOT_SHOWN)],
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

    @router.post("", operation_id="startRun", responses=contract.NOT_FOUND_OR_CONFLICT)
    def start(request: contract.RunRequest) -> contract.RunView:
        return host.start(by_key[request.process].prepare(request))

    @router.get("/current", operation_id="getCurrentRun")
    def current() -> contract.RunView:
        return host.current().view

    @router.post("/{run_id}/decision", operation_id="decideRun", responses=contract.NOT_FOUND_OR_CONFLICT)
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


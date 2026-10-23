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

Po wyniku, a przed końcem Uruchomienia w dzienniku, każde działanie po wyniku
(``AfterRun``, np. Kontrola ilości) dostaje zakończone Uruchomienie (``EndedRun``)
w osobnej osłonie: tylko krótka praca lokalna, nigdy sieć, a jego wyjątek nie
zmienia wyniku.
"""

from __future__ import annotations

import threading
import uuid
from collections.abc import AsyncIterator, Mapping, Sequence
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
from rozliczenia.centrum.run_view import ProcessView, Shown
from rozliczenia.centrum.stops import NO_DIAGNOSIS, StoppedRun, Stops
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
class Viewed(Generic[SummaryT]):
    """Widok rozmówcy Centrum: wynik dla karty i podsumowanie silnika, z którego powstał, dla działań po wyniku."""

    shown: Shown
    summary: SummaryT


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

    def viewed(self, inputs: InputsT, summary: SummaryT) -> Viewed[SummaryT]:
        """Widok dla ``run_process(view=...)``: tylko wskazuje podsumowanie, więc osłona rdzenia widzi to co dotąd."""

        return Viewed(self.view.shown(inputs, summary), summary)


@dataclass(frozen=True)
class EndedRun:
    """Zakończone Uruchomienie procesu z Centrum, każdą drogą: wszystko, co wiadomo po wyniku."""

    info: contract.RunInfo
    prepared: PreparedRun[Any, Any]
    outcome: Outcome[Viewed[Any]] | None
    """Wynik rdzenia; ``None``, gdy rdzeń nie oddał wyniku (ostatnia siatka adaptera)."""
    stopped: StoppedRun | None
    result: contract.RunOutcome
    progress: contract.Progress
    started_at: datetime
    ended_at: datetime

    @property
    def summary(self) -> object | None:
        """Podsumowanie silnika tylko wtedy, gdy karta pokazuje zakończony proces (``result.ending == "finished"``)."""

        if self.result.ending != "finished" or self.outcome is None or self.outcome.view is None:
            return None
        summary: object = self.outcome.view.summary
        return summary


class AfterRun(Protocol):
    def run_ended(self, run: EndedRun) -> None:
        """Na wątku Uruchomienia, przed końcem Uruchomienia: tylko lokalny zapis w milisekundach, bez sieci.

        Wyjątek nie zmienia wyniku: ``RunHost.after`` zapisuje jego typ w dzienniku i woła następne działanie.
        """
        ...


# Odmowa w trakcie Aktualizacji narzędzia: uruchomienia procesu, zamknięcia Centrum albo innej aktualizacji.
_UPDATING = "Trwa aktualizacja narzędzia. Poczekaj na jej wynik, potem {then}."
# Odmowa po przyjętym zamknięciu: wątek, który teraz by wystartował, zginąłby z końcem serwera.
_CLOSING = "Centrum rozliczeń się zamyka. Kliknij skrót „Centrum rozliczeń” na pulpicie, potem {then}."


class RunHost:
    """Jedno Uruchomienie procesu naraz w obrębie serwera i jego widoki dla przeglądarki.

    To samo miejsce „jedno naraz” zajmuje Aktualizacja narzędzia (``begin_update``
    do ``end_update``): w jej trakcie start Uruchomienia jest odrzucony, a w trakcie
    Uruchomienia ona. ``shutdown_refusal()`` odmawia zamknięcia serwera, gdy
    Uruchomienie trwa (także gdy czeka na decyzję taty) albo trwa aktualizacja, a gdy
    nie odmawia, od tej chwili odrzuca oba starty. Początek i koniec każdego Uruchomienia
    trafiają do dziennika Centrum jako bezpieczne fakty, a rekord metryk każdego
    Uruchomienia z Centrum do ``CentrumRuns``. Zatrzymanie zakończonego Uruchomienia
    przejmuje jego właściciel (``stops``); Diagnoza i „Wyślij do Maksa” idą tylko do
    Zatrzymania bieżącego Uruchomienia, a nowy stan Zgłoszenia trafia na jego kartę.
    Działania po wyniku (``after_run``) biegną przed końcem Uruchomienia, więc
    przyjęte zamknięcie Centrum albo Aktualizacja narzędzia ich nie przerwie.
    """

    def __init__(
        self, log: CentrumLog, centrum_runs: CentrumRuns, stops: Stops, *, after_run: Sequence[AfterRun]
    ) -> None:
        self._log = log
        self._centrum_runs = centrum_runs
        self._stops = stops
        self._after_run = tuple(after_run)
        self._lock = threading.Lock()
        self._sequence = 0
        self._events: list[contract.RunEvent] = [contract.RunEvent(sequence=0, view=contract.RunIdle(state="idle"))]
        self._run: _Run | None = None
        self._updating = False
        self._closing = False

    def shutdown_refusal(self) -> str | None:
        """Dlaczego teraz nie można zamknąć Centrum (``Shutdown.refuse_while``); ``None``, gdy nic nie trwa.

        ``None`` przyjmuje zamknięcie w tej samej blokadzie: kolejne Uruchomienie ani aktualizacja już nie wystartują.
        """

        with self._lock:
            busy = self._busy_locked("zamknij Centrum rozliczeń")
            if busy is None:
                self._closing = True
            return busy

    def begin_update(self) -> None:
        """Zajmuje miejsce „jedno naraz” na Aktualizację narzędzia; ``contract.Refusal``, gdy jest zajęte."""

        with self._lock:
            if self._closing:
                raise contract.Refusal(409, _CLOSING.format(then="zaktualizuj narzędzie"))
            if self._updating:
                raise contract.Refusal(409, "Trwa już aktualizacja narzędzia. Poczekaj na jej wynik.")
            busy = self._busy_locked("zaktualizuj narzędzie")
            if busy is not None:
                raise contract.Refusal(409, busy)
            self._updating = True

    def end_update(self) -> None:
        with self._lock:
            self._updating = False

    def _busy_locked(self, then: str) -> str | None:
        """Co teraz trwa, z prośbą, żeby poczekać i ``then``; ``None``, gdy nic."""

        if self._updating:
            return _UPDATING.format(then=then)
        run = self._run
        if run is None or run.ended:
            return None
        return (
            f"Trwa Uruchomienie procesu: {run.info.title}, okres {run.info.period}. "
            f"Poczekaj na jego wynik w Uruchomieniach, potem {then}."
        )

    def current(self) -> contract.RunEvent:
        with self._lock:
            return self._events[-1]

    def events_after(self, sequence: int) -> list[contract.RunEvent]:
        with self._lock:
            return [event for event in self._events if event.sequence > sequence]

    def start(self, prepared: PreparedRun[Any, Any]) -> contract.RunView:
        with self._lock:
            if self._closing:
                raise contract.Refusal(409, _CLOSING.format(then="uruchom proces"))
            if self._updating:
                raise contract.Refusal(409, _UPDATING.format(then="uruchom proces"))
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

    def diagnose(self, run_id: str) -> contract.Diagnosis:
        view, state = self._stops.diagnose(self._stopped(run_id))
        self._show_report(run_id, state)
        return view

    def send_report(self, run_id: str) -> contract.ReportState:
        state = self._stops.send(self._stopped(run_id))
        self._show_report(run_id, state)
        return state

    def _stopped(self, run_id: str) -> StoppedRun:
        with self._lock:
            run = self._run
            if run is None or run.info.id != run_id:
                raise contract.Refusal(404, "Nie ma takiego Uruchomienia procesu.")
            stopped = run.stopped
        if not run.ended or stopped is None:
            raise contract.Refusal(409, NO_DIAGNOSIS)
        return stopped

    def remember(self, prepared: PreparedRun[Any, Any], since: datetime) -> None:
        """Zapamiętuje rekord metryk, który dopisało to Uruchomienie, jako Uruchomienie z Centrum."""

        metrics = MetricsStore(prepared.metrics_path, prepared.process.counter_names)
        self._centrum_runs.remember(prepared.key, metrics, since, datetime.now(timezone.utc))

    def failed(self, failure: Exception) -> None:
        """Wyniku Uruchomienia nie dało się pokazać: do dziennika tylko typ wyjątku, bez jego tekstu."""

        self._log.unexpected_failure(failure, where="wynik Uruchomienia procesu")

    def _show_report(self, run_id: str, state: contract.ReportState) -> None:
        """Nowy stan Zgłoszenia w wyniku zakończonego Uruchomienia ``run_id`` dla każdej karty Centrum."""

        with self._lock:
            view = self._events[-1].view
            if isinstance(view, contract.RunFinished) and view.run.id == run_id:
                result = view.result.model_copy(update={"report": state})
                self._publish_locked(view.model_copy(update={"result": result}))

    def after(self, run: EndedRun) -> None:
        """Każde działanie po wyniku we własnej osłonie: błąd jednego nie pomija następnych ani nie zmienia wyniku."""

        for action in self._after_run:
            try:
                action.run_ended(run)
            except Exception as failure:  # noqa: BLE001 - działanie po wyniku nie może zmienić wyniku Uruchomienia
                self._log.unexpected_failure(failure, where="po wyniku Uruchomienia procesu")

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

    ``show_progress`` zamienia snapshot projekcji na widok i publikuje go.
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
        self.stopped: StoppedRun | None = None

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
        outcome: Outcome[Viewed[Any]] | None = None
        since = datetime.now(timezone.utc)
        try:
            outcome = run_process(
                prepared.process, prepared.inputs, self, view=prepared.viewed, metrics_path=prepared.metrics_path
            )
            self._host.remember(prepared, since)
            stop = None if isinstance(outcome.ending, Finished) else outcome.ending
            stopped = self._host._stops.ended(self.info, stop)
            result = _run_result(outcome, prepared, stopped)
        except Exception as failure:  # noqa: BLE001 - granica wątku Uruchomienia: typ wyjątku trafia do dziennika Centrum
            self._host.failed(failure)
            stop = Stop("after_engine", _RESULT_NOT_SHOWN, CallTrace.of(failure))
            stopped = self._host._stops.ended(self.info, stop)
            result = _unexpected_result(prepared.dry_run, stopped)
        self.stopped = stopped
        ended = EndedRun(self.info, prepared, outcome, stopped, result, self._progress, since, datetime.now(timezone.utc))
        self._host.after(ended)
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

    def show_progress(self, snapshot: ProgressSnapshot) -> None:
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
    outcome: Outcome[Viewed[Any]],
    prepared: PreparedRun[Any, Any],
    stopped: StoppedRun | None,
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
    shown = None if outcome.view is None else outcome.view.shown
    return contract.RunOutcome(
        result=outcome.result,
        headline=headline,
        ending=kind,
        next_action=next_action,
        stop_kind=None if stopped is None else stopped.kind,
        diagnosis=None if stopped is None else stopped.offer,
        report=None if stopped is None else stopped.report,
        stops=stops,
        warnings=[] if shown is None else [contract.Message.of(warning) for warning in shown.warnings],
        notices=list(outcome.notices),
        summary=None if shown is None else shown.summary,
    )


def _unexpected_result(dry_run: bool, stopped: StoppedRun) -> contract.RunOutcome:
    """Ostatnia siatka: błąd samego adaptera po zakończeniu rdzenia (np. kontraktu wyniku); rdzeń zapisał już metryki."""

    return contract.RunOutcome(
        result="BLAD_KRYTYCZNY",
        headline="Błąd",
        ending="after_engine",
        next_action="rerun" if dry_run else "open_period_folder",
        stop_kind=stopped.kind,
        diagnosis=stopped.offer,
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
    """Proces, który Centrum umie uruchomić: jego rdzeń, co pokazać przed startem i jak przygotować Uruchomienie."""

    @property
    def key(self) -> contract.ProcessKey: ...

    @property
    def process(self) -> Process[Any, Any]: ...

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

    @router.post("/{run_id}/diagnosis", operation_id="diagnoseRun", responses=contract.NOT_FOUND_OR_CONFLICT)
    def run_diagnosis(run_id: str) -> contract.Diagnosis:
        return host.diagnose(run_id)

    @router.post("/{run_id}/report", operation_id="reportRun", responses=contract.NOT_FOUND_OR_CONFLICT)
    def send_report(run_id: str) -> contract.ReportState:
        return host.send_report(run_id)

    return router


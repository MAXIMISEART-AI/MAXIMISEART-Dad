"""Uruchomienie procesu: rdzeń wspólny dla każdego rozmówcy i wejście ``run`` dla CLI.

Rdzeń (``run_process``) prowadzi Uruchomienie procesu od gotowego wejścia
procesu do wyniku: pomiar ``Czas uruchomienia`` bez czasu decyzji taty, jedną
projekcję postępu (ADR 0002) z odłączanym obserwatorem, przechwycenie każdego
wyjątku, widok podsumowania rozmówcy w tej samej osłonie, rekord metryk i
wynik jako strukturę (``Outcome``). Każde zakończenie to ``Finished`` albo
``Stop`` z Komunikatem z katalogu procesu. Rozmówca (``Interlocutor``)
pokazuje tacie Decyzję w trakcie silnika (``decision``), pokazuje postęp i sam
renderuje wynik: terminal (``TerminalConversation``) albo inny, np. Centrum
rozliczeń. Decyzję składa proces, nie rozmówca.

``run`` to wejście CLI obu procesów: parsuje argumenty, ustala wejście
procesu w rozmowie w terminalu, renderuje linie końcowe (status, ``Czas
uruchomienia``, podsumowanie, P50/P95 z pliku metryk) i zwraca kod wyjścia.
Proces opisuje tylko to, co jest jego i wspólne dla każdego rozmówcy
(``Process``); CLI procesu to argumenty, rozmowa i linie zakończenia
(``CliEntry``). Tekst wyjątku nigdy nie przechodzi
przez ten seam: tata widzi wyłącznie Komunikaty i linie podane przez proces.
"""

from __future__ import annotations

import argparse
from collections.abc import Callable, Iterator, Mapping, Sequence
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
import sys
import time
from typing import Any, Generic, Literal, Protocol, TextIO, TypeVar

from .call_trace import CallTrace
from .decision import Conversation, Decision
from .domain import ProgressEvent, ProgressObserver, ProgressPhase
from .message import Message, StopError
from .progress import ProgressProjection, ProgressSnapshot
from .telemetry import UNKNOWN_PERIOD, MetricsStore, comparable_records, metric_record, statistics_for
from .terminal_conversation import TerminalConversation

__all__ = [
    "Finished",
    "Interlocutor",
    "Outcome",
    "Process",
    "ProcessInputs",
    "Stop",
    "CliEntry",
    "TerminalSummary",
    "run",
    "run_process",
]

_DETACHED_OBSERVER_NOTICE = "Podgląd postępu przestał się aktualizować; wynik nie zależy od tego."
_EXIT_CODES = {"OK": 0, "WYMAGA_SPRAWDZENIA": 2, "BLAD_KRYTYCZNY": 1}


class ProcessInputs(Protocol):
    """Wejście procesu znane rdzeniowi: okres do metryk i podglądu oraz tryb."""

    @property
    def period(self) -> str: ...

    @property
    def dry_run(self) -> bool: ...


InputsT = TypeVar("InputsT", bound=ProcessInputs)
SummaryT = TypeVar("SummaryT")
ViewT = TypeVar("ViewT")


class Interlocutor(Conversation, Protocol):
    """Rozmówca Uruchomienia procesu: Decyzja taty w trakcie silnika i podgląd postępu.

    Podgląd dostaje wyłącznie niemutowalne snapshoty i neutralne powiadomienia
    jedynej projekcji postępu (ADR 0002). Wyjątek z metody podglądu odłącza
    go na resztę Uruchomienia bez wpływu na wynik.
    """

    def start_progress(self, snapshot: ProgressSnapshot, *, title: str, shows_templates: bool) -> None: ...

    def show_progress(self, snapshot: ProgressSnapshot, event: ProgressEvent) -> None: ...

    def stop_progress(self) -> None: ...


@dataclass(frozen=True)
class Stop:
    """Zatrzymanie Uruchomienia procesu; zawsze z Komunikatem z katalogu procesu (``message``).

    ``stop``: własne zatrzymanie procesu (``StopError``) z jego Komunikatem.
    ``unexpected``: inny wyjątek przed końcem silnika, z Komunikatem
    ``Process.unexpected_failure``. ``after_engine``: silnik skończył, ale nie
    dało się zbudować podsumowania, z Komunikatem ``Process.plan_not_shown``
    (DRY-RUN) albo ``Process.summary_not_shown`` (RUN).

    ``trace``: ślad wywołań nieoczekiwanego wyjątku (``unexpected``,
    ``after_engine``) dla Zgłoszenia do Maksa; nie należy do tożsamości
    Zatrzymania i nie trafia do terminala, dziennika ani metryk.
    """

    kind: Literal["stop", "unexpected", "after_engine"]
    message: Message
    trace: CallTrace | None = field(default=None, compare=False, repr=False)


@dataclass(frozen=True)
class Finished:
    """Fakty zakończonego procesu, te same w metrykach: wynik, liczniki i czasy etapów.

    Klucze ``counters`` to dokładnie ``Process.counter_names``.
    """

    result: Literal["OK", "WYMAGA_SPRAWDZENIA"]
    counters: Mapping[str, int]
    phase_durations_ms: Mapping[ProgressPhase, int]


@dataclass(frozen=True)
class Process(Generic[InputsT, SummaryT]):
    """Opis procesu dla rdzenia Uruchomienia procesu, wspólny dla każdego rozmówcy.

    ``name`` to nazwa procesu z GLOSSARY, a ``title`` nagłówek podglądu
    postępu. ``execute`` wywołuje silnik z gotowym wejściem procesu.
    Zatrzymanie zgłasza ``StopError`` z Komunikatem z katalogu procesu.
    Komunikaty zakończeń z tego samego katalogu (``unexpected_failure``,
    ``plan_not_shown``, ``summary_not_shown``) rdzeń dołącza do każdego innego
    zatrzymania, więc żaden rozmówca nie dobiera treści sam. ``finished`` to
    czysta funkcja faktów zakończonego procesu. ``metrics_path`` to domyślny
    plik metryk, ten sam dla CLI i Centrum rozliczeń.
    """

    name: str
    title: str
    shows_templates: bool
    counter_names: frozenset[str]
    metrics_path: Callable[[], Path]
    metrics_failure_tail: str
    execute: Callable[[InputsT, ProgressObserver, Conversation], SummaryT]
    finished: Callable[[SummaryT], Finished]
    unexpected_failure: Message
    plan_not_shown: Message
    summary_not_shown: Message


@dataclass(frozen=True)
class Outcome(Generic[ViewT]):
    """Wynik Uruchomienia procesu dla rozmówcy, bez linii terminala.

    ``view`` to widok podsumowania rozmówcy, gdy proces się zakończył
    (``Finished``); zrobiła go funkcja rozmówcy w osłonie rdzenia.
    ``notices`` to neutralne ostrzeżenia: niezapisane metryki i odłączony
    podgląd postępu. ``metrics_saved``: rekord metryk trafił do pliku metryk.
    """

    ending: Finished | Stop
    view: ViewT | None
    total_duration_ms: int
    notices: tuple[str, ...]
    metrics_saved: bool

    @property
    def result(self) -> Literal["OK", "WYMAGA_SPRAWDZENIA", "BLAD_KRYTYCZNY"]:
        return self.ending.result if isinstance(self.ending, Finished) else "BLAD_KRYTYCZNY"


@dataclass(frozen=True)
class TerminalSummary:
    """Podsumowanie w terminalu: ``status_lines`` przed ``Czas uruchomienia``, ``summary_lines`` po nim."""

    status_lines: Sequence[str]
    summary_lines: Sequence[str]


@dataclass(frozen=True)
class CliEntry(Generic[InputsT, SummaryT]):
    """CLI procesu: argumenty, ustalenie wejścia procesu w terminalu i linie zakończenia.

    ``parser`` ma ``--dry-run`` i ``--metrics``. ``gather`` ustala wejście
    procesu z argumentów w rozmowie w terminalu; zatrzymanie zgłasza
    ``StopError`` z Komunikatem z katalogu procesu. ``summary`` robi linie
    podsumowania; rdzeń woła ją w swojej osłonie, więc jej wyjątek to błąd po
    silniku. ``stop`` renderuje zatrzymanie z ``Stop.message.terminal_lines``.
    """

    parser: Callable[[], argparse.ArgumentParser]
    gather: Callable[[argparse.Namespace, TerminalConversation], InputsT]
    summary: Callable[[InputsT, SummaryT], TerminalSummary]
    stop: Callable[[Stop], Sequence[str]]


@dataclass
class _Clock:
    """``Czas uruchomienia`` od startu silnika, bez czasu decyzji taty."""

    started: float = field(default_factory=time.perf_counter)
    paused_s: float = 0.0

    def elapsed_ms(self) -> int:
        return max(0, round((time.perf_counter() - self.started - self.paused_s) * 1000))

    @contextmanager
    def paused(self) -> Iterator[None]:
        paused_at = time.perf_counter()
        try:
            yield
        finally:
            self.paused_s += time.perf_counter() - paused_at


class _ClockedConversation:
    """Rozmowa rozmówcy dla silnika; czas czekania na Decyzję taty wstrzymuje zegar rdzenia."""

    def __init__(self, interlocutor: Interlocutor, clock: _Clock) -> None:
        self._interlocutor = interlocutor
        self._clock = clock

    @property
    def continue_hint(self) -> str:
        return self._interlocutor.continue_hint

    def confirm(self, decision: Decision) -> bool:
        with self._clock.paused():
            return self._interlocutor.confirm(decision)


class _Observation:
    """Obserwator silnika: jedna projekcja postępu i podgląd rozmówcy (ADR 0002).

    Wyjątek projekcji albo podglądu oznacza odłączenie: sekwencer etapów
    przestaje wysyłać zdarzenia, a rdzeń kończy jedną neutralną linią.
    """

    def __init__(self, interlocutor: Interlocutor, mode: str, period: str) -> None:
        self._interlocutor = interlocutor
        self.projection = ProgressProjection(mode, period)
        self.failed = False

    def start(self, *, title: str, shows_templates: bool) -> None:
        try:
            self._interlocutor.start_progress(self.projection.snapshot, title=title, shows_templates=shows_templates)
        except Exception:  # noqa: BLE001 - ADR 0002: awaria podglądu odłącza go, rdzeń zgłasza to neutralną linią
            self.failed = True

    def __call__(self, event: ProgressEvent) -> None:
        try:
            update = self.projection.update(event)
            if self.failed:
                raise RuntimeError("Progress view is detached.")
            self._interlocutor.show_progress(update.snapshot, update.event)
        except Exception:
            self.failed = True
            raise

    def stop(self) -> None:
        try:
            self._interlocutor.stop_progress()
        except Exception:  # noqa: BLE001 - ADR 0002: awaria podglądu odłącza go, rdzeń zgłasza to neutralną linią
            self.failed = True


def _stop_from(error: Exception, process: Process[Any, Any]) -> Stop:
    """Własne zatrzymanie procesu z jego Komunikatem; każdy inny wyjątek to Komunikat nieoczekiwanego błędu."""

    if isinstance(error, StopError):
        return Stop("stop", error.message)
    return Stop("unexpected", process.unexpected_failure, CallTrace.of(error))


def _gather(
    process: Process[InputsT, SummaryT],
    entry: CliEntry[InputsT, SummaryT],
    args: argparse.Namespace,
    conversation: TerminalConversation,
) -> InputsT | Stop:
    try:
        return entry.gather(args, conversation)
    except Exception as error:  # noqa: BLE001 - granica procesu: _stop_from rozróżnia błąd typowany od nieoczekiwanego
        return _stop_from(error, process)


# Budowa podsumowania i widoku rozmówcy odroczona do chwili po pomiarze Czasu
# uruchomienia i zatrzymaniu podglądu, żeby jej czas się nie liczył, a linie szły pod podglądem.
_DeferredSummary = Callable[[], tuple[Finished, ViewT]]


def _run_engine(
    process: Process[InputsT, SummaryT],
    inputs: InputsT,
    observation: _Observation,
    conversation: Conversation,
    view: Callable[[InputsT, SummaryT], ViewT],
) -> _DeferredSummary[ViewT] | Stop:
    """Silnik z podglądem jako obserwatorem; po sukcesie zwraca odroczoną budowę podsumowania i widoku."""

    try:
        summary = process.execute(inputs, observation, conversation)
    except Exception as error:  # noqa: BLE001 - granica procesu: _stop_from rozróżnia błąd typowany od nieoczekiwanego
        return _stop_from(error, process)
    except BaseException:
        observation.stop()
        raise
    return lambda: (process.finished(summary), view(inputs, summary))


def _build_summary(
    engine_outcome: _DeferredSummary[ViewT] | Stop, *, not_shown: Message
) -> tuple[Finished | Stop, ViewT | None]:
    """Buduje odroczone podsumowanie i widok; błąd to zatrzymanie ``after_engine`` z Komunikatem ``not_shown``."""

    if isinstance(engine_outcome, Stop):
        return engine_outcome, None
    try:
        return engine_outcome()
    except Exception as error:  # noqa: BLE001 - granica procesu: kończy jako zatrzymanie "after_engine" w wyniku i metrykach
        return Stop("after_engine", not_shown, CallTrace.of(error)), None


def _metrics_warning(process: Process[Any, Any]) -> str:
    return f"Ostrzeżenie: Nie zapisano metryk; {process.metrics_failure_tail}"


def _conduct(
    process: Process[InputsT, SummaryT],
    gathered: InputsT | Stop,
    interlocutor: Interlocutor,
    view: Callable[[InputsT, SummaryT], ViewT],
    metrics_path: Path,
    *,
    dry_run: bool,
) -> Outcome[ViewT]:
    """Rdzeń od ustalonego wejścia procesu (albo zatrzymania przy jego ustalaniu) do wyniku."""

    mode = "DRY-RUN" if dry_run else "RUN"
    period = UNKNOWN_PERIOD if isinstance(gathered, Stop) else gathered.period
    # Czas liczony od startu silnika, bez okien wyboru i czasu odpowiedzi taty.
    started_at = datetime.now(timezone.utc).isoformat()
    clock = _Clock()
    observation = _Observation(interlocutor, mode, period)
    observation.start(title=process.title, shows_templates=process.shows_templates)

    engine_outcome = (
        gathered
        if isinstance(gathered, Stop)
        else _run_engine(process, gathered, observation, _ClockedConversation(interlocutor, clock), view)
    )
    total_duration_ms = clock.elapsed_ms()
    observation.stop()
    ending, shown = _build_summary(
        engine_outcome, not_shown=process.plan_not_shown if dry_run else process.summary_not_shown
    )

    finished = ending if isinstance(ending, Finished) else None
    record = metric_record(
        mode=mode,
        period=period,
        started_at=started_at,
        total_duration_ms=total_duration_ms,
        phase_durations_ms=(
            finished.phase_durations_ms if finished else observation.projection.snapshot.phase_durations_ms
        ),
        result=finished.result if finished else "BLAD_KRYTYCZNY",
        counters=finished.counters if finished else dict.fromkeys(process.counter_names, 0),
    )
    notices: list[str] = []
    try:
        MetricsStore(metrics_path, process.counter_names).append(record)
        metrics_saved = True
    except (OSError, UnicodeError, ValueError):
        metrics_saved = False
        notices.append(_metrics_warning(process))
    if observation.failed:
        notices.append(_DETACHED_OBSERVER_NOTICE)

    return Outcome(
        ending=ending,
        view=shown,
        total_duration_ms=total_duration_ms,
        notices=tuple(notices),
        metrics_saved=metrics_saved,
    )


def run_process(
    process: Process[InputsT, SummaryT],
    inputs: InputsT,
    interlocutor: Interlocutor,
    *,
    view: Callable[[InputsT, SummaryT], ViewT],
    metrics_path: Path,
) -> Outcome[ViewT]:
    """Prowadzi jedno Uruchomienie procesu z gotowym wejściem procesu i dowolnym rozmówcą.

    Bez ``argparse`` i bez strumieni terminala. ``view`` robi z podsumowania
    silnika widok rozmówcy; jej wyjątek to błąd po silniku z Komunikatem
    zakończenia procesu. Rekord metryk trafia do ``metrics_path``; rozmówca
    renderuje ``Outcome`` sam.
    """

    return _conduct(process, inputs, interlocutor, view, metrics_path, dry_run=inputs.dry_run)


def _statistics_lines(records: list[dict[str, Any]], counter_names: frozenset[str]) -> list[str]:
    labels = {"total": "całe uruchomienie"}
    lines: list[str] = []
    for mode in ("RUN", "DRY-RUN"):
        comparable = comparable_records(records, mode, counter_names)
        stats = statistics_for(records, mode, counter_names)
        if stats is None:
            continue
        lines.append(f"Statystyki {mode} | próbek: {len(comparable)}")
        lines.extend(f"{labels.get(name, name)} | P50: {p50} ms | P95: {p95} ms" for name, (p50, p95) in stats.items())
    return lines


def _final_lines(
    process: Process[Any, Any], entry: CliEntry[Any, Any], outcome: Outcome[TerminalSummary], metrics_path: Path
) -> list[str]:
    """Linie końcowe w terminalu: status, ``Czas uruchomienia``, podsumowanie, P50/P95 i ostrzeżenia."""

    if isinstance(outcome.ending, Stop):
        status, summary = list(entry.stop(outcome.ending)), []
    else:
        assert outcome.view is not None  # zakończony proces zawsze ma widok podsumowania
        status, summary = list(outcome.view.status_lines), list(outcome.view.summary_lines)
    statistics: list[str] = []
    notices = list(outcome.notices)
    if outcome.metrics_saved:
        try:
            statistics = _statistics_lines(
                MetricsStore(metrics_path, process.counter_names).read(), process.counter_names
            )
        except (OSError, UnicodeError, ValueError):
            # Historia nieczytelna tuż po zapisie: jak przy nieudanym zapisie, ostrzeżenie zamiast statystyk.
            notices.insert(0, _metrics_warning(process))
    return [*status, f"Czas uruchomienia: {outcome.total_duration_ms} ms", *summary, *statistics, *notices]


def run(
    process: Process[InputsT, SummaryT],
    entry: CliEntry[InputsT, SummaryT],
    argv: list[str] | None = None,
    *,
    output: TextIO | None = None,
    input_stream: TextIO | None = None,
) -> int:
    """Wejście CLI: Uruchomienie procesu w terminalu; ``0`` OK, ``2`` Wymaga sprawdzenia, ``1`` zatrzymanie."""

    terminal = TerminalConversation(output or sys.stdout, input_stream or sys.stdin)
    args = entry.parser().parse_args(argv)
    gathered = _gather(process, entry, args, terminal)
    outcome = _conduct(process, gathered, terminal, entry.summary, args.metrics, dry_run=args.dry_run)
    terminal.print_lines(_final_lines(process, entry, outcome, args.metrics))
    return _EXIT_CODES[outcome.result]

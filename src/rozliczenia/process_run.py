"""Uruchomienie procesu: rdzeń wspólny dla każdego rozmówcy i wejście ``run`` dla CLI.

Rdzeń (``run_process``) prowadzi Uruchomienie procesu od gotowego wejścia
procesu do wyniku: pomiar ``Czas uruchomienia`` bez czasu decyzji taty, jedną
projekcję postępu (ADR 0002) z odłączanym obserwatorem, przechwycenie każdego
wyjątku, zamianę na ``Stop`` albo ``Finished``, metryki z P50/P95 i linie
końcowe. Rozmówca (``Interlocutor``) rozmawia z tatą i pokazuje postęp:
terminal (``TerminalConversation``) albo inny, np. Centrum rozliczeń.

``run`` to wejście CLI obu procesów: parsuje argumenty, ustala wejście
procesu w rozmowie w terminalu i zwraca kod wyjścia. Proces opisuje tylko to,
co jest jego (``Process``). Tekst wyjątku nigdy nie przechodzi przez ten seam:
tata widzi wyłącznie linie podane przez proces.
"""

from __future__ import annotations

import argparse
from collections.abc import Callable, Iterator, Mapping, Sequence
from contextlib import AbstractContextManager, contextmanager
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
import sys
import time
from typing import Any, Generic, Literal, Protocol, TextIO, TypeVar

from .domain import ProgressEvent, ProgressObserver, ProgressPhase
from .message import Message, StopError
from .progress import ProgressNotice, ProgressProjection, ProgressSnapshot
from .telemetry import UNKNOWN_PERIOD, MetricsStore, comparable_records, metric_record, statistics_for
from .terminal_conversation import TerminalConversation

__all__ = [
    "Conversation",
    "Decision",
    "Finished",
    "Interlocutor",
    "Outcome",
    "Process",
    "ProcessInputs",
    "Stop",
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


@dataclass(frozen=True)
class Decision:
    """Pytanie do taty w trakcie silnika: tytuł, komunikat, liczby z etykietami i pytanie.

    Terminal pokazuje ``lines`` i pyta ``t``/``n``; inny rozmówca pokazuje te
    same części bez parsowania linii.
    """

    title: str
    message: Message
    counts_title: str
    counts: Sequence[tuple[str, int]]
    question: str

    @property
    def lines(self) -> list[str]:
        return [
            self.title,
            f"Co się stało: {self.message.what}",
            f"Gdzie: {self.message.where}",
            f"Co zrobić: {self.message.action}",
            f"{self.counts_title}:",
            *(f"- {label}: {count}" for label, count in self.counts),
        ]


class Conversation(Protocol):
    """Rozmowa z tatą w trakcie silnika, dostępna dla ``Process.execute``.

    ``confirm`` to decyzja taty (np. o niepełnym okresie): ``True`` to zgoda.
    ``continue_hint`` mówi, jak u tego rozmówcy wyraża się zgodę (do komunikatu
    po odmowie). ``ask`` to pytanie o tekst; ``None``, gdy odpowiedzi nie ma.
    ``paused`` wstrzymuje podgląd na dłuższą rozmowę. Czas ``confirm`` i
    ``paused`` nie wlicza się do ``Czas uruchomienia``.
    """

    @property
    def continue_hint(self) -> str: ...

    def say(self, *lines: str) -> None: ...

    def ask(self, prompt: str) -> str | None: ...

    def confirm(self, decision: Decision) -> bool: ...

    def paused(self) -> AbstractContextManager[None]: ...


class Interlocutor(Conversation, Protocol):
    """Rozmówca Uruchomienia procesu: rozmowa z tatą i podgląd postępu.

    Podgląd dostaje wyłącznie niemutowalne snapshoty i neutralne powiadomienia
    jedynej projekcji postępu (ADR 0002). Wyjątek z metody podglądu odłącza
    go na resztę Uruchomienia bez wpływu na wynik.
    """

    def start_progress(self, snapshot: ProgressSnapshot, *, title: str, shows_templates: bool) -> None: ...

    def show_progress(self, snapshot: ProgressSnapshot, notice: ProgressNotice) -> None: ...

    def stop_progress(self) -> None: ...


@dataclass(frozen=True)
class Stop:
    """Zatrzymanie Uruchomienia procesu przekazywane procesowi do ``stopped``.

    ``stop``: własne zatrzymanie procesu (``StopError``) z liniami terminala
    ``lines`` i jego Komunikatem (``message``).
    ``unexpected``: inny wyjątek przed końcem silnika. ``after_engine``: silnik
    skończył, ale nie dało się zbudować podsumowania. Tylko ``stop`` ma linie
    i komunikat. ``dry_run``: Uruchomienie DRY-RUN, w którym nic nie zapisano.
    """

    kind: Literal["stop", "unexpected", "after_engine"]
    dry_run: bool
    lines: tuple[str, ...] = ()
    message: Message | None = None


@dataclass(frozen=True)
class Finished:
    """Wynik zakończonego procesu: linie dla taty i dane do metryk.

    ``status_lines`` są przed ``Czas uruchomienia``, ``summary_lines`` po nim.
    Klucze ``counters`` to dokładnie ``Process.counter_names``.
    """

    status_lines: Sequence[str]
    summary_lines: Sequence[str]
    result: Literal["OK", "WYMAGA_SPRAWDZENIA"]
    counters: Mapping[str, int]
    phase_durations_ms: Mapping[ProgressPhase, int]


@dataclass(frozen=True)
class Process(Generic[InputsT, SummaryT]):
    """Opis procesu dla rdzenia Uruchomienia procesu.

    ``execute`` wywołuje silnik z gotowym wejściem procesu. Zatrzymanie
    zgłasza ``StopError`` z Komunikatem z katalogu procesu (``gather`` też).
    ``finished`` i ``stopped`` są czystymi funkcjami linii końcowych, wspólnymi
    dla każdego rozmówcy.

    Tylko dla CLI: ``parser`` ma ``--dry-run`` i ``--metrics``, a ``gather``
    ustala wejście procesu z argumentów w rozmowie w terminalu.
    """

    title: str
    shows_templates: bool
    parser: Callable[[], argparse.ArgumentParser]
    counter_names: frozenset[str]
    metrics_failure_tail: str
    gather: Callable[[argparse.Namespace, TerminalConversation], InputsT]
    execute: Callable[[InputsT, ProgressObserver, Conversation], SummaryT]
    finished: Callable[[InputsT, SummaryT], Finished]
    stopped: Callable[[Stop], Sequence[str]]


@dataclass(frozen=True)
class Outcome(Generic[SummaryT]):
    """Wynik Uruchomienia procesu dla rozmówcy, z liniami takimi samymi jak w terminalu.

    ``summary`` to podsumowanie silnika, gdy proces się zakończył (``Finished``).
    ``notice_lines`` to ostrzeżenie o niezapisanych metrykach i linia o
    odłączonym podglądzie postępu.
    """

    ending: Finished | Stop
    summary: SummaryT | None
    total_duration_ms: int
    status_lines: tuple[str, ...]
    summary_lines: tuple[str, ...]
    statistics_lines: tuple[str, ...]
    notice_lines: tuple[str, ...]

    @property
    def result(self) -> Literal["OK", "WYMAGA_SPRAWDZENIA", "BLAD_KRYTYCZNY"]:
        return self.ending.result if isinstance(self.ending, Finished) else "BLAD_KRYTYCZNY"

    @property
    def lines(self) -> tuple[str, ...]:
        """Wszystkie linie końcowe w kolejności, w jakiej widzi je tata."""

        return (
            *self.status_lines,
            f"Czas uruchomienia: {self.total_duration_ms} ms",
            *self.summary_lines,
            *self.statistics_lines,
            *self.notice_lines,
        )


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
    """Rozmowa rozmówcy dla silnika; decyzja i pauza taty wstrzymują zegar rdzenia."""

    def __init__(self, interlocutor: Interlocutor, clock: _Clock) -> None:
        self._interlocutor = interlocutor
        self._clock = clock

    @property
    def continue_hint(self) -> str:
        return self._interlocutor.continue_hint

    def say(self, *lines: str) -> None:
        self._interlocutor.say(*lines)

    def ask(self, prompt: str) -> str | None:
        return self._interlocutor.ask(prompt)

    def confirm(self, decision: Decision) -> bool:
        with self._clock.paused():
            return self._interlocutor.confirm(decision)

    @contextmanager
    def paused(self) -> Iterator[None]:
        with self._clock.paused(), self._interlocutor.paused():
            yield


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
            self._interlocutor.show_progress(update.snapshot, update.notice)
        except Exception:
            self.failed = True
            raise

    def stop(self) -> None:
        try:
            self._interlocutor.stop_progress()
        except Exception:  # noqa: BLE001 - ADR 0002: awaria podglądu odłącza go, rdzeń zgłasza to neutralną linią
            self.failed = True


def _stop_from(error: Exception, *, dry_run: bool) -> Stop:
    """Linie terminala to ``terminal_line`` Komunikatu, jeśli jest, a w przeciwnym razie jego trzy części."""

    if not isinstance(error, StopError):
        return Stop("unexpected", dry_run)
    return Stop("stop", dry_run, tuple(error.message.terminal_lines), error.message)


def _gather(
    process: Process[InputsT, SummaryT], args: argparse.Namespace, conversation: TerminalConversation
) -> InputsT | Stop:
    try:
        return process.gather(args, conversation)
    except Exception as error:  # noqa: BLE001 - granica procesu: _stop_from rozróżnia błąd typowany od nieoczekiwanego
        return _stop_from(error, dry_run=args.dry_run)


# Budowa podsumowania odroczona do chwili po pomiarze Czasu uruchomienia i
# zatrzymaniu podglądu, żeby jej czas się nie liczył, a linie szły pod podglądem.
_DeferredSummary = Callable[[], tuple[Finished, SummaryT]]


def _run_engine(
    process: Process[InputsT, SummaryT],
    inputs: InputsT,
    observation: _Observation,
    conversation: Conversation,
    *,
    dry_run: bool,
) -> _DeferredSummary[SummaryT] | Stop:
    """Silnik z podglądem jako obserwatorem; po sukcesie zwraca odroczoną budowę podsumowania."""

    try:
        summary = process.execute(inputs, observation, conversation)
    except Exception as error:  # noqa: BLE001 - granica procesu: _stop_from rozróżnia błąd typowany od nieoczekiwanego
        return _stop_from(error, dry_run=dry_run)
    except BaseException:
        observation.stop()
        raise
    return lambda: (process.finished(inputs, summary), summary)


def _build_summary(
    engine_outcome: _DeferredSummary[SummaryT] | Stop, *, dry_run: bool
) -> tuple[Finished | Stop, SummaryT | None]:
    """Buduje odroczone podsumowanie; jego błąd to zatrzymanie ``after_engine``."""

    if isinstance(engine_outcome, Stop):
        return engine_outcome, None
    try:
        return engine_outcome()
    except Exception:  # noqa: BLE001 - granica procesu: kończy jako zatrzymanie "after_engine" w wyniku i metrykach
        return Stop("after_engine", dry_run), None


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


def _conduct(
    process: Process[InputsT, SummaryT],
    gathered: InputsT | Stop,
    interlocutor: Interlocutor,
    metrics_path: Path,
) -> Outcome[SummaryT]:
    """Rdzeń od ustalonego wejścia procesu (albo zatrzymania przy jego ustalaniu) do wyniku."""

    dry_run = gathered.dry_run
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
        else _run_engine(process, gathered, observation, _ClockedConversation(interlocutor, clock), dry_run=dry_run)
    )
    total_duration_ms = clock.elapsed_ms()
    observation.stop()
    ending, summary = _build_summary(engine_outcome, dry_run=dry_run)

    if isinstance(ending, Finished):
        finished: Finished | None = ending
        status_lines, summary_lines = tuple(ending.status_lines), tuple(ending.summary_lines)
    else:
        finished = None
        status_lines, summary_lines = tuple(process.stopped(ending)), ()

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
    store = MetricsStore(metrics_path, process.counter_names)
    statistics_lines: list[str] = []
    notice_lines: list[str] = []
    try:
        store.append(record)
        statistics_lines = _statistics_lines(store.read(), process.counter_names)
    except (OSError, UnicodeError, ValueError):
        notice_lines.append(f"Ostrzeżenie: Nie zapisano metryk; {process.metrics_failure_tail}")
    if observation.failed:
        notice_lines.append(_DETACHED_OBSERVER_NOTICE)

    return Outcome(
        ending=ending,
        summary=summary,
        total_duration_ms=total_duration_ms,
        status_lines=status_lines,
        summary_lines=summary_lines,
        statistics_lines=tuple(statistics_lines),
        notice_lines=tuple(notice_lines),
    )


def run_process(
    process: Process[InputsT, SummaryT],
    inputs: InputsT,
    interlocutor: Interlocutor,
    *,
    metrics_path: Path,
) -> Outcome[SummaryT]:
    """Prowadzi jedno Uruchomienie procesu z gotowym wejściem procesu i dowolnym rozmówcą.

    Bez ``argparse`` i bez strumieni terminala. Rekord metryk trafia do
    ``metrics_path``; linie końcowe są w ``Outcome``, rozmówca pokazuje je sam.
    """

    return _conduct(process, inputs, interlocutor, metrics_path)


def run(
    process: Process[InputsT, SummaryT],
    argv: list[str] | None = None,
    *,
    output: TextIO | None = None,
    input_stream: TextIO | None = None,
    metrics_path: Path | None = None,
) -> int:
    """Wejście CLI: Uruchomienie procesu w terminalu; ``0`` OK, ``2`` Wymaga sprawdzenia, ``1`` zatrzymanie."""

    terminal = TerminalConversation(output or sys.stdout, input_stream or sys.stdin)
    args = process.parser().parse_args(argv)
    gathered = _gather(process, args, terminal)
    outcome = _conduct(process, gathered, terminal, metrics_path or args.metrics)
    terminal.print_lines(outcome.lines)
    return _EXIT_CODES[outcome.result]

"""Uruchomienie procesu: jedno wejście ``run`` dla CLI obu procesów taty.

Moduł prowadzi Uruchomienie procesu od argumentów do kodu wyjścia: rozmowę z
tatą, start pomiaru i podglądu postępu, przechwycenie każdego wyjątku,
``Czas uruchomienia``, metryki z P50/P95 i linię o odłączonym obserwatorze.
Proces opisuje tylko to, co jest jego (``Process``). Tekst wyjątku nigdy nie
przechodzi przez ten seam: tata widzi wyłącznie linie podane przez proces.
"""

from __future__ import annotations

import argparse
from collections.abc import Callable, Iterator, Mapping, Sequence
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime, timezone
import os
from pathlib import Path
import sys
import time
from typing import Any, Generic, Literal, Protocol, TextIO, TypeVar

from .domain import ProgressEvent, ProgressObserver, ProgressPhase
from .plain_progress import PlainProgressAdapter
from .progress import ProgressNotice, ProgressProjection
from .rich_progress import Console, Live, RichProgressAdapter
from .telemetry import UNKNOWN_PERIOD, MetricsStore, comparable_records, metric_record, statistics_for

__all__ = ["Conversation", "Finished", "Process", "Stop", "run"]

_DETACHED_OBSERVER_NOTICE = "Podgląd postępu przestał się aktualizować; wynik nie zależy od tego."
_EXIT_CODES = {"OK": 0, "WYMAGA_SPRAWDZENIA": 2}


class _Inputs(Protocol):
    @property
    def period(self) -> str: ...


InputsT = TypeVar("InputsT", bound=_Inputs)
SummaryT = TypeVar("SummaryT")


@dataclass(frozen=True)
class Stop:
    """Zatrzymanie Uruchomienia procesu przekazywane procesowi do ``stopped``.

    ``stop``: własne zatrzymanie procesu z bezpiecznymi liniami ``lines``.
    ``unexpected``: inny wyjątek przed końcem silnika. ``after_engine``: silnik
    skończył, ale nie dało się zbudować podsumowania. Tylko ``stop`` ma linie.
    ``dry_run``: Uruchomienie z ``--dry-run``, w którym nic nie zapisano.
    """

    kind: Literal["stop", "unexpected", "after_engine"]
    dry_run: bool
    lines: tuple[str, ...] = ()


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
    """Opis procesu dla ``run``.

    ``parser`` ma ``--dry-run`` i ``--metrics``. ``gather`` ustala wejście
    (pliki, okres) przed startem pomiaru; ``execute`` wywołuje silnik.
    Zatrzymanie zgłaszają wyjątkiem ``stop_type``, którego tekst jest z
    kontraktu bezpieczny; ``stop_lines`` zamienia go na linie. ``finished`` i
    ``stopped`` są czystymi funkcjami linii końcowych.
    """

    title: str
    shows_templates: bool
    parser: Callable[[], argparse.ArgumentParser]
    counter_names: frozenset[str]
    metrics_failure_tail: str
    stop_type: type[Exception]
    stop_lines: Callable[[Exception], Sequence[str]]
    gather: Callable[[argparse.Namespace, Conversation], InputsT]
    execute: Callable[[InputsT, ProgressObserver, Conversation], SummaryT]
    finished: Callable[[InputsT, SummaryT], Finished]
    stopped: Callable[[Stop], Sequence[str]]


def _ask_in_dialog(ask: Callable[[Any], str]) -> str:
    """Lokalne okno tkinter; pusty wynik, gdy anulowano albo okna nie da się pokazać."""

    try:
        import tkinter as tk
        from tkinter import filedialog

        root = tk.Tk()
        root.withdraw()
        try:
            return ask(filedialog) or ""
        finally:
            root.destroy()
    except Exception:
        return ""


def _is_interactive(stream: TextIO) -> bool:
    try:
        return bool(stream.isatty())
    except (AttributeError, OSError, ValueError):
        return False


@dataclass
class _Clock:
    """``Czas uruchomienia`` od startu silnika, bez czasu wstrzymania na pytanie."""

    started: float = field(default_factory=time.perf_counter)
    paused_s: float = 0.0

    def elapsed_ms(self) -> int:
        return max(0, round((time.perf_counter() - self.started - self.paused_s) * 1000))


class Conversation:
    """Rozmowa z tatą: okna wyboru, komunikaty, pytanie i wstrzymanie podglądu.

    Przed startem silnika pisze wprost do wyjścia. W trakcie silnika pytanie
    trzeba zadać w ``paused()``: podgląd postępu stoi, a czas oczekiwania nie
    wlicza się do ``Czas uruchomienia``.
    """

    def __init__(self, output: TextIO, input_stream: TextIO) -> None:
        self._output = output
        self._input_stream = input_stream
        self._dashboard: _Dashboard | None = None
        self._clock: _Clock | None = None

    def choose_file(self, title: str, filetypes: Sequence[tuple[str, str]]) -> Path | None:
        selected = _ask_in_dialog(lambda dialog: dialog.askopenfilename(title=title, filetypes=list(filetypes)))
        return Path(selected) if selected else None

    def choose_folder(self, title: str) -> Path | None:
        selected = _ask_in_dialog(lambda dialog: dialog.askdirectory(title=title, mustexist=True))
        return Path(selected) if selected else None

    def say(self, *lines: str) -> None:
        for line in lines:
            self._write(line + "\n")

    def ask(self, prompt: str) -> str | None:
        """Odpowiedź bez otaczających spacji; ``None``, gdy wejście się skończyło.

        Gdy odpowiedź nie pochodzi z terminala (który sam wyświetla Enter),
        dopisuje koniec linii, żeby kolejny komunikat nie trafił do linii pytania.
        """

        self._write(prompt)
        answer = self._input_stream.readline()
        if not _is_interactive(self._input_stream):
            self._write("\n")
        return None if answer == "" else answer.strip()

    @contextmanager
    def paused(self) -> Iterator[None]:
        """Wstrzymuje podgląd i zegar; po wyjątku (np. odmowie taty) podgląd nie wraca."""

        dashboard, clock = self._dashboard, self._clock
        if dashboard is None or clock is None:
            yield
            return
        paused_at = time.perf_counter()
        dashboard.stop()
        try:
            yield
        finally:
            clock.paused_s += time.perf_counter() - paused_at
        dashboard.resume()

    def _attach(self, dashboard: _Dashboard, clock: _Clock) -> None:
        self._dashboard = dashboard
        self._clock = clock

    def _write(self, text: str) -> None:
        try:
            self._output.write(text)
            self._output.flush()
        except (OSError, ValueError):
            pass


class _Dashboard:
    """Podgląd postępu Rich z liniowym trybem tekstowym dla nieinteraktywnego wyjścia."""

    def __init__(self, output: TextIO, mode: str, period: str, *, title: str, shows_templates: bool):
        self.output = output
        self.state = ProgressProjection(mode, period)
        self.plain_adapter = PlainProgressAdapter(self.print_line, title=title, shows_templates=shows_templates)
        self.rich_adapter = RichProgressAdapter(title=title, shows_templates=shows_templates)
        self._output_failed = False
        self.observer_failed = False
        try:
            self.console: Any | None = Console(file=output) if Console is not None else None
        except Exception:
            self.console = None
        self.interactive = (
            self._supports_live_output(output)
            and self.console is not None
            and self.console.color_system is not None
        )
        self.live: Any | None = None

    @staticmethod
    def _supports_live_output(output: TextIO) -> bool:
        if os.environ.get("NO_COLOR") is not None or os.environ.get("TERM") == "dumb":
            return False
        try:
            return bool(output.isatty())
        except (AttributeError, OSError):
            return False

    def start(self) -> None:
        if self.interactive and Live is not None:
            try:
                self.live = Live(self.render(), console=self.console, auto_refresh=False)
                self.live.start(refresh=True)
                return
            except Exception:
                self._disable_rich()
        elif self.interactive:
            self._disable_rich()
        self.plain_adapter.start(self.state.snapshot)

    def __call__(self, event: ProgressEvent) -> None:
        """Pokazuje jedno Zdarzenie przebiegu; wyjątek odłącza obserwatora (ADR 0002)."""

        try:
            self._show(event)
        except Exception:
            self.observer_failed = True
            raise

    def _show(self, event: ProgressEvent) -> None:
        update = self.state.update(event)
        if self._output_failed:
            raise OSError("Terminal output is unavailable.")
        if self.interactive:
            try:
                if self.live is None:
                    raise RuntimeError("Rich dashboard did not start.")
                self.live.update(self.rich_adapter.render(update.snapshot, update.notice), refresh=True)
                return
            except Exception:
                self._disable_rich()
                self.plain_adapter.start(update.snapshot)
        self.plain_adapter.update(update.snapshot, update.notice)
        if self._output_failed:
            raise OSError("Terminal output is unavailable.")

    def stop(self) -> None:
        """Zatrzymuje widok na żywo, żeby kolejne linie szły pod nim."""

        if self.live is not None:
            try:
                self.live.stop()
            except Exception:
                self._disable_rich()
            else:
                self.live = None

    def resume(self) -> None:
        """Wznawia widok na żywo po ``stop()``, np. po pytaniu do taty między etapami."""

        if not self.interactive or self.live is not None or Live is None:
            return
        try:
            self.live = Live(self.render(), console=self.console, auto_refresh=False)
            self.live.start(refresh=True)
        except Exception:
            self._disable_rich()

    @property
    def phase_durations_ms(self) -> Mapping[ProgressPhase, int]:
        """Czasy etapów widziane dotąd przez podgląd, także po przerwaniu."""

        return self.state.snapshot.phase_durations_ms

    def print_statistics(self, records: list[dict[str, Any]], counter_names: frozenset[str]) -> None:
        labels = {"total": "całe uruchomienie"}
        for mode in ("RUN", "DRY-RUN"):
            comparable = comparable_records(records, mode, counter_names)
            stats = statistics_for(records, mode, counter_names)
            if stats is None:
                continue
            self.print_line(f"Statystyki {mode} | próbek: {len(comparable)}")
            for name, (p50, p95) in stats.items():
                self.print_line(f"{labels.get(name, name)} | P50: {p50} ms | P95: {p95} ms")

    def render(self, notice: ProgressNotice | None = None) -> Any:
        return self.rich_adapter.render(self.state.snapshot, notice)

    def _disable_rich(self) -> None:
        live, self.live = self.live, None
        if live is not None:
            try:
                live.stop()
            except Exception:
                pass
        self.interactive = False
        self.console = None

    def print_line(self, message: str) -> None:
        if self._output_failed:
            return
        try:
            if self.interactive and self.console is not None:
                self.console.print(message)
            else:
                self.output.write(f"{message}\n")
        except (OSError, UnicodeError, ValueError):
            self._output_failed = True


def _stop_from(process: Process[Any, Any], error: Exception, *, dry_run: bool) -> Stop:
    if not isinstance(error, process.stop_type):
        return Stop("unexpected", dry_run)
    try:
        return Stop("stop", dry_run, tuple(process.stop_lines(error)))
    except Exception:
        return Stop("unexpected", dry_run)


def _gather(
    process: Process[InputsT, SummaryT], args: argparse.Namespace, conversation: Conversation
) -> InputsT | Stop:
    try:
        return process.gather(args, conversation)
    except Exception as error:
        return _stop_from(process, error, dry_run=args.dry_run)


# Budowa podsumowania odroczona do chwili po pomiarze Czasu uruchomienia i
# zatrzymaniu podglądu, żeby jej czas się nie liczył, a linie szły pod podglądem.
_DeferredSummary = Callable[[], Finished]


def _run_engine(
    process: Process[InputsT, SummaryT],
    inputs: InputsT,
    dashboard: _Dashboard,
    conversation: Conversation,
    *,
    dry_run: bool,
) -> _DeferredSummary | Stop:
    """Silnik z podglądem jako obserwatorem; po sukcesie zwraca odroczoną budowę podsumowania."""

    try:
        summary = process.execute(inputs, dashboard, conversation)
    except Exception as error:
        return _stop_from(process, error, dry_run=dry_run)
    except BaseException:
        dashboard.stop()
        raise
    return lambda: process.finished(inputs, summary)


def _build_summary(engine_outcome: _DeferredSummary | Stop, *, dry_run: bool) -> Finished | Stop:
    """Buduje odroczone podsumowanie; jego błąd to zatrzymanie ``after_engine``."""

    if isinstance(engine_outcome, Stop):
        return engine_outcome
    try:
        return engine_outcome()
    except Exception:
        return Stop("after_engine", dry_run)


def run(
    process: Process[InputsT, SummaryT],
    argv: list[str] | None = None,
    *,
    output: TextIO | None = None,
    input_stream: TextIO | None = None,
    metrics_path: Path | None = None,
) -> int:
    """Prowadzi jedno Uruchomienie procesu; ``0`` OK, ``2`` Wymaga sprawdzenia, ``1`` zatrzymanie."""

    output = output or sys.stdout
    conversation = Conversation(output, input_stream or sys.stdin)
    args = process.parser().parse_args(argv)
    mode = "DRY-RUN" if args.dry_run else "RUN"
    store = MetricsStore(metrics_path or args.metrics, process.counter_names)

    gathered = _gather(process, args, conversation)
    period = UNKNOWN_PERIOD if isinstance(gathered, Stop) else gathered.period
    # Czas liczony od startu silnika, bez okien wyboru i czasu odpowiedzi taty.
    started_at = datetime.now(timezone.utc).isoformat()
    clock = _Clock()
    dashboard = _Dashboard(output, mode, period, title=process.title, shows_templates=process.shows_templates)
    dashboard.start()
    conversation._attach(dashboard, clock)
    engine_outcome = (
        gathered
        if isinstance(gathered, Stop)
        else _run_engine(process, gathered, dashboard, conversation, dry_run=args.dry_run)
    )
    total_duration_ms = clock.elapsed_ms()
    dashboard.stop()
    ending = _build_summary(engine_outcome, dry_run=args.dry_run)

    if isinstance(ending, Finished):
        status_lines, summary_lines = ending.status_lines, ending.summary_lines
    else:
        status_lines, summary_lines = process.stopped(ending), ()
    for line in status_lines:
        dashboard.print_line(line)
    dashboard.print_line(f"Czas uruchomienia: {total_duration_ms} ms")
    for line in summary_lines:
        dashboard.print_line(line)

    finished = ending if isinstance(ending, Finished) else None
    record = metric_record(
        mode=mode,
        period=period,
        started_at=started_at,
        total_duration_ms=total_duration_ms,
        phase_durations_ms=finished.phase_durations_ms if finished else dashboard.phase_durations_ms,
        result=finished.result if finished else "BLAD_KRYTYCZNY",
        counters=finished.counters if finished else dict.fromkeys(process.counter_names, 0),
    )
    try:
        store.append(record)
        dashboard.print_statistics(store.read(), process.counter_names)
    except (OSError, UnicodeError, ValueError):
        dashboard.print_line(f"Ostrzeżenie: Nie zapisano metryk; {process.metrics_failure_tail}")

    if dashboard.observer_failed:
        dashboard.print_line(_DETACHED_OBSERVER_NOTICE)
    return _EXIT_CODES[finished.result] if finished else 1

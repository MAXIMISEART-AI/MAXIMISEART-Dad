"""Sekwencer etapów: protokół etapów procesu, Zdarzenia przebiegu i pomiar czasów."""

from __future__ import annotations

import time
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from types import MappingProxyType
from typing import Callable, TypeVar

from .domain import (
    ProgressEvent,
    ProgressEventFactory,
    ProgressObserver,
    ProgressPhase,
    ProgressProtocolError,
    ProgressState,
)


ResultT = TypeVar("ResultT")
_PHASE_ORDER = tuple(ProgressPhase)
_WORKER_STATES = frozenset({ProgressState.WORKER_START, ProgressState.WORKER_END, ProgressState.FAILED})


def elapsed_ms_since(started: float) -> int:
    """Zwraca nieujemny czas w milisekundach od odczytu ``time.perf_counter()``."""

    return max(0, round((time.perf_counter() - started) * 1000))


def _zero(result: object) -> int:
    """Liczba domyślna, gdy etap nie podaje żadnej wartości."""

    return 0


def _count(value: int, label: str) -> int:
    if type(value) is not int or value < 0:
        raise ProgressProtocolError(f"{label} musi być nieujemną liczbą całkowitą.")
    return value


class PhaseRunner:
    """Właściciel protokołu etapów jednego uruchomienia procesu.

    Proces wywołuje cztery etapy w stałej kolejności: ``check``, ``read``,
    ``plan`` i ``save``. Sekwencer wysyła START, END albo jedno FAILED każdego
    etapu oraz zdarzenia pośrednie: ``ISSUE_COUNT`` po Odczycie danych i
    ``PLAN_READY`` po Planowaniu. END Zapisywania dostaje liczbę Szablonów
    pracownika z planu.

    Funkcje liczące są czystymi funkcjami wyniku etapu; sekwencer wywołuje je
    przed END. Liczba problemów jest łączna dla uruchomienia, a pominięta w
    Planowaniu oznacza wartość z Odczytu danych.

    Zegar uruchomienia startuje przy utworzeniu. Awaria obserwatora odłącza go
    do końca uruchomienia i nie zmienia wyniku etapów. Czas etapu jest
    zapisywany także po przerwaniu.
    """

    def __init__(self, observer: ProgressObserver | None) -> None:
        self._observer = observer
        self._run_started = time.perf_counter()
        self._phase_started = self._run_started
        self._next_phase = 0
        self._active_phase: ProgressPhase | None = None
        # Któryś etap tego uruchomienia został przerwany; kolejnego etapu już nie ma.
        self._run_interrupted = False
        # Bieżące Zapisywanie zgłosiło już FAILED zdarzeniem wykonawcy, więc
        # sekwencer nie wysyła drugiego FAILED etapu.
        self._worker_failure_reported = False
        self._issue_count = 0
        self._template_total = 0
        self._durations_ms: dict[ProgressPhase, int] = {}

    def check(self, operation: Callable[[], ResultT]) -> ResultT:
        """Sprawdzanie."""

        return self._run_phase(ProgressPhase.CHECKING, operation)

    def read(
        self,
        operation: Callable[[], ResultT],
        *,
        issue_count: Callable[[ResultT], int] = _zero,
    ) -> ResultT:
        """Odczyt danych, a po nim ``ISSUE_COUNT``."""

        def record_counts(result: ResultT) -> None:
            self._record_issue_count(issue_count(result))

        result = self._run_phase(ProgressPhase.READING, operation, record_counts)
        self._emit(ProgressEventFactory.issue_count(elapsed_ms=self.elapsed_ms(), issue_count=self._issue_count))
        return result

    def plan(
        self,
        operation: Callable[[], ResultT],
        *,
        template_total: Callable[[ResultT], int] = _zero,
        issue_count: Callable[[ResultT], int] | None = None,
    ) -> ResultT:
        """Planowanie, a po nim ``PLAN_READY``."""

        def record_counts(result: ResultT) -> None:
            if issue_count is not None:
                self._record_issue_count(issue_count(result))
            self._template_total = _count(template_total(result), "Liczba Szablonów pracownika")

        result = self._run_phase(ProgressPhase.PLANNING, operation, record_counts)
        self._emit(
            ProgressEventFactory.plan_ready(
                template_total=self._template_total,
                elapsed_ms=self.elapsed_ms(),
                issue_count=self._issue_count,
            )
        )
        return result

    def save(self, operation: Callable[[], ResultT]) -> ResultT:
        """Zapisywanie; END ma liczbę Szablonów pracownika z planu."""

        return self._run_phase(ProgressPhase.SAVING, operation)

    def notify(self, event: ProgressEvent) -> None:
        """Przekazuje obserwatorowi zdarzenie wykonawcy z trwającego Zapisywania."""

        if event.worker_name is None or event.state not in _WORKER_STATES:
            raise ProgressProtocolError(
                f"Zdarzenie {event.state.value} etapu {event.phase.value} wysyła tylko sekwencer etapów."
            )
        if self._active_phase is not ProgressPhase.SAVING:
            raise ProgressProtocolError("Zdarzenie wykonawcy jest dozwolone tylko w trakcie Zapisywania.")
        if event.state is ProgressState.FAILED:
            self._worker_failure_reported = True
        self._emit(event)

    @contextmanager
    def paused(self) -> Iterator[None]:
        """Wstrzymuje zegar uruchomienia między etapami, np. na czas odpowiedzi taty."""

        if self._active_phase is not None:
            raise ProgressProtocolError(
                f"Nie można wstrzymać zegara w trakcie etapu {self._active_phase.value}."
            )
        paused_at = time.perf_counter()
        try:
            yield
        finally:
            self._run_started += time.perf_counter() - paused_at

    def elapsed_ms(self) -> int:
        """Czas od rozpoczęcia uruchomienia, bez czasu wstrzymania."""

        return elapsed_ms_since(self._run_started)

    def phase_elapsed_ms(self) -> int:
        """Czas od rozpoczęcia bieżącego (ostatniego) etapu."""

        return elapsed_ms_since(self._phase_started)

    def durations_ms(self) -> Mapping[ProgressPhase, int]:
        """Nowa kopia tylko do odczytu czasów etapów zmierzonych do tej chwili."""

        return MappingProxyType(dict(self._durations_ms))

    def _run_phase(
        self,
        phase: ProgressPhase,
        operation: Callable[[], ResultT],
        record_counts: Callable[[ResultT], None] | None = None,
    ) -> ResultT:
        """Wykonuje etap; ``record_counts`` zapisuje liczby z wyniku przed END."""

        self._enter(phase)
        self._phase_started = time.perf_counter()
        self._worker_failure_reported = False
        self._emit(ProgressEventFactory.phase_started(phase, elapsed_ms=self.elapsed_ms()))
        try:
            result = operation()
            if record_counts is not None:
                record_counts(result)
        except Exception:
            phase_elapsed_ms = self.phase_elapsed_ms()
            self._durations_ms[phase] = phase_elapsed_ms
            self._active_phase = None
            self._run_interrupted = True
            if not self._worker_failure_reported:
                self._emit(
                    ProgressEventFactory.phase_failed(
                        phase,
                        elapsed_ms=self.elapsed_ms(),
                        phase_elapsed_ms=phase_elapsed_ms,
                    )
                )
            raise
        phase_elapsed_ms = self.phase_elapsed_ms()
        self._durations_ms[phase] = phase_elapsed_ms
        self._active_phase = None
        final_template = self._template_total if phase is ProgressPhase.SAVING else 0
        self._emit(
            ProgressEventFactory.phase_ended(
                phase,
                template_index=final_template,
                template_total=final_template,
                elapsed_ms=self.elapsed_ms(),
                phase_elapsed_ms=phase_elapsed_ms,
            )
        )
        return result

    def _record_issue_count(self, issue_count: int) -> None:
        issue_count = _count(issue_count, "Liczba problemów")
        if issue_count < self._issue_count:
            raise ProgressProtocolError("Liczba problemów uruchomienia nie może się zmniejszyć.")
        self._issue_count = issue_count

    def _enter(self, phase: ProgressPhase) -> None:
        if self._active_phase is not None:
            raise ProgressProtocolError(
                f"Nie można rozpocząć etapu {phase.value} w trakcie etapu {self._active_phase.value}."
            )
        if self._run_interrupted:
            raise ProgressProtocolError(f"Nie można rozpocząć etapu {phase.value} po przerwaniu uruchomienia.")
        expected = _PHASE_ORDER[self._next_phase] if self._next_phase < len(_PHASE_ORDER) else None
        if phase is not expected:
            expected_label = expected.value if expected is not None else "brak, uruchomienie jest zakończone"
            raise ProgressProtocolError(
                f"Etap {phase.value} uruchomiony poza kolejnością; oczekiwano: {expected_label}."
            )
        self._next_phase += 1
        self._active_phase = phase

    def _emit(self, event: ProgressEvent) -> None:
        if self._observer is None:
            return
        try:
            self._observer(event)
        except Exception:  # noqa: BLE001 - ADR 0002: awaria obserwatora odłącza go, rdzeń zgłasza to neutralną linią
            self._observer = None

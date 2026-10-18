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


def elapsed_ms_since(started: float) -> int:
    """Zwraca nieujemny czas w milisekundach od odczytu ``time.perf_counter()``."""

    return max(0, round((time.perf_counter() - started) * 1000))


def zero(result: object) -> int:
    """Liczba domyślna, gdy etap nie podaje żadnej wartości."""

    return 0


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
        self._failure_reported = False
        self._issue_count = 0
        self._template_total = 0
        self._durations_ms: dict[ProgressPhase, int] = {}

    def check(self, operation: Callable[[], ResultT]) -> ResultT:
        """Sprawdzanie."""

        return self._run_phase(ProgressPhase.CHECKING, operation, lambda result: None)

    def read(
        self,
        operation: Callable[[], ResultT],
        *,
        issue_count: Callable[[ResultT], int] = zero,
    ) -> ResultT:
        """Odczyt danych, a po nim ``ISSUE_COUNT``."""

        def settle(result: ResultT) -> None:
            self._issue_count = issue_count(result)

        result = self._run_phase(ProgressPhase.READING, operation, settle)
        self._emit(ProgressEventFactory.issue_count(elapsed_ms=self.elapsed_ms(), issue_count=self._issue_count))
        return result

    def plan(
        self,
        operation: Callable[[], ResultT],
        *,
        template_total: Callable[[ResultT], int] = zero,
        issue_count: Callable[[ResultT], int] | None = None,
    ) -> ResultT:
        """Planowanie, a po nim ``PLAN_READY``."""

        def settle(result: ResultT) -> None:
            if issue_count is not None:
                self._issue_count = issue_count(result)
            self._template_total = template_total(result)

        result = self._run_phase(ProgressPhase.PLANNING, operation, settle)
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

        return self._run_phase(ProgressPhase.SAVING, operation, lambda result: None)

    def notify(self, event: ProgressEvent) -> None:
        """Przekazuje obserwatorowi zdarzenie wykonawcy z trwającego Zapisywania."""

        if event.state is ProgressState.FAILED:
            self._failure_reported = True
        self._emit(event)

    @contextmanager
    def paused(self) -> Iterator[None]:
        """Wstrzymuje zegar uruchomienia między etapami, np. na czas odpowiedzi taty."""

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
        settle: Callable[[ResultT], None],
    ) -> ResultT:
        expected = _PHASE_ORDER[self._next_phase] if self._next_phase < len(_PHASE_ORDER) else None
        if phase is not expected:
            raise ProgressProtocolError(f"Etap {phase.value} uruchomiony poza kolejnością.")
        self._next_phase += 1
        self._phase_started = time.perf_counter()
        self._failure_reported = False
        self._emit(ProgressEventFactory.phase_started(phase, elapsed_ms=self.elapsed_ms()))
        try:
            result = operation()
            settle(result)
        except Exception:
            phase_elapsed_ms = self.phase_elapsed_ms()
            self._durations_ms[phase] = phase_elapsed_ms
            if not self._failure_reported:
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

    def _emit(self, event: ProgressEvent) -> None:
        if self._observer is None:
            return
        try:
            self._observer(event)
        except Exception:
            self._observer = None

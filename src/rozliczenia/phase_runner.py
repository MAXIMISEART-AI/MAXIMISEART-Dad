"""Sekwencer etapów: protokół etapów procesu, Zdarzenia przebiegu i pomiar czasów."""

from __future__ import annotations

import time
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from types import MappingProxyType
from typing import Callable, TypeVar

from .domain import (
    IssueCountReady,
    PhaseEnded,
    PhaseFailed,
    PhaseStarted,
    PlanReady,
    ProgressEvent,
    ProgressObserver,
    ProgressPhase,
    ProgressProtocolError,
    WorkerEnded,
    WorkerEvent,
    WorkerFailed,
    WorkerStarted,
)


ResultT = TypeVar("ResultT")
_PHASE_ORDER = tuple(ProgressPhase)


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
    ``plan`` i ``save``. Sekwencer wysyła ``PhaseStarted``, ``PhaseEnded`` albo
    jedno ``PhaseFailed`` każdego etapu oraz zdarzenia pośrednie:
    ``IssueCountReady`` po Odczycie danych i ``PlanReady`` po Planowaniu.
    ``PhaseEnded`` Zapisywania dostaje liczbę Szablonów pracownika z planu.

    Funkcje liczące są czystymi funkcjami wyniku etapu; sekwencer wywołuje je
    przed END. Liczba problemów jest łączna dla uruchomienia, a pominięta w
    Planowaniu oznacza wartość z Odczytu danych.

    Sekwencer jest jedynym miejscem, które sprawdza kolejność Zdarzeń
    przebiegu: etapów i Szablonów pracownika w Zapisywaniu. Pomyłka to
    ``ProgressProtocolError`` w miejscu wywołania, także bez obserwatora.

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
        self._templates_completed = 0
        # Szablon pracownika, który się rozpoczął i jeszcze nie zakończył: (Wykonawca, pozycja).
        self._active_worker: tuple[str, int] | None = None
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
        """Odczyt danych, a po nim ``IssueCountReady``."""

        def record_counts(result: ResultT) -> None:
            self._record_issue_count(issue_count(result))

        result = self._run_phase(ProgressPhase.READING, operation, record_counts)
        self._emit(IssueCountReady(elapsed_ms=self.elapsed_ms(), issue_count=self._issue_count))
        return result

    def plan(
        self,
        operation: Callable[[], ResultT],
        *,
        template_total: Callable[[ResultT], int] = _zero,
        issue_count: Callable[[ResultT], int] | None = None,
    ) -> ResultT:
        """Planowanie, a po nim ``PlanReady``."""

        def record_counts(result: ResultT) -> None:
            if issue_count is not None:
                self._record_issue_count(issue_count(result))
            self._template_total = _count(template_total(result), "Liczba Szablonów pracownika")

        result = self._run_phase(ProgressPhase.PLANNING, operation, record_counts)
        self._emit(PlanReady(elapsed_ms=self.elapsed_ms(), template_total=self._template_total, issue_count=self._issue_count))
        return result

    def save(self, operation: Callable[[], ResultT]) -> ResultT:
        """Zapisywanie; END ma liczbę Szablonów pracownika z planu, a wszystkie muszą się zakończyć."""

        def every_template_ended(_result: ResultT) -> None:
            if self._active_worker is not None or self._templates_completed != self._template_total:
                raise ProgressProtocolError(
                    f"Zapisywanie kończy się po {self._templates_completed} z {self._template_total} Szablonów pracownika."
                )

        return self._run_phase(ProgressPhase.SAVING, operation, every_template_ended)

    def notify(self, event: WorkerEvent) -> None:
        """Przekazuje obserwatorowi zdarzenie Szablonu pracownika z trwającego Zapisywania.

        Szablony pracownika idą po kolei od 1 do liczby z planu; zakończenie albo
        przerwanie dotyczy szablonu, który się rozpoczął.
        """

        if not isinstance(event, (WorkerStarted, WorkerEnded, WorkerFailed)):
            raise ProgressProtocolError(f"Zdarzenie {type(event).__name__} wysyła tylko sekwencer etapów.")
        if self._active_phase is not ProgressPhase.SAVING:
            raise ProgressProtocolError("Zdarzenie wykonawcy jest dozwolone tylko w trakcie Zapisywania.")
        if event.template_total != self._template_total:
            raise ProgressProtocolError("Zdarzenie wykonawcy ma inną liczbę Szablonów pracownika niż plan.")
        position = (event.worker_name, event.template_index)
        if isinstance(event, WorkerStarted):
            if self._active_worker is not None:
                raise ProgressProtocolError("Nie można rozpocząć drugiego Szablonu pracownika przed zakończeniem pierwszego.")
            if event.template_index != self._templates_completed + 1:
                raise ProgressProtocolError("Zdarzenie rozpoczęcia musi wskazywać następny Szablon pracownika.")
            self._active_worker = position
        else:
            if self._active_worker != position:
                raise ProgressProtocolError("Zdarzenie nie pasuje do bieżącego Szablonu pracownika.")
            self._active_worker = None
            if isinstance(event, WorkerEnded):
                self._record_issue_count(event.issue_count)
                self._templates_completed = event.template_index
            else:
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
        self._emit(PhaseStarted(phase, elapsed_ms=self.elapsed_ms()))
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
                self._emit(PhaseFailed(phase, elapsed_ms=self.elapsed_ms(), phase_elapsed_ms=phase_elapsed_ms))
            raise
        phase_elapsed_ms = self.phase_elapsed_ms()
        self._durations_ms[phase] = phase_elapsed_ms
        self._active_phase = None
        self._emit(
            PhaseEnded(
                phase,
                elapsed_ms=self.elapsed_ms(),
                phase_elapsed_ms=phase_elapsed_ms,
                template_total=self._template_total if phase is ProgressPhase.SAVING else 0,
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

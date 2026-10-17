"""Uruchamianie faz przebiegu z opcjonalnym obserwatorem i pomiarem czasów."""

from __future__ import annotations

import time
from typing import Callable, TypeVar

from .domain import (
    ProgressEvent,
    ProgressEventFactory,
    ProgressObserver,
    ProgressPhase,
    ProgressState,
)


ResultT = TypeVar("ResultT")


def elapsed_ms_since(started: float) -> int:
    """Zwraca nieujemny czas w milisekundach od odczytu ``time.perf_counter()``."""

    return max(0, round((time.perf_counter() - started) * 1000))


class PhaseRunner:
    """Sekwencjonuje fazy jednego przebiegu i przekazuje Zdarzenia przebiegu.

    Zegar przebiegu startuje przy utworzeniu. Awaria obserwatora odłącza go do
    końca przebiegu i nie zmienia wyniku faz. Każda faza zgłasza START, a potem
    END albo jedno FAILED; czas fazy trafia do ``phase_durations_ms`` także po
    przerwaniu.
    """

    def __init__(self, observer: ProgressObserver | None) -> None:
        self._observer = observer
        self._run_started = time.perf_counter()
        self._phase_started = self._run_started
        self._failure_reported = False
        self.phase_durations_ms: dict[ProgressPhase, int] = {}

    def elapsed_ms(self) -> int:
        """Czas od rozpoczęcia przebiegu."""

        return elapsed_ms_since(self._run_started)

    def phase_elapsed_ms(self) -> int:
        """Czas od rozpoczęcia bieżącej (ostatniej) fazy."""

        return elapsed_ms_since(self._phase_started)

    def notify(self, event: ProgressEvent) -> None:
        """Przekazuje zdarzenie obserwatorowi, odłączając go po pierwszej awarii."""

        if event.state is ProgressState.FAILED:
            self._failure_reported = True
        if self._observer is None:
            return
        try:
            self._observer(event)
        except Exception:
            self._observer = None

    def run(
        self,
        phase: ProgressPhase,
        operation: Callable[[], ResultT],
        *,
        template_total: int = 0,
    ) -> ResultT:
        """Wykonuje fazę; ``template_total`` trafia jako końcowa pozycja do END."""

        self._phase_started = time.perf_counter()
        self._failure_reported = False
        self.notify(ProgressEventFactory.phase_started(phase, elapsed_ms=self.elapsed_ms()))
        try:
            result = operation()
        except Exception:
            phase_elapsed_ms = self.phase_elapsed_ms()
            self.phase_durations_ms[phase] = phase_elapsed_ms
            if not self._failure_reported:
                self.notify(
                    ProgressEventFactory.phase_failed(
                        phase,
                        elapsed_ms=self.elapsed_ms(),
                        phase_elapsed_ms=phase_elapsed_ms,
                    )
                )
            raise
        phase_elapsed_ms = self.phase_elapsed_ms()
        self.phase_durations_ms[phase] = phase_elapsed_ms
        self.notify(
            ProgressEventFactory.phase_ended(
                phase,
                template_index=template_total,
                template_total=template_total,
                elapsed_ms=self.elapsed_ms(),
                phase_elapsed_ms=phase_elapsed_ms,
            )
        )
        return result

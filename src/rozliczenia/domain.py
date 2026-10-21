"""Pojęcia i wyniki procesu rozliczeń."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from types import MappingProxyType
from typing import Callable, ClassVar, Literal, Mapping


class ProgressPhase(StrEnum):
    """Typed phase values while retaining the existing Polish strings."""

    CHECKING = "Sprawdzanie"
    READING = "Odczyt danych"
    PLANNING = "Planowanie"
    SAVING = "Zapisywanie"


class ProgressProtocolError(ValueError):
    """Błąd kodu: Zdarzenie przebiegu poza kolejnością etapów albo Szablonów pracownika."""


PHASES = tuple(phase.value for phase in ProgressPhase)
WorkerStatus = Literal["ZAPISANO", "PUSTY_SZABLON", "PLAN"]
"""Wynik Przetworzenia Szablonu pracownika; szablonu, którego nie da się bezpiecznie zapisać, nie ma w wynikach."""


@dataclass(frozen=True)
class Issue:
    """Problem możliwy do pokazania bez ujawniania danych klientów."""

    code: str
    message: str


@dataclass(frozen=True)
class WorkerResult:
    """Bezpieczny wynik dla jednego szablonu."""

    worker_name: str
    output_file: Path
    rows: int
    status: WorkerStatus


@dataclass(frozen=True)
class PhaseStarted:
    """Etap się rozpoczął."""

    phase: ProgressPhase
    elapsed_ms: int


@dataclass(frozen=True)
class PhaseEnded:
    """Etap się zakończył; END Zapisywania ma liczbę Szablonów pracownika z planu."""

    phase: ProgressPhase
    elapsed_ms: int
    phase_elapsed_ms: int
    template_total: int = 0


@dataclass(frozen=True)
class PhaseFailed:
    """Etap został przerwany; uruchomienie nie ma już kolejnych zdarzeń."""

    phase: ProgressPhase
    elapsed_ms: int
    phase_elapsed_ms: int


@dataclass(frozen=True)
class IssueCountReady:
    """Liczba problemów po Odczycie danych."""

    elapsed_ms: int
    issue_count: int
    phase: ClassVar[ProgressPhase] = ProgressPhase.READING


@dataclass(frozen=True)
class PlanReady:
    """Plan gotowy: liczba Szablonów pracownika i łączna liczba problemów."""

    elapsed_ms: int
    template_total: int
    issue_count: int
    phase: ClassVar[ProgressPhase] = ProgressPhase.PLANNING


@dataclass(frozen=True)
class WorkerStarted:
    """Przetworzenie Szablonu pracownika ``template_index`` z ``template_total`` się rozpoczęło."""

    worker_name: str
    template_index: int
    template_total: int
    elapsed_ms: int
    phase: ClassVar[ProgressPhase] = ProgressPhase.SAVING


@dataclass(frozen=True)
class WorkerEnded:
    """Przetworzenie Szablonu pracownika się zakończyło; ``issue_count`` jest łączna dla uruchomienia."""

    worker_name: str
    template_index: int
    template_total: int
    status: WorkerStatus
    rows: int
    elapsed_ms: int
    issue_count: int
    phase: ClassVar[ProgressPhase] = ProgressPhase.SAVING


@dataclass(frozen=True)
class WorkerFailed:
    """Przetworzenie Szablonu pracownika zostało przerwane; przerywa też Zapisywanie."""

    worker_name: str
    template_index: int
    template_total: int
    elapsed_ms: int
    phase_elapsed_ms: int
    phase: ClassVar[ProgressPhase] = ProgressPhase.SAVING


WorkerEvent = WorkerStarted | WorkerEnded | WorkerFailed
"""Zdarzenie przebiegu, które proces zgłasza sam w trakcie Zapisywania."""

ProgressEvent = PhaseStarted | PhaseEnded | PhaseFailed | IssueCountReady | PlanReady | WorkerEvent
"""Zdarzenie przebiegu (GLOSSARY); każdy rodzaj ma tylko swoje pola, a kolejność sprawdza ``PhaseRunner``."""

ProgressObserver = Callable[[ProgressEvent], None]


@dataclass
class SettlementSummary:
    """Podsumowanie operacyjne bez zawartości wierszy klientów."""

    period: str
    source_file: Path
    target_directory: Path
    results: list[WorkerResult] = field(default_factory=list)
    issues: list[Issue] = field(default_factory=list)
    phase_durations_ms: Mapping[ProgressPhase, int] = field(default_factory=lambda: MappingProxyType({}))

    @property
    def written_count(self) -> int:
        return sum(result.status == "ZAPISANO" for result in self.results)

    @property
    def planned_count(self) -> int:
        return sum(result.status == "PLAN" for result in self.results)

    @property
    def empty_count(self) -> int:
        return sum(result.status == "PUSTY_SZABLON" for result in self.results)

    @property
    def total_rows(self) -> int:
        return sum(result.rows for result in self.results)

    @property
    def template_count(self) -> int:
        return len(self.results)

    @property
    def ok(self) -> bool:
        return not self.issues

"""Pojęcia i wyniki procesu rozliczeń."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable


PHASES = ("Sprawdzanie", "Odczyt danych", "Planowanie", "Zapisywanie")
SKIPPED_STATUSES = frozenset({"ZABLOKOWANY", "ZLY_SZABLON", "POMINIĘTO"})
ProgressObserver = Callable[["ProgressEvent"], None]


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
    status: str


@dataclass(frozen=True)
class ProgressEvent:
    """Bezpieczne zdarzenie postępu dla terminala lub innego adaptera."""

    phase: str
    state: str
    template_index: int = 0
    template_total: int = 0
    worker_name: str | None = None
    status: str | None = None
    rows: int = 0
    elapsed_ms: int | None = None
    phase_elapsed_ms: int | None = None
    worker_elapsed_ms: int | None = None


@dataclass
class SettlementSummary:
    """Podsumowanie operacyjne bez zawartości wierszy klientów."""

    period: str
    source_file: Path
    target_directory: Path
    results: list[WorkerResult] = field(default_factory=list)
    issues: list[Issue] = field(default_factory=list)

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
    def skipped_count(self) -> int:
        return sum(result.status in SKIPPED_STATUSES for result in self.results)

    @property
    def template_count(self) -> int:
        return len(self.results)

    @property
    def ok(self) -> bool:
        return not self.issues

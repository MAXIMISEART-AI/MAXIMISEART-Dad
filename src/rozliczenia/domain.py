"""Pojęcia i wyniki procesu rozliczeń."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path


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
    def ok(self) -> bool:
        return not self.issues

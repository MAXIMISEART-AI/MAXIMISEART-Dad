"""Rozmówca w testach rdzenia Uruchomienia procesu i silników, bez terminala i bez Centrum rozliczeń."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Literal

from rozliczenia.decision import Decision
from rozliczenia.domain import ProgressEvent
from rozliczenia.progress import ProgressSnapshot


@dataclass
class Tata:
    """Rozmówca w teście: zapisuje każdą Decyzję, robi ``before_answer`` i odpowiada ``consent``."""

    consent: bool = True
    continue_hint: str = "przy pytaniu wpisz t"
    before_answer: Callable[[], None] = lambda: None
    decisions: list[Decision] = field(default_factory=list)
    progress_view: list[Literal["start", "stop"]] = field(default_factory=list)

    def confirm(self, decision: Decision) -> bool:
        self.decisions.append(decision)
        self.before_answer()
        return self.consent

    def start_progress(self, snapshot: ProgressSnapshot, **_view: object) -> None:
        self.progress_view.append("start")

    def show_progress(self, snapshot: ProgressSnapshot, event: ProgressEvent) -> None:
        pass

    def stop_progress(self) -> None:
        self.progress_view.append("stop")

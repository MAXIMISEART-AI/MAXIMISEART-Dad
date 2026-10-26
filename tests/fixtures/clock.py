"""Zegar w sekundach, który przesuwa tylko test: czasy rdzenia i sekwencera etapów bez prawdziwego snu."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class ManualClock:
    """Podróbka ``time.perf_counter``; stoi, dopóki test go nie przesunie."""

    seconds: float = 0.0

    def __call__(self) -> float:
        return self.seconds

    def advance(self, seconds: float) -> None:
        self.seconds += seconds

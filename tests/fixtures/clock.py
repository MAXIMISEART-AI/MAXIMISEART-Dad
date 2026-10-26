"""Zegar w sekundach, który przesuwa tylko test: czasy rdzenia, sekwencera etapów i Centrum bez prawdziwego snu."""

from __future__ import annotations

import heapq
import itertools
import threading
from collections.abc import Callable
from dataclasses import dataclass, field


@dataclass
class ManualClock:
    """Podróbka ``time.perf_counter`` i zegara Centrum (``Clock``); stoi, dopóki test go nie przesunie.

    ``advance`` woła w wątku testu, po kolei, każde ``wake`` z ``after``, którego chwila minęła, także ustawione w
    trakcie budzenia. ``pause`` tylko przesuwa czas: przerwę bierze kod pod testem, często pod własną blokadą, więc
    budzenia, których chwila minęła, woła dopiero następne ``advance``.
    """

    seconds: float = 0.0
    _wakes: list[tuple[float, int, Callable[[], None]]] = field(default_factory=list)
    _order: itertools.count[int] = field(default_factory=itertools.count)
    _lock: threading.Lock = field(default_factory=threading.Lock)

    def __call__(self) -> float:
        return self.seconds

    def after(self, seconds: float, wake: Callable[[], None]) -> None:
        with self._lock:
            heapq.heappush(self._wakes, (self.seconds + seconds, next(self._order), wake))

    def pause(self, seconds: float) -> None:
        with self._lock:
            self.seconds += seconds

    @property
    def wakes(self) -> int:
        """Budzenia z ``after``, których chwila jeszcze nie nadeszła."""

        with self._lock:
            return len(self._wakes)

    def advance(self, seconds: float = 0.0, *, minutes: float = 0.0) -> None:
        self.seconds += seconds + minutes * 60
        while True:
            with self._lock:
                if not self._wakes or self._wakes[0][0] > self.seconds:
                    return
                _, _, wake = heapq.heappop(self._wakes)
            wake()

"""Interaktywny terminal i podgląd Rich renderowany do zwykłego tekstu.

Wspólne dla testów Uruchomienia procesu i CLI obu procesów: ``TtyOutput``
udaje terminal, a ``install_fake_rich`` podmienia ``Console`` i ``Live`` w
``terminal_conversation``, żeby dało się czytać, co podgląd pokazał.
"""

from __future__ import annotations

from io import StringIO
from typing import Any, TextIO

import pytest

import rozliczenia.terminal_conversation as terminal_conversation


class TtyOutput(StringIO):
    def isatty(self) -> bool:
        return True


class FakeConsole:
    color_system = "standard"

    def __init__(self, *, file: TextIO) -> None:
        from rich.console import Console as RichConsole

        self.renderer = RichConsole(file=file, color_system=None, width=120)

    def print(self, renderable: Any) -> None:
        self.renderer.print(renderable)


class FakeLive:
    """Widok na żywo, który drukuje każde odświeżenie i zapisuje je w dzienniku."""

    def __init__(self, live_log: list[str], console: FakeConsole, *, auto_refresh: bool) -> None:
        self.console = console
        self.live_log = live_log
        live_log.append(f"auto_refresh={auto_refresh}")

    def start(self, *, refresh: bool) -> None:
        self.live_log.append("start")

    def update(self, renderable: Any, *, refresh: bool) -> None:
        self.live_log.append(f"update refresh={refresh}")
        self.console.print(renderable)

    def stop(self) -> None:
        self.live_log.append("stop")


def install_fake_rich(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """Rich renderuje do zwykłego tekstu; zwraca dziennik startów, odświeżeń i zatrzymań widoku na żywo."""

    pytest.importorskip("rich")
    live_log: list[str] = []

    def make_live(_renderable: Any, *, console: FakeConsole, auto_refresh: bool = True, **_kwargs: Any) -> FakeLive:
        return FakeLive(live_log, console, auto_refresh=auto_refresh)

    monkeypatch.setattr(terminal_conversation, "Console", FakeConsole)
    monkeypatch.setattr(terminal_conversation, "Live", make_live)
    return live_log


def live_starts_and_stops(live_log: list[str]) -> list[str]:
    return [entry for entry in live_log if entry in ("start", "stop")]

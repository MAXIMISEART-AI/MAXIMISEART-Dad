"""CLI obu procesów w testach: wywołanie z argumentami, okna wyboru, interaktywny terminal i podgląd Rich.

``TtyOutput`` udaje terminal, a ``install_fake_rich`` podmienia ``Console`` i ``Live`` w
``terminal_conversation``, żeby dało się czytać, co podgląd pokazał.
"""

from __future__ import annotations

from datetime import date
from io import StringIO
from pathlib import Path
import sys
import time
import types
from typing import Any, TextIO

import pytest

from rozliczenia import cli, preparation_cli
import rozliczenia.terminal_conversation as terminal_conversation

from tests.fixtures.preparation import PERIOD, PreparationFixture


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


def run_cli(
    source_path: Path,
    config_path: Path,
    metrics_path: Path,
    *extra_args: str,
) -> tuple[int, str]:
    output = StringIO()
    exit_code = cli.main(
        [
            "--source",
            str(source_path),
            "--config",
            str(config_path),
            "--worker-template",
            str(config_path.parent / "Wzorzec rozliczenia pracownika.xlsx"),
            "--metrics",
            str(metrics_path),
            *extra_args,
        ],
        output=output,
    )
    return exit_code, output.getvalue()


def install_source_dialog(monkeypatch: pytest.MonkeyPatch, *, selected: str, answer_after_s: float = 0) -> list[str]:
    """Zastępuje okno wyboru Pliku zbiorczego (tkinter); zwraca tytuły pokazanych okien."""

    shown: list[str] = []

    class FakeRoot:
        def withdraw(self) -> None:
            pass

        def destroy(self) -> None:
            pass

    def askopenfilename(*, title: str, **_kwargs: object) -> str:
        shown.append(title)
        time.sleep(answer_after_s)
        return selected

    filedialog = types.ModuleType("tkinter.filedialog")
    setattr(filedialog, "askopenfilename", askopenfilename)
    tk_module = types.ModuleType("tkinter")
    setattr(tk_module, "Tk", FakeRoot)
    setattr(tk_module, "filedialog", filedialog)
    monkeypatch.setitem(sys.modules, "tkinter", tk_module)
    monkeypatch.setitem(sys.modules, "tkinter.filedialog", filedialog)
    return shown


def metrics_path_for(fixture: PreparationFixture) -> Path:
    return fixture.register_path.parent / "przygotowanie-metrics.jsonl"


def preparation_arguments(fixture: PreparationFixture, *extra_args: str) -> list[str]:
    return [
        "--register",
        str(fixture.register_path),
        "--periods-directory",
        str(fixture.periods_directory),
        "--period",
        PERIOD,
        "--config",
        str(fixture.config_path),
        "--internal-template",
        str(fixture.internal_template_path),
        "--collective-template",
        str(fixture.collective_template_path),
        "--metrics",
        str(metrics_path_for(fixture)),
        *extra_args,
    ]


def run_preparation_cli(fixture: PreparationFixture, *extra_args: str) -> tuple[int, str]:
    output = StringIO()
    exit_code = preparation_cli.main(preparation_arguments(fixture, *extra_args), output=output)
    return exit_code, output.getvalue()


def without_option(arguments: list[str], option: str) -> list[str]:
    index = arguments.index(option)
    return arguments[:index] + arguments[index + 2 :]


def run_cli_asking_for_period(
    fixture: PreparationFixture, answers: str, *extra_args: str, today: date = date(2026, 9, 16)
) -> tuple[int, str]:
    output = StringIO()
    arguments = without_option(preparation_arguments(fixture, *extra_args), "--period")
    exit_code = preparation_cli.main(arguments, output=output, input_stream=StringIO(answers), today=today)
    return exit_code, output.getvalue()


def run_cli_answering(fixture: PreparationFixture, answers: str, *extra_args: str) -> tuple[int, str]:
    output = StringIO()
    exit_code = preparation_cli.main(
        preparation_arguments(fixture, *extra_args), output=output, input_stream=StringIO(answers)
    )
    return exit_code, output.getvalue()

"""Terminal jako rozmówca Uruchomienia procesu.

Okna wyboru tkinter, komunikaty i pytania w terminalu oraz podgląd postępu
Rich z liniowym trybem tekstowym dla nieinteraktywnego wyjścia. Rdzeń
Uruchomienia procesu (``process_run``) nie zna strumieni terminala: dostaje
tego rozmówcę tak samo jak każdego innego.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator, Sequence
from contextlib import contextmanager
import os
from pathlib import Path
from typing import Any, TextIO

from .decision import Decision
from .plain_progress import PlainProgressAdapter
from .progress import ProgressNotice, ProgressSnapshot
from .rich_progress import Console, Live, RichProgressAdapter

__all__ = ["TerminalConversation"]

_YES_ANSWERS = ("t", "tak")


def _decision_lines(decision: Decision) -> list[str]:
    """Decyzja w terminalu: tytuł, trzy części Komunikatu i liczby z etykietami."""

    return [
        decision.title,
        *decision.message.text.splitlines(),
        f"{decision.counts_title}:",
        *(f"- {label}: {count}" for label, count in decision.counts),
    ]


def _ask_in_dialog(ask: Callable[[Any], str]) -> str:
    """Lokalne okno tkinter; pusty wynik, gdy anulowano albo okna nie da się pokazać."""

    try:
        import tkinter as tk
        from tkinter import filedialog
    except ImportError:
        return ""
    try:
        root = tk.Tk()
        root.withdraw()
        try:
            return ask(filedialog) or ""
        finally:
            root.destroy()
    except tk.TclError:  # brak ekranu albo okna Tk
        return ""


def _is_interactive(stream: TextIO) -> bool:
    try:
        return bool(stream.isatty())
    except (AttributeError, OSError, ValueError):
        return False


class TerminalConversation:
    """Rozmowa z tatą w terminalu: okna wyboru, komunikaty, pytania i podgląd postępu.

    Okna wyboru, ``say`` i ``ask`` służą do ustalenia wejścia procesu przed
    silnikiem i piszą wprost do wyjścia. W trakcie silnika terminal jest
    rozmówcą rdzenia: Decyzja taty (``confirm``) zatrzymuje widok na żywo, a
    wznawia go dopiero po zgodzie taty.
    """

    def __init__(self, output: TextIO, input_stream: TextIO) -> None:
        self._output = output
        self._input_stream = input_stream
        self._dashboard: _Dashboard | None = None

    def choose_file(self, title: str, filetypes: Sequence[tuple[str, str]]) -> Path | None:
        selected = _ask_in_dialog(lambda dialog: dialog.askopenfilename(title=title, filetypes=list(filetypes)))
        return Path(selected) if selected else None

    def choose_folder(self, title: str) -> Path | None:
        selected = _ask_in_dialog(lambda dialog: dialog.askdirectory(title=title, mustexist=True))
        return Path(selected) if selected else None

    def say(self, *lines: str) -> None:
        for line in lines:
            self._write(line + "\n")

    def ask(self, prompt: str) -> str | None:
        """Odpowiedź bez otaczających spacji; ``None``, gdy wejście się skończyło.

        Gdy odpowiedź nie pochodzi z terminala (który sam wyświetla Enter),
        dopisuje koniec linii, żeby kolejny komunikat nie trafił do linii pytania.
        """

        self._write(prompt)
        answer = self._input_stream.readline()
        if not _is_interactive(self._input_stream):
            self._write("\n")
        return None if answer == "" else answer.strip()

    @property
    def continue_hint(self) -> str:
        return "przy pytaniu wpisz t"

    def confirm(self, decision: Decision) -> bool:
        """Pokazuje linie decyzji i pyta ``t``/``n``; podgląd wraca tylko po zgodzie taty."""

        with self._view_stopped() as resume:
            self.say(*_decision_lines(decision))
            answer = self.ask(f"{decision.question} Wpisz t (tak) albo n (nie): ")
            consent = answer is not None and answer.casefold() in _YES_ANSWERS
            if consent:
                resume()
            return consent

    def start_progress(self, snapshot: ProgressSnapshot, *, title: str, shows_templates: bool) -> None:
        self._dashboard = _Dashboard(self._output, title=title, shows_templates=shows_templates)
        self._dashboard.start(snapshot)

    def show_progress(self, snapshot: ProgressSnapshot, notice: ProgressNotice) -> None:
        if self._dashboard is not None:
            self._dashboard.show(snapshot, notice)

    def stop_progress(self) -> None:
        if self._dashboard is not None:
            self._dashboard.stop()

    def print_lines(self, lines: Sequence[str]) -> None:
        """Linie końcowe pod zatrzymanym podglądem, tą samą drogą co jego linie."""

        for line in lines:
            if self._dashboard is not None:
                self._dashboard.print_line(line)
            else:
                self.say(line)

    @contextmanager
    def _view_stopped(self) -> Iterator[Callable[[], None]]:
        dashboard = self._dashboard
        if dashboard is None:
            yield lambda: None
            return
        dashboard.stop()
        yield dashboard.resume

    def _write(self, text: str) -> None:
        try:
            self._output.write(text)
            self._output.flush()
        except (OSError, ValueError):
            pass


class _Dashboard:
    """Podgląd postępu Rich z liniowym trybem tekstowym dla nieinteraktywnego wyjścia.

    Renderuje wyłącznie snapshoty projekcji postępu (ADR 0002). Awaria wyjścia
    zgłasza wyjątek z ``show``, żeby rdzeń odłączył obserwatora.
    """

    def __init__(self, output: TextIO, *, title: str, shows_templates: bool):
        self.output = output
        self.snapshot: ProgressSnapshot | None = None
        self.plain_adapter = PlainProgressAdapter(self.print_line, title=title, shows_templates=shows_templates)
        self.rich_adapter = RichProgressAdapter(title=title, shows_templates=shows_templates)
        self._output_failed = False
        self.console: Any | None = None
        self.live: Any | None = None
        self.interactive = False
        with self._plain_text_on_rich_failure():
            self.console = Console(file=output) if Console is not None else None
        self.interactive = (
            self._supports_live_output(output)
            and self.console is not None
            and self.console.color_system is not None
        )

    @staticmethod
    def _supports_live_output(output: TextIO) -> bool:
        if os.environ.get("NO_COLOR") is not None or os.environ.get("TERM") == "dumb":
            return False
        try:
            return bool(output.isatty())
        except (AttributeError, OSError):
            return False

    def start(self, snapshot: ProgressSnapshot) -> None:
        self.snapshot = snapshot
        if self.interactive and Live is not None:
            with self._plain_text_on_rich_failure():
                self.live = Live(self.render(), console=self.console, auto_refresh=False)
                self.live.start(refresh=True)
                return
        elif self.interactive:
            self._disable_rich()
        self.plain_adapter.start(snapshot)

    def show(self, snapshot: ProgressSnapshot, notice: ProgressNotice) -> None:
        self.snapshot = snapshot
        if self._output_failed:
            raise OSError("Terminal output is unavailable.")
        if self.interactive:
            with self._plain_text_on_rich_failure():
                if self.live is None:
                    raise RuntimeError("Rich dashboard did not start.")
                self.live.update(self.rich_adapter.render(snapshot, notice), refresh=True)
                return
            self.plain_adapter.start(snapshot)
        self.plain_adapter.update(snapshot, notice)
        if self._output_failed:
            raise OSError("Terminal output is unavailable.")

    def stop(self) -> None:
        """Zatrzymuje widok na żywo, żeby kolejne linie szły pod nim."""

        if self.live is not None:
            with self._plain_text_on_rich_failure():
                self.live.stop()
                self.live = None

    def resume(self) -> None:
        """Wznawia widok na żywo po ``stop()``, np. po pytaniu do taty między etapami."""

        if not self.interactive or self.live is not None or Live is None:
            return
        with self._plain_text_on_rich_failure():
            self.live = Live(self.render(), console=self.console, auto_refresh=False)
            self.live.start(refresh=True)

    def render(self) -> Any:
        return self.rich_adapter.render(self.snapshot) if self.snapshot is not None else None

    @contextmanager
    def _plain_text_on_rich_failure(self) -> Iterator[None]:
        """Awaria Rich przełącza podgląd na tryb tekstowy, zamiast odłączać go od rdzenia (ADR 0002)."""

        try:
            yield
        except Exception:  # noqa: BLE001 - granica z Rich: każda jego awaria to powrót do trybu tekstowego
            self._disable_rich()

    def _disable_rich(self) -> None:
        live, self.live = self.live, None
        self.interactive = False
        self.console = None
        if live is not None:
            with self._plain_text_on_rich_failure():
                live.stop()

    def print_line(self, message: str) -> None:
        if self._output_failed:
            return
        try:
            if self.interactive and self.console is not None:
                self.console.print(message)
            else:
                self.output.write(f"{message}\n")
        except (OSError, UnicodeError, ValueError):
            self._output_failed = True

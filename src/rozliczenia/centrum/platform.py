"""Akcje systemowe komputera taty za jednym adapterem: otwarcie pliku albo folderu i okna wyboru.

U taty (Windows) plik otwiera skojarzony program, czyli Excel, a okna wyboru
to te same okna tkinter co w CLI. Przy rozwoju na macOS działają odpowiedniki
systemu: ``open`` i ``osascript``, bo tkinter na macOS działa tylko w wątku
głównym, a serwer obsługuje żądania w wątkach roboczych. Testy API podają
własny adapter do ``create_app``; serwer dostaje ``system_platform()``.
"""

from __future__ import annotations

import os
import subprocess
import sys
import threading
from collections.abc import Callable, Sequence
from pathlib import Path
from types import ModuleType
from typing import Any, Protocol

FileTypes = Sequence[tuple[str, str]]  # (opis, wzorzec nazwy), jak w oknach wyboru CLI


class Platform(Protocol):
    def open_path(self, path: Path) -> None:
        """Otwiera plik w domyślnym programie (Excel) albo folder w menedżerze plików."""

    def choose_file(self, title: str, filetypes: FileTypes) -> Path | None:
        """Natywne okno wyboru pliku; ``None``, gdy tata anulował."""

    def choose_folder(self, title: str) -> Path | None:
        """Natywne okno wyboru folderu; ``None``, gdy tata anulował."""


def system_platform() -> Platform:
    if sys.platform == "darwin":
        return _MacPlatform()
    return _TkPlatform()


class _TkPlatform:
    """Windows u taty (Linux przy rozwoju): okna tkinter w wątku żądania, jedno naraz, nad przeglądarką."""

    def __init__(self) -> None:
        self._dialog_lock = threading.Lock()

    def open_path(self, path: Path) -> None:
        if sys.platform == "win32":
            os.startfile(path)  # .xlsx otwiera Excel, folder Eksplorator
        else:
            subprocess.Popen(["xdg-open", str(path)])

    def choose_file(self, title: str, filetypes: FileTypes) -> Path | None:
        return self._ask(
            lambda dialog, parent: dialog.askopenfilename(parent=parent, title=title, filetypes=list(filetypes))
        )

    def choose_folder(self, title: str) -> Path | None:
        return self._ask(lambda dialog, parent: dialog.askdirectory(parent=parent, title=title, mustexist=True))

    def _ask(self, ask: Callable[[ModuleType, Any], object]) -> Path | None:
        import tkinter
        from tkinter import filedialog

        with self._dialog_lock:
            root = tkinter.Tk()
            try:
                root.withdraw()
                root.attributes("-topmost", True)
                chosen = ask(filedialog, root)
            finally:
                root.destroy()
        return Path(chosen) if isinstance(chosen, str) and chosen else None


class _MacPlatform:
    def open_path(self, path: Path) -> None:
        subprocess.run(["open", str(path)], check=False)

    def choose_file(self, title: str, filetypes: FileTypes) -> Path | None:
        return self._choose(f"choose file with prompt {_applescript_text(title)}")

    def choose_folder(self, title: str) -> Path | None:
        return self._choose(f"choose folder with prompt {_applescript_text(title)}")

    def _choose(self, command: str) -> Path | None:
        result = subprocess.run(
            ["osascript", "-e", f"POSIX path of ({command})"],
            capture_output=True,
            text=True,
            check=False,
        )
        chosen = result.stdout.strip()
        return Path(chosen) if result.returncode == 0 and chosen else None


def _applescript_text(text: str) -> str:
    escaped = text.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'

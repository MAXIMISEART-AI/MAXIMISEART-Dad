"""Ślad wywołań nieoczekiwanego wyjątku w kodzie narzędzia, bez treści wyjątku.

Ślad to typ wyjątku i ramki kodu narzędzia: plik względem katalogu narzędzia,
linia i funkcja. Treść wyjątku może mieć dane z Rejestru zleceń, a pełna ścieżka
nazwę konta, więc ślad nie ma ani jednego, ani drugiego. Ramki bibliotek i
biblioteki standardowej są pomijane. Ślad niesie tylko Zatrzymanie w pamięci;
pokazuje go wyłącznie Zgłoszenie do Maksa (ADR 0007).
"""

from __future__ import annotations

import traceback
from dataclasses import dataclass
from pathlib import Path
from typing import Final

from rozliczenia import TOOL_ROOT

_OUTSIDE_TOOL: Final = frozenset({".venv", "site-packages"})


@dataclass(frozen=True)
class CallFrame:
    """Ramka kodu narzędzia: plik względem katalogu narzędzia (z ``/``), linia i funkcja."""

    file: str
    line: int
    function: str


@dataclass(frozen=True)
class CallTrace:
    """Typ wyjątku i ramki kodu narzędzia od miejsca przechwycenia do miejsca rzucenia."""

    exception_type: str
    frames: tuple[CallFrame, ...]

    @classmethod
    def of(cls, error: BaseException, *, root: Path = TOOL_ROOT) -> CallTrace:
        frames = tuple(
            CallFrame(file, frame.lineno or 0, frame.name)
            for frame in traceback.extract_tb(error.__traceback__)
            if (file := _tool_file(frame.filename, root)) is not None
        )
        return cls(_type_name(type(error)), frames)


def _type_name(kind: type[BaseException]) -> str:
    return kind.__qualname__ if kind.__module__ == "builtins" else f"{kind.__module__}.{kind.__qualname__}"


def _tool_file(filename: str, root: Path) -> str | None:
    """Plik ramki względem ``root``; ``None`` poza kodem narzędzia (biblioteki, środowisko Pythona)."""

    path = Path(filename)
    if not path.is_absolute():  # np. „<frozen runpy>” albo „<string>”
        return None
    try:
        relative = path.resolve().relative_to(root)
    except (OSError, ValueError):
        return None
    if _OUTSIDE_TOOL & set(relative.parts):
        return None
    return relative.as_posix()

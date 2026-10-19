"""Tożsamość Centrum w ``health``: nazwa usługi i wersja narzędzia.

Wersja pochodzi z ``pyproject.toml``: u taty pakiet nie jest instalowany, więc
nie ma metadanych pakietu. Moduł używa tylko biblioteki standardowej, bo
launcher rozpoznaje po nich działające Centrum, zanim wczyta FastAPI.
"""

from __future__ import annotations

import tomllib
from pathlib import Path
from typing import Final

SERVICE: Final = "centrum-rozliczen"
_PYPROJECT = Path(__file__).resolve().parents[3] / "pyproject.toml"


def tool_version() -> str:
    with _PYPROJECT.open("rb") as file:
        version = tomllib.load(file)["project"]["version"]
    if not isinstance(version, str):
        raise ValueError("pyproject.toml nie podaje wersji narzędzia.")
    return version

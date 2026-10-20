"""Tożsamość Centrum w ``health``: nazwa usługi, wersja i commit narzędzia.

Wersja pochodzi z ``pyproject.toml``: u taty pakiet nie jest instalowany, więc
nie ma metadanych pakietu. Commit to ``HEAD`` klonu Gita narzędzia, czytany z
plików katalogu Gita bez uruchamiania programu ``git`` (Centrum działa bez
konsoli). Moduł używa tylko biblioteki standardowej, bo launcher rozpoznaje po
nich działające Centrum, zanim wczyta FastAPI.
"""

from __future__ import annotations

import re
import tomllib
from pathlib import Path
from typing import Final

SERVICE: Final = "centrum-rozliczen"
_TOOL_ROOT = Path(__file__).resolve().parents[3]
_PYPROJECT = _TOOL_ROOT / "pyproject.toml"
_COMMIT = re.compile(r"[0-9a-f]{40}")


def tool_version() -> str:
    with _PYPROJECT.open("rb") as file:
        version = tomllib.load(file)["project"]["version"]
    if not isinstance(version, str):
        raise ValueError("pyproject.toml nie podaje wersji narzędzia.")
    return version


def tool_commit(root: Path = _TOOL_ROOT) -> str | None:
    """Commit ``HEAD`` klonu narzędzia; ``None``, gdy narzędzie nie jest klonem albo pliki są nieczytelne."""

    try:
        repository = root / ".git"
        if repository.is_file():  # osobny katalog roboczy: „gitdir: …” wskazuje jego katalog
            pointer = repository.read_text(encoding="utf-8").removeprefix("gitdir:").strip()
            repository = (root / pointer).resolve()
        common_file = repository / "commondir"
        common = (repository / common_file.read_text(encoding="utf-8").strip()) if common_file.is_file() else repository
        head = (repository / "HEAD").read_text(encoding="utf-8").strip()
        if not head.startswith("ref:"):
            return head if _COMMIT.fullmatch(head) else None
        ref = head.removeprefix("ref:").strip()
        for directory in (repository, common):
            if (directory / ref).is_file():
                commit = (directory / ref).read_text(encoding="utf-8").strip()
                return commit if _COMMIT.fullmatch(commit) else None
        packed_file = common / "packed-refs"
        packed = packed_file.read_text(encoding="utf-8") if packed_file.is_file() else ""
    except (OSError, UnicodeError):
        return None
    for line in packed.splitlines():
        commit, _, name = line.partition(" ")
        if name == ref and _COMMIT.fullmatch(commit):
            return commit
    return None

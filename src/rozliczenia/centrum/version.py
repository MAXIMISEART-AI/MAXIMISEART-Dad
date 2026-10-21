"""Tożsamość Centrum w ``health``: nazwa usługi, wersja i commit narzędzia.

Wersja pochodzi z ``pyproject.toml``: u taty pakiet nie jest instalowany, więc
nie ma metadanych pakietu. Commit to ``HEAD`` klonu Gita, w którym leży
narzędzie, odczytany z plików ``.git`` bez uruchamiania ``git`` (Centrum działa
bez konsoli, a ``git`` nie musi być w ``PATH``). Moduł używa tylko biblioteki
standardowej, bo launcher rozpoznaje po nich działające Centrum, zanim wczyta
FastAPI.
"""

from __future__ import annotations

from datetime import date, datetime
import re
import tomllib
from pathlib import Path
from typing import Final

from rozliczenia import TOOL_ROOT

SERVICE: Final = "centrum-rozliczen"
_PYPROJECT = TOOL_ROOT / "pyproject.toml"
_COMMIT = re.compile(r"[0-9a-f]{40}")
_SHORT_COMMIT = 7


def tool_version() -> str:
    with _PYPROJECT.open("rb") as file:
        version = tomllib.load(file)["project"]["version"]
    if not isinstance(version, str):
        raise ValueError("pyproject.toml nie podaje wersji narzędzia.")
    return version


def is_commit(text: str) -> bool:
    """Czy ``text`` to pełny commit Gita (40 znaków szesnastkowych)."""

    return _COMMIT.fullmatch(text) is not None


def tool_commit(root: Path = TOOL_ROOT) -> str | None:
    """Pełny commit ``HEAD`` narzędzia w ``root``; ``None``, gdy narzędzie nie leży w klonie Gita.

    Obsługuje zwykły klon, katalog roboczy ``git worktree`` (plik ``.git``),
    odłączony ``HEAD`` i gałąź spakowaną w ``packed-refs``.
    """

    try:
        git_directory = _git_directory(root)
        if git_directory is None:
            return None
        head = (git_directory / "HEAD").read_text(encoding="utf-8").strip()
        if not head.startswith("ref: "):
            return head if is_commit(head) else None
        return _resolved(head.removeprefix("ref: "), git_directory)
    except (OSError, UnicodeDecodeError):
        return None


def short_commit(commit: str) -> str:
    """Skrót commitu, po którym Maks znajdzie go w historii repozytorium."""

    return commit[:_SHORT_COMMIT]


def commit_since(commit: str, root: Path = TOOL_ROOT) -> date | None:
    """Dzień, od którego narzędzie w ``root`` jest na ``commit``: data ostatniego wpisu reflogu ``HEAD``.

    ``None``, gdy reflogu nie ma, jest pusty albo jego ostatni wpis prowadzi do innego commitu.
    """

    try:
        git_directory = _git_directory(root)
        if git_directory is None:
            return None
        entries = (git_directory / "logs" / "HEAD").read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeDecodeError):
        return None
    if not entries:
        return None
    fields = entries[-1].partition("\t")[0].split(" ")  # <stary> <nowy> <kto> <sekundy> <strefa>
    if len(fields) < 5 or fields[1] != commit:
        return None
    try:
        return datetime.fromtimestamp(int(fields[-2]), datetime.strptime(fields[-1], "%z").tzinfo).date()
    except (ValueError, OverflowError):
        return None


def _git_directory(root: Path) -> Path | None:
    dot_git = root / ".git"
    if dot_git.is_dir():
        return dot_git
    if dot_git.is_file():  # katalog roboczy git worktree: „gitdir: <ścieżka>”
        pointer = dot_git.read_text(encoding="utf-8").strip()
        if pointer.startswith("gitdir: "):
            return (root / pointer.removeprefix("gitdir: ")).resolve()
    return None


def _resolved(ref: str, git_directory: Path) -> str | None:
    common = git_directory
    commondir = git_directory / "commondir"
    if commondir.is_file():  # gałęzie katalogu roboczego leżą we wspólnym katalogu Gita
        common = (git_directory / commondir.read_text(encoding="utf-8").strip()).resolve()
    for directory in dict.fromkeys((git_directory, common)):
        loose = directory / ref
        if loose.is_file():
            commit = loose.read_text(encoding="utf-8").strip()
            return commit if is_commit(commit) else None
    packed = common / "packed-refs"
    if packed.is_file():
        for line in packed.read_text(encoding="utf-8").splitlines():
            commit, _, name = line.partition(" ")
            if name == ref and is_commit(commit):
                return commit
    return None

"""Git w testach z jedną konfiguracją, tą samą na Macu Maksa i na runnerach CI.

Bez niej Git czyta konfigurację systemową i globalną komputera testów. Na Macu Command Line Tools ustawiają
``init.defaultBranch=main``, a Ubuntu w CI tworzy ``master``, więc test z ``git init --bare`` przechodził lokalnie i padał
w CI. ``hermetic_git`` (sesja z ``tests/conftest.py``) wyłącza konfigurację systemową, podstawia globalną z ``CONFIG``
i odrzuca każde uruchomienie gita z procesu testów ze środowiskiem, które ją gubi.
"""

from __future__ import annotations

from collections.abc import Iterator, Mapping, Sequence
from contextlib import contextmanager
import os
from pathlib import Path
import subprocess
from typing import Any

import pytest

CONFIG: Mapping[str, str] = {
    "init.defaultBranch": "main",
    "user.name": "test",
    "user.email": "test@example.com",
    "core.autocrlf": "false",
    "commit.gpgSign": "false",
    "tag.gpgSign": "false",
    # Od Gita 2.54 konserwacja po ``commit`` robi też ``git worktree prune`` w tle i usuwa worktree zakładany
    # w następnym kroku testu (#312).
    "maintenance.auto": "false",
    "gc.auto": "0",
}
_MACHINE_VARIABLES = ("GIT_CONFIG_PARAMETERS", "GIT_CONFIG_COUNT", "GIT_CONFIG_SYSTEM")
_FIX = (
    "zbuduj env z os.environ (np. os.environ | {...}) albo nie podawaj env; konfigurację komputera z czymś więcej "
    "podstaw przez computer_git_config z tests/fixtures/git_config.py"
)
_configs: set[str] = set()

__all__ = ["CONFIG", "computer_git_config", "hermetic_git"]


def _text(extra: str) -> str:
    sections: dict[str, list[str]] = {}
    for key, value in CONFIG.items():
        section, _, name = key.rpartition(".")
        sections.setdefault(section, []).append(f"\t{name} = {value}\n")
    return "".join(f"[{section}]\n{''.join(lines)}" for section, lines in sections.items()) + extra


def computer_git_config(path: Path, extra: str) -> Path:
    """Globalna konfiguracja Gita komputera: ``CONFIG`` i ``extra``; podstaw ją jako ``GIT_CONFIG_GLOBAL``."""

    path.write_text(_text(extra), encoding="utf-8")
    _configs.add(str(path))
    return path


def _runs_git(args: object) -> bool:
    if isinstance(args, str):
        program: object = args.split(maxsplit=1)[0] if args.strip() else ""
    elif isinstance(args, Sequence) and args:
        program = args[0]
    else:
        program = args
    return isinstance(program, (str, os.PathLike)) and Path(program).name.lower() in {"git", "git.exe"}


def _problem(environment: Mapping[str, str]) -> str | None:
    if environment.get("GIT_CONFIG_NOSYSTEM") != "1":
        return "GIT_CONFIG_NOSYSTEM nie jest 1, więc git czyta konfigurację systemową komputera"
    if environment.get("GIT_CONFIG_GLOBAL") not in _configs:
        return f"GIT_CONFIG_GLOBAL={environment.get('GIT_CONFIG_GLOBAL')!r} to nie konfiguracja testów"
    return None


@contextmanager
def hermetic_git(directory: Path) -> Iterator[None]:
    """Git w tym procesie i w jego potomkach tylko z ``CONFIG``, bez konfiguracji systemowej komputera."""

    config = computer_git_config(directory / "gitconfig", "")
    original_init = subprocess.Popen.__init__

    def checked_init(self: subprocess.Popen[Any], args: Any, *rest: Any, **options: Any) -> None:
        environment = options.get("env")
        problem = _problem(os.environ if environment is None else environment) if _runs_git(args) else None
        if problem is not None:
            raise AssertionError(f"Test uruchamia gita ze środowiskiem bez konfiguracji testów: {problem}. Napraw: {_FIX}.")
        original_init(self, args, *rest, **options)

    with pytest.MonkeyPatch.context() as patch:
        for name in _MACHINE_VARIABLES:
            patch.delenv(name, raising=False)
        patch.setenv("GIT_CONFIG_NOSYSTEM", "1")
        patch.setenv("GIT_CONFIG_GLOBAL", str(config))
        patch.setattr(subprocess.Popen, "__init__", checked_init)
        yield

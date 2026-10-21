"""Klon narzędzia w testach: prawdziwy Git, lokalne repozytorium „origin” zamiast GitHuba.

``tool_repository`` buduje w katalogu testu repozytorium wydawcy (tu Maks
commituje nowe wersje), jego kopię bez katalogu roboczego jako „origin” i klon
narzędzia taty na pierwszym commicie. ``publish`` dodaje do `main` w „origin”
nowy commit, a ``in_clone`` robi w klonie to, co mógłby zrobić ktoś przy
komputerze taty. Pomocniki pomijają konfigurację Gita komputera, na którym
biegną testy; żaden nie łączy się z siecią.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
import os
from pathlib import Path
import subprocess
import threading

# Pliki pierwszej wersji narzędzia: śledzona konfiguracja wykonawców sprzed #161 i biblioteki.
FIRST_VERSION: Mapping[str, str] = {
    "pyproject.toml": '[project]\nname = "narzedzie"\nversion = "0.1.0"\n',
    "requirements.txt": "openpyxl>=3.1.5\n",
    "config/worker_mapping.yaml": "schema_version: 1\nworkers:\n  przyklad: Przykładowy Wykonawca\n",
    "config/worker_mapping.example.yaml": "schema_version: 1\nworkers:\n  przyklad: Przykładowy Wykonawca\n",
    "src/narzedzie.py": "WERSJA = 1\n",
}
# Wymagania nowej wersji: jedna biblioteka więcej.
NEW_REQUIREMENTS = "openpyxl>=3.1.5\nfastapi>=0.115\n"
_IDENTITY = {
    "GIT_AUTHOR_NAME": "Maks Testowy",
    "GIT_AUTHOR_EMAIL": "maks@example.invalid",
    "GIT_COMMITTER_NAME": "Maks Testowy",
    "GIT_COMMITTER_EMAIL": "maks@example.invalid",
}


def isolated_git_environment() -> dict[str, str]:
    """Środowisko Gita bez konfiguracji globalnej i systemowej komputera testów."""

    return os.environ | {"GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_NOSYSTEM": "1"} | _IDENTITY


def git(directory: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(directory), *args],
        env=isolated_git_environment(),
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )
    assert result.returncode == 0, f"git {' '.join(args)}: {result.stderr}"
    return result.stdout.strip()


def _write(root: Path, files: Mapping[str, str | None]) -> None:
    for name, content in files.items():
        path = root / name
        if content is None:
            path.unlink()
        else:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content, encoding="utf-8")


@dataclass(frozen=True)
class ToolRepository:
    publisher: Path
    origin: Path
    clone: Path

    def publish(self, files: Mapping[str, str | None], *, untrack: tuple[str, ...] = ()) -> str:
        """Nowy commit na `main` w „origin”: ``files`` zmienia pliki (``None`` usuwa), ``untrack`` przestaje je śledzić."""

        _write(self.publisher, files)
        if untrack:
            git(self.publisher, "rm", "--cached", "--quiet", *untrack)
        git(self.publisher, "add", "--all")
        git(self.publisher, "commit", "--quiet", "--message", "Nowa wersja narzędzia")
        git(self.publisher, "push", "--quiet", "origin", "main")
        return git(self.publisher, "rev-parse", "HEAD")

    def head(self) -> str:
        return git(self.clone, "rev-parse", "HEAD")

    def in_clone(self, *args: str) -> str:
        return git(self.clone, *args)

    def read(self, name: str) -> str:
        return (self.clone / name).read_text(encoding="utf-8")


def tool_repository(directory: Path, files: Mapping[str, str] = FIRST_VERSION) -> ToolRepository:
    """Wydawca z pierwszą wersją ``files``, „origin” bez katalogu roboczego i klon taty na tym samym commicie."""

    publisher = directory / "wydawca"
    publisher.mkdir(parents=True)
    git(publisher, "init", "--quiet", "--initial-branch", "main")
    _write(publisher, files)
    git(publisher, "add", "--all")
    git(publisher, "commit", "--quiet", "--message", "Pierwsza wersja narzędzia")
    origin = directory / "origin.git"
    git(directory, "clone", "--quiet", "--bare", str(publisher), str(origin))
    git(publisher, "remote", "add", "origin", str(origin))
    clone = directory / "narzedzie"
    git(directory, "clone", "--quiet", str(origin), str(clone))
    return ToolRepository(publisher, origin, clone)


class FakeInstaller:
    """Instalator bibliotek w miejscu pip: zapamiętuje plik wymagań z jego treścią i kończy się ``succeeds``.

    ``hold`` zatrzymuje każdą instalację, dopóki test jej nie puści (``set``).
    """

    def __init__(self, *, succeeds: bool = True, hold: threading.Event | None = None) -> None:
        self.succeeds = succeeds
        self.hold = hold
        self.installed: list[tuple[Path, str]] = []

    def __call__(self, requirements: Path) -> bool:
        self.installed.append((requirements, requirements.read_text(encoding="utf-8")))
        if self.hold is not None:
            self.hold.wait()
        return self.succeeds

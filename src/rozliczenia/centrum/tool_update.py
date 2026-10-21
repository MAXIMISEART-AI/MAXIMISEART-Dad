"""Aktualizacja narzędzia: przesunięcie klonu narzędzia taty na najnowszy `main` publicznego repozytorium.

Jedna operacja, ``ToolClone.update``, robi to, co Maks zrobiłby ręcznie
(ADR 0009): znajduje Gita for Windows także poza ``PATH``, pobiera `main` ze
stałego adresu publicznego repozytorium i przesuwa klon tylko do przodu.
Wynik to kod (``UPDATED``, ``UP_TO_DATE`` albo kod Komunikatu porażki) z
commitem przed i po; treść Komunikatów należy do Centrum
(``update_messages``).

Żadne polecenie Gita nie otwiera okna ani nie czeka na odpowiedź: bez
terminala, bez pomocnika logowania i bez okna konsoli w Windows. Każde ufa
klonowi tylko na czas wywołania (``safe.directory``), a konfiguracja Gita taty
zostaje bez zmian. Adres repozytorium wstrzykuje się z zewnątrz; ``origin`` w
klonie taty nie ma znaczenia.

Moduł używa tylko biblioteki standardowej: opiekun ponownego startu działa z
jego kopii sprzed aktualizacji, bez bibliotek narzędzia.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
import os
from pathlib import Path
import shutil
import subprocess
import sys
from typing import Final, Literal

GITHUB_REPOSITORY: Final = "https://github.com/MAXIMISEART-AI/MAXIMISEART-Dad.git"
BRANCH: Final = "main"

UPDATED: Final = "ok"
UP_TO_DATE: Final = "AKTUALNA"
# Kod Komunikatu porażki, której nikt nie przewidział (``GitFailed`` albo inny wyjątek); zamienia go Centrum.
UNEXPECTED: Final = "NIEOCZEKIWANY_BLAD"

Step = Literal["fetching", "installing"]

_FETCHED: Final = f"refs/remotes/origin/{BRANCH}"
_FETCH_TIMEOUT_S: Final = 120.0
_LOCAL_TIMEOUT_S: Final = 60.0
# Zmienne, którymi Git dostałby inne repozytorium albo okno z pytaniem o hasło.
_FOREIGN_VARIABLES: Final = (
    "GIT_DIR",
    "GIT_WORK_TREE",
    "GIT_INDEX_FILE",
    "GIT_OBJECT_DIRECTORY",
    "GIT_ALTERNATE_OBJECT_DIRECTORIES",
    "GIT_COMMON_DIR",
    "GIT_NAMESPACE",
    "GIT_ASKPASS",
    "SSH_ASKPASS",
)


@dataclass(frozen=True)
class UpdateResult:
    """Wynik Aktualizacji narzędzia: kod, commit przed i po oraz czy instalowano biblioteki."""

    code: str
    before: str | None
    after: str | None
    installed: bool = False


def find_git(
    *,
    which: Callable[[str], str | None] = shutil.which,
    registry: Callable[[str], str | None] | None = None,
    environ: Mapping[str, str] = os.environ,
) -> Path | None:
    """``git.exe`` z ``PATH``, potem z katalogu Git for Windows w rejestrze, potem ze znanych miejsc instalacji."""

    found = which("git")
    if found:
        return Path(found)
    install_path = registry or _registered_git_for_windows
    candidates = [Path(path, "cmd", "git.exe") for hive in ("HKLM", "HKCU") if (path := install_path(hive))]
    for variable, folders in (
        ("ProgramFiles", ("Git",)),
        ("ProgramFiles(x86)", ("Git",)),
        ("LOCALAPPDATA", ("Programs", "Git")),
    ):
        base = environ.get(variable)
        if base:
            candidates.append(Path(base, *folders, "cmd", "git.exe"))
    return next((candidate for candidate in candidates if candidate.is_file()), None)


def _registered_git_for_windows(hive: str) -> str | None:
    """Wartość ``InstallPath`` klucza ``SOFTWARE\\GitForWindows`` w ``HKLM`` albo ``HKCU``; poza Windows ``None``."""

    if sys.platform != "win32":
        return None
    import winreg

    root = winreg.HKEY_LOCAL_MACHINE if hive == "HKLM" else winreg.HKEY_CURRENT_USER
    try:
        with winreg.OpenKey(root, r"SOFTWARE\GitForWindows", 0, winreg.KEY_READ | winreg.KEY_WOW64_64KEY) as key:
            value, _ = winreg.QueryValueEx(key, "InstallPath")
    except OSError:
        return None
    return value if isinstance(value, str) and value else None


class GitFailed(Exception):
    """Polecenie Gita nie przeszło z nieprzewidzianego powodu; ``str()`` to samo polecenie, bez wyjścia Gita."""


@dataclass(frozen=True)
class ToolClone:
    """Klon narzędzia w ``root`` i adres repozytorium, z którego przychodzi nowa wersja (``origin``)."""

    root: Path
    origin: str = GITHUB_REPOSITORY
    find_git: Callable[[], Path | None] = find_git

    @classmethod
    def of_system(cls) -> ToolClone:
        """Klon, z którego działa to Centrum, i publiczne repozytorium na GitHubie (tylko w Centrum, nie u opiekuna)."""

        return cls(Path(__file__).resolve().parents[3])

    def update(self, backup: Path, on_step: Callable[[Step], None] = lambda step: None) -> UpdateResult:
        """Przesuwa klon do przodu na najnowszy `main`; wszystko albo nic.

        ``backup`` to pusty katalog tymczasowy Centrum na kopię plików taty.
        ``on_step`` dostaje każdy krok, zanim się zacznie.
        """

        git = self.find_git()
        if git is None:
            raise GitFailed("brak Gita")
        run = _Git(git, self.root)
        before = run.text("rev-parse", "HEAD")
        on_step("fetching")
        run.fetch(self.origin)
        after = run.text("rev-parse", _FETCHED)
        if after == before:
            return UpdateResult(UP_TO_DATE, before, after)
        run.check("merge", "--ff-only", "--quiet", _FETCHED)
        return UpdateResult(UPDATED, before, after)


@dataclass(frozen=True)
class _Git:
    """Polecenia Gita w klonie ``root``: bez okien i pytań, z zaufaniem do klonu tylko na to wywołanie."""

    executable: Path
    root: Path

    def run(self, *args: str, timeout_s: float = _LOCAL_TIMEOUT_S) -> subprocess.CompletedProcess[str]:
        command = [
            str(self.executable),
            "-c",
            f"safe.directory={self.root.as_posix()}",
            "-c",
            "credential.helper=",
            "-c",
            "core.askPass=",
            "-C",
            str(self.root),
            *args,
        ]
        return subprocess.run(
            command,
            env=_quiet_environment(),
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout_s,
            check=False,
            creationflags=_NO_WINDOW,
        )

    def check(self, *args: str) -> None:
        if self.run(*args).returncode != 0:
            raise GitFailed(args[0])

    def text(self, *args: str) -> str:
        result = self.run(*args)
        if result.returncode != 0:
            raise GitFailed(args[0])
        return result.stdout.strip()

    def fetch(self, origin: str) -> None:
        result = self.run(
            "-c",
            "http.proxy=",
            "fetch",
            "--quiet",
            "--no-tags",
            origin,
            f"+refs/heads/{BRANCH}:{_FETCHED}",
            timeout_s=_FETCH_TIMEOUT_S,
        )
        if result.returncode != 0:
            raise GitFailed("fetch")


# Pod pythonw każde polecenie konsolowe otworzyłoby w Windows własne okno konsoli.
_NO_WINDOW: Final = getattr(subprocess, "CREATE_NO_WINDOW", 0)


def _quiet_environment() -> dict[str, str]:
    """Środowisko Gita bez pytań i okien, z komunikatami po angielsku i bez serwera proxy."""

    environment = {
        name: value
        for name, value in os.environ.items()
        if name not in _FOREIGN_VARIABLES and not name.lower().endswith("_proxy")
    }
    return environment | {"GIT_TERMINAL_PROMPT": "0", "GCM_INTERACTIVE": "never", "LC_ALL": "C", "LANGUAGE": "C"}

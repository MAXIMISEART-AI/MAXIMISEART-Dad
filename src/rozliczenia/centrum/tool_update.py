"""Aktualizacja narzędzia: przesunięcie klonu narzędzia taty na najnowszy `main` publicznego repozytorium.

Jedna operacja, ``ToolClone.update``, robi to, co Maks zrobiłby ręcznie
(ADR 0009): znajduje Gita for Windows także poza ``PATH``, pobiera `main` ze
stałego adresu publicznego repozytorium i przesuwa klon tylko do przodu.
Pliki taty w ``config/``, które nowa wersja usuwa albo przestaje śledzić,
zostają u niego z dokładnie tą treścią, którą miały (``_DadFiles``).
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

from collections.abc import Callable, Iterator, Mapping
from contextlib import contextmanager
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
# Kody Komunikatów porażek, przy których klon zostaje bez zmian.
NO_GIT: Final = "BRAK_GITA"
# Brak sieci albo GitHub nie odpowiedział w limicie czasu.
NO_CONNECTION: Final = "BRAK_POLACZENIA"
# GitHub prosi o logowanie; Git nie pyta i kończy od razu.
LOGIN: Final = "LOGOWANIE"
OTHER_BRANCH: Final = "INNA_GALAZ"
# Lokalne commity, zmienione śledzone pliki albo nieśledzony plik, który nowa wersja by nadpisała.
LOCAL_CHANGES: Final = "ZMIANY_NA_KOMPUTERZE"
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
            return UpdateResult(NO_GIT, None, None)
        run = _Git(git, self.root)
        before = run.text("rev-parse", "HEAD")
        if run.branch() != BRANCH:
            return UpdateResult(OTHER_BRANCH, before, None)
        on_step("fetching")
        fetch_failure = run.fetch(self.origin)
        if fetch_failure is not None:
            return UpdateResult(fetch_failure, before, None)
        after = run.text("rev-parse", _FETCHED)
        if after == before:
            return UpdateResult(UP_TO_DATE, before, after)
        dad_files = _DadFiles.leaving(run, _FETCHED)
        if _has_local_commits(run) or _changed_tracked_files(run, keep=frozenset(dad_files.names)):
            return UpdateResult(LOCAL_CHANGES, before, None)
        with dad_files.set_aside(run, backup):
            # Git odmawia przed zmianą czegokolwiek, np. gdy nieśledzony plik zostałby nadpisany plikiem nowej wersji.
            if run.run("merge", "--ff-only", "--quiet", _FETCHED).returncode != 0:
                return UpdateResult(LOCAL_CHANGES, before, None)
        return UpdateResult(UPDATED, before, after)


def _has_local_commits(run: _Git) -> bool:
    """Klon ma commity, których nie ma pobrany `main`: przesunięcie do przodu by je pominęło."""

    return run.text("rev-list", "--count", f"{_FETCHED}..HEAD") != "0"


def _changed_tracked_files(run: _Git, *, keep: frozenset[str]) -> bool:
    """Śledzony plik klonu różni się od ``HEAD`` (w indeksie albo na dysku), poza plikami taty ``keep``."""

    entries = run.entries("status", "--porcelain=v1", "-z", "--untracked-files=no", "--no-renames")
    return any(entry[3:] not in keep for entry in entries)


@dataclass(frozen=True)
class _DadFiles:
    """Pliki taty w ``config/``, które przesunięcie klonu usunęłoby: nowa wersja je usuwa albo przestaje śledzić.

    Tata może je mieć zmienione (Konfiguracja wykonawców z prawdziwymi
    nazwiskami po #161); te zmiany nie zatrzymują Aktualizacji narzędzia.
    Przed przesunięciem trafiają do kopii i wracają do stanu z ``HEAD``, żeby
    Git nie odmówił; po przesunięciu (udanym albo nie) wraca ich kopia. Inne
    pliki taty (Wzorce, Ustawienia taty, klucz do Zgłoszeń, dziennik, metryki)
    Git zostawia sam, bo ich nie śledzi.
    """

    names: tuple[str, ...]

    @classmethod
    def leaving(cls, git: _Git, fetched: str) -> _DadFiles:
        """Pliki ``config/`` śledzone w ``HEAD``, których nie ma w ``fetched``, a które tata ma u siebie."""

        listed = git.output(
            "diff", "--name-only", "-z", "--no-renames", "--diff-filter=D", "HEAD", fetched, "--", "config/"
        )
        return cls(tuple(name for name in listed.split("\0") if name and (git.root / name).is_file()))

    @contextmanager
    def set_aside(self, git: _Git, backup: Path) -> Iterator[None]:
        """Kopiuje pliki do ``backup`` i przywraca im treść z ``HEAD``; po bloku (udanym albo nie) wgrywa kopie z powrotem."""

        for name in self.names:
            copy = backup / name
            copy.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(git.root / name, copy)
        try:
            if self.names:
                git.check("checkout", "HEAD", "--", *(f":(literal){name}" for name in self.names))
            yield
        finally:
            for name in self.names:
                target = git.root / name
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(backup / name, target)


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
        return self.output(*args).strip()

    def entries(self, *args: str) -> list[str]:
        """Wpisy wyjścia rozdzielone znakiem NUL (``-z``), bez ostatniego pustego."""

        return [entry for entry in self.output(*args).split("\0") if entry]

    def branch(self) -> str | None:
        """Gałąź, na której stoi klon; ``None``, gdy stoi na commicie bez gałęzi."""

        result = self.run("symbolic-ref", "--quiet", "--short", "HEAD")
        return result.stdout.strip() if result.returncode == 0 else None

    def output(self, *args: str) -> str:
        result = self.run(*args)
        if result.returncode != 0:
            raise GitFailed(args[0])
        return result.stdout

    def fetch(self, origin: str) -> str | None:
        """Pobiera `main` z ``origin``; ``None``, gdy się udało, inaczej kod porażki (logowanie albo brak sieci).

        Adres jest stały, więc każda inna porażka pobrania to brak połączenia z GitHubem.
        """

        try:
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
        except subprocess.TimeoutExpired:
            return NO_CONNECTION
        if result.returncode == 0:
            return None
        asked_for_login = any(sign in result.stderr.lower() for sign in _LOGIN_SIGNS)
        return LOGIN if asked_for_login else NO_CONNECTION


# Git bez pytań kończy tak, gdy serwer prosi o logowanie (GitHub także przy repozytorium, którego nie widzi).
_LOGIN_SIGNS: Final = ("terminal prompts disabled", "could not read username", "could not read password", "authentication failed")

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

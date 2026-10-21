"""Aktualizacja narzędzia: przesunięcie klonu narzędzia taty na najnowszy `main` publicznego repozytorium.

Jedna operacja, ``ToolClone.update``, robi to, co Maks zrobiłby ręcznie
(ADR 0009): znajduje Gita for Windows także poza ``PATH``, pobiera `main` ze
stałego adresu publicznego repozytorium i przesuwa klon tylko do przodu.
Pliki taty w ``config/``, które nowa wersja usuwa albo przestaje śledzić,
zostają u niego z dokładnie tą treścią, którą miały (``_DadFiles``). Gdy nowa
wersja zmienia ``requirements.txt``, biblioteki instaluje ten sam Python, w
którym działa Centrum (``pip_install``); nieudana instalacja cofa klon do
commitu sprzed aktualizacji (``ToolClone.roll_back``). Bibliotek się nie cofa:
wymagania mają tylko dolne granice wersji, więc stara wersja dalej je spełnia.
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
# Kod Komunikatu porażki, której nikt nie przewidział (``GitFailed`` albo inny wyjątek); zamienia go Centrum.
UNEXPECTED: Final = "NIEOCZEKIWANY_BLAD"
# Kod Komunikatu: biblioteki nowej wersji się nie zainstalowały, a klon wrócił do commitu sprzed aktualizacji.
LIBRARIES_FAILED: Final = "INSTALACJA_BIBLIOTEK"

Step = Literal["fetching", "installing"]

_FETCHED: Final = f"refs/remotes/origin/{BRANCH}"
_FETCH_TIMEOUT_S: Final = 120.0
_LOCAL_TIMEOUT_S: Final = 60.0
_REQUIREMENTS: Final = "requirements.txt"
# Pip na wolnym łączu taty pobiera i rozpakowuje koła bibliotek przez kilka minut.
_INSTALL_TIMEOUT_S: Final = 15 * 60.0
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


def pip_install(requirements: Path) -> bool:
    """Instaluje ``requirements`` tym samym Pythonem, w którym działa Centrum; ``False``, gdy pip się nie uda.

    Bez ``--user``: pip sam przechodzi na instalację użytkownika, gdy nie może
    pisać do globalnego Pythona. Wyjście pip nie trafia nigdzie; bez okna
    konsoli i bez pytań.
    """

    command = [sys.executable, "-m", "pip", "install", "--disable-pip-version-check", "--no-input", "--quiet"]
    try:
        result = subprocess.run(
            [*command, "-r", str(requirements)],
            cwd=requirements.parent,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=_INSTALL_TIMEOUT_S,
            check=False,
            creationflags=_NO_WINDOW,
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    return result.returncode == 0


class GitFailed(Exception):
    """Polecenie Gita nie przeszło z nieprzewidzianego powodu; ``str()`` to samo polecenie, bez wyjścia Gita."""


@dataclass(frozen=True)
class ToolClone:
    """Klon narzędzia w ``root`` i adres repozytorium, z którego przychodzi nowa wersja (``origin``).

    ``install`` instaluje biblioteki z podanego pliku wymagań i mówi, czy się udało.
    """

    root: Path
    origin: str = GITHUB_REPOSITORY
    find_git: Callable[[], Path | None] = find_git
    install: Callable[[Path], bool] = pip_install

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
        dad_files = _DadFiles.leaving(run, _FETCHED)
        with dad_files.set_aside(run, backup):
            run.check("merge", "--ff-only", "--quiet", _FETCHED)
        try:
            installed = self._install_libraries(run, before, after, on_step)
        except BaseException:
            _roll_back(run, before, backup)
            raise
        if installed is False:
            _roll_back(run, before, backup)
            return UpdateResult(LIBRARIES_FAILED, before, after, installed=True)
        return UpdateResult(UPDATED, before, after, installed=installed is True)

    def _install_libraries(self, run: _Git, before: str, after: str, on_step: Callable[[Step], None]) -> bool | None:
        """Instaluje biblioteki, gdy ``after`` zmienia wymagania: czy się udało, a ``None``, gdy nie było czego instalować."""

        if not run.changed(before, after, _REQUIREMENTS):
            return None
        on_step("installing")
        return self.install(self.root / _REQUIREMENTS)

    def roll_back(self, before: str, backup: Path) -> None:
        """Cofa przesunięty klon do commitu ``before`` z plikami taty z ``backup`` (katalog kopii ``update``)."""

        git = self.find_git()
        if git is None:
            raise GitFailed("brak Gita")
        _roll_back(_Git(git, self.root), before, backup)


def _roll_back(git: _Git, before: str, backup: Path) -> None:
    """``git reset --keep before``, a pliki taty z ``backup`` przed nim znikają z klonu i po nim do niego wracają.

    Po przesunięciu klonu pliki taty są w nim nieśledzone, a ``before`` je
    śledzi: Git odmówiłby ich nadpisania. Po cofnięciu mają treść taty, tak jak
    przed kliknięciem.
    """

    names = [copy.relative_to(backup) for copy in backup.rglob("*") if copy.is_file()]
    for name in names:
        (git.root / name).unlink(missing_ok=True)
    try:
        git.check("reset", "--keep", "--quiet", before)
    finally:
        for name in names:
            target = git.root / name
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(backup / name, target)


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

    def output(self, *args: str) -> str:
        result = self.run(*args)
        if result.returncode != 0:
            raise GitFailed(args[0])
        return result.stdout

    def changed(self, before: str, after: str, name: str) -> bool:
        """Czy ``after`` dodaje albo zmienia plik ``name`` względem ``before``."""

        result = self.run("diff", "--quiet", "--no-renames", "--diff-filter=AM", before, after, "--", f":(literal){name}")
        if result.returncode not in (0, 1):
            raise GitFailed("diff")
        return result.returncode == 1

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

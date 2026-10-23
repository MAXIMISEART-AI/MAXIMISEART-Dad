"""Aktualizacja narzędzia: przesunięcie klonu narzędzia taty na najnowsze Wydanie publicznego repozytorium.

Jedna operacja, ``ToolClone.update``, robi to, co Maks zrobiłby ręcznie
(ADR 0009): znajduje Gita for Windows także poza ``PATH``, pobiera `main` i tagi
Wydań (ADR 0014) ze stałego adresu publicznego repozytorium i przesuwa klon
tylko do przodu, na commit najnowszego Wydania, które leży na `main`. Lokalna
gałąź klonu to dalej `main`.
Pliki taty w ``config/``, które nowa wersja usuwa albo przestaje śledzić,
zostają u niego z dokładnie tą treścią, którą miały (``_DadFiles``). Gdy nowa
wersja zmienia ``requirements.txt``, biblioteki instaluje ten sam Python, w
którym działa Centrum (``pip_install``); nieudana instalacja cofa klon do
commitu sprzed aktualizacji (``ToolClone.roll_back``). Bibliotek się nie cofa:
wymagania mają tylko dolne granice wersji, więc stara wersja dalej je spełnia.
Gdy nie uda się samo cofnięcie, wynik mówi to wprost (``ROLLBACK_FAILED``).
Gdy kopia pliku taty nie wróci do przesuniętego klonu, klon też się cofa; gdy
nie wróci ostatecznie, wynikiem jest ``ROLLBACK_FAILED``, a treść taty zostaje
w kopii. Wynik to kod (``UPDATED``, ``UP_TO_DATE`` albo kod Komunikatu porażki) z
commitem przed i po; treść Komunikatów należy do Centrum
(``update_messages``).

Żadne polecenie Gita nie otwiera okna ani nie czeka na odpowiedź: bez
terminala, bez pomocnika logowania i bez okna konsoli w Windows. Każde kończy
się w swoim limicie czasu, także gdy pomocnik Gita (np. ``git-remote-https``)
zostaje po nim przy zerwanym połączeniu: wyjście idzie do plików tymczasowych,
nie do potoków, a po limicie ginie całe drzewo procesów Gita. Każde ufa
klonowi tylko na czas wywołania (``safe.directory``), a konfiguracja Gita taty
zostaje bez zmian. Adres repozytorium wstrzykuje się z zewnątrz; ``origin`` w
klonie taty nie ma znaczenia.

Zanim aktualizacja zmieni klon, zapisuje dziennik „Aktualizacja w toku”
(``JOURNAL`` w ``config/`` klonu): commit przed i po oraz kopię plików taty.
Dziennik znika dopiero przy wyniku ostatecznym: po odmowie z plikami taty z
powrotem, po udanym cofnięciu albo gdy opiekun ponownego startu zobaczy, że
nowa wersja odpowiada. Gdy komputer zgaśnie w trakcie, skrót przy następnym
starcie zastaje dziennik i cofa klon (``ToolClone.roll_back``). Gdy w
Centrum nie uda się samo cofnięcie, następne kliknięcie najpierw kończy je z
dziennika, a potem aktualizuje jak zwykle.

Moduł używa tylko biblioteki standardowej: opiekun ponownego startu działa z
jego kopii sprzed aktualizacji, a skrót cofa przerwaną aktualizację, zanim
wczyta biblioteki nowej wersji.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass, replace
import json
import os
from pathlib import Path
import re
import shutil
import signal
import subprocess
import sys
import tempfile
import time
from typing import IO, Final, Literal, TypeGuard

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
# Najnowsze Wydanie wskazuje commit spoza `main`: tag założony ręcznie, poza tworzeniem Wydania (ADR 0014).
RELEASE_OFF_MAIN: Final = "WYDANIE_SPOZA_MAIN"
# Kod Komunikatu porażki, której nikt nie przewidział (``GitFailed`` albo inny wyjątek); zamienia go Centrum.
UNEXPECTED: Final = "NIEOCZEKIWANY_BLAD"
# Kod Komunikatu: biblioteki nowej wersji się nie zainstalowały, a klon wrócił do commitu sprzed aktualizacji.
LIBRARIES_FAILED: Final = "INSTALACJA_BIBLIOTEK"
# Kod Komunikatu: nowa wersja nie odpowiedziała po ponownym starcie, więc opiekun cofnął klon i uruchomił starą.
NEW_VERSION_FAILED: Final = "NOWA_WERSJA_NIE_WYSTARTOWALA"
# Kod Komunikatu: klon miał wrócić do commitu sprzed aktualizacji, ale cofnięcie się nie udało.
ROLLBACK_FAILED: Final = "COFNIECIE_NIEUDANE"

Step = Literal["fetching", "installing"]

# Wynik aktualizacji po ponownym starcie Centrum: plik obok Ustawień taty, który zapisuje opiekun ponownego startu,
# a Centrum, które potem wystartuje, odczytuje raz i usuwa.
RESULT_FILE: Final = "centrum-aktualizacja.json"
JOURNAL: Final = "centrum-aktualizacja-w-toku"
GUARDIAN_LEASE_S: Final = 10 * 60.0
_JOURNAL_FORMAT: Final = 1

_FETCHED_MAIN: Final = f"refs/remotes/origin/{BRANCH}"
# Własna przestrzeń na tagi Wydań z GitHuba: tag usunięty albo przesunięty na GitHubie nie zostaje w klonie.
_RELEASES: Final = "refs/wydania/"
_FETCH_TIMEOUT_S: Final = 120.0
_LOCAL_TIMEOUT_S: Final = 60.0
# Pobranie, które przez tyle sekund idzie wolniej niż tyle bajtów na sekundę, kończy sam Git: połączenie stoi.
_STALLED_BYTES_PER_S: Final = 1000
_STALLED_FOR_S: Final = 30
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


_RELEASE_TAG: Final = re.compile(r"v(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)")


@dataclass(frozen=True, order=True)
class Release:
    """Wydanie: tag ``vMAJOR.MINOR.PATCH``; nowsze to wyższy numer, nie dalszy tag w porządku alfabetycznym."""

    number: tuple[int, int, int]
    tag: str

    @classmethod
    def of_tag(cls, tag: str) -> Release | None:
        """Wydanie z nazwy tagu; ``None`` dla każdego innego tagu."""

        found = _RELEASE_TAG.fullmatch(tag)
        return None if found is None else cls((int(found[1]), int(found[2]), int(found[3])), tag)


def newest_release(tags: Iterable[str]) -> Release | None:
    """Najnowsze Wydanie wśród ``tags``; ``None``, gdy żaden tag nie jest Wydaniem."""

    return max((release for tag in tags if (release := Release.of_tag(tag)) is not None), default=None)


@dataclass(frozen=True)
class UpdateResult:
    """Wynik Aktualizacji narzędzia: kod, commit przed i po oraz czy instalowano biblioteki."""

    code: str
    before: str | None
    after: str | None
    installed: bool = False


def write_result(path: Path, result: UpdateResult) -> None:
    """Zapisuje wynik aktualizacji w całości albo wcale (plik tymczasowy obok, potem podmiana)."""

    record = {"wynik": result.code, "przed": result.before, "po": result.after, "biblioteki": result.installed}
    temporary = path.with_name(path.name + ".tmp")
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary.write_text(json.dumps(record) + "\n", encoding="utf-8")
    os.replace(temporary, path)


def read_result(path: Path) -> UpdateResult | None:
    """Wynik aktualizacji z pliku ``write_result``; ``None``, gdy pliku nie ma albo jest nieczytelny."""

    try:
        record = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(record, dict):
        return None
    code, before, after = record.get("wynik"), record.get("przed"), record.get("po")
    if not isinstance(code, str) or not _commit_or_none(before) or not _commit_or_none(after):
        return None
    return UpdateResult(code, before, after, record.get("biblioteki") is True)


def _commit_or_none(value: object) -> TypeGuard[str | None]:
    return value is None or isinstance(value, str)


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


class JournalKept(Exception):
    """Dziennik „Aktualizacja w toku” zostaje bez zmian: nie da się go bezpiecznie użyć ani zastąpić; ``str()`` mówi czemu."""


@dataclass(frozen=True)
class InterruptedUpdate:
    """Aktualizacja narzędzia z dziennika: commit przed i po, a od ponownego startu termin opiekuna (``guardian_until``)."""

    before: str
    after: str
    guardian_until: float | None = None

    def guardian_may_run(self, now: float) -> bool:
        """Czy opiekun ponownego startu może jeszcze kończyć tę aktualizację (``now`` w sekundach od epoki)."""

        return self.guardian_until is not None and now < self.guardian_until


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

    def update(self, on_step: Callable[[Step], None] = lambda step: None) -> UpdateResult:
        """Przesuwa klon do przodu na najnowsze Wydanie; wszystko albo nic.

        Klon, który już zawiera commit najnowszego Wydania (także na nowszym
        commicie `main` z wersji, która pobierała `main`), i GitHub bez
        żadnego Wydania to ``UP_TO_DATE``: aktualizacja nigdy nie cofa wersji.
        Wydanie, którego commitu nie ma na `main`, to ``RELEASE_OFF_MAIN``,
        a klon zostaje bez zmian.

        ``on_step`` dostaje każdy krok, zanim się zacznie. Po ``UPDATED``
        dziennik „Aktualizacja w toku” zostaje, dopóki nowa wersja nie
        odpowie (``confirm_update``) albo klon się nie cofnie (``roll_back``).
        Dziennik z wcześniejszej aktualizacji, której nie kończy już opiekun
        ponownego startu, najpierw cofa klon; gdy to się nie uda, wynikiem
        jest ``ROLLBACK_FAILED``.
        """

        git = self.find_git()
        if git is None:
            return UpdateResult(NO_GIT, None, None)
        run = _Git(git, self.root)
        journal = self._journal
        interrupted = journal.read()
        if interrupted is not None and not interrupted.guardian_may_run(time.time()):
            if not _moved_back(run, journal):
                return UpdateResult(ROLLBACK_FAILED, interrupted.before, interrupted.after)
        before = run.text("rev-parse", "HEAD")
        if run.branch() != BRANCH:
            return UpdateResult(OTHER_BRANCH, before, None)
        on_step("fetching")
        fetch_failure = run.fetch(self.origin)
        if fetch_failure is not None:
            return UpdateResult(fetch_failure, before, None)
        newest = newest_release(run.output("for-each-ref", "--format=%(refname:lstrip=2)", _RELEASES).split())
        if newest is None:
            return UpdateResult(UP_TO_DATE, before, before)
        after = run.text("rev-parse", f"{_RELEASES}{newest.tag}^{{commit}}")
        if run.is_ancestor(after, before):
            return UpdateResult(UP_TO_DATE, before, before)
        if not run.is_ancestor(after, _FETCHED_MAIN):
            return UpdateResult(RELEASE_OFF_MAIN, before, None)
        dad_files = _DadFiles.leaving(run, after)
        if _has_local_commits(run, after) or _changed_tracked_files(run, keep=frozenset(dad_files.names)):
            return UpdateResult(LOCAL_CHANGES, before, None)
        journal.begin(self.root, dad_files.names, before, after)
        moved = False
        try:
            with dad_files.set_aside(run, journal.backup):
                # Git odmawia przed zmianą czegokolwiek, np. gdy nieśledzony plik zostałby nadpisany plikiem nowej wersji.
                moved = run.run("merge", "--ff-only", "--quiet", after).returncode == 0
        except _NotPutBack:
            # Wszystko albo nic: klon wraca sprzed kliknięcia, a cofnięcie jeszcze raz wgrywa pliki taty.
            if moved and _moved_back(run, journal):
                return UpdateResult(UNEXPECTED, before, after)
            return UpdateResult(ROLLBACK_FAILED, before, after if moved else None)
        except _NotSetAside:
            journal.end()
            raise
        if not moved:
            journal.end()
            return UpdateResult(LOCAL_CHANGES, before, None)
        try:
            installed = self._install_libraries(run, before, after, on_step)
        except Exception:
            if _moved_back(run, journal):
                raise
            return UpdateResult(ROLLBACK_FAILED, before, after, installed=True)
        if installed is False:
            code = LIBRARIES_FAILED if _moved_back(run, journal) else ROLLBACK_FAILED
            return UpdateResult(code, before, after, installed=True)
        return UpdateResult(UPDATED, before, after, installed=installed is True)

    def _install_libraries(self, run: _Git, before: str, after: str, on_step: Callable[[Step], None]) -> bool | None:
        """Instaluje biblioteki, gdy ``after`` zmienia wymagania: czy się udało, a ``None``, gdy nie było czego instalować."""

        if not run.changed(before, after, _REQUIREMENTS):
            return None
        on_step("installing")
        return self.install(self.root / _REQUIREMENTS)

    def roll_back(self) -> None:
        """Cofa aktualizację z dziennika „Aktualizacja w toku” do commitu przed nią, z plikami taty z jego kopii.

        Po cofnięciu dziennik znika. Każda porażka (``GitFailed`` także bez
        Gita, ``OSError``, ``JournalKept``) zostawia dziennik na następną próbę.
        """

        git = self.find_git()
        if git is None:
            raise GitFailed("brak Gita")
        _roll_back(_Git(git, self.root), self._journal)

    def interrupted_update(self) -> InterruptedUpdate | None:
        """Aktualizacja z dziennika „Aktualizacja w toku”; ``None``, gdy żadna nie trwa, ``JournalKept``, gdy jest nieczytelny."""

        return self._journal.read()

    @contextmanager
    def leased_to_guardian(self) -> Iterator[None]:
        """Na start opiekuna ponownego startu: przez ``GUARDIAN_LEASE_S`` ani skrót, ani kliknięcie nie cofają tej aktualizacji.

        Gdy blok rzuci, opiekun nie wystartował, więc termin znika.
        """

        self._journal.lease(time.time() + GUARDIAN_LEASE_S)
        try:
            yield
        except BaseException:
            self._journal.lease(None)
            raise

    def confirm_update(self) -> None:
        """Nowa wersja odpowiada: aktualizacja jest skończona, a jej dziennik znika."""

        self._journal.end()

    @property
    def _journal(self) -> _Journal:
        return _Journal(self.root / "config" / JOURNAL)


def _roll_back(git: _Git, journal: _Journal) -> None:
    """``git reset --keep`` do commitu przed aktualizacją z ``journal``; pliki taty z jego kopii przed nim znikają z klonu i po nim do niego wracają.

    Po przesunięciu klonu pliki taty są w nim nieśledzone, a commit przed je
    śledzi: Git odmówiłby ich nadpisania. Po cofnięciu mają treść taty, tak jak
    przed kliknięciem, a dziennik znika. Klon na innym commicie niż przed albo
    po aktualizacji to ``JournalKept``: ktoś go zmienił, więc cofnięcie mogłoby
    zgubić cudzą pracę.
    """

    update = journal.read()
    if update is None:
        raise JournalKept("brak dziennika")
    if git.text("rev-parse", "HEAD") not in (update.before, update.after):
        raise JournalKept("klon na innym commicie")
    names = [copy.relative_to(journal.backup).as_posix() for copy in journal.backup.rglob("*") if copy.is_file()]
    for name in names:
        (git.root / name).unlink(missing_ok=True)
    try:
        git.check("reset", "--keep", "--quiet", update.before)
    finally:
        _put_back(git.root, journal.backup, names)
    journal.end()


def _moved_back(git: _Git, journal: _Journal) -> bool:
    """``_roll_back``, który mówi, czy się udało, zamiast rzucać."""

    try:
        _roll_back(git, journal)
    except (GitFailed, OSError, subprocess.SubprocessError, JournalKept):
        return False
    return True


def _put_back(root: Path, backup: Path, names: Iterable[str]) -> None:
    """Wgrywa do klonu w ``root`` kopie plików taty ``names`` z ``backup`` z dokładnie ich treścią."""

    for name in names:
        target = root / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(backup / name, target)


def _has_local_commits(run: _Git, target: str) -> bool:
    """Klon ma commity, których nie ma ``target``: przesunięcie do przodu by je pominęło."""

    return run.text("rev-list", "--count", f"{target}..HEAD") != "0"


def _changed_tracked_files(run: _Git, *, keep: frozenset[str]) -> bool:
    """Śledzony plik klonu różni się od ``HEAD`` (w indeksie albo na dysku), poza plikami taty ``keep``."""

    entries = run.entries("status", "--porcelain=v1", "-z", "--untracked-files=no", "--no-renames")
    return any(entry[3:] not in keep for entry in entries)


class _NotSetAside(GitFailed):
    """``git checkout HEAD --`` nie przywrócił plikom taty treści z ``HEAD``, zanim klon się przesunął."""


class _NotPutBack(Exception):
    """Kopia pliku taty nie wróciła do klonu; jego treść jest tylko w kopii w dzienniku."""


@dataclass(frozen=True)
class _Journal:
    """Dziennik „Aktualizacja w toku” w katalogu ``directory``: ``stan.json`` i kopia plików taty (``backup``).

    ``stan.json`` to ``{"format": 1, "przed", "po", "opiekun_do"}``. Nieznany
    ``format`` albo nieczytelny plik zostaje nietknięty (``JournalKept``);
    nieznane klucze nie mają znaczenia. Kopia trafia na dysk przed
    ``stan.json``, więc dziennik nigdy nie wskazuje niepełnej kopii.
    """

    directory: Path

    @property
    def backup(self) -> Path:
        return self.directory / "pliki-taty"

    @property
    def _state(self) -> Path:
        return self.directory / "stan.json"

    def read(self) -> InterruptedUpdate | None:
        try:
            record = json.loads(self._state.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return None
        except (OSError, ValueError) as unreadable:
            raise JournalKept("nieczytelny") from unreadable
        if not isinstance(record, dict) or record.get("format") != _JOURNAL_FORMAT:
            raise JournalKept("nieznany format")
        before, after, until = record.get("przed"), record.get("po"), record.get("opiekun_do")
        if not isinstance(before, str) or not isinstance(after, str):
            raise JournalKept("bez commitów")
        if not isinstance(until, (int, float)) or isinstance(until, bool):
            until = None
        return InterruptedUpdate(before, after, until)

    def begin(self, root: Path, names: Iterable[str], before: str, after: str) -> None:
        """Kopia plików taty ``names`` z klonu ``root``, potem ``stan.json``; trwająca aktualizacja to ``JournalKept``."""

        if self._state.exists():
            raise JournalKept("poprzednia aktualizacja w toku")
        self.end()
        for name in names:
            copy = self.backup / name
            copy.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(root / name, copy)
            _flush_to_disk(copy)
        self._write(InterruptedUpdate(before, after))

    def lease(self, until: float | None) -> None:
        update = self.read()
        if update is None:
            raise JournalKept("brak dziennika")
        self._write(replace(update, guardian_until=until))

    def end(self) -> None:
        """Najpierw ``stan.json``: bez niego reszta katalogu nic nie znaczy i znika, jeśli się da."""

        self._state.unlink(missing_ok=True)
        shutil.rmtree(self.directory, ignore_errors=True)

    def _write(self, update: InterruptedUpdate) -> None:
        record = {"format": _JOURNAL_FORMAT, "przed": update.before, "po": update.after, "opiekun_do": update.guardian_until}
        temporary = self._state.with_name(self._state.name + ".tmp")
        self.directory.mkdir(parents=True, exist_ok=True)
        temporary.write_text(json.dumps(record) + "\n", encoding="utf-8")
        _flush_to_disk(temporary)
        os.replace(temporary, self._state)


def _flush_to_disk(path: Path) -> None:
    """Treść pliku na dysku, nie tylko w pamięci systemu: dziennik ma przetrwać wyłączenie komputera."""

    with path.open("r+b") as written:
        os.fsync(written.fileno())


@dataclass(frozen=True)
class _DadFiles:
    """Pliki taty w ``config/``, które przesunięcie klonu usunęłoby: nowa wersja je usuwa albo przestaje śledzić.

    Tata może je mieć zmienione (Konfiguracja wykonawców z prawdziwymi
    nazwiskami po #161); te zmiany nie zatrzymują Aktualizacji narzędzia.
    Przed przesunięciem trafiają do kopii w dzienniku „Aktualizacja w toku”
    i wracają do stanu z ``HEAD``, żeby Git nie odmówił; po przesunięciu
    (udanym albo nie) wraca ich kopia. Inne
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
        """Przywraca plikom treść z ``HEAD``; po bloku (udanym albo nie) wgrywa z powrotem ich kopie z ``backup``.

        ``_NotPutBack``, gdy kopia nie wróci (np. plik zablokowany): treść taty jest wtedy tylko w ``backup``.
        ``_NotSetAside``, gdy Git nie przywróci treści z ``HEAD``: kopie już wróciły, a klon się nie zmienił.
        """

        try:
            restored = (f":(literal){name}" for name in self.names)
            if self.names and git.run("checkout", "HEAD", "--", *restored).returncode != 0:
                raise _NotSetAside("checkout")
            yield
        finally:
            try:
                _put_back(git.root, backup, self.names)
            except OSError as failure:
                raise _NotPutBack from failure


@dataclass(frozen=True)
class _Git:
    """Polecenia Gita w klonie ``root``: bez okien i pytań, z zaufaniem do klonu tylko na to wywołanie."""

    executable: Path
    root: Path

    def run(self, *args: str, timeout_s: float = _LOCAL_TIMEOUT_S) -> subprocess.CompletedProcess[str]:
        """Polecenie Gita z wyjściem i błędami jako tekst; ``subprocess.TimeoutExpired`` najpóźniej po ``timeout_s``.

        Wyjście idzie do plików tymczasowych: potok, który pomocnik Gita trzyma
        otwarty po końcu Gita, wstrzymałby odczyt, a w Windows także po limicie czasu.
        """

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
        with tempfile.TemporaryFile() as output, tempfile.TemporaryFile() as errors:
            process = subprocess.Popen(
                command,
                env=_quiet_environment(),
                stdin=subprocess.DEVNULL,
                stdout=output,
                stderr=errors,
                creationflags=_NO_WINDOW,
                start_new_session=sys.platform != "win32",
            )
            try:
                returncode = process.wait(timeout=timeout_s)
            except subprocess.TimeoutExpired:
                _kill_tree(process)
                raise
            return subprocess.CompletedProcess(command, returncode, _text_of(output), _text_of(errors))

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

    def is_ancestor(self, ancestor: str, descendant: str) -> bool:
        """Czy ``ancestor`` to ``descendant`` albo jego przodek."""

        result = self.run("merge-base", "--is-ancestor", ancestor, descendant)
        if result.returncode not in (0, 1):
            raise GitFailed("merge-base")
        return result.returncode == 0

    def changed(self, before: str, after: str, name: str) -> bool:
        """Czy ``after`` dodaje albo zmienia plik ``name`` względem ``before``."""

        result = self.run("diff", "--quiet", "--no-renames", "--diff-filter=AM", before, after, "--", f":(literal){name}")
        if result.returncode not in (0, 1):
            raise GitFailed("diff")
        return result.returncode == 1

    def fetch(self, origin: str) -> str | None:
        """Pobiera `main` i tagi Wydań z ``origin``; ``None``, gdy się udało, inaczej kod porażki (logowanie albo brak sieci).

        Adres jest stały, więc każda inna porażka pobrania to brak połączenia z GitHubem.
        """

        try:
            result = self.run(
                "-c",
                "http.proxy=",
                "-c",
                f"http.lowSpeedLimit={_STALLED_BYTES_PER_S}",
                "-c",
                f"http.lowSpeedTime={_STALLED_FOR_S}",
                "fetch",
                "--quiet",
                "--no-tags",
                "--prune",
                origin,
                f"+refs/heads/{BRANCH}:{_FETCHED_MAIN}",
                f"+refs/tags/v*:{_RELEASES}v*",
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


def _text_of(file: IO[bytes]) -> str:
    file.seek(0)
    return file.read().decode("utf-8", errors="replace")


def _kill_tree(process: subprocess.Popen[bytes]) -> None:
    """Zabija Gita razem z jego pomocnikami: w Windows ``taskkill /T``, gdzie indziej całą jego sesję."""

    if sys.platform == "win32":
        subprocess.run(
            ["taskkill", "/F", "/T", "/PID", str(process.pid)],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=_KILL_TIMEOUT_S,
            check=False,
            creationflags=_NO_WINDOW,
        )
    else:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except OSError:
            pass  # Git i jego pomocnicy już się zakończyli
    process.kill()
    process.wait()


# Tyle czeka zabijanie drzewa procesów Gita po limicie czasu.
_KILL_TIMEOUT_S: Final = 10.0


def _quiet_environment() -> dict[str, str]:
    """Środowisko Gita bez pytań i okien, z komunikatami po angielsku i bez serwera proxy."""

    environment = {
        name: value
        for name, value in os.environ.items()
        if name not in _FOREIGN_VARIABLES and not name.lower().endswith("_proxy")
    }
    return environment | {"GIT_TERMINAL_PROMPT": "0", "GCM_INTERACTIVE": "never", "LC_ALL": "C", "LANGUAGE": "C"}

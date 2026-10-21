"""Aktualizacja narzędzia na prawdziwym Gicie: klon taty i lokalne repozytorium „origin” zamiast GitHuba.

Moduł ``tool_update`` ma jedną operację, którą widzą dwa wejścia (akcja API
Centrum i opiekun ponownego startu), więc jego macierz reguł jest tutaj, na
jego interfejsie. Żaden test nie łączy się z siecią.
"""

from __future__ import annotations

from collections.abc import Callable
import os
from pathlib import Path
import sys
import time

import pytest

from rozliczenia.centrum.tool_update import ToolClone, UpdateResult, find_git

from tests.fixtures.tool_clone import (
    ToolRepository,
    origin_asking_for_login,
    tool_repository,
    unreachable_origin,
)


@pytest.fixture(autouse=True)
def git_bez_konfiguracji_komputera_testow(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", os.devnull)
    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")


@pytest.fixture
def repository(tmp_path: Path) -> ToolRepository:
    return tool_repository(tmp_path / "repozytoria")


def update(repository: ToolRepository, tmp_path: Path) -> UpdateResult:
    backup = tmp_path / "kopia-plikow-taty"
    return ToolClone(repository.clone, origin=str(repository.origin)).update(backup)


def test_aktualizacja_przesuwa_klon_do_przodu_na_najnowszy_main(repository: ToolRepository, tmp_path: Path) -> None:
    before = repository.head()
    newest = repository.publish({"src/narzedzie.py": "WERSJA = 2\n"})

    result = update(repository, tmp_path)

    assert result == UpdateResult("ok", before=before, after=newest, installed=False)
    assert repository.head() == newest
    assert repository.read("src/narzedzie.py") == "WERSJA = 2\n"


def test_klon_na_najnowszym_commicie_jest_juz_aktualny(repository: ToolRepository, tmp_path: Path) -> None:
    current = repository.head()

    result = update(repository, tmp_path)

    assert result == UpdateResult("AKTUALNA", before=current, after=current, installed=False)
    assert repository.head() == current


def test_bez_gita_na_komputerze_aktualizacja_konczy_sie_brakiem_gita_a_klon_zostaje_bez_zmian(
    repository: ToolRepository, tmp_path: Path
) -> None:
    repository.publish({"src/narzedzie.py": "WERSJA = 2\n"})
    unchanged = repository.state()

    result = ToolClone(repository.clone, origin=str(repository.origin), find_git=lambda: None).update(tmp_path / "kopia")

    assert result == UpdateResult("BRAK_GITA", before=None, after=None)
    assert repository.state() == unchanged


def test_bez_polaczenia_z_githubem_aktualizacja_konczy_sie_brakiem_polaczenia_a_klon_zostaje_bez_zmian(
    repository: ToolRepository, tmp_path: Path
) -> None:
    before = repository.head()
    unchanged = repository.state()

    result = ToolClone(repository.clone, origin=unreachable_origin()).update(tmp_path / "kopia")

    assert result == UpdateResult("BRAK_POLACZENIA", before=before, after=None)
    assert repository.state() == unchanged


def credential_helper_that_waits(tmp_path: Path) -> Path:
    """Konfiguracja Gita komputera z pomocnikiem logowania, który zapisuje ślad i czeka na odpowiedź taty."""

    asked = tmp_path / "pomocnik-logowania-zapytany"
    helper = tmp_path / "pomocnik_logowania.py"
    helper.write_text(
        f"import pathlib, time\npathlib.Path({str(asked)!r}).touch()\ntime.sleep(60)\n", encoding="utf-8"
    )
    config = tmp_path / "gitconfig"
    command = f"!'{Path(sys.executable).as_posix()}' '{helper.as_posix()}'"
    config.write_text(f'[credential]\n\thelper = "{command}"\n', encoding="utf-8")
    return config


def test_github_proszacy_o_logowanie_konczy_sie_od_razu_bez_pytania_a_klon_zostaje_bez_zmian(
    repository: ToolRepository, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Na komputerze taty Git for Windows ma pomocnika logowania z oknem; tu pomocnik czekałby minutę.
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", str(credential_helper_that_waits(tmp_path)))
    before = repository.head()
    unchanged = repository.state()

    with origin_asking_for_login() as origin:
        started = time.monotonic()
        result = ToolClone(repository.clone, origin=origin).update(tmp_path / "kopia")
        elapsed = time.monotonic() - started

    assert result == UpdateResult("LOGOWANIE", before=before, after=None)
    assert elapsed < 20
    assert not (tmp_path / "pomocnik-logowania-zapytany").exists()
    assert repository.state() == unchanged


def test_klon_na_innej_galezi_daje_odmowe_a_klon_zostaje_bez_zmian(repository: ToolRepository, tmp_path: Path) -> None:
    repository.publish({"src/narzedzie.py": "WERSJA = 2\n"})
    repository.in_clone("checkout", "--quiet", "-b", "proba-maksa")
    before = repository.head()
    unchanged = repository.state()

    result = update(repository, tmp_path)

    assert result == UpdateResult("INNA_GALAZ", before=before, after=None)
    assert repository.state() == unchanged


def local_commit(repository: ToolRepository) -> None:
    repository.write("src/narzedzie.py", "WERSJA = 1  # poprawka na komputerze taty\n")
    repository.in_clone("commit", "--quiet", "--all", "--message", "Poprawka na komputerze taty")


def changed_tracked_file(repository: ToolRepository) -> None:
    repository.write("src/narzedzie.py", "WERSJA = 1  # poprawka na komputerze taty\n")


def untracked_file_that_new_version_adds(repository: ToolRepository) -> None:
    repository.write("src/nowy_modul.py", "# plik zostawiony na komputerze taty\n")


@pytest.mark.parametrize(
    "change",
    [local_commit, changed_tracked_file, untracked_file_that_new_version_adds],
    ids=["lokalny-commit", "zmieniony-sledzony-plik", "niesledzony-plik-z-nowej-wersji"],
)
def test_zmiany_na_komputerze_daja_odmowe_a_klon_zostaje_bez_zmian(
    repository: ToolRepository, tmp_path: Path, change: Callable[[ToolRepository], None]
) -> None:
    repository.publish({"src/narzedzie.py": "WERSJA = 2\n", "src/nowy_modul.py": "WERSJA_MODULU = 2\n"})
    change(repository)
    before = repository.head()
    unchanged = repository.state()

    result = update(repository, tmp_path)

    assert result == UpdateResult("ZMIANY_NA_KOMPUTERZE", before=before, after=None)
    assert repository.state() == unchanged


def installed_git(directory: Path) -> Path:
    """Git for Windows zainstalowany w ``directory``: polecenie ``cmd\\git.exe``."""

    git = directory / "cmd" / "git.exe"
    git.parent.mkdir(parents=True)
    git.touch()
    return git


def no_registry(hive: str) -> str | None:
    return None


def test_git_z_path_ma_pierwszenstwo(tmp_path: Path) -> None:
    in_program_files = installed_git(tmp_path / "Program Files" / "Git")

    found = find_git(
        which=lambda name: "/usr/bin/git" if name == "git" else None,
        registry=no_registry,
        environ={"ProgramFiles": str(in_program_files.parents[2])},
    )

    assert found == Path("/usr/bin/git")


@pytest.mark.parametrize("hive", ["HKLM", "HKCU"])
def test_git_poza_path_z_katalogu_git_for_windows_w_rejestrze(tmp_path: Path, hive: str) -> None:
    git = installed_git(tmp_path / "Narzedzia" / "Git")

    found = find_git(
        which=lambda name: None,
        registry=lambda asked: str(git.parents[1]) if asked == hive else None,
        environ={},
    )

    assert found == git


@pytest.mark.parametrize(
    ("variable", "folders"),
    [
        ("ProgramFiles", ("Git",)),
        ("ProgramFiles(x86)", ("Git",)),
        ("LOCALAPPDATA", ("Programs", "Git")),
    ],
)
def test_git_poza_path_i_rejestrem_ze_znanych_miejsc_instalacji(
    tmp_path: Path, variable: str, folders: tuple[str, ...]
) -> None:
    git = installed_git(tmp_path.joinpath(*folders))

    found = find_git(which=lambda name: None, registry=no_registry, environ={variable: str(tmp_path)})

    assert found == git


def test_wpis_w_rejestrze_bez_gita_na_dysku_to_brak_gita(tmp_path: Path) -> None:
    found = find_git(
        which=lambda name: None,
        registry=lambda hive: str(tmp_path / "odinstalowany Git"),
        environ={"ProgramFiles": str(tmp_path / "Program Files")},
    )

    assert found is None

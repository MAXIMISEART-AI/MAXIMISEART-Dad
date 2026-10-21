"""Aktualizacja narzędzia na prawdziwym Gicie: klon taty i lokalne repozytorium „origin” zamiast GitHuba.

Moduł ``tool_update`` ma jedną operację, którą widzą dwa wejścia (akcja API
Centrum i opiekun ponownego startu), więc jego macierz reguł jest tutaj, na
jego interfejsie. Żaden test nie łączy się z siecią.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from rozliczenia.centrum.tool_update import GitFailed, ToolClone, UpdateResult, find_git

from tests.fixtures.tool_clone import FIRST_VERSION, NEW_REQUIREMENTS, FakeInstaller, ToolRepository, tool_repository


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


REAL_NAMES = "schema_version: 1\nworkers:\n  jan: Jan Kowalski\n"
RATES = "stawki:\n  przyklad: 10\n"


def test_konfiguracja_wykonawcow_ktorej_nowa_wersja_nie_sledzi_zostaje_z_prawdziwymi_nazwiskami(
    repository: ToolRepository, tmp_path: Path
) -> None:
    (repository.clone / "config" / "worker_mapping.yaml").write_text(REAL_NAMES, encoding="utf-8")
    newest = repository.publish({".gitignore": "config/worker_mapping.yaml\n"}, untrack=("config/worker_mapping.yaml",))

    result = update(repository, tmp_path)

    assert (result.code, result.after) == ("ok", newest)
    assert repository.head() == newest
    assert repository.read("config/worker_mapping.yaml") == REAL_NAMES


@pytest.mark.parametrize(
    "new_version",
    [
        {"config/stawki.yaml": None},
        {"config/stawki.yaml": None, "config/stawki-wykonawcow.yaml": RATES},
    ],
    ids=["usuniety", "przeniesiony"],
)
def test_plik_konfiguracji_usuniety_w_nowej_wersji_zostaje_u_taty(
    tmp_path: Path, new_version: dict[str, str | None]
) -> None:
    repository = tool_repository(tmp_path / "repozytoria", {**FIRST_VERSION, "config/stawki.yaml": RATES})
    newest = repository.publish(new_version)

    result = update(repository, tmp_path)

    assert (result.code, repository.head()) == ("ok", newest)
    assert repository.read("config/stawki.yaml") == RATES


# Pliki taty, których Git nie śledzi: Wzorce, Ustawienia taty, klucz do Zgłoszeń, metryki i dziennik.
UNTRACKED_DAD_FILES = {
    "config/Wzorzec rozliczenia pracownika.xlsx": "wzorzec pracownika",
    "config/Wzorzec pliku zbiorczego.xlsx": "wzorzec zbiorczy",
    "config/Wzorzec rozliczenia wewnętrznego.xlsx": "wzorzec wewnętrzny",
    "config/centrum-ustawienia.yaml": "folder_okresow: Załączniki\n",
    "config/zgloszenia-klucz.txt": "klucz-syntetyczny\n",
    ".rozliczenia-metrics.jsonl": '{"przebieg": 1}\n',
    ".przygotowanie-pliku-zbiorczego-metrics.jsonl": '{"przygotowanie": 1}\n',
    "logs/centrum-rozliczen.log": "2026-10-21T10:00:00 start\n",
}


def test_aktualizacja_nie_dotyka_wzorcow_ustawien_klucza_metryk_dziennika_ani_plikow_okresow(
    repository: ToolRepository, tmp_path: Path
) -> None:
    for name, content in UNTRACKED_DAD_FILES.items():
        (repository.clone / name).parent.mkdir(parents=True, exist_ok=True)
        (repository.clone / name).write_text(content, encoding="utf-8")
    period_file = tmp_path / "Załączniki" / "06_12_10_2026" / "Plik zbiorczy.xlsx"
    period_file.parent.mkdir(parents=True)
    period_file.write_text("plik okresu", encoding="utf-8")
    (repository.clone / "config" / "worker_mapping.yaml").write_text(REAL_NAMES, encoding="utf-8")
    untouched = [period_file, *(repository.clone / name for name in UNTRACKED_DAD_FILES)]
    modified = {path: path.stat().st_mtime_ns for path in untouched}
    repository.publish({".gitignore": "config/worker_mapping.yaml\n"}, untrack=("config/worker_mapping.yaml",))

    assert update(repository, tmp_path).code == "ok"

    assert {name: repository.read(name) for name in UNTRACKED_DAD_FILES} == UNTRACKED_DAD_FILES
    assert period_file.read_text(encoding="utf-8") == "plik okresu"
    assert {path: path.stat().st_mtime_ns for path in untouched} == modified


def test_odmowa_przesuniecia_zostawia_pliki_taty_i_klon_bez_zmian(repository: ToolRepository, tmp_path: Path) -> None:
    before = repository.head()
    (repository.clone / "config" / "worker_mapping.yaml").write_text(REAL_NAMES, encoding="utf-8")
    (repository.clone / "config" / "rejestr.yaml").write_text("zachowany u taty\n", encoding="utf-8")
    repository.publish(
        {".gitignore": "config/worker_mapping.yaml\n", "config/rejestr.yaml": "z nowej wersji\n"},
        untrack=("config/worker_mapping.yaml",),
    )

    with pytest.raises(GitFailed):
        update(repository, tmp_path)

    assert repository.head() == before
    assert repository.read("config/worker_mapping.yaml") == REAL_NAMES
    assert repository.read("config/rejestr.yaml") == "zachowany u taty\n"
    assert repository.in_clone("status", "--porcelain", "--branch").splitlines() == [
        "## main...origin/main [behind 1]",
        " M config/worker_mapping.yaml",
        "?? config/rejestr.yaml",
    ]


def test_zmiana_wymagan_instaluje_biblioteki_nowej_wersji(repository: ToolRepository, tmp_path: Path) -> None:
    before = repository.head()
    newest = repository.publish({"requirements.txt": NEW_REQUIREMENTS, "src/narzedzie.py": "WERSJA = 2\n"})
    installer = FakeInstaller()
    steps: list[str] = []
    clone = ToolClone(repository.clone, origin=str(repository.origin), install=installer)

    result = clone.update(tmp_path / "kopia-plikow-taty", steps.append)

    assert result == UpdateResult("ok", before=before, after=newest, installed=True)
    assert installer.installed == [(repository.clone / "requirements.txt", NEW_REQUIREMENTS)]
    assert steps == ["fetching", "installing"]


def test_bez_zmiany_wymagan_biblioteki_nie_sa_instalowane(repository: ToolRepository, tmp_path: Path) -> None:
    repository.publish({"src/narzedzie.py": "WERSJA = 2\n"})
    installer = FakeInstaller()
    steps: list[str] = []
    clone = ToolClone(repository.clone, origin=str(repository.origin), install=installer)

    result = clone.update(tmp_path / "kopia-plikow-taty", steps.append)

    assert (result.code, result.installed) == ("ok", False)
    assert installer.installed == []
    assert steps == ["fetching"]


DAD_SETTINGS = "config/centrum-ustawienia.yaml"


def moved_with_new_requirements(repository: ToolRepository) -> str:
    """Nowa wersja zmienia wymagania, przestaje śledzić zmienioną u taty Konfigurację wykonawców i usuwa jej przykład."""

    (repository.clone / "config" / "worker_mapping.yaml").write_text(REAL_NAMES, encoding="utf-8")
    (repository.clone / DAD_SETTINGS).write_text("folder_okresow: Załączniki\n", encoding="utf-8")
    return repository.publish(
        {
            ".gitignore": "config/worker_mapping.yaml\n",
            "config/worker_mapping.example.yaml": None,
            "requirements.txt": NEW_REQUIREMENTS,
            "src/narzedzie.py": "WERSJA = 2\n",
        },
        untrack=("config/worker_mapping.yaml",),
    )


def assert_back_before_click(repository: ToolRepository, before: str) -> None:
    assert repository.head() == before
    assert repository.read("src/narzedzie.py") == "WERSJA = 1\n"
    assert repository.read("requirements.txt") == FIRST_VERSION["requirements.txt"]
    assert repository.read("config/worker_mapping.yaml") == REAL_NAMES
    assert repository.read("config/worker_mapping.example.yaml") == FIRST_VERSION["config/worker_mapping.example.yaml"]
    assert repository.read(DAD_SETTINGS) == "folder_okresow: Załączniki\n"
    assert repository.in_clone("status", "--porcelain", "--branch").splitlines() == [
        "## main...origin/main [behind 1]",
        " M config/worker_mapping.yaml",
        "?? config/centrum-ustawienia.yaml",
    ]


def test_nieudana_instalacja_bibliotek_cofa_klon_z_plikami_taty_i_daje_komunikat(
    repository: ToolRepository, tmp_path: Path
) -> None:
    before = repository.head()
    newest = moved_with_new_requirements(repository)
    clone = ToolClone(repository.clone, origin=str(repository.origin), install=FakeInstaller(succeeds=False))

    result = clone.update(tmp_path / "kopia-plikow-taty")

    assert result == UpdateResult("INSTALACJA_BIBLIOTEK", before=before, after=newest, installed=True)
    assert_back_before_click(repository, before)


def test_wyjatek_instalatora_cofa_klon_z_plikami_taty(repository: ToolRepository, tmp_path: Path) -> None:
    before = repository.head()
    moved_with_new_requirements(repository)

    def broken_installer(requirements: Path) -> bool:
        raise RuntimeError("instalator się wysypał")

    clone = ToolClone(repository.clone, origin=str(repository.origin), install=broken_installer)

    with pytest.raises(RuntimeError):
        clone.update(tmp_path / "kopia-plikow-taty")

    assert_back_before_click(repository, before)


def test_cofniecie_po_udanej_aktualizacji_wraca_do_commitu_sprzed_niej_z_plikami_taty(
    repository: ToolRepository, tmp_path: Path
) -> None:
    before = repository.head()
    moved_with_new_requirements(repository)
    backup = tmp_path / "kopia-plikow-taty"
    clone = ToolClone(repository.clone, origin=str(repository.origin), install=FakeInstaller())
    assert clone.update(backup).code == "ok"

    clone.roll_back(before, backup)

    assert_back_before_click(repository, before)

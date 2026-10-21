"""Aktualizacja narzędzia na prawdziwym Gicie: klon taty i lokalne repozytorium „origin” zamiast GitHuba.

Moduł ``tool_update`` ma jedną operację, którą widzą dwa wejścia (akcja API
Centrum i opiekun ponownego startu), więc jego macierz reguł jest tutaj, na
jego interfejsie. Żaden test nie łączy się z siecią.
"""

from __future__ import annotations

from collections.abc import Callable
import os
from pathlib import Path
import shutil
import sys
import time

import pytest

from rozliczenia.centrum.tool_update import JournalKept, ToolClone, UpdateResult, find_git

from tests.fixtures.tool_clone import (
    FIRST_VERSION,
    NEW_REQUIREMENTS,
    FakeInstaller,
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


def update(repository: ToolRepository) -> UpdateResult:
    return ToolClone(repository.clone, origin=str(repository.origin)).update()


def test_aktualizacja_przesuwa_klon_do_przodu_na_najnowszy_main(repository: ToolRepository, tmp_path: Path) -> None:
    before = repository.head()
    newest = repository.publish({"src/narzedzie.py": "WERSJA = 2\n"})

    result = update(repository)

    assert result == UpdateResult("ok", before=before, after=newest, installed=False)
    assert repository.head() == newest
    assert repository.read("src/narzedzie.py") == "WERSJA = 2\n"


def test_klon_na_najnowszym_commicie_jest_juz_aktualny(repository: ToolRepository, tmp_path: Path) -> None:
    current = repository.head()

    result = update(repository)

    assert result == UpdateResult("AKTUALNA", before=current, after=current, installed=False)
    assert repository.head() == current


def test_bez_gita_na_komputerze_aktualizacja_konczy_sie_brakiem_gita_a_klon_zostaje_bez_zmian(
    repository: ToolRepository, tmp_path: Path
) -> None:
    repository.publish({"src/narzedzie.py": "WERSJA = 2\n"})
    unchanged = repository.state()

    result = ToolClone(repository.clone, origin=str(repository.origin), find_git=lambda: None).update()

    assert result == UpdateResult("BRAK_GITA", before=None, after=None)
    assert repository.state() == unchanged


def test_bez_polaczenia_z_githubem_aktualizacja_konczy_sie_brakiem_polaczenia_a_klon_zostaje_bez_zmian(
    repository: ToolRepository, tmp_path: Path
) -> None:
    before = repository.head()
    unchanged = repository.state()

    result = ToolClone(repository.clone, origin=unreachable_origin()).update()

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
        result = ToolClone(repository.clone, origin=origin).update()
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

    result = update(repository)

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

    result = update(repository)

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


REAL_NAMES = "schema_version: 1\nworkers:\n  jan: Jan Kowalski\n"
RATES = "stawki:\n  przyklad: 10\n"


def test_konfiguracja_wykonawcow_ktorej_nowa_wersja_nie_sledzi_zostaje_z_prawdziwymi_nazwiskami(
    repository: ToolRepository, tmp_path: Path
) -> None:
    (repository.clone / "config" / "worker_mapping.yaml").write_text(REAL_NAMES, encoding="utf-8")
    newest = repository.publish({".gitignore": "config/worker_mapping.yaml\n"}, untrack=("config/worker_mapping.yaml",))

    result = update(repository)

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

    result = update(repository)

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

    assert update(repository).code == "ok"

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

    result = update(repository)

    assert result == UpdateResult("ZMIANY_NA_KOMPUTERZE", before=before, after=None)
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

    result = clone.update(steps.append)

    assert result == UpdateResult("ok", before=before, after=newest, installed=True)
    assert installer.installed == [(repository.clone / "requirements.txt", NEW_REQUIREMENTS)]
    assert steps == ["fetching", "installing"]


def test_bez_zmiany_wymagan_biblioteki_nie_sa_instalowane(repository: ToolRepository, tmp_path: Path) -> None:
    repository.publish({"src/narzedzie.py": "WERSJA = 2\n"})
    installer = FakeInstaller()
    steps: list[str] = []
    clone = ToolClone(repository.clone, origin=str(repository.origin), install=installer)

    result = clone.update(steps.append)

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

    result = clone.update()

    assert result == UpdateResult("INSTALACJA_BIBLIOTEK", before=before, after=newest, installed=True)
    assert_back_before_click(repository, before)


def test_wyjatek_instalatora_cofa_klon_z_plikami_taty(repository: ToolRepository, tmp_path: Path) -> None:
    before = repository.head()
    moved_with_new_requirements(repository)

    def broken_installer(requirements: Path) -> bool:
        raise RuntimeError("instalator się wysypał")

    clone = ToolClone(repository.clone, origin=str(repository.origin), install=broken_installer)

    with pytest.raises(RuntimeError):
        clone.update()

    assert_back_before_click(repository, before)


def test_cofniecie_po_udanej_aktualizacji_wraca_do_commitu_sprzed_niej_z_plikami_taty(
    repository: ToolRepository, tmp_path: Path
) -> None:
    before = repository.head()
    moved_with_new_requirements(repository)
    clone = ToolClone(repository.clone, origin=str(repository.origin), install=FakeInstaller())
    assert clone.update().code == "ok"

    clone.roll_back()

    assert_back_before_click(repository, before)


def test_cofniecie_nie_rusza_klonu_przesunietego_po_aktualizacji_na_inny_commit(
    repository: ToolRepository, tmp_path: Path
) -> None:
    moved_with_new_requirements(repository)
    clone = ToolClone(repository.clone, origin=str(repository.origin), install=FakeInstaller())
    assert clone.update().code == "ok"
    repository.write("src/narzedzie.py", "WERSJA = 3\n")
    repository.in_clone("commit", "--quiet", "--all", "--message", "Poprawka Maksa")
    by_maks = repository.state()

    with pytest.raises(JournalKept):
        clone.roll_back()

    assert repository.state() == by_maks


def test_aktualizacja_w_toku_nie_zastepuje_kopii_pliku_taty_kolejnym_kliknieciem(
    repository: ToolRepository, tmp_path: Path
) -> None:
    before = repository.head()
    (repository.clone / "config" / "worker_mapping.yaml").write_text(REAL_NAMES, encoding="utf-8")
    (repository.clone / "config" / "rejestr.yaml").write_text("zachowany u taty\n", encoding="utf-8")
    repository.publish(
        {".gitignore": "config/worker_mapping.yaml\n", "config/rejestr.yaml": "z nowej wersji\n"},
        untrack=("config/worker_mapping.yaml",),
    )
    git = git_locking_after_merge(tmp_path, repository.clone / "config" / "worker_mapping.yaml")
    clone = ToolClone(repository.clone, origin=str(repository.origin), find_git=lambda: git)
    assert clone.update().code == "COFNIECIE_NIEUDANE"

    with pytest.raises(JournalKept):
        clone.update()
    clone.roll_back()

    assert repository.head() == before
    assert repository.read("config/worker_mapping.yaml") == REAL_NAMES


def git_whose_helper_holds_its_output(tmp_path: Path, commit: str) -> Path:
    """Git, którego pomocnik (jak ``git-remote-https`` przy pobraniu) zostaje po nim z jego wyjściem otwartym na minutę.

    Odpowiada jak klon na `main` już na najnowszym commicie ``commit``.
    """

    script = tmp_path / "git_z_pomocnikiem.py"
    script.write_text(
        "import subprocess, sys\n"
        f"COMMIT = {commit!r}\n"
        "args = [arg for index, arg in enumerate(sys.argv[1:]) if arg != '-c' and sys.argv[index] != '-c']\n"
        "command = args[2] if args[:1] == ['-C'] else args[0]\n"
        "if command == 'fetch':\n"
        "    subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)'])\n"
        "print('main' if command == 'symbolic-ref' else COMMIT)\n",
        encoding="utf-8",
    )
    return _executable(tmp_path, script)


def _executable(directory: Path, script: Path) -> Path:
    """Polecenie ``git`` w ``directory``, które uruchamia skrypt Pythona ``script`` z argumentami Gita."""

    if os.name == "nt":
        git = directory / "git.cmd"
        git.write_text(f'@"{sys.executable}" "{script}" %*\n', encoding="utf-8")
    else:
        git = directory / "git"
        git.write_text(f"#!{sys.executable}\nexec(open({str(script)!r}, encoding='utf-8').read())\n", encoding="utf-8")
        git.chmod(0o755)
    return git


def test_pomocnik_gita_trzymajacy_jego_wyjscie_nie_wstrzymuje_aktualizacji(tmp_path: Path) -> None:
    commit = "1" * 40
    git = git_whose_helper_holds_its_output(tmp_path, commit)

    started = time.monotonic()
    result = ToolClone(tmp_path, origin="https://example.invalid/narzedzie.git", find_git=lambda: git).update()
    elapsed = time.monotonic() - started

    assert result == UpdateResult("AKTUALNA", before=commit, after=commit)
    assert elapsed < 20


def installer_that_changes(repository: ToolRepository, name: str) -> Callable[[Path], bool]:
    """Instalator, który nie zainstaluje bibliotek, a po drodze zmienia plik ``name`` klonu: cofnięcie go nie przejdzie."""

    def install(requirements: Path) -> bool:
        repository.write(name, "zmienione w trakcie instalacji\n")
        return False

    return install


def test_gdy_cofniecie_po_nieudanej_instalacji_sie_nie_uda_wynik_mowi_to_wprost(
    repository: ToolRepository, tmp_path: Path
) -> None:
    before = repository.head()
    newest = repository.publish({"requirements.txt": NEW_REQUIREMENTS, "src/narzedzie.py": "WERSJA = 2\n"})
    clone = ToolClone(
        repository.clone, origin=str(repository.origin), install=installer_that_changes(repository, "src/narzedzie.py")
    )

    result = clone.update()

    assert result == UpdateResult("COFNIECIE_NIEUDANE", before=before, after=newest, installed=True)
    assert repository.head() == newest


def test_gdy_plik_taty_nie_wroci_po_przesunieciu_klon_wraca_do_poprzedniej_wersji_z_plikiem_taty(
    repository: ToolRepository, tmp_path: Path
) -> None:
    before = repository.head()
    (repository.clone / "config" / "worker_mapping.yaml").write_text(REAL_NAMES, encoding="utf-8")
    newest = repository.publish({".gitignore": "config/worker_mapping.yaml\n"}, untrack=("config/worker_mapping.yaml",))
    # Folder config/ zablokowany, gdy kopia pliku taty ma do niego wrócić po przesunięciu klonu.
    git = git_locking_after_merge(tmp_path, repository.clone / "config")
    clone = ToolClone(repository.clone, origin=str(repository.origin), find_git=lambda: git)

    result = clone.update()

    assert result == UpdateResult("NIEOCZEKIWANY_BLAD", before=before, after=newest)
    assert repository.head() == before
    assert repository.read("config/worker_mapping.yaml") == REAL_NAMES


def git_locking_after_merge(tmp_path: Path, locked: Path) -> Path:
    """Prawdziwy Git, po którego ``merge`` ``locked`` jest tylko do odczytu aż do następnego polecenia Gita.

    Tak na chwilę blokuje plik albo folder antywirus czy OneDrive. Windows nie
    zważa na atrybut tylko do odczytu folderu, więc tam folder blokuje wpis
    uprawnień, który odmawia tworzenia w nim plików.
    """

    real = shutil.which("git")
    assert real is not None
    script = tmp_path / "git_blokujacy.py"
    script.write_text(
        "import os, stat, subprocess, sys\n"
        f"locked = {str(locked)!r}\n"
        "acl = os.name == 'nt' and os.path.isdir(locked)\n"
        "def lock(on):\n"
        "    if acl:\n"
        "        rule = ['/deny', '*S-1-1-0:(WD,AD)'] if on else ['/remove:d', '*S-1-1-0']\n"
        "        subprocess.run(['icacls', locked, *rule], capture_output=True, check=True)\n"
        "    else:\n"
        "        os.chmod(locked, stat.S_IREAD | stat.S_IEXEC if on else stat.S_IRWXU)\n"
        "if os.path.exists(locked):\n"
        "    lock(False)\n"
        f"code = subprocess.call([{real!r}, *sys.argv[1:]])\n"
        "if 'merge' in sys.argv:\n"
        "    lock(True)\n"
        "sys.exit(code)\n",
        encoding="utf-8",
    )
    return _executable(tmp_path, script)


def test_gdy_plik_taty_nie_wroci_po_odmowie_przesuniecia_wynik_mowi_to_wprost_a_cofniecie_przywraca_plik_taty(
    repository: ToolRepository, tmp_path: Path
) -> None:
    before = repository.head()
    (repository.clone / "config" / "worker_mapping.yaml").write_text(REAL_NAMES, encoding="utf-8")
    (repository.clone / "config" / "rejestr.yaml").write_text("zachowany u taty\n", encoding="utf-8")
    repository.publish(
        {".gitignore": "config/worker_mapping.yaml\n", "config/rejestr.yaml": "z nowej wersji\n"},
        untrack=("config/worker_mapping.yaml",),
    )
    # Plik taty zablokowany do zapisu (np. przez antywirusa), gdy kopia ma do niego wrócić.
    git = git_locking_after_merge(tmp_path, repository.clone / "config" / "worker_mapping.yaml")
    clone = ToolClone(repository.clone, origin=str(repository.origin), find_git=lambda: git)

    result = clone.update()
    clone.roll_back()

    assert result == UpdateResult("COFNIECIE_NIEUDANE", before=before, after=None)
    assert repository.head() == before
    assert repository.read("config/worker_mapping.yaml") == REAL_NAMES

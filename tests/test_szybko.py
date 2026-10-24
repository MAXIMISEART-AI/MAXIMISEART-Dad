"""``tools/szybko.py``: ruff, mypy dla obu systemów, testy struktury i testy dotknięte zmianą, raz na tych samych plikach."""

from __future__ import annotations

import os
from pathlib import Path
import re
import shutil
import subprocess
import sys

import pytest

from tests.fixtures.git_repo import commit, git, repository

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

import szybko  # noqa: E402

BY_CHANGE_ONLY = {
    "tests/test_brama_pre_push.py": "sprawdza zachowanie bramy pushem w repozytorium testu, a nie całe repozytorium",
    "tests/test_praca_w_toku.py": "sprawdza werdykt narzędzia na repozytoriach testu, a nie całe repozytorium; trwa ok. 19 s",
    "tests/test_szybko.py": "sprawdza samo szybko w repozytoriach testu; graf wybiera go przy zmianie tools/szybko.py i AGENTS.md",
}

BASE_FILES = {
    ".agents/skills/verify-x/scripts/skrypt.py": "WARTOSC = 1\n",
    "uruchom.py": "WARTOSC = 1\n",
    "tools/hooks/pre-push": "#!/usr/bin/env python3\n",
    "src/pakiet/__init__.py": "",
    "src/pakiet/a.py": "def wartosc() -> int:\n    return 1\n",
    "src/pakiet/posredni.py": "from pakiet.a import wartosc\n\n\ndef podwojona() -> int:\n    return 2 * wartosc()\n",
    "src/pakiet/b.py": "def inna() -> int:\n    return 1\n",
    "tests/__init__.py": "",
    "tests/test_posredni.py": (
        "from pakiet.posredni import podwojona\n\n\ndef test_podwojona() -> None:\n    assert podwojona() == 2\n"
    ),
    "tests/test_zawsze_pada.py": "from pakiet.b import inna\n\n\ndef test_niedotkniety() -> None:\n    assert inna() == 2\n",
    "tools/narzedzie.py": "print('wynik')\n",
    "src/pakiet/narzedzia.py": "from pathlib import Path\n\nSKRYPT = Path('tools', 'narzedzie.py')\n",
    "tests/test_narzedzie.py": (
        "from pathlib import Path\nimport subprocess\nimport sys\n\nfrom pakiet.narzedzia import SKRYPT\n\n\n"
        "def test_narzedzie() -> None:\n"
        "    root = Path(__file__).resolve().parents[1]\n"
        "    done = subprocess.run([sys.executable, str(root / SKRYPT)], capture_output=True, text=True, check=True)\n"
        "    assert done.stdout == 'wynik\\n'\n"
    ),
    "src/witryna/__init__.py": "",
    "src/witryna/strona.py": (
        "from pathlib import Path\n\n\ndef tytul() -> str:\n"
        "    return (Path(__file__).parent / 'strona.html').read_text(encoding='utf-8').strip()\n"
    ),
    "src/witryna/strona.html": "Centrum\n",
    "tests/test_strona.py": "from witryna.strona import tytul\n\n\ndef test_tytul() -> None:\n    assert tytul() == 'Centrum'\n",
    "skille/a/OPIS.md": "pilnuje: src\n",
    "tests/test_opisy.py": (
        "from pathlib import Path\n\nSKILLE = Path(__file__).resolve().parents[1] / 'skille'\n\n\n"
        "def test_opisy() -> None:\n"
        "    assert [p.read_text(encoding='utf-8') for p in SKILLE.glob('*/OPIS.md')] == ['pilnuje: src\\n']\n"
    ),
    "docs/dane/wpis.md": "zgodny\n",
    "tests/test_dane.py": (
        "import os\nfrom pathlib import Path\n\nDANE = Path(__file__).resolve().parents[1] / 'docs' / 'dane'\n\n\n"
        "def test_dane() -> None:\n"
        "    assert [(DANE / name).read_text(encoding='utf-8') for name in sorted(os.listdir(DANE))] == ['zgodny\\n']\n"
    ),
}
COUNTED = (
    "import os\nfrom pathlib import Path\n\nfrom pakiet.posredni import podwojona\n\n\n"
    "def test_podwojona() -> None:\n"
    "    with Path(os.environ['PRZEBIEGI']).open('a', encoding='utf-8') as runs:\n"
    "        runs.write('.')\n"
    "    assert podwojona() == 2\n"
)


@pytest.fixture(autouse=True)
def wspolny_cache_mypy(tmp_path_factory: pytest.TempPathFactory, monkeypatch: pytest.MonkeyPatch) -> None:
    """Mypy repozytoriów testu dzieli cache workera: typeshed i biblioteki nie są sprawdzane na nowo w każdym teście.

    Pliki repozytorium mają w każdym teście inną ścieżkę, więc mypy sprawdza je od nowa. Krok dla Windows ma własne
    ``--cache-dir`` w repozytorium testu i zmienna go nie dotyczy.
    """

    monkeypatch.setenv("MYPY_CACHE_DIR", str(tmp_path_factory.getbasetemp() / "mypy-szybko"))


def _structure_stubs(body: str) -> dict[str, str]:
    stubs: dict[str, str] = {}
    for node in szybko.STRUCTURE:
        path, _, name = node.partition("::")
        header = "from pathlib import Path\n" if "Path(" in body else ""
        stubs[path] = stubs.get(path, header) + f"\n\ndef {name or 'test_struktura'}() -> None:\n    {body}\n"
    return stubs


def _repo(tmp_path: Path, structure: str = "pass") -> Path:
    # Zadanie pytest na Windows w CI instaluje tylko requirements.txt; szybko biegnie tam w zadaniu na Linuksie.
    for static_check in ("ruff", "mypy"):
        pytest.importorskip(static_check, reason="szybko uruchamia ruff i mypy z dodatku dev")
    repo = repository(tmp_path / "repo", {**BASE_FILES, **_structure_stubs(structure)})
    # Krok najstarszego Pythona sprawdzają osobne testy; tu requires-python to Python, którym biegnie szybko.
    pyproject = (repo / "pyproject.toml").read_text(encoding="utf-8")
    current = f'requires-python = ">={sys.version_info[0]}.{sys.version_info[1]}"'
    (repo / "pyproject.toml").write_text(re.sub(r"requires-python = .*", current, pyproject), encoding="utf-8")
    for name in (".gitignore", "tools/szybko.py"):
        shutil.copy2(ROOT / name, repo / name)
    commit(repo, "baza")
    git(repo, "update-ref", "refs/remotes/origin/main", "HEAD")
    return repo


def _szybko(
    repo: Path, *arguments: str, runs: Path | None = None, workers: str | None = "2"
) -> subprocess.CompletedProcess[str]:
    environment = {name: value for name, value in os.environ.items() if name != "PYTEST_XDIST_AUTO_NUM_WORKERS"}
    environment |= {"PRZEBIEGI": str(runs)} if runs else {}
    environment |= {"PYTEST_XDIST_AUTO_NUM_WORKERS": workers} if workers else {}
    return subprocess.run(
        [sys.executable, str(repo / "tools" / "szybko.py"), *arguments],
        cwd=repo,
        env=environment,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )


def _write(repo: Path, name: str, text: str) -> None:
    (repo / name).parent.mkdir(parents=True, exist_ok=True)
    (repo / name).write_text(text, encoding="utf-8")


@pytest.mark.parametrize("committed", [True, False], ids=["zacommitowana", "niezacommitowana"])
def test_zmiana_modulu_uruchamia_testy_ktore_go_importuja_a_pozostalych_nie(tmp_path: Path, committed: bool) -> None:
    repo = _repo(tmp_path)
    _write(repo, "src/pakiet/a.py", "def wartosc() -> int:\n    return 5\n")
    if committed:
        commit(repo, "zmiana a")

    answered = _szybko(repo)

    assert (answered.returncode, answered.stdout.splitlines()[-1]) == (1, "SZYBKO FAIL | pytest")
    assert "FAILED tests/test_posredni.py::test_podwojona" in answered.stdout
    assert "test_zawsze_pada" not in answered.stdout


def test_zmiana_bez_bledu_konczy_sie_ok_choc_niedotkniety_test_pada(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    _write(repo, "src/pakiet/a.py", "def wartosc() -> int:\n    return 0 + 1\n")

    answered = _szybko(repo)

    assert (answered.returncode, answered.stdout.splitlines()[-1]) == (0, "SZYBKO OK"), answered.stdout


def test_zielony_test_biegnie_znowu_dopiero_po_zmianie_pliku_od_ktorego_zalezy(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    runs = tmp_path / "przebiegi"
    _write(repo, "tests/test_posredni.py", COUNTED)
    first, again = _szybko(repo, runs=runs), _szybko(repo, runs=runs)
    _write(repo, "src/pakiet/a.py", "def wartosc() -> int:\n    return 2 - 1\n")
    after_change = _szybko(repo, runs=runs)

    assert [answered.stdout.splitlines()[-1] for answered in (first, again, after_change)] == ["SZYBKO OK"] * 3
    assert runs.read_text(encoding="utf-8") == ".."


def test_pamiec_zielonych_nie_przepuszcza_zmiany_pliku_danych_pakietu(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    with (repo / "src" / "witryna" / "strona.py").open("a", encoding="utf-8") as module:
        module.write("\n\nWERSJA = 2\n")
    green = _szybko(repo)
    _write(repo, "src/witryna/strona.html", "Inny tytuł\n")
    after_change = _szybko(repo)

    assert [green.stdout.splitlines()[-1], after_change.stdout.splitlines()[-1]] == ["SZYBKO OK", "SZYBKO FAIL | pytest"]
    assert "FAILED tests/test_strona.py::test_tytul" in after_change.stdout


@pytest.mark.parametrize(("workers", "expected"), [(None, "4"), ("3", "3")], ids=["bez zmiennej", "ze zmienną"])
def test_pytest_bierze_cztery_workery_chyba_ze_zmienna_mowi_inaczej(tmp_path: Path, workers: str | None, expected: str) -> None:
    repo = _repo(tmp_path)
    _write(
        repo,
        "tests/test_workery.py",
        f"import os\n\n\ndef test_workery() -> None:\n    assert os.environ['PYTEST_XDIST_AUTO_NUM_WORKERS'] == '{expected}'\n",
    )

    answered = _szybko(repo, workers=workers)

    assert (answered.returncode, answered.stdout.splitlines()[-1]) == (0, "SZYBKO OK"), answered.stdout


def test_test_ktory_padl_biegnie_znowu_bez_zmian(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    runs = tmp_path / "przebiegi"
    _write(repo, "tests/test_posredni.py", COUNTED.replace("== 2", "== 3"))

    answered = [_szybko(repo, runs=runs).stdout.splitlines()[-1] for _ in range(2)]

    assert answered == ["SZYBKO FAIL | pytest"] * 2
    assert runs.read_text(encoding="utf-8") == ".."


def test_nowy_niesledzony_test_biegnie(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    _write(repo, "tests/test_nowy.py", "def test_nowy() -> None:\n    assert False\n")

    answered = _szybko(repo)

    assert "FAILED tests/test_nowy.py::test_nowy" in answered.stdout
    assert answered.returncode == 1


@pytest.mark.parametrize(
    ("changed", "failing"),
    [
        ("tools/narzedzie.py", "tests/test_narzedzie.py::test_narzedzie"),
        ("docs/dane/wpis.md", "tests/test_dane.py::test_dane"),
        ("skille/a/OPIS.md", "tests/test_opisy.py::test_opisy"),
        ("src/witryna/strona.html", "tests/test_strona.py::test_tytul"),
    ],
    ids=[
        "skrypt, który test uruchamia",
        "plik katalogu, który test czyta",
        "plik z globu na katalogu",
        "plik danych pakietu, który czyta jego moduł",
    ],
)
def test_test_jest_dotkniety_zmiana_pliku_ktory_wskazuje_sciezka(tmp_path: Path, changed: str, failing: str) -> None:
    repo = _repo(tmp_path)
    _write(repo, changed, "print('inny')\n")

    answered = _szybko(repo)

    assert f"FAILED {failing}" in answered.stdout
    assert "test_zawsze_pada" not in answered.stdout


@pytest.mark.parametrize("changed", ["pyproject.toml", "requirements.txt", "tests/conftest.py"])
def test_zmiana_konfiguracji_albo_conftest_uruchamia_pelny_zestaw(tmp_path: Path, changed: str) -> None:
    repo = _repo(tmp_path)
    with (repo / changed).open("a", encoding="utf-8") as file:
        file.write("\n")

    answered = _szybko(repo)

    assert "FAILED tests/test_zawsze_pada.py::test_niedotkniety" in answered.stdout
    assert answered.returncode == 1


def test_testy_struktury_biegna_przy_zmianie_ktora_ich_nie_dotyka(tmp_path: Path) -> None:
    repo = _repo(tmp_path, structure="assert False")
    _write(repo, "docs/notatka.md", "nowa\n")

    answered = _szybko(repo)

    failed = set(re.findall(r"^FAILED (\S+)", answered.stdout, re.MULTILINE))
    assert {node if "::" in node else f"{node}::test_struktura" for node in szybko.STRUCTURE} <= failed
    assert answered.returncode == 1


def test_testy_struktury_biegna_tez_na_mergu_z_baza_ktora_poszla_dalej(tmp_path: Path) -> None:
    unique = (
        "numbers = [p.name[:4] for p in (Path(__file__).parents[1] / 'docs' / 'adr').glob('*.md')]\n"
        "    assert len(numbers) == len(set(numbers))"
    )
    repo = _repo(tmp_path, structure=unique)
    git(repo, "checkout", "--quiet", "-b", "inna-galaz")
    _write(repo, "docs/adr/0002-z-main.md", "# ADR 0002\n")
    git(repo, "update-ref", "refs/remotes/origin/main", commit(repo, "ADR 0002 na main"))
    git(repo, "checkout", "--quiet", "-b", "galaz", "HEAD~1")
    _write(repo, "docs/adr/0002-z-galezi.md", "# ADR 0002\n")
    commit(repo, "ADR 0002 na gałęzi")

    answered = _szybko(repo)

    last = answered.stdout.splitlines()[-1]
    assert (answered.returncode, last) == (1, "SZYBKO FAIL | testy struktury po mergu z origin/main"), answered.stdout


def test_konflikt_z_baza_jest_uwaga_a_nie_porazka(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    git(repo, "checkout", "--quiet", "-b", "inna-galaz")
    _write(repo, "docs/notatka.md", "z main\n")
    git(repo, "update-ref", "refs/remotes/origin/main", commit(repo, "notatka na main"))
    git(repo, "checkout", "--quiet", "-b", "galaz", "HEAD~1")
    _write(repo, "docs/notatka.md", "z gałęzi\n")
    commit(repo, "notatka na gałęzi")

    answered = _szybko(repo)

    assert "UWAGA: merge z origin/main ma konflikt w docs/notatka.md" in answered.stdout
    assert (answered.returncode, answered.stdout.splitlines()[-1]) == (0, "SZYBKO OK"), answered.stdout


def test_blad_typu_tylko_na_windows_wywraca_szybkie_sprawdzenie(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    _write(repo, "src/pakiet/system.py", "import os\n\n\ndef zakoncz(grupa: int) -> None:\n    os.killpg(grupa, 9)\n")

    answered = _szybko(repo)

    # Na Windows zwykły krok mypy też sprawdza Windows, więc pada razem z krokiem dla Windows.
    expected = "SZYBKO FAIL | mypy, mypy (Windows)" if sys.platform == "win32" else "SZYBKO FAIL | mypy (Windows)"
    assert (answered.returncode, answered.stdout.splitlines()[-1]) == (1, expected), answered.stdout


ONLY_NEWER_PYTHON = (
    "from dataclasses import dataclass, field\nfrom types import MappingProxyType\n\n\n"
    "@dataclass(frozen=True)\nclass Ilosci:\n    wartosci: object = field(default=MappingProxyType({}))\n"
)


def _requiring(repo: Path, version: tuple[int, int]) -> None:
    _write(repo, "pyproject.toml", f'[project]\nname = "pakiet"\nrequires-python = ">={version[0]}.{version[1]}"\n\n[tool.mypy]\nfiles = ["src"]\n')
    commit(repo, "requires-python")
    git(repo, "update-ref", "refs/remotes/origin/main", "HEAD")


def test_modul_ktory_nie_importuje_sie_najstarszym_pythonem_wywraca_szybkie_sprawdzenie(tmp_path: Path) -> None:
    if sys.version_info[:2] == (3, 11) or shutil.which("uv") is None:
        pytest.skip("krok biegnie, gdy szybko ma Pythona nowszego niż 3.11 i uv, które da Pythona 3.11")
    repo = _repo(tmp_path)
    _requiring(repo, (3, 11))
    _write(repo, "src/pakiet/ilosci.py", ONLY_NEWER_PYTHON)

    answered = _szybko(repo)

    assert "pakiet.ilosci: ValueError: mutable default" in answered.stdout
    last = answered.stdout.splitlines()[-1]
    assert (answered.returncode, last) == (1, "SZYBKO FAIL | import src pod Pythonem 3.11"), answered.stdout


def test_bez_uv_krok_najstarszego_pythona_pada_z_droga_naprawy(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    _requiring(repo, (3, sys.version_info[1] - 1))
    git_folder = str(Path(shutil.which("git") or "git").parent)
    if shutil.which("uv", path=git_folder):
        pytest.skip("uv leży w tym samym folderze co git")

    answered = subprocess.run(
        [sys.executable, str(repo / "tools" / "szybko.py")],
        cwd=repo,
        env={**os.environ, "PATH": git_folder, "PYTEST_XDIST_AUTO_NUM_WORKERS": "2"},
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )

    oldest = f"3.{sys.version_info[1] - 1}"
    assert f"brak uv, więc szybko nie sprawdzi Pythona {oldest}: zainstaluj uv albo .venv z {oldest}" in answered.stdout
    last = answered.stdout.splitlines()[-1]
    assert (answered.returncode, last) == (1, f"SZYBKO FAIL | import src pod Pythonem {oldest}"), answered.stdout


FAKE_UV = f"""#!{sys.executable}
import os, subprocess, sys
with open(os.environ["WYWOLANIA_UV"], "a", encoding="utf-8") as calls:
    calls.write(("offline" if "--offline" in sys.argv else "online") + "\\n")
if "--offline" in sys.argv and os.environ["CACHE_UV"] == "zimny":
    sys.exit(1)
arguments = sys.argv[1:]
sys.exit(subprocess.run([sys.executable, *arguments[arguments.index("python") + 1 :]]).returncode)
"""


@pytest.mark.parametrize(("cache", "calls"), [("ciepły", ["offline"]), ("zimny", ["offline", "online"])])
def test_uv_pyta_siec_tylko_bez_cache_a_modul_ktory_sie_nie_importuje_wywraca_krok(
    tmp_path: Path, cache: str, calls: list[str]
) -> None:
    repo = _repo(tmp_path)
    _requiring(repo, (3, sys.version_info[1] - 1))
    _write(repo, "src/pakiet/stary.py", "raise ImportError('tylko na nowszym Pythonie')\n")
    fake = tmp_path / "bin" / "uv"
    fake.parent.mkdir()
    fake.write_text(FAKE_UV, encoding="utf-8")
    fake.chmod(0o755)
    log = tmp_path / "wywolania.txt"

    answered = subprocess.run(
        [sys.executable, str(repo / "tools" / "szybko.py")],
        cwd=repo,
        env={**os.environ, "PATH": f"{fake.parent}{os.pathsep}{os.environ['PATH']}", "WYWOLANIA_UV": str(log), "CACHE_UV": cache},
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )

    assert log.read_text(encoding="utf-8").split() == calls
    assert "pakiet.stary: ImportError: tylko na nowszym Pythonie" in answered.stdout
    last = answered.stdout.splitlines()[-1]
    assert (answered.returncode, last) == (1, f"SZYBKO FAIL | import src pod Pythonem 3.{sys.version_info[1] - 1}"), answered.stdout


def test_requires_python_bez_najstarszej_wersji_wywraca_szybkie_sprawdzenie(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    _write(repo, "pyproject.toml", '[project]\nname = "pakiet"\nrequires-python = "~=3.11"\n\n[tool.mypy]\nfiles = ["src"]\n')
    commit(repo, "requires-python")
    git(repo, "update-ref", "refs/remotes/origin/main", "HEAD")

    answered = _szybko(repo)

    assert "requires-python '~=3.11' nie ma postaci >=X.Y" in answered.stdout
    last = answered.stdout.splitlines()[-1]
    assert (answered.returncode, last) == (1, "SZYBKO FAIL | import src pod najstarszym Pythonem"), answered.stdout


def test_szybko_na_najstarszym_pythonie_nie_ma_osobnego_kroku_importu(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    _requiring(repo, sys.version_info[:2])

    answered = _szybko(repo)

    assert "import src pod Pythonem" not in answered.stdout
    assert (answered.returncode, answered.stdout.splitlines()[-1]) == (0, "SZYBKO OK"), answered.stdout


def test_nieznana_baza_konczy_sie_jedna_linia_wyniku(tmp_path: Path) -> None:
    repo = _repo(tmp_path)

    answered = _szybko(repo, "--baza", "nie-ma-takiej")

    assert (answered.returncode, answered.stdout.splitlines()) == (1, ["SZYBKO FAIL | nieznana baza nie-ma-takiej"])


def test_kazdy_test_z_tabeli_regul_w_agents_md_jest_testem_struktury_albo_ma_powod() -> None:
    table = (ROOT / "AGENTS.md").read_text(encoding="utf-8").split("## Reguły i co ich pilnuje", 1)[1]
    guards = [line.rsplit("|", 2)[-2] for line in table.splitlines() if line.startswith("|")]
    named = {path for guard in guards for path in re.findall(r"tests/test_\w+\.py", guard)}
    structure = {node.partition("::")[0] for node in szybko.STRUCTURE}

    collected = subprocess.run(
        [sys.executable, "-m", "pytest", "--collect-only", "-q", "-p", "no:cacheprovider", *szybko.STRUCTURE],
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )

    undecided = named - structure - BY_CHANGE_ONLY.keys()
    assert undecided == set(), "dopisz test do STRUCTURE w tools/szybko.py albo powód do BY_CHANGE_ONLY"
    assert BY_CHANGE_ONLY.keys() - named == set(), "BY_CHANGE_ONLY ma test spoza tabeli"
    assert collected.returncode == 0, collected.stdout

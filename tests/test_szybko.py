"""``tools/szybko.py`` sprawdza zmianę w sekundach: ruff, mypy dla obu systemów, testy struktury i testy dotknięte zmianą.

Każdy test buduje małe repozytorium z narzędziami checkoutu i gałęzią ``origin/main``. ``tests/test_b.py`` w nim
zawsze pada, więc szybkie sprawdzenie, które go uruchomi, choć zmiana go nie dotyka, kończy się porażką.
"""

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
    "tests/test_b.py": "from pakiet.b import inna\n\n\ndef test_niedotkniety() -> None:\n    assert inna() == 2\n",
    "tools/narzedzie.py": "print('wynik')\n",
    "tests/test_narzedzie.py": (
        "from pathlib import Path\nimport subprocess\nimport sys\n\n"
        "TOOL = Path(__file__).resolve().parents[1] / 'tools' / 'narzedzie.py'\n\n\n"
        "def test_narzedzie() -> None:\n"
        "    done = subprocess.run([sys.executable, str(TOOL)], capture_output=True, text=True, check=True)\n"
        "    assert done.stdout == 'wynik\\n'\n"
    ),
    "docs/dane/wpis.md": "zgodny\n",
    "tests/test_dane.py": (
        "from pathlib import Path\n\nDANE = Path(__file__).resolve().parents[1] / 'docs' / 'dane'\n\n\n"
        "def test_dane() -> None:\n    assert [p.read_text() for p in DANE.glob('*.md')] == ['zgodny\\n']\n"
    ),
}


def _structure_stubs(body: str) -> dict[str, str]:
    stubs: dict[str, str] = {}
    for node in szybko.STRUCTURE:
        path, _, name = node.partition("::")
        header = "from pathlib import Path\n" if "Path(" in body else ""
        stubs[path] = stubs.get(path, header) + f"\n\ndef {name or 'test_struktura'}() -> None:\n    {body}\n"
    return stubs


def _repo(tmp_path: Path, structure: str = "pass") -> Path:
    repo = repository(tmp_path / "repo", {**BASE_FILES, **_structure_stubs(structure)})
    for name in (".gitignore", "tools/szybko.py"):
        shutil.copy2(ROOT / name, repo / name)
    commit(repo, "baza")
    git(repo, "update-ref", "refs/remotes/origin/main", "HEAD")
    return repo


def _szybko(repo: Path, *arguments: str, runs: Path | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(repo / "tools" / "szybko.py"), *arguments],
        cwd=repo,
        env={**os.environ, "PYTEST_XDIST_AUTO_NUM_WORKERS": "2", "PRZEBIEGI": str(runs)},
        capture_output=True,
        text=True,
        encoding="utf-8",
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
    assert "test_b" not in answered.stdout


def test_zmiana_bez_bledu_konczy_sie_ok_choc_niedotkniety_test_pada(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    _write(repo, "src/pakiet/a.py", "def wartosc() -> int:\n    return 0 + 1\n")

    answered = _szybko(repo)

    assert (answered.returncode, answered.stdout.splitlines()[-1]) == (0, "SZYBKO OK"), answered.stdout


COUNTED = (
    "import os\nfrom pathlib import Path\n\nfrom pakiet.posredni import podwojona\n\n\n"
    "def test_podwojona() -> None:\n"
    "    with Path(os.environ['PRZEBIEGI']).open('a', encoding='utf-8') as runs:\n"
    "        runs.write('.')\n"
    "    assert podwojona() == 2\n"
)


def test_zielony_test_biegnie_znowu_dopiero_po_zmianie_pliku_od_ktorego_zalezy(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    runs = tmp_path / "przebiegi"
    _write(repo, "tests/test_posredni.py", COUNTED)
    first, again = _szybko(repo, runs=runs), _szybko(repo, runs=runs)
    _write(repo, "src/pakiet/a.py", "def wartosc() -> int:\n    return 2 - 1\n")
    after_change = _szybko(repo, runs=runs)

    assert [answered.stdout.splitlines()[-1] for answered in (first, again, after_change)] == ["SZYBKO OK"] * 3
    assert runs.read_text(encoding="utf-8") == ".."


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
    [("tools/narzedzie.py", "tests/test_narzedzie.py::test_narzedzie"), ("docs/dane/wpis.md", "tests/test_dane.py::test_dane")],
    ids=["skrypt, który test uruchamia", "plik katalogu, który test czyta"],
)
def test_test_jest_dotkniety_zmiana_pliku_ktory_wskazuje_sciezka(tmp_path: Path, changed: str, failing: str) -> None:
    repo = _repo(tmp_path)
    _write(repo, changed, "print('inny')\n")

    answered = _szybko(repo)

    assert f"FAILED {failing}" in answered.stdout
    assert "test_b" not in answered.stdout


@pytest.mark.parametrize("changed", ["pyproject.toml", "requirements.txt", "tests/conftest.py"])
def test_zmiana_konfiguracji_albo_conftest_uruchamia_pelny_zestaw(tmp_path: Path, changed: str) -> None:
    repo = _repo(tmp_path)
    with (repo / changed).open("a", encoding="utf-8") as file:
        file.write("\n")

    answered = _szybko(repo)

    assert "FAILED tests/test_b.py::test_niedotkniety" in answered.stdout
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

    assert (answered.returncode, answered.stdout.splitlines()[-1]) == (1, "SZYBKO FAIL | testy struktury po mergu z origin/main")


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

    assert (answered.returncode, answered.stdout.splitlines()[-1]) == (1, "SZYBKO FAIL | mypy (Windows)"), answered.stdout


def test_nieznana_baza_konczy_sie_jedna_linia_wyniku(tmp_path: Path) -> None:
    repo = _repo(tmp_path)

    answered = _szybko(repo, "--baza", "nie-ma-takiej")

    assert (answered.returncode, answered.stdout.splitlines()) == (1, ["SZYBKO FAIL | nieznana baza nie-ma-takiej"])


def test_testy_struktury_to_istniejace_testy_regul_z_tabeli_w_agents_md() -> None:
    table = (ROOT / "AGENTS.md").read_text(encoding="utf-8").split("## Reguły i co ich pilnuje", 1)[1]
    guards = [line.rsplit("|", 2)[-2] for line in table.splitlines() if line.startswith("|")]
    named = {path for guard in guards for path in re.findall(r"tests/test_\w+\.py", guard)}

    collected = subprocess.run(
        [sys.executable, "-m", "pytest", "--collect-only", "-q", "-p", "no:cacheprovider", *szybko.STRUCTURE],
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )

    assert {node.partition("::")[0] for node in szybko.STRUCTURE} == named
    assert collected.returncode == 0, collected.stdout

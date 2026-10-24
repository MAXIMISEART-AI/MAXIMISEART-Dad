"""``tools/mutacje_zmiany.py`` psuje zmienione linie ``src/`` i pada, gdy żaden test tego nie widzi.

Przebiegi idą w małym repozytorium z narzędziami checkoutu: baza ma ``return a``, zmiana ``return a and b``.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

import pytest

from tests.fixtures.git_repo import commit, git, repository

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

from mutacje_zmiany import Hunk, exceptions, mutants  # noqa: E402

MODULE = "src/rozliczenia/warunek.py"
BASE = 'def oba(a: bool, b: bool) -> bool:\n    return a\n'
CHANGED = 'def oba(a: bool, b: bool) -> bool:\n    return a and b\n'
ONE_CASE = "from rozliczenia.warunek import oba\n\n\ndef test_oba() -> None:\n    assert oba(True, True) is True\n"
ALL_CASES = (
    "from rozliczenia.warunek import oba\n\n\n"
    "def test_oba() -> None:\n"
    "    assert oba(True, True) is True\n"
    "    assert oba(True, False) is False\n"
    "    assert oba(False, True) is False\n"
)


def _repo(tmp_path: Path, test: str, changed: str = CHANGED) -> Path:
    repo = repository(tmp_path, {"src/rozliczenia/__init__.py": "", MODULE: BASE, "tests/test_warunek.py": test})
    for name in ("szybko.py", "mutacje_zmiany.py", "pokrycie_linii.py"):
        shutil.copy2(ROOT / "tools" / name, repo / "tools" / name)
    commit(repo, "baza")
    git(repo, "branch", "--quiet", "baza")
    (repo / MODULE).write_text(changed, encoding="utf-8")
    return repo


def _run(repo: Path, *arguments: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(repo / "tools" / "mutacje_zmiany.py"), "--baza", "baza", "--rownolegle", "2", *arguments],
        cwd=repo,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=300,
        check=False,
    )


def test_zmiana_bez_testu_ktory_ja_widzi_konczy_sie_fail_z_nazwa_mutacji(tmp_path: Path) -> None:
    done = _run(_repo(tmp_path, ONE_CASE))

    assert done.returncode == 1, done.stdout + done.stderr
    survived = [line for line in done.stdout.splitlines() if line.startswith("NIEWYKRYTA")]
    assert any("warunek.py:2 bez `b` w `and`" in line for line in survived), done.stdout
    assert any("warunek.py:2 zmiana linii 2 cofnięta do bazy" in line for line in survived), done.stdout
    assert done.stdout.splitlines()[-1].startswith("MUTACJE ZMIANY FAIL | przeżyło")


def test_zmiana_z_testami_ktore_widza_kazda_mutacje_konczy_sie_ok(tmp_path: Path) -> None:
    done = _run(_repo(tmp_path, ALL_CASES))

    assert done.returncode == 0, done.stdout + done.stderr
    assert "NIEWYKRYTA" not in done.stdout
    assert done.stdout.splitlines()[-1] == "MUTACJE ZMIANY OK | mutacje=4 | wyjątki=0"


def test_czesci_dziela_mutacje_miedzy_siebie(tmp_path: Path) -> None:
    repo = _repo(tmp_path, ONE_CASE)

    parts = [_run(repo, "--czesc", f"{number}/2") for number in (1, 2)]

    names = [{line.split(" → ")[0].split(": ", 1)[1] for line in done.stdout.splitlines() if "WYKRYTA: " in line} for done in parts]
    assert len(names[0]) == len(names[1]) == 2, [done.stdout for done in parts]
    assert not names[0] & names[1]


def test_wyjatek_w_linii_mutacji_ja_pomija_a_wygasly_juz_nie(tmp_path: Path) -> None:
    allowed = CHANGED.replace("a and b\n", "a and b  # mutacje-zmiany: tylko na próbę | do 2999-01-01 | zgoda Maks\n")
    expired = CHANGED.replace("a and b\n", "a and b  # mutacje-zmiany: tylko na próbę | do 2000-01-01 | zgoda Maks\n")

    excused = _run(_repo(tmp_path / "wazny", ONE_CASE, allowed))
    stale = _run(_repo(tmp_path / "wygasly", ONE_CASE, expired))

    assert excused.returncode == 0, excused.stdout + excused.stderr
    assert "WYJĄTEK: src/rozliczenia/warunek.py:2 bez `b` w `and` (tylko na próbę, do 2999-01-01, zgoda Maks)" in excused.stdout
    assert stale.returncode == 1, stale.stdout + stale.stderr


def test_testy_ktore_padaja_bez_mutacji_koncza_sie_bez_werdyktu_mutacji(tmp_path: Path) -> None:
    done = _run(_repo(tmp_path, ONE_CASE.replace("is True", "is False")))

    assert done.returncode == 2, done.stdout + done.stderr
    assert "NIEWYKRYTA" not in done.stdout and "WYKRYTA" not in done.stdout


def test_zmiana_poza_src_nie_daje_mutacji(tmp_path: Path) -> None:
    repo = _repo(tmp_path, ONE_CASE, BASE)
    (repo / "tools" / "inne.py").write_text("def f(a: bool, b: bool) -> bool:\n    return a and b\n", encoding="utf-8")

    done = _run(repo)

    assert done.returncode == 0, done.stdout + done.stderr
    assert done.stdout.splitlines()[-1] == "MUTACJE ZMIANY OK | brak mutacji zmienionych linii src/ od baza"


def _described(text: str, changed: list[int], old: tuple[str, ...] = ()) -> dict[str, str]:
    hunks = [Hunk(line, 1, old if index == 0 else ()) for index, line in enumerate(changed)]
    return {mutant.description: mutant.source for mutant in mutants("m.py", text, hunks)}


@pytest.mark.parametrize(
    ("code", "description", "mutated"),
    [
        ("x = a or b\n", "bez `a` w `or`", "x = (b)\n"),
        ("x = a if w else b\n", "`a if w else b` zawsze `a`", "x = (a)\n"),
        ("f(zamkniete=True)\n", "`True` → `False`", "f(zamkniete=False)\n"),
        ("if w:\n    f()\n", "warunek `w` zawsze `False`", "if False:\n    f()\n"),
        ("x = a > b\n", "granica `a > b` → `>=`", "x = (a >= b)\n"),
        ("def f():\n    return wynik\n", "`return wynik` → `return None`", "def f():\n    return None\n"),
        ("zapisz(plik)\n", "bez wywołania `zapisz(plik)`", "pass\n"),
        ("klucz = (a.etykieta, a.kod)\n", "krotka bez `a.kod`", "klucz = (a.etykieta,)\n"),
    ],
)
def test_kazdy_rodzaj_mutacji_psuje_zmieniona_linie(code: str, description: str, mutated: str) -> None:
    lines = list(range(1, code.count("\n") + 1))

    assert _described(code, lines)[description] == mutated


def test_niezmieniona_linia_nie_dostaje_mutacji() -> None:
    assert _described("x = a or b\ny = c or d\n", [2]).keys() == {"bez `c` w `or`", "bez `d` w `or`", "zmiana linii 2 cofnięta do bazy"}


def test_mutacja_trafia_w_wezel_za_polskimi_znakami_w_tej_samej_linii() -> None:
    code = 'x = f("żółć") or zażółć\n'

    assert _described(code, [1])["bez `zażółć` w `or`"] == 'x = (f("żółć"))\n'


def test_cofniecie_fragmentu_przywraca_linie_bazy() -> None:
    code = 'def f(s: str) -> bool:\n    return NAGLOWEK_LINII.search(s) is not None\n'

    reverted = _described(code, [2], ("    return NAGLOWEK in s",))["zmiana linii 2 cofnięta do bazy"]

    assert reverted == "def f(s: str) -> bool:\n    return NAGLOWEK in s\n"


def test_cofniecie_samego_docstringu_komentarza_albo_importu_nie_jest_mutacja() -> None:
    code = '"""Nowy opis."""\n\nfrom a import b, c  # nowy komentarz\n\nx = 1\n'

    old = ('"""Stary opis."""', "", "from a import b")

    assert _described(code, [1, 2, 3], old) == {}


def test_cofniecie_samej_adnotacji_albo_aliasu_typu_nie_jest_mutacja() -> None:
    code = "Odbiorca = Callable[[str], bool] | None\n\n\ndef f(x: int) -> dict[str, str | int]:\n    return {}\n"

    old = ("def f(x: int) -> dict[str, str]:",)

    assert [d for d in _described(code, [1, 4], ()) if "cofnięta" in d] == []
    assert [d for d in _described(code, [4], old) if "cofnięta" in d] == []


def test_dekorator_nie_dostaje_mutacji() -> None:
    assert [d for d in _described("@dataclass(frozen=True)\nclass A:\n    x: int\n", [1]) if "cofnięta" not in d] == []


def test_adnotacje_i_docstringi_nie_dostaja_mutacji() -> None:
    code = 'def f(x: tuple[int, str] | None = None) -> bool:\n    """Opis."""\n'

    assert [description for description in _described(code, [1, 2]) if "cofnięta" not in description] == []


def test_wyjatek_w_samodzielnym_komentarzu_dotyczy_linii_pod_nim() -> None:
    code = "# mutacje-zmiany: to samo | do 2026-12-31 | zgoda Maks\nx = a or b\ny = 1  # mutacje-zmiany: inne | do 2027-01-31 | zgoda Maks\n"

    found = exceptions(code, "m.py")

    assert sorted(found) == [2, 3]
    assert (found[2].reason, str(found[2].until), found[2].who) == ("to samo", "2026-12-31", "Maks")


@pytest.mark.parametrize("comment", ["# mutacje-zmiany: bez terminu", "# mutacje-zmiany: powód | do 2026-13-01 | zgoda Maks"])
def test_wyjatek_w_zlej_postaci_nazywa_plik_i_linie(comment: str) -> None:
    with pytest.raises(ValueError, match=r"^m\.py:2: "):
        exceptions(f"x = 1\ny = 2  {comment}\n", "m.py")


def test_pokrycie_przypisuje_zmieniona_linie_testom_ktore_ja_wykonuja_takze_w_watku(tmp_path: Path) -> None:
    module = tmp_path / "modul.py"
    module.write_text(
        "import threading\n\n\n"
        "def w_watku() -> None:\n"
        "    x = 1\n\n\n"
        "def wprost() -> int:\n"
        "    return 2\n\n\n"
        "def watek() -> None:\n"
        "    t = threading.Thread(target=w_watku)\n"
        "    t.start()\n"
        "    t.join()\n",
        encoding="utf-8",
    )
    (tmp_path / "test_modul.py").write_text(
        "import modul\n\n\ndef test_wprost() -> None:\n    modul.wprost()\n\n\ndef test_watek() -> None:\n    modul.watek()\n",
        encoding="utf-8",
    )
    found = tmp_path / "wynik"
    found.mkdir()
    settings = {"linie": {str(module): [5, 9]}, "wynik": str(found)}
    done = subprocess.run(
        [sys.executable, "-m", "pytest", "-q", "-p", "pokrycie_linii", "-p", "no:cacheprovider", "test_modul.py"],
        cwd=tmp_path,
        env={**os.environ, "PYTHONPATH": os.pathsep.join([str(ROOT / "tools"), str(tmp_path)]), "POKRYCIE_LINII": json.dumps(settings)},
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=120,
        check=False,
    )

    assert done.returncode == 0, done.stdout + done.stderr
    [written] = found.iterdir()
    assert json.loads(written.read_text(encoding="utf-8")) == {
        "test_modul.py::test_wprost": {str(module): [9]},
        "test_modul.py::test_watek": {str(module): [5]},
    }

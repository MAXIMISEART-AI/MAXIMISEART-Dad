"""``tools/mutacje_zmiany.py`` psuje zmienione linie ``src/`` i pada, gdy żaden test tego nie widzi.

Przebiegi idą w małym repozytorium z narzędziami checkoutu: baza ma ``return a``, zmiana ``return a and b``.
"""

from __future__ import annotations

import datetime
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

from mutacje_zmiany import Hunk, exceptions, mutants, selected  # noqa: E402
import pokrycie_procesu  # noqa: E402

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


def _repo(tmp_path: Path, test: str, changed: str = CHANGED, base: str = BASE, conftest: str = "", other: str = "") -> Path:
    files = {".gitignore": "__pycache__/\n", "src/rozliczenia/__init__.py": "", MODULE: base, "tests/test_warunek.py": test}
    if conftest:
        files["tests/conftest.py"] = conftest
    if other:
        files["src/rozliczenia/inny.py"] = other
    repo = repository(tmp_path, files)
    for name in ("szybko.py", "mutacje_zmiany.py", "pokrycie_linii.py", "pokrycie_procesu.py"):
        shutil.copy2(ROOT / "tools" / name, repo / "tools" / name)
    commit(repo, "baza")
    git(repo, "branch", "--quiet", "baza")
    (repo / MODULE).write_text(changed, encoding="utf-8")
    return repo


def _run(repo: Path, *arguments: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(repo / "tools" / "mutacje_zmiany.py"), "--baza", "baza", "--rownolegle", "2", *arguments],
        cwd=repo,
        # Jeden worker xdist: testy biegną w kolejności z pliku, więc fixture sesji ustawia zawsze pierwszy z nich.
        # Narzędzie biegnie jak w zadaniu CI, bo poza nim odmawia startu (tools/ciezkie_ci.py).
        env={**os.environ, "PYTEST_XDIST_AUTO_NUM_WORKERS": "1", "GITHUB_ACTIONS": "true"},
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=300,
        check=False,
    )


def test_zmiana_bez_testu_ktory_ja_widzi_konczy_sie_fail_z_nazwa_mutacji_takze_w_zapisie_dla_scal_pr(tmp_path: Path) -> None:
    record = tmp_path / "zapis" / "czesc.json"

    done = _run(_repo(tmp_path / "repo", ONE_CASE), "--zapis", str(record))

    assert done.returncode == 1, done.stdout + done.stderr
    survived = [line.removeprefix("NIEWYKRYTA: ").partition(" → ")[0] for line in done.stdout.splitlines() if line.startswith("NIEWYKRYTA")]
    assert sorted(survived) == ["src/rozliczenia/warunek.py:2 bez `b` w `and`", "src/rozliczenia/warunek.py:2 zmiana linii 2 cofnięta do bazy"]
    assert done.stdout.splitlines()[-1].startswith("MUTACJE ZMIANY FAIL | przeżyło 2")
    written = json.loads(record.read_text(encoding="utf-8"))
    assert (written["czesc"], written["wynik"], sorted(written["przezyte"])) == ("1/1", done.stdout.splitlines()[-1], sorted(survived))


def test_zmiana_z_testami_ktore_widza_kazda_mutacje_konczy_sie_ok(tmp_path: Path) -> None:
    done = _run(_repo(tmp_path, ALL_CASES))

    assert done.returncode == 0, done.stdout + done.stderr
    assert "NIEWYKRYTA" not in done.stdout
    assert done.stdout.splitlines()[-1] == "MUTACJE ZMIANY OK | mutacje=2 | wyjątki=0 | innego systemu=0"


def test_czesci_dziela_mutacje_miedzy_siebie(tmp_path: Path) -> None:
    repo = _repo(tmp_path, ONE_CASE)

    parts = [_run(repo, "--czesc", f"{number}/2") for number in (1, 2)]

    names = [{line.split(" → ")[0].split(": ", 1)[1] for line in done.stdout.splitlines() if "WYKRYTA: " in line} for done in parts]
    assert len(names[0]) == len(names[1]) == 1, [done.stdout for done in parts]
    assert not names[0] & names[1]


def test_wyjatek_w_linii_mutacji_ja_pomija_a_wygasly_juz_nie(tmp_path: Path) -> None:
    allowed = CHANGED.replace("a and b\n", "a and b  # mutacje-zmiany: tylko na próbę | do 2999-01-01 | zgoda Maks\n")
    expired = CHANGED.replace("a and b\n", "a and b  # mutacje-zmiany: tylko na próbę | do 2000-01-01 | zgoda Maks\n")

    excused = _run(_repo(tmp_path / "wazny", ONE_CASE, allowed))
    stale = _run(_repo(tmp_path / "wygasly", ONE_CASE, expired))

    assert excused.returncode == 0, excused.stdout + excused.stderr
    assert "WYJĄTEK: src/rozliczenia/warunek.py:2 bez `b` w `and` (tylko na próbę, do 2999-01-01, zgoda Maks)" in excused.stdout
    assert stale.returncode == 1, stale.stdout + stale.stderr


def test_mutacje_kodu_sprawdzanego_tylko_w_podprocesie_wykrywa_juz_pierwszy_przebieg(tmp_path: Path) -> None:
    base = BASE + "\n\ndef dwa() -> int:\n    return 1\n"
    changed = CHANGED + "\n\ndef dwa() -> int:\n    return 2\n"
    in_subprocess = (
        "import subprocess\nimport sys\n\n\n"
        "def test_z_podprocesu() -> None:\n"
        "    code = 'from rozliczenia.warunek import dwa; assert dwa() == 2'\n"
        "    subprocess.run([sys.executable, '-c', code], check=True)\n"
    )

    tests = "import subprocess\nimport sys\n" + ALL_CASES + "\n\n" + in_subprocess.replace("import subprocess\nimport sys\n\n\n", "")

    done = _run(_repo(tmp_path, tests, changed, base))

    assert done.returncode == 0, done.stdout + done.stderr
    found = next(line for line in done.stdout.splitlines() if "warunek.py:6 `return 2` → `return None`" in line)
    # Tylko test podprocesu: pozostałe testy pliku (``test_oba``) w pierwszym przebiegu nie biegną.
    assert found.startswith("WYKRYTA: ") and "→ 1 failed in" in found, done.stdout


def test_mutacje_kodu_w_procesie_z_flaga_izolacji_wykrywa_test_ktory_go_uruchomil(tmp_path: Path) -> None:
    base = BASE + "\n\ndef dwa() -> int:\n    return 1\n"
    changed = CHANGED + "\n\ndef dwa() -> int:\n    return 2\n"
    isolated = (
        "\n\ndef test_dwa_w_izolowanym_procesie() -> None:\n"
        "    code = 'import sys; sys.path.insert(0, \"src\"); from rozliczenia.warunek import dwa; assert dwa() == 2'\n"
        "    subprocess.run([sys.executable, '-I', '-c', code], check=True)\n"
    )

    done = _run(_repo(tmp_path, "import subprocess\nimport sys\n" + ALL_CASES + isolated, changed, base))

    assert done.returncode == 0, done.stdout + done.stderr
    assert "WYKRYTA: src/rozliczenia/warunek.py:6 `return 2` → `return None`" in done.stdout


def test_mutacje_stalej_modulu_wykrywa_test_innego_modulu_ktory_ja_czyta_przy_imporcie(tmp_path: Path) -> None:
    base = "LIMIT = 3\n\n\ndef nazwa() -> str:\n    return 'a'\n"
    other = "from rozliczenia.warunek import LIMIT\n\n\ndef duze(n: int) -> bool:\n    return n > LIMIT\n"
    changed = base.replace("LIMIT = 3", "LIMIT = 5").replace("return 'a'", "return 'b'")
    tests = (
        "from rozliczenia.inny import duze\nfrom rozliczenia.warunek import nazwa\n\n\n"
        "def test_nazwa() -> None:\n    assert nazwa() == 'b'\n\n\n"
        "def test_duze() -> None:\n    assert duze(4) is False\n    assert duze(6) is True\n"
    )

    done = _run(_repo(tmp_path, tests, changed, base, other=other))

    assert done.returncode == 0, done.stdout + done.stderr
    assert "WYKRYTA: src/rozliczenia/warunek.py:1 zmiana linii 1 cofnięta do bazy" in done.stdout


def test_mutacje_kodu_fixture_sesji_wykrywa_test_ktory_tylko_dostal_jej_wynik(tmp_path: Path) -> None:
    base = "def wartosc() -> int:\n    return 1\n\n\ndef inna() -> int:\n    return 7\n"
    conftest = "import pytest\n\nfrom rozliczenia.warunek import wartosc\n\n\n@pytest.fixture(scope='session')\ndef liczba() -> int:\n    return wartosc()\n"
    tests = (
        "from rozliczenia.warunek import inna\n\n\n"
        "def test_inna() -> None:\n    assert inna() == 7\n\n\n"
        "def test_typ(liczba: int) -> None:\n    assert isinstance(liczba, int)\n\n\n"
        "def test_wartosc(liczba: int) -> None:\n    assert liczba == 2\n"
    )

    done = _run(_repo(tmp_path, tests, base.replace("return 1", "return 2"), base, conftest))

    assert done.returncode == 0, done.stdout + done.stderr
    assert "WYKRYTA: src/rozliczenia/warunek.py:2 zmiana linii 2 cofnięta do bazy" in done.stdout


def test_cofniecie_przywraca_usunieta_linie_zaczynajaca_sie_od_dwoch_minusow(tmp_path: Path) -> None:
    base = 'TEKST = """\n-- stare\n"""\n'
    tests = "from rozliczenia.warunek import TEKST\n\n\ndef test_tekst() -> None:\n    assert '-- stare' not in TEKST\n"

    done = _run(_repo(tmp_path, tests, base.replace("-- stare", "nowe"), base))

    assert done.returncode == 0, done.stdout + done.stderr
    assert "WYKRYTA: src/rozliczenia/warunek.py:2 zmiana linii 2 cofnięta do bazy" in done.stdout


def test_przeniesiony_plik_bez_zmian_nie_daje_mutacji(tmp_path: Path) -> None:
    repo = _repo(tmp_path, ONE_CASE, BASE)
    git(repo, "mv", MODULE, "src/rozliczenia/przeniesiony.py")

    done = _run(repo)

    assert done.returncode == 0, done.stdout + done.stderr
    assert done.stdout.splitlines()[-1] == "MUTACJE ZMIANY OK | brak mutacji zmienionych linii src/ od baza"


def test_plik_bez_zaleznych_testow_konczy_sie_fail(tmp_path: Path) -> None:
    repo = _repo(tmp_path, "def test_nic() -> None:\n    pass\n")

    done = _run(repo)

    assert done.returncode == 1, done.stdout + done.stderr
    assert "żaden test nie zależy od src/rozliczenia/warunek.py" in done.stdout


def test_wyjatek_nad_fragmentem_obejmuje_jego_cofniecie(tmp_path: Path) -> None:
    comment = "    # mutacje-zmiany: tylko na próbę | do 2999-01-01 | zgoda Maks\n"
    changed = CHANGED.replace("    return a and b\n", comment + "    return a and b\n")

    done = _run(_repo(tmp_path, ONE_CASE, changed))

    assert done.returncode == 0, done.stdout + done.stderr
    assert "WYJĄTEK: src/rozliczenia/warunek.py:2 zmiana linii 2–3 cofnięta do bazy" in done.stdout


def test_wyjatek_w_srodku_fragmentu_nie_obejmuje_cofniecia_calego_fragmentu(tmp_path: Path) -> None:
    base = "def oba(a, b):\n    return a\n"
    changed = CHANGED.replace("a and b\n", "a and b  # mutacje-zmiany: tylko na próbę | do 2999-01-01 | zgoda Maks\n")

    done = _run(_repo(tmp_path, ONE_CASE, changed, base))

    assert done.returncode == 1, done.stdout + done.stderr
    assert "NIEWYKRYTA: src/rozliczenia/warunek.py:1 zmiana linii 1–2 cofnięta do bazy" in done.stdout


def test_nowy_niesledzony_plik_dostaje_mutacje(tmp_path: Path) -> None:
    repo = _repo(tmp_path, ONE_CASE, BASE)
    (repo / "src" / "rozliczenia" / "nowy.py").write_text("def jeden(a: bool) -> bool:\n    return a or False\n", encoding="utf-8")

    done = _run(repo)

    assert done.returncode == 1, done.stdout + done.stderr
    assert "NIEWYKRYTA: src/rozliczenia/nowy.py:2 `False` → `True` → żaden test nie zależy od src/rozliczenia/nowy.py" in done.stdout


def test_wyjatek_obowiazuje_jeszcze_w_dniu_terminu(tmp_path: Path) -> None:
    today = datetime.datetime.now(datetime.UTC).date()
    changed = CHANGED.replace("a and b\n", f"a and b  # mutacje-zmiany: tylko na próbę | do {today} | zgoda Maks\n")

    done = _run(_repo(tmp_path, ALL_CASES.replace("    assert oba(True, False) is False\n", ""), changed))

    assert done.returncode == 0, done.stdout + done.stderr
    assert f"WYJĄTEK: src/rozliczenia/warunek.py:2 bez `b` w `and` (tylko na próbę, do {today}, zgoda Maks)" in done.stdout


def test_galaz_innego_systemu_jest_pominieta_a_nie_niewykryta(tmp_path: Path) -> None:
    other = "nt" if sys.platform != "win32" else "posix"
    branch = "if sys.platform == 'win32':" if sys.platform != "win32" else "if sys.platform != 'win32':"
    base = f"import sys\n\n{branch}\n    SYSTEM = 'stary'\n"
    changed = base.replace("'stary'", f"'{other}'")

    done = _run(_repo(tmp_path, "import rozliczenia.warunek\n\n\ndef test_import() -> None:\n    pass\n", changed, base))

    assert done.returncode == 0, done.stdout + done.stderr
    assert f"POMINIĘTA: src/rozliczenia/warunek.py:4 zmiana linii 4 cofnięta do bazy → kod innego systemu niż {sys.platform}" in done.stdout
    assert done.stdout.splitlines()[-1].endswith("innego systemu=1")


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


def test_biegnie_kazde_cofniecie_fragmentu_i_jedna_mutacja_linii_z_jej_najglebszego_wezla() -> None:
    code = "def f(a, b, c):\n    if a and b:\n        return c > 1\n    zapisz(a)\n    return (a, b)\n"
    hunks = [Hunk(2, 2, ("    if a:", "        return c")), Hunk(5, 1, ("    return a",))]

    every = mutants("m.py", code, hunks)
    chosen = [(mutant.line, mutant.description) for mutant in selected("m.py", code, hunks)]

    assert chosen == [
        (2, "bez `b` w `and`"),
        (2, "zmiana linii 2–3 cofnięta do bazy"),
        (3, "granica `c > 1` → `>=`"),
        (5, "krotka bez `b`"),
        (5, "zmiana linii 5 cofnięta do bazy"),
    ]
    assert len(every) > len(chosen)
    assert {mutant.line for mutant in every if not mutant.revert} == {line for line, description in chosen if "cofnięta" not in description}


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


def test_gałąź_innego_systemu_i_jej_warunek_sa_oznaczone() -> None:
    code = "import sys\n\nif sys.platform == 'win32':\n    x = a or b\nelse:\n    y = c or d\n"
    hunks = [Hunk(line, 1, ()) for line in (3, 4, 6)]

    def other(platform: str) -> dict[str, bool]:
        return {m.description: m.other_system for m in mutants("m.py", code, hunks, platform) if "cofnięta" not in m.description}

    assert other("linux") == {
        "warunek `sys.platform == 'win32'` zawsze `True`": True,
        "warunek `sys.platform == 'win32'` zawsze `False`": True,
        "bez `a` w `or`": True,
        "bez `b` w `or`": True,
        "bez `c` w `or`": False,
        "bez `d` w `or`": False,
    }
    assert {d for d, flag in other("win32").items() if flag} == {
        "warunek `sys.platform == 'win32'` zawsze `True`",
        "warunek `sys.platform == 'win32'` zawsze `False`",
        "bez `c` w `or`",
        "bez `d` w `or`",
    }


@pytest.mark.parametrize(
    "code",
    [
        "x = (a or b) if sys.platform == 'win32' else c\n",
        "def f():\n    if sys.platform != 'win32':\n        return None\n    return a or b\n",
        "if sys.platform == 'darwin':\n    x = a or b\n",
    ],
)
def test_kod_innego_systemu_w_kazdej_postaci_jest_oznaczony(code: str) -> None:
    hunks = [Hunk(line, 1, ()) for line in range(1, code.count("\n") + 1)]
    runs_on = "win32" if "win32" in code else "darwin"

    def flagged(platform: str) -> set[str]:
        return {m.description for m in mutants("m.py", code, hunks, platform) if m.other_system and "w `or`" in m.description}

    assert flagged("linux") == {"bez `a` w `or`", "bez `b` w `or`"}
    assert flagged(runs_on) == set()


def test_cofniecie_fragmentu_gałęzi_windows_z_komentarzem_jest_oznaczone() -> None:
    code = "if sys.platform == 'win32':\n    # tylko Windows\n    x = 2\n"

    found = mutants("m.py", code, [Hunk(2, 2, ("    x = 1",))], "linux")

    assert [m.other_system for m in found if "cofnięta" in m.description] == [True]


def test_mutacja_funkcji_z_cache_ma_stan_wspolny() -> None:
    code = "@functools.cache\ndef zb() -> int:\n    return a or b\n\n\ndef inna() -> int:\n    return c or d\n"
    hunks = [Hunk(line, 1, ()) for line in (3, 7)]

    shared = {m.description: m.shared_state for m in mutants("m.py", code, hunks) if "w `or`" in m.description}

    assert shared == {"bez `a` w `or`": True, "bez `b` w `or`": True, "bez `c` w `or`": False, "bez `d` w `or`": False}


def test_cofniecie_liczy_linie_jak_git_mimo_separatora_unicode() -> None:
    code = 'a = "x\u2028y"\nb = 2\nc = 3\n'

    assert _described(code, [3], ("c = 4",))["zmiana linii 3 cofnięta do bazy"] == 'a = "x\u2028y"\nb = 2\nc = 4\n'


def test_adnotacja_pola_modelu_zostaje_mutacja_a_stala_nie_jest_aliasem() -> None:
    model = "class Model(BaseModel):\n    pole: int | None\n"
    constant = "TIMEOUT_S = 5 * 60\n"

    assert "zmiana linii 2 cofnięta do bazy" in _described(model, [2], ("    pole: int",))
    assert "zmiana linii 1 cofnięta do bazy" in _described(constant, [1], ("TIMEOUT_S = 3 * 60",))
    assert "zmiana linii 1 cofnięta do bazy" in _described('NAZWA = OPCJE["nowa"]\n', [1], ('NAZWA = OPCJE["stara"]',))


def test_w_pliku_z_pydantic_adnotacja_i_alias_typu_zostaja_mutacja() -> None:
    code = "from pydantic import BaseModel\nWynik = Annotated[A | B, Field(discriminator='rodzaj')]\n\n\ndef trasa() -> Wynik:\n    pass\n"

    assert "zmiana linii 2 cofnięta do bazy" in _described(code, [2], ("Wynik = A | B",))
    assert "zmiana linii 5 cofnięta do bazy" in _described(code, [5], ("def trasa() -> A:",))


def test_adnotacje_i_docstringi_nie_dostaja_mutacji() -> None:
    code = 'def f(x: tuple[int, str] | None = None) -> bool:\n    """Opis."""\n\n\nif TYPE_CHECKING:\n    g(a or b)\n'

    assert [description for description in _described(code, [1, 2, 5, 6]) if "cofnięta" not in description] == []


def test_wyjatek_w_samodzielnym_komentarzu_dotyczy_linii_pod_nim() -> None:
    code = "# mutacje-zmiany: to samo | do 2026-12-31 | zgoda Maks\nx = a or b\ny = 1  # mutacje-zmiany: inne | do 2027-01-31 | zgoda Maks\n"

    found = exceptions(code, "m.py")

    assert sorted(found) == [1, 2, 3]
    assert (found[2].reason, str(found[2].until), found[2].who) == ("to samo", "2026-12-31", "Maks")


@pytest.mark.parametrize("comment", ["# mutacje-zmiany: bez terminu", "# mutacje-zmiany: powód | do 2026-13-01 | zgoda Maks"])
def test_wyjatek_w_zlej_postaci_nazywa_plik_i_linie(comment: str) -> None:
    with pytest.raises(ValueError, match=r"^m\.py:2: "):
        exceptions(f"x = 1\ny = 2  {comment}\n", "m.py")


def test_pokrycie_przypisuje_zmieniona_linie_testom_ktore_ja_wykonuja_w_watku_i_w_podprocesie(tmp_path: Path) -> None:
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
        "    t.join()\n\n\n"
        "def w_podprocesie() -> int:\n"
        "    return 3\n",
        encoding="utf-8",
    )
    (tmp_path / "test_modul.py").write_text(
        "import os\nimport subprocess\nimport sys\n\nimport modul\n\n\n"
        "def test_wprost() -> None:\n    modul.wprost()\n\n\n"
        "def test_watek() -> None:\n    modul.watek()\n\n\n"
        "def test_podproces() -> None:\n"
        "    code = 'import modul; modul.w_podprocesie()'\n"
        "    subprocess.run([sys.executable, '-c', code], env=dict(os.environ), check=True)\n",
        encoding="utf-8",
    )
    site = tmp_path / "site"
    site.mkdir()
    (site / "sitecustomize.py").write_text(pokrycie_procesu.SITECUSTOMIZE, encoding="utf-8")
    found = tmp_path / "wynik"
    found.mkdir()
    settings = {"linie": {str(module): [5, 9, 18]}, "wynik": str(found)}
    done = subprocess.run(
        [sys.executable, "-m", "pytest", "-q", "-p", "pokrycie_linii", "-p", "no:cacheprovider", "test_modul.py"],
        cwd=tmp_path,
        env={
            **{name: value for name, value in os.environ.items() if name != pokrycie_procesu.TEST},
            "PYTHONPATH": os.pathsep.join([str(site), str(ROOT / "tools"), str(tmp_path)]),
            "POKRYCIE_LINII": json.dumps(settings),
        },
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=120,
        check=False,
    )

    assert done.returncode == 0, done.stdout + done.stderr
    merged: dict[str, dict[str, list[int]]] = {}
    for written in found.iterdir():
        merged |= json.loads(written.read_text(encoding="utf-8"))["linie"]
    assert merged == {
        "test_modul.py::test_wprost": {str(module): [9]},
        "test_modul.py::test_watek": {str(module): [5]},
        "test_modul.py::test_podproces": {str(module): [18]},
    }

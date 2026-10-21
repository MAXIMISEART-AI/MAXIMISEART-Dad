"""``tools/mutacje.py`` dowodzi, że polecenie pada na zepsutym kodzie, bez dotykania checkoutu.

Mutacje dopisują kod na końcu modułów ``rozliczenia`` w kopii checkoutu; kotwicą jest cała treść
modułu, więc test nie zależy od niej.
"""

from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys

import pytest

from tests.fixtures.git_repo import commit, git, repository

ROOT = Path(__file__).resolve().parents[1]
TOOL = ROOT / "tools" / "mutacje.py"
PACKAGE = "src/rozliczenia/__init__.py"
IMPORT = ("-c", "import rozliczenia")


def _appended(module: str, code: str) -> list[str]:
    """Zmiana mutacji: ``code`` dopisany na końcu modułu."""

    source = (ROOT / module).read_text(encoding="utf-8")
    return [module, source, f"{source}{code}\n"]


def _mutacje(*arguments: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(TOOL), *arguments],
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=120,
        check=False,
    )


def test_mutacja_kodu_kopii_jest_wykryta_mimo_edytowalnej_instalacji_checkoutu() -> None:
    answered = _mutacje("--zmiana", *_appended(PACKAGE, "raise SystemExit(3)"), "--", *IMPORT)

    assert answered.returncode == 0, answered.stdout
    assert answered.stdout.splitlines()[-2:] == ["WYKRYTA: mutacja → kod wyjścia 3", "MUTACJE OK"]


def test_mutacja_bez_wplywu_na_polecenie_jest_niewykryta() -> None:
    answered = _mutacje("--zmiana", *_appended(PACKAGE, "# bez skutku"), "--", *IMPORT)

    assert answered.returncode == 1
    assert answered.stdout.splitlines()[0].startswith("NIEWYKRYTA: mutacja")


def test_mutacja_w_kilku_plikach_zmienia_wszystkie_naraz(tmp_path: Path) -> None:
    both = "import rozliczenia as r, rozliczenia.message as m; raise SystemExit(getattr(r, 'A', 0) + getattr(m, 'B', 0))"
    mutations = tmp_path / "mutacje.json"
    mutations.write_text(
        json.dumps(
            [
                {
                    "nazwa": "dwa pliki",
                    "zmiany": [_appended(PACKAGE, "A = 1"), _appended("src/rozliczenia/message.py", "B = 1")],
                }
            ]
        ),
        encoding="utf-8",
    )

    answered = _mutacje("--plik", str(mutations), "--", "-c", both)

    assert "WYKRYTA: dwa pliki → kod wyjścia 2" in answered.stdout.splitlines()


@pytest.mark.parametrize("anchor", ["tego tekstu nie ma w pliku", "\n"], ids=["brak", "wiele-razy"])
def test_mutacja_z_kotwica_nie_dokladnie_raz_w_pliku_jest_nieaktualna(anchor: str) -> None:
    answered = _mutacje("--zmiana", PACKAGE, anchor, "", "--", *IMPORT)

    assert answered.returncode == 1
    assert answered.stdout.splitlines()[0].startswith("NIEAKTUALNA: mutacja → kotwicy nie ma dokładnie raz")


def test_polecenie_czerwone_bez_mutacji_nie_daje_werdyktu() -> None:
    answered = _mutacje("--zmiana", *_appended(PACKAGE, ""), "--", "-c", "raise SystemExit(1)")

    assert answered.returncode == 2
    assert answered.stdout.splitlines()[0].startswith("PODSTAWA CZERWONA:")
    assert "WYKRYTA" not in answered.stdout


def test_kopia_ma_niezacommitowane_zmiany_checkoutu_a_checkout_zostaje_nietkniety(tmp_path: Path) -> None:
    package = "src/rozliczenia"
    repo = repository(
        tmp_path / "repo",
        {f"{package}/{name}.py": "WARTOSC = 0\n" for name in ("__init__", "w_indeksie", "poza_indeksem", "usuniety")},
    )
    commit(repo, "baza")
    (repo / package / "w_indeksie.py").write_text("WARTOSC = 1\n", encoding="utf-8")
    git(repo, "add", f"{package}/w_indeksie.py")
    (repo / package / "poza_indeksem.py").write_text("WARTOSC = 1\n", encoding="utf-8")
    (repo / package / "nowy.py").write_text("WARTOSC = 1\n", encoding="utf-8")
    (repo / package / "usuniety.py").unlink()
    status = git(repo, "status", "--porcelain")
    sees_changes = (
        "import importlib.util as u, rozliczenia.w_indeksie as a, rozliczenia.poza_indeksem as b, rozliczenia.nowy as c; "
        "raise SystemExit(0 if a.WARTOSC + b.WARTOSC + c.WARTOSC == 3 and not u.find_spec('rozliczenia.usuniety') else 9)"
    )
    tool = [sys.executable, str(repo / "tools" / "mutacje.py")]

    answered = subprocess.run(
        [*tool, "--zmiana", f"{package}/nowy.py", "WARTOSC = 1", "WARTOSC = 2", "--", "-c", sees_changes],
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=120,
    )

    assert answered.stdout.splitlines() == ["WYKRYTA: mutacja → kod wyjścia 9", "MUTACJE OK"]
    assert (git(repo, "status", "--porcelain"), git(repo, "worktree", "list", "--porcelain").count("worktree ")) == (status, 1)


def test_plik_mutacji_spoza_repozytorium_jest_odrzucony_przed_zmiana() -> None:
    answered = _mutacje("--zmiana", str(ROOT / PACKAGE), "x", "y", "--", *IMPORT)

    assert answered.returncode == 2
    assert "plik mutacji musi leżeć w repozytorium" in answered.stderr

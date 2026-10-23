"""``tools/skille_dla_zmiany.py`` wskazuje skille ``verify-*`` dla zmiany z ``pilnuje:`` w ich ``SKILL.md``.

Testy zachowania budują własne repozytorium z kopią narzędzia. Testy struktury sprawdzają skille i ``AGENTS.md``
tego checkoutu: routing skilli żyje we frontmatterach, a ``AGENTS.md`` tylko odsyła do narzędzia.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path
import shutil
import subprocess
import sys
from types import ModuleType

import pytest

from tests.fixtures.git_repo import commit, git

ROOT = Path(__file__).resolve().parents[1]
TOOLS = ROOT / "tools"
SKILLS = ROOT / ".agents" / "skills"
VERDICT = "SKILLE VERIFY: "
REPO = {
    ".agents/skills/verify-a/SKILL.md": "---\nname: verify-a\ndescription: a\npilnuje:\n  - src/a/*\n  - tools/narzedzie.py\n---\n",
    ".agents/skills/verify-b/SKILL.md": "---\nname: verify-b\ndescription: b\npilnuje:\n  - docs/b.md\n---\n",
    ".agents/skills/verify-b/scripts/run_b.py": "print('b')\n",
    ".agents/skills/inny/SKILL.md": "---\nname: inny\ndescription: nie verify\npilnuje:\n  - docs/b.md\n---\n",
    "src/a/b/gleboki.py": "X = 1\n",
    "src/ab.py": "Y = 1\n",
    "tools/narzedzie.py": "Z = 1\n",
    "docs/b.md": "b\n",
    "docs/inny.md": "inny\n",
}


def _repo(root: Path, files: dict[str, str] = REPO) -> str:
    for name, text in files.items():
        (root / name).parent.mkdir(parents=True, exist_ok=True)
        (root / name).write_text(text, encoding="utf-8")
    (root / "tools").mkdir(exist_ok=True)
    for name in ("skille_dla_zmiany.py", "mutacje_skilli.py", "potomne.py"):
        shutil.copy(TOOLS / name, root / "tools" / name)
    git(root, "init", "--quiet")
    return commit(root, "baza")


def _run(root: Path, *arguments: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(root / "tools" / "skille_dla_zmiany.py"), *arguments],
        cwd=root,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )


def _skills(result: subprocess.CompletedProcess[str]) -> list[str]:
    assert result.returncode == 0, result.stdout + result.stderr
    last = result.stdout.splitlines()[-1]
    assert last.startswith(VERDICT), result.stdout
    named = last.removeprefix(VERDICT)
    return [] if named == "brak" else named.split(", ")


def _append(root: Path, name: str) -> None:
    with (root / name).open("a", encoding="utf-8") as file:
        file.write("zmiana\n")


@pytest.mark.parametrize(
    ("changed", "skills", "reason"),
    [
        ("src/a/b/gleboki.py", ["verify-a"], "verify-a: src/a/b/gleboki.py (src/a/*)"),
        ("tools/narzedzie.py", ["verify-a"], "verify-a: tools/narzedzie.py"),
        ("docs/b.md", ["verify-b"], "verify-b: docs/b.md"),
        (".agents/skills/verify-b/scripts/run_b.py", ["verify-b"], "verify-b: .agents/skills/verify-b/scripts/run_b.py (folder skilla)"),
        ("src/ab.py", [], None),
        ("docs/inny.md", [], None),
        (".agents/skills/inny/SKILL.md", [], None),
    ],
)
def test_zmiana_wskazuje_skille_ktorych_glob_albo_folder_obejmuje_zmieniony_plik(
    tmp_path: Path, changed: str, skills: list[str], reason: str | None
) -> None:
    base = _repo(tmp_path)
    _append(tmp_path, changed)
    commit(tmp_path, "zmiana")

    result = _run(tmp_path, base)

    assert _skills(result) == skills
    assert result.stdout.splitlines()[:-1] == ([reason] if reason else [])


def test_zmiana_bez_commitu_nowy_plik_i_przeniesienie_poza_glob_wskazuja_skill(tmp_path: Path) -> None:
    base = _repo(tmp_path)

    _append(tmp_path, "docs/b.md")
    assert _skills(_run(tmp_path, base)) == ["verify-b"]
    git(tmp_path, "checkout", "--", "docs/b.md")

    (tmp_path / "src/a/nowy.py").write_text("N = 1\n", encoding="utf-8")
    assert _skills(_run(tmp_path, base)) == ["verify-a"]
    (tmp_path / "src/a/nowy.py").unlink()

    git(tmp_path, "mv", "docs/b.md", "docs/przeniesiony.md")
    commit(tmp_path, "przeniesienie")
    assert _skills(_run(tmp_path, base)) == ["verify-b"]


def test_zmiana_tylko_w_bazie_po_rozgalezieniu_nie_wskazuje_skilla(tmp_path: Path) -> None:
    _repo(tmp_path)
    trunk = git(tmp_path, "rev-parse", "--abbrev-ref", "HEAD")
    git(tmp_path, "checkout", "--quiet", "-b", "praca")
    _append(tmp_path, "tools/narzedzie.py")
    commit(tmp_path, "praca")
    git(tmp_path, "checkout", "--quiet", trunk)
    _append(tmp_path, "docs/b.md")
    moved = commit(tmp_path, "baza poszła dalej")
    git(tmp_path, "checkout", "--quiet", "praca")

    assert _skills(_run(tmp_path, moved)) == ["verify-a"]


def test_skill_bez_pilnuje_albo_z_nieczytelnym_pilnuje_obowiazuje_zawsze(tmp_path: Path) -> None:
    base = _repo(
        tmp_path,
        {
            **REPO,
            ".agents/skills/verify-bez/SKILL.md": "---\nname: verify-bez\ndescription: bez klucza\n---\n",
            ".agents/skills/verify-zly/SKILL.md": "---\nname: verify-zly\npilnuje: docs/b.md\n---\n",
        },
    )

    result = _run(tmp_path, base)

    assert _skills(result) == ["verify-bez", "verify-zly"]
    assert result.stdout.splitlines()[0] == "verify-bez: .agents/skills/verify-bez/SKILL.md nie ma klucza pilnuje"


def test_wiele_plikow_jednego_skilla_skraca_powod(tmp_path: Path) -> None:
    base = _repo(tmp_path)
    for number in range(5):
        (tmp_path / f"src/a/plik{number}.py").write_text("P = 1\n", encoding="utf-8")

    result = _run(tmp_path, base)

    assert result.stdout.splitlines() == [
        "verify-a: src/a/plik0.py (src/a/*), src/a/plik1.py (src/a/*), src/a/plik2.py (src/a/*) i 2 innych",
        f"{VERDICT}verify-a",
    ]


def test_baza_ktorej_nie_ma_daje_nieznane_skille_i_kod_bledu(tmp_path: Path) -> None:
    _repo(tmp_path)

    result = _run(tmp_path, "nie-ma-takiej-bazy")

    assert result.returncode == 1
    assert result.stdout.splitlines()[-1].startswith(f"{VERDICT}nieznane (git diff: ")
    assert "nie-ma-takiej-bazy" in result.stdout


def _load_tool(monkeypatch: pytest.MonkeyPatch) -> ModuleType:
    monkeypatch.syspath_prepend(str(TOOLS))
    spec = importlib.util.spec_from_file_location("skille_dla_zmiany", TOOLS / "skille_dla_zmiany.py")
    assert spec is not None and spec.loader is not None
    tool = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(tool)
    return tool


def test_kazdy_skill_verify_deklaruje_pilnuje(monkeypatch: pytest.MonkeyPatch) -> None:
    tool = _load_tool(monkeypatch)
    skills = sorted(SKILLS.glob("verify-*/SKILL.md"))

    without = [md.parent.name for md in skills if tool.guarded(md) is None]

    assert skills
    assert without == [], "dopisz do frontmattera SKILL.md klucz pilnuje: z globami ścieżek, przy których zmianie skill obowiązuje"


"""``tools/mutacje_skilli.py`` nie przepuszcza skryptu mutacji, który zgubił się albo nie dał werdyktu.

Każdy test buduje własne ``.agents/skills`` obok kopii narzędzia, więc narzędzie widzi tylko te skille.
"""

from __future__ import annotations

from pathlib import Path
import shutil
import subprocess
import sys

import pytest

TOOL = Path(__file__).resolve().parents[1] / "tools" / "mutacje_skilli.py"
PASSING = 'print("WYKRYTA: proba")\nprint("MUTACJE OK")\n'


def _skill(root: Path, name: str, scripts: dict[str, str], skill_md: str = "") -> None:
    skill = root / ".agents" / "skills" / name
    for script, body in scripts.items():
        (skill / "scripts" / script).parent.mkdir(parents=True, exist_ok=True)
        (skill / "scripts" / script).write_text(body, encoding="utf-8")
    skill.mkdir(parents=True, exist_ok=True)
    (skill / "SKILL.md").write_text(skill_md, encoding="utf-8")


def _run(root: Path, *args: str) -> subprocess.CompletedProcess[str]:
    (root / "tools").mkdir(exist_ok=True)
    shutil.copy(TOOL, root / "tools" / TOOL.name)
    return subprocess.run(
        [sys.executable, str(root / "tools" / TOOL.name), *args],
        cwd=root,
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=120,
        check=False,
    )


def test_skrypty_z_werdyktem_przechodza(tmp_path: Path) -> None:
    _skill(tmp_path, "verify-a", {"check_a_mutations.py": PASSING}, "py -3 scripts\\check_a_mutations.py")

    result = _run(tmp_path)

    assert result.returncode == 0, result.stdout
    assert result.stdout.splitlines()[-1] == "MUTACJE SKILLI OK"


def test_skrypt_mutacji_o_zlej_nazwie_albo_w_podfolderze_daje_fail(tmp_path: Path) -> None:
    _skill(tmp_path, "verify-a", {"check_a_mutations.py": PASSING})
    _skill(tmp_path, "verify-b", {"check_mutation_proba.py": PASSING, "sub/check_sub_mutations.py": PASSING})

    result = _run(tmp_path)

    assert result.returncode == 1
    final = result.stdout.splitlines()[-1]
    assert ".agents/skills/verify-b/scripts/check_mutation_proba.py" in final
    assert ".agents/skills/verify-b/scripts/sub/check_sub_mutations.py" in final


def test_skrypt_wskazany_w_skill_md_a_usuniety_daje_fail(tmp_path: Path) -> None:
    _skill(tmp_path, "verify-a", {"check_a_mutations.py": PASSING})
    _skill(tmp_path, "verify-b", {}, "py -3 .agents\\skills\\verify-b\\scripts\\check_b_mutations.py")

    result = _run(tmp_path)

    assert result.returncode == 1
    assert ".agents/skills/verify-b/scripts/check_b_mutations.py" in result.stdout.splitlines()[-1]


@pytest.mark.parametrize(
    "mention",
    [
        "Nazwij skrypt `scripts/check_<co>_mutations.py`.",
        "Zobacz też `check_b_mutations.py` w verify-b.",
        "py -3 .agents\\skills\\verify-b\\scripts\\check_b_mutations.py",
        "Testy runnera są w `tests/test_mutations.py`.",
    ],
)
def test_wzmianka_w_prozie_nie_daje_fail(tmp_path: Path, mention: str) -> None:
    _skill(tmp_path, "verify-a", {"check_a_mutations.py": PASSING}, f"py -3 scripts\\check_a_mutations.py\n{mention}\n")
    _skill(tmp_path, "verify-b", {"check_b_mutations.py": PASSING})

    result = _run(tmp_path)

    assert result.returncode == 0, result.stdout
    assert result.stdout.splitlines()[-1] == "MUTACJE SKILLI OK"


def test_skrypt_bez_werdyktu_daje_fail(tmp_path: Path) -> None:
    _skill(tmp_path, "verify-a", {"check_a_mutations.py": "def main() -> int:\n    return 0\n"})

    result = _run(tmp_path)

    assert result.returncode == 1
    assert ".agents/skills/verify-a/scripts/check_a_mutations.py" in result.stdout.splitlines()[-1]


def test_skrypt_po_limicie_czasu_daje_fail_a_kolejne_dalej_ruszaja(tmp_path: Path) -> None:
    _skill(tmp_path, "verify-a", {"check_a_mutations.py": "import time\ntime.sleep(60)\n"})
    _skill(tmp_path, "verify-b", {"check_b_mutations.py": PASSING})

    result = _run(tmp_path, "--limit-s", "1")

    assert result.returncode == 1
    assert "OK   .agents/skills/verify-b/scripts/check_b_mutations.py" in result.stdout
    final = result.stdout.splitlines()[-1]
    assert ".agents/skills/verify-a/scripts/check_a_mutations.py" in final
    assert "verify-b" not in final

"""``tools/ci_lokalnie.py`` odtwarza lokalnie te same polecenia co CI, więc nie może się z nim rozjechać.

Każde polecenie z zadań CI, które narzędzie odtwarza, ma w nim swój krok, a każdy krok narzędzia ma
swoje polecenie w CI. Zadanie CI, którego narzędzie nie odtwarza, ma wskazane miejsce, które je zastępuje. ``--kazdy-commit``
wskazuje każdy commit gałęzi, na którym krok pada, także gdy HEAD przechodzi.
"""

from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys

import yaml

from tests.fixtures.git_repo import commit, git, repository

ROOT = Path(__file__).resolve().parents[1]
TOOL = ROOT / "tools" / "ci_lokalnie.py"
WORKFLOW = ROOT / ".github" / "workflows" / "ci.yml"
# Linie `run:`, które przygotowują runner, a nie sprawdzają kodu.
RUNNER_SETUP = ("pip install", "py -3 -c", "Add-Content")


def _tool_steps() -> dict[str, object]:
    answered = subprocess.run(
        [sys.executable, str(TOOL), "--kroki-ci"], capture_output=True, text=True, encoding="utf-8", check=True
    )
    steps: dict[str, object] = json.loads(answered.stdout)
    return steps


def _commands(job: dict[str, object]) -> list[str]:
    """Polecenia sprawdzające z kroków `run:` zadania, z `py -3` zapisanym jak `python`."""

    commands = []
    for step in job.get("steps", []):  # type: ignore[attr-defined]
        for line in str(step.get("run", "")).splitlines():
            command = line.strip().replace("py -3 ", "python ")
            if command.startswith(("python ", "npm ", 'stale="$(git')) and not any(
                setup in command for setup in RUNNER_SETUP
            ):
                commands.append(command)
    return commands


def test_kazde_zadanie_ci_jest_odtworzone_albo_ma_wskazane_zastepstwo() -> None:
    steps = _tool_steps()
    jobs = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))["jobs"]

    assert set(jobs) == set(steps["lokalnie"]) | set(steps["gdzie_indziej"])  # type: ignore[call-overload]


def test_kazde_polecenie_odtwarzanych_zadan_ma_krok_i_odwrotnie() -> None:
    steps = _tool_steps()
    jobs = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))["jobs"]
    fragments: list[str] = steps["fragmenty"]  # type: ignore[assignment]
    commands = [command for job in steps["lokalnie"] for command in _commands(jobs[job])]  # type: ignore[attr-defined]

    without_step = [command for command in commands if not any(fragment in command for fragment in fragments)]
    without_command = [fragment for fragment in fragments if not any(fragment in command for command in commands)]

    assert without_step == []
    assert without_command == []


def test_kazdy_commit_wskazuje_commit_ze_zlamanym_krokiem_choc_head_przechodzi(tmp_path: Path) -> None:
    repo = repository(tmp_path / "repo", {"tests/test_dobry.py": "def test_dobry() -> None:\n    pass\n"})
    base = commit(repo, "baza")
    (repo / "tests" / "test_zepsuty.py").write_text("def test_zepsuty() -> None:\n    assert False\n", encoding="utf-8")
    broken = commit(repo, "zepsuty test")
    (repo / "tests" / "test_zepsuty.py").unlink()
    head = commit(repo, "bez zepsutego testu")
    tool = [sys.executable, str(repo / "tools" / "ci_lokalnie.py"), "--tylko", "pytest"]

    every_commit = subprocess.run([*tool, "--kazdy-commit", base], capture_output=True, text=True, encoding="utf-8")
    only_head = subprocess.run(tool, capture_output=True, text=True, encoding="utf-8")

    assert (only_head.returncode, only_head.stdout.splitlines()[-1]) == (0, "CI LOKALNIE OK")
    assert (every_commit.returncode, every_commit.stdout.splitlines()[-1]) == (1, f"COMMITY FAIL | {broken[:7]} (pytest)")
    assert (git(repo, "rev-parse", "HEAD"), git(repo, "worktree", "list", "--porcelain").count("worktree ")) == (head, 1)


def test_kazdy_commit_przechodzi_gdy_kazdy_commit_przechodzi(tmp_path: Path) -> None:
    repo = repository(tmp_path / "repo", {"tests/test_dobry.py": "def test_dobry() -> None:\n    pass\n"})
    base = commit(repo, "baza")
    for name in ("drugi", "trzeci"):
        (repo / "tests" / f"test_{name}.py").write_text(f"def test_{name}() -> None:\n    pass\n", encoding="utf-8")
        commit(repo, name)

    answered = subprocess.run(
        [sys.executable, str(repo / "tools" / "ci_lokalnie.py"), "--tylko", "pytest", "--kazdy-commit", base],
        capture_output=True,
        text=True,
        encoding="utf-8",
    )

    assert (answered.returncode, answered.stdout.splitlines()[-1]) == (0, "COMMITY OK (2)")


def test_kazdy_commit_od_nieistniejacej_bazy_nazywa_baze_bez_tracebacku(tmp_path: Path) -> None:
    repo = repository(tmp_path / "repo", {"tests/test_dobry.py": "def test_dobry() -> None:\n    pass\n"})
    commit(repo, "baza")

    answered = subprocess.run(
        [sys.executable, str(repo / "tools" / "ci_lokalnie.py"), "--kazdy-commit", "nie-ma-takiej-bazy"],
        capture_output=True,
        text=True,
        encoding="utf-8",
    )

    assert (answered.returncode, answered.stdout.splitlines()[-1:]) == (1, ["COMMITY FAIL | nieznana baza nie-ma-takiej-bazy"])
    assert "Traceback" not in answered.stderr

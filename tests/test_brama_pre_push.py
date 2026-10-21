"""Brama ``tools/hooks/pre-push``: push agenta z HEAD przechodzi tylko po ``CI LOKALNIE OK`` albo z pieczątką jego drzewa.

Każdy test robi prawdziwy ``git push`` do tymczasowego repozytorium bare. ``tools/ci_lokalnie.py`` zastępuje
atrapa ``.venv/bin/python``, która od razu kończy się werdyktem, więc testy nie uruchamiają pełnego CI.
Push robi agent (``AI_AGENT``), chyba że test mówi inaczej.
"""

from __future__ import annotations

import os
from pathlib import Path
import shutil
import subprocess

import pytest

HOOK = Path(__file__).resolve().parents[1] / "tools" / "hooks" / "pre-push"
BRANCH = "refs/heads/zmiana"
AGENT_MARKERS = ("AI_AGENT", "CLAUDECODE")

pytestmark = pytest.mark.skipif(
    os.name == "nt",
    reason="Atrapa .venv/bin/python to skrypt sh, a tools/setup_worktree.py nie włącza bramy na Windows.",
)


def _git(cwd: Path, *args: str, agent: str | None = "claude-code") -> subprocess.CompletedProcess[str]:
    environment = {
        name: value
        for name, value in os.environ.items()
        if not name.startswith("GIT_") and name not in AGENT_MARKERS
    }
    environment |= {"GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": os.devnull}
    if agent is not None:
        environment["AI_AGENT"] = agent
    return subprocess.run(
        ["git", "-c", "user.name=Test", "-c", "user.email=test@example.com", *args],
        cwd=cwd,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )


@pytest.fixture
def checkout(tmp_path: Path) -> Path:
    remote, checkout = tmp_path / "zdalne.git", tmp_path / "checkout"
    _git(tmp_path, "init", "-q", "--bare", str(remote))
    _git(tmp_path, "init", "-q", str(checkout))
    (checkout / "tools" / "hooks").mkdir(parents=True)
    shutil.copy2(HOOK, checkout / "tools" / "hooks" / "pre-push")
    (checkout / ".gitignore").write_text(".venv/\n", encoding="utf-8")
    _git(checkout, "add", "-A")
    _git(checkout, "commit", "-q", "-m", "start")
    _git(checkout, "config", "core.hooksPath", "tools/hooks")
    _git(checkout, "remote", "add", "origin", str(remote))
    return checkout


def _ci_lokalnie(checkout: Path, *, passes: bool) -> None:
    python = checkout / ".venv" / "bin" / "python"
    python.parent.mkdir(parents=True, exist_ok=True)
    verdict = "CI LOKALNIE OK" if passes else "CI LOKALNIE FAIL | ruff"
    python.write_text(f"#!/bin/sh\necho '{verdict}'\nexit {0 if passes else 1}\n", encoding="utf-8")
    python.chmod(0o755)


def _stamp_head_tree(checkout: Path) -> None:
    git_dir = checkout / _git(checkout, "rev-parse", "--git-dir").stdout.strip()
    tree = _git(checkout, "rev-parse", "HEAD^{tree}").stdout.strip()
    (git_dir / "ci-lokalnie-ok").write_text(tree, encoding="utf-8")


def _remote_branch(checkout: Path) -> str:
    return _git(checkout, "ls-remote", "origin", BRANCH).stdout.split("\t")[0]


@pytest.mark.parametrize("passes", [True, False])
def test_push_head_bez_pieczatki_rozstrzyga_ci_lokalnie(checkout: Path, passes: bool) -> None:
    _ci_lokalnie(checkout, passes=passes)

    pushed = _git(checkout, "push", "origin", f"HEAD:{BRANCH}")

    assert (pushed.returncode == 0) == passes
    assert "CI LOKALNIE" in pushed.stderr + pushed.stdout
    head = _git(checkout, "rev-parse", "HEAD").stdout.strip()
    assert _remote_branch(checkout) == (head if passes else "")


@pytest.mark.parametrize("untracked", [False, True])
def test_push_drzewa_z_pieczatka_przechodzi_bez_ci_lokalnie(checkout: Path, untracked: bool) -> None:
    _ci_lokalnie(checkout, passes=False)
    _stamp_head_tree(checkout)
    if untracked:
        (checkout / "szkic.py").write_text("", encoding="utf-8")

    pushed = _git(checkout, "push", "origin", f"HEAD:{BRANCH}")

    assert pushed.returncode == 0, pushed.stderr
    assert _remote_branch(checkout) == _git(checkout, "rev-parse", "HEAD").stdout.strip()


def test_pieczatka_innego_drzewa_nie_przepuszcza_pushu(checkout: Path) -> None:
    _ci_lokalnie(checkout, passes=False)
    _stamp_head_tree(checkout)
    (checkout / "nowy.txt").write_text("zmiana drzewa", encoding="utf-8")
    _git(checkout, "add", "nowy.txt")
    _git(checkout, "commit", "-q", "-m", "nowe drzewo")

    pushed = _git(checkout, "push", "origin", f"HEAD:{BRANCH}")

    assert pushed.returncode != 0
    assert _remote_branch(checkout) == ""


def test_usuniecie_galezi_przechodzi_bez_ci_lokalnie(checkout: Path) -> None:
    _ci_lokalnie(checkout, passes=True)
    assert _git(checkout, "push", "origin", f"HEAD:{BRANCH}").returncode == 0
    _ci_lokalnie(checkout, passes=False)

    deleted = _git(checkout, "push", "origin", "--delete", BRANCH)

    assert deleted.returncode == 0, deleted.stderr
    assert _remote_branch(checkout) == ""


def test_push_bez_venv_jest_odrzucony_ze_wskazaniem_setup_worktree(checkout: Path) -> None:
    pushed = _git(checkout, "push", "origin", f"HEAD:{BRANCH}")

    assert pushed.returncode != 0
    assert "tools/setup_worktree.py" in pushed.stderr + pushed.stdout
    assert _remote_branch(checkout) == ""


def test_push_czlowieka_przechodzi_bez_ci_lokalnie_i_bez_komunikatu(checkout: Path) -> None:
    _ci_lokalnie(checkout, passes=False)

    pushed = _git(checkout, "push", "origin", f"HEAD:{BRANCH}", agent=None)

    assert pushed.returncode == 0, pushed.stderr
    assert "pre-push" not in pushed.stderr + pushed.stdout
    assert _remote_branch(checkout) == _git(checkout, "rev-parse", "HEAD").stdout.strip()

"""Brama ``tools/hooks/pre-push``: push agenta z HEAD przechodzi tylko po ``CI LOKALNIE OK`` albo z pieczątką jego drzewa.

Każdy test robi prawdziwy ``git push`` do tymczasowego repozytorium bare. ``tools/ci_lokalnie.py`` zastępuje
atrapa ``.venv/bin/python``, która od razu kończy się werdyktem, więc testy nie uruchamiają pełnego CI.
Push robi agent (``AI_AGENT``), chyba że test mówi inaczej.
"""

from __future__ import annotations

from collections.abc import Callable
import os
from pathlib import Path
import shutil
import signal
import subprocess
import sys
import time

import pytest

HOOK = Path(__file__).resolve().parents[1] / "tools" / "hooks" / "pre-push"
BRANCH = "refs/heads/zmiana"
AGENT_MARKERS = ("AI_AGENT", "CLAUDECODE")

pytestmark = pytest.mark.skipif(
    os.name == "nt",
    reason="Atrapa .venv/bin/python to skrypt sh, a tools/setup_worktree.py nie włącza bramy na Windows.",
)


def _environment(agent: str | None) -> dict[str, str]:
    environment = {
        name: value
        for name, value in os.environ.items()
        if not name.startswith("GIT_") and name not in AGENT_MARKERS
    }
    environment |= {"GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": os.devnull}
    if agent is not None:
        environment["AI_AGENT"] = agent
    return environment


def _git(cwd: Path, *args: str, agent: str | None = "claude-code") -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", "-c", "user.name=Test", "-c", "user.email=test@example.com", *args],
        cwd=cwd,
        env=_environment(agent),
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


def _fake_python(checkout: Path, body: str) -> None:
    python = checkout / ".venv" / "bin" / "python"
    python.parent.mkdir(parents=True, exist_ok=True)
    python.write_text(f"#!/bin/sh\necho \"$@\" > argumenty.txt\n{body}\n", encoding="utf-8")
    python.chmod(0o755)


def _ci_lokalnie(checkout: Path, *, passes: bool) -> None:
    verdict = "CI LOKALNIE OK" if passes else "CI LOKALNIE FAIL | ruff"
    _fake_python(checkout, f"echo '{verdict}'\nexit {0 if passes else 1}")


def _hanging_ci_lokalnie(checkout: Path) -> list[Path]:
    """Atrapa, która wisi z procesem potomnym jak pytest pod ci_lokalnie; zwraca pliki z PID-ami obu."""

    _fake_python(checkout, "sleep 120 &\necho $! > potomek.pid\necho $$ > ci.pid\nwait")
    return [checkout / "ci.pid", checkout / "potomek.pid"]


def _wait_for(condition: Callable[[], bool]) -> bool:
    deadline = time.monotonic() + 15
    while time.monotonic() < deadline:
        if condition():
            return True
        time.sleep(0.1)
    return False


def _alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    return True


def _start_push(checkout: Path) -> subprocess.Popen[str]:
    return subprocess.Popen(
        ["git", "push", "origin", f"HEAD:{BRANCH}"],
        cwd=checkout,
        env=_environment("claude-code"),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        start_new_session=True,
    )


def _started_ci(pid_files: list[Path]) -> list[int]:
    assert _wait_for(lambda: all(path.exists() and path.read_text().strip() for path in pid_files))
    return [int(path.read_text()) for path in pid_files]


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


@pytest.mark.parametrize("detached", [False, True])
def test_push_head_odlaczonego_albo_galezi_rozstrzyga_ci_lokalnie(checkout: Path, detached: bool) -> None:
    _git(checkout, "checkout", "-q", "-b", "zmiana")
    _git(checkout, "push", "-q", "origin", "zmiana", agent=None)
    published = _git(checkout, "rev-parse", "HEAD").stdout.strip()
    _git(checkout, "commit", "-q", "--allow-empty", "-m", "nowy commit")
    if detached:
        _git(checkout, "checkout", "-q", "--detach")
    _ci_lokalnie(checkout, passes=False)

    pushed = _git(checkout, "push", "origin", "HEAD:zmiana" if detached else "zmiana")

    assert pushed.returncode != 0
    assert "CI LOKALNIE FAIL" in pushed.stderr + pushed.stdout
    assert _remote_branch(checkout) == published


def test_brama_prosi_ci_lokalnie_o_przerwanie_na_pierwszym_bledzie(checkout: Path) -> None:
    _ci_lokalnie(checkout, passes=False)

    _git(checkout, "push", "origin", f"HEAD:{BRANCH}")

    assert (checkout / "argumenty.txt").read_text().split() == ["tools/ci_lokalnie.py", "--do-pierwszego-bledu"]


GROUP_SIGNALS = {"SIGTERM dla grupy pushu": signal.SIGTERM, "SIGINT dla grupy pushu": signal.SIGINT}
if sys.platform != "win32":
    # Tak kończy push limit czasu agenta; SIGKILL nie daje bramie posprzątać.
    GROUP_SIGNALS["SIGKILL dla grupy pushu"] = signal.SIGKILL


@pytest.mark.parametrize("stop", ["zabity sam git push", *GROUP_SIGNALS])
def test_ci_lokalnie_nie_przezywa_przerwanego_pushu(checkout: Path, stop: str) -> None:
    pid_files = _hanging_ci_lokalnie(checkout)
    push = _start_push(checkout)
    started = _started_ci(pid_files)

    if stop == "zabity sam git push":
        push.kill()
    else:
        os.kill(-push.pid, GROUP_SIGNALS[stop])
    push.wait(timeout=10)

    assert _wait_for(lambda: not any(_alive(pid) for pid in started)), stop


def test_drugi_push_z_tego_checkoutu_nie_uruchamia_drugiego_ci_lokalnie(checkout: Path) -> None:
    pid_files = _hanging_ci_lokalnie(checkout)
    first = _start_push(checkout)
    try:
        started = _started_ci(pid_files)
        for path in pid_files:
            path.unlink()

        second = _git(checkout, "push", "origin", f"HEAD:{BRANCH}")

        assert second.returncode != 0
        assert not any(path.exists() for path in pid_files)
        assert all(_alive(pid) for pid in started)
    finally:
        os.kill(-first.pid, signal.SIGTERM)
        first.wait(timeout=10)


def test_udany_ci_lokalnie_z_zombie_w_grupie_przepuszcza_push(checkout: Path) -> None:
    # Potomek wychodzi z grupy i nie zbiera swojego dziecka, więc w grupie ci_lokalnie zostaje samo zombie,
    # na które macOS odpowiada EPERM.
    leaves_zombie = (
        "import os, time\n"
        "if os.fork() == 0:\n    os._exit(0)\n"
        "os.setpgid(0, 0)\n"
        "open('rodzic.pid', 'w').write(str(os.getpid()))\n"
        "time.sleep(30)\n"
    )
    _fake_python(checkout, f"'{sys.executable}' -c \"{leaves_zombie}\" > /dev/null 2>&1 &\nsleep 1\necho 'CI LOKALNIE OK'")
    try:
        pushed = _git(checkout, "push", "origin", f"HEAD:{BRANCH}")

        assert pushed.returncode == 0, pushed.stderr
        assert _remote_branch(checkout) == _git(checkout, "rev-parse", "HEAD").stdout.strip()
    finally:
        os.kill(int((checkout / "rodzic.pid").read_text()), signal.SIGTERM)

"""``tools/mutacje_skilli.py`` nie przepuszcza skryptu mutacji, który zgubił się albo nie dał werdyktu.

Każdy test buduje własne ``.agents/skills`` obok kopii narzędzia, więc narzędzie widzi tylko te skille.
"""

from __future__ import annotations

import contextlib
from pathlib import Path
import os
import shutil
import signal
import subprocess
import sys
import time
from typing import Callable

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


def _start(root: Path) -> subprocess.Popen[str]:
    (root / "tools").mkdir(exist_ok=True)
    shutil.copy(TOOL, root / "tools" / TOOL.name)
    return subprocess.Popen(
        [sys.executable, str(root / "tools" / TOOL.name)],
        cwd=root,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        text=True,
        encoding="utf-8",
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


def test_wyjscie_skryptu_mutacji_widac_w_trakcie_jego_pracy(tmp_path: Path) -> None:
    seen = tmp_path / "linia-widziana"
    script = (
        "import pathlib, sys, time\n"
        "print('WYKRYTA: pierwsza', flush=True)\n"
        "deadline = time.monotonic() + 20\n"
        f"while not pathlib.Path({str(seen)!r}).exists():\n"
        "    if time.monotonic() > deadline:\n"
        "        sys.exit(3)\n"
        "    time.sleep(0.05)\n" + PASSING
    )
    _skill(tmp_path, "verify-a", {"check_a_mutations.py": script})

    runner = _start(tmp_path)
    assert runner.stdout is not None
    lines = []
    for line in runner.stdout:
        lines.append(line.rstrip("\n"))
        if line.startswith("WYKRYTA: pierwsza"):
            seen.touch()
    runner.wait(timeout=30)

    assert (runner.returncode, lines[-1]) == (0, "MUTACJE SKILLI OK"), lines


def _leaves_child(marker: Path, escape: bool) -> str:
    """Skrypt z werdyktem, który kończy się kodem 0, a zostawia potomka z otwartym stdout."""

    ready = marker.with_name("potomek-gotowy")
    child = (
        ("import os\nos.setsid()\n" if escape else "")
        + f"import os, pathlib, time\npathlib.Path({str(ready)!r}).write_text(str(os.getpid()))\ntime.sleep(3)\n"
        + f"pathlib.Path({str(marker)!r}).touch()\ntime.sleep(600)\n"
    )
    return (
        f"import pathlib, subprocess, sys, time\nsubprocess.Popen([sys.executable, '-c', {child!r}])\n"
        + f"while not pathlib.Path({str(ready)!r}).exists():\n    time.sleep(0.05)\n"
        + PASSING
    )


def test_potomek_skryptu_z_otwartym_wyjsciem_ginie_razem_ze_skryptem(tmp_path: Path) -> None:
    marker = tmp_path / "potomek-zyje"
    _skill(tmp_path, "verify-a", {"check_a_mutations.py": _leaves_child(marker, escape=False)})

    result = _run(tmp_path, "--limit-s", "60")
    time.sleep(6)

    assert result.returncode == 0, result.stdout
    assert result.stdout.splitlines()[-1] == "MUTACJE SKILLI OK"
    assert not marker.exists()


@pytest.mark.skipif(sys.platform == "win32", reason="na Windows potomek nie wychodzi z Job Object skryptu")
def test_potomek_poza_grupa_procesow_z_otwartym_wyjsciem_daje_fail_po_limicie(tmp_path: Path) -> None:
    _skill(tmp_path, "verify-a", {"check_a_mutations.py": _leaves_child(tmp_path / "potomek-zyje", escape=True)})
    _skill(tmp_path, "verify-b", {"check_b_mutations.py": PASSING})

    started = time.monotonic()
    try:
        result = _run(tmp_path, "--limit-s", "5")
    finally:
        os.kill(int((tmp_path / "potomek-gotowy").read_text()), signal.SIGTERM)

    assert time.monotonic() - started < 60
    assert result.returncode == 1
    assert "OK   .agents/skills/verify-b/scripts/check_b_mutations.py" in result.stdout
    final = result.stdout.splitlines()[-1]
    assert ".agents/skills/verify-a/scripts/check_a_mutations.py" in final
    assert "verify-b" not in final


@pytest.mark.parametrize(
    "mention",
    [
        "py -3 ./.agents/skills/verify-a/scripts/check_a_mutations.py",
        "py -3 .\\.agents\\skills\\verify-a\\scripts\\check_a_mutations.py",
        "py -3 {root}/.agents/skills/verify-a/scripts/check_a_mutations.py",
    ],
)
def test_sciezka_z_kropka_albo_bezwzgledna_do_skryptu_w_repo_przechodzi(tmp_path: Path, mention: str) -> None:
    _skill(tmp_path, "verify-a", {"check_a_mutations.py": PASSING}, mention.format(root=tmp_path))

    result = _run(tmp_path)

    assert result.returncode == 0, result.stdout + result.stderr
    assert result.stdout.splitlines()[-1] == "MUTACJE SKILLI OK"


def test_sciezka_bezwzgledna_spoza_repo_daje_nazwany_fail(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    outside = tmp_path / "gdzie-indziej" / "scripts" / "check_x_mutations.py"
    _skill(root, "verify-a", {"check_a_mutations.py": PASSING}, f"py -3 scripts/check_a_mutations.py\npy -3 {outside}\n")

    result = _run(root)

    assert result.returncode == 1, result.stdout + result.stderr
    assert "Traceback" not in result.stderr
    assert outside.as_posix() in result.stdout.splitlines()[-1]


@pytest.mark.skipif(sys.platform == "win32", reason="grupa procesów z samymi zombie jest tylko na POSIX")
def test_grupa_skryptu_z_samymi_zombie_nie_wywraca_runnera(tmp_path: Path) -> None:
    ready = tmp_path / "potomek-gotowy"
    child = (
        "import os, pathlib, subprocess, sys, time\n"
        "subprocess.Popen([sys.executable, '-c', 'pass']).pid\n"
        "os.setsid()\n"
        f"time.sleep(1)\npathlib.Path({str(ready)!r}).write_text(str(os.getpid()))\ntime.sleep(600)\n"
    )
    script = (
        f"import pathlib, subprocess, sys, time\n"
        f"subprocess.Popen([sys.executable, '-c', {child!r}], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)\n"
        f"while not pathlib.Path({str(ready)!r}).exists():\n    time.sleep(0.05)\n" + PASSING
    )
    _skill(tmp_path, "verify-a", {"check_a_mutations.py": script})

    try:
        result = _run(tmp_path, "--limit-s", "60")
    finally:
        if ready.exists():
            os.kill(int(ready.read_text()), signal.SIGTERM)

    assert result.returncode == 0, result.stdout + result.stderr
    assert result.stdout.splitlines()[-1] == "MUTACJE SKILLI OK"


def _hard_kill(runner: subprocess.Popen[bytes]) -> None:
    runner.kill()


STOPS: dict[str, Callable[[subprocess.Popen[bytes]], None]] = {"SIGKILL samego runnera": _hard_kill}
if sys.platform != "win32":

    def _stop_like_gate(runner: subprocess.Popen[bytes]) -> None:
        """Sekwencja z tools/hooks/pre-push: SIGTERM do grupy, a po chwili SIGKILL."""

        for signum in (signal.SIGTERM, signal.SIGKILL):
            try:
                os.killpg(runner.pid, signum)
            except (ProcessLookupError, PermissionError):
                break
            time.sleep(2)

    def _ctrl_c(runner: subprocess.Popen[bytes]) -> None:
        os.killpg(runner.pid, signal.SIGINT)

    STOPS |= {"brama pre-push": _stop_like_gate, "Ctrl+C": _ctrl_c}


@pytest.mark.parametrize("stop", sorted(STOPS))
def test_przerwany_runner_nie_zostawia_skryptu_mutacji(tmp_path: Path, stop: str) -> None:
    ready, marker = tmp_path / "skrypt-gotowy", tmp_path / "skrypt-przezyl"
    script = (
        f"import os, pathlib, time\npathlib.Path({str(ready)!r}).write_text(str(os.getpid()))\n"
        f"time.sleep(5)\npathlib.Path({str(marker)!r}).touch()\ntime.sleep(600)\n"
    )
    _skill(tmp_path, "verify-a", {"check_a_mutations.py": script})
    (tmp_path / "tools").mkdir()
    shutil.copy(TOOL, tmp_path / "tools" / TOOL.name)
    runner = subprocess.Popen(
        [sys.executable, str(tmp_path / "tools" / TOOL.name)],
        cwd=tmp_path,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        start_new_session=sys.platform != "win32",
    )
    try:
        deadline = time.monotonic() + 60
        while not ready.exists() and time.monotonic() < deadline:
            time.sleep(0.05)
        assert ready.exists(), "skrypt mutacji nie ruszył"
        STOPS[stop](runner)
        runner.wait(timeout=30)
        time.sleep(7)

        assert not marker.exists(), "skrypt mutacji przeżył runner"
    finally:
        runner.kill()
        runner.wait()
        if ready.exists():
            with contextlib.suppress(OSError):
                os.kill(int(ready.read_text()), signal.SIGTERM)

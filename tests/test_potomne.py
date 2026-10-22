"""``tools/potomne.py``: drzewo procesów polecenia i kopia commitu nie przeżywają wyniku ani narzędzia.

Macierz przypadków biegnie raz, na interfejsie modułu i na prawdziwych procesach. Narzędzia, które go
używają, mają po jednym teście, że ich procesy giną razem z nimi.
"""

from __future__ import annotations

from collections.abc import Callable
import contextlib
import os
from pathlib import Path
import re
import signal
import subprocess
import sys
import threading
import time

import pytest

from tests.fixtures.git_repo import commit, git
from tests.fixtures.potomne import TOOLS, beating, potomne, with_grandchild

POSIX_ONLY = pytest.mark.skipif(sys.platform == "win32", reason="sesje, grupy procesów i sygnały są tylko na POSIX")
OWN_TREE_OR_COPY = re.compile(
    r"killpg|taskkill|start_new_session|process_group|setsid|setpgid|setpgrp|CreateJobObject|CREATE_NEW_PROCESS_GROUP"
    r"|[\"']worktree[\"'],\s*[\"']add[\"']"
)


def _repository(path: Path) -> Path:
    path.mkdir()
    git(path, "init", "--quiet")
    (path / "plik.txt").write_text("w commicie\n", encoding="utf-8")
    commit(path, "baza")
    (path / "plik.txt").write_text("w checkoucie\n", encoding="utf-8")
    return path


def _worktrees(repo: Path) -> int:
    return git(repo, "worktree", "list", "--porcelain").count("worktree ")


def _wait_for(condition: Callable[[], bool], seconds: float = 60) -> None:
    deadline = time.monotonic() + seconds
    while not condition() and time.monotonic() < deadline:
        time.sleep(0.05)


def test_potomek_trzymajacy_wyjscie_ginie_z_koncem_polecenia_a_wynik_jest_pelny(tmp_path: Path) -> None:
    beats = tmp_path / "wnuk-zyje"

    done = potomne.run(
        with_grandchild(beats, "print('gotowe'); print('uwaga', file=sys.stderr); sys.exit(3)"), cwd=tmp_path
    )

    assert (done.returncode, done.stdout, done.stderr) == (3, "gotowe\n", "uwaga\n")
    assert not beating(beats)


def test_echo_drukuje_wyjscie_razem_z_stderr(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    code = "import sys; print('a', flush=True); print('b', file=sys.stderr, flush=True)"

    done = potomne.run([sys.executable, "-c", code], cwd=tmp_path, echo=True)

    assert (done.stdout, done.stderr, capsys.readouterr().out) == ("a\nb\n", "", "a\nb\n")


def test_po_limicie_drzewo_ginie_a_run_rzuca_timeout(tmp_path: Path) -> None:
    beats = tmp_path / "wnuk-zyje"

    with pytest.raises(subprocess.TimeoutExpired):
        potomne.run(with_grandchild(beats, "time.sleep(60)"), cwd=tmp_path, timeout=5)

    assert not beating(beats)


def test_stop_konczy_trwajace_polecenie_a_nowe_nie_biegnie(tmp_path: Path) -> None:
    beats, marker = tmp_path / "wnuk-zyje", tmp_path / "nowe-polecenie"
    stop = threading.Event()
    raised: list[str] = []

    def running() -> None:
        try:
            potomne.run(with_grandchild(beats, "time.sleep(60)"), cwd=tmp_path, stop=stop)
        except potomne.Stopped:
            raised.append("Stopped")

    thread = threading.Thread(target=running)
    thread.start()
    _wait_for(beats.exists)
    stop.set()
    thread.join(timeout=10)

    assert raised == ["Stopped"]
    assert not beating(beats)
    with pytest.raises(potomne.Stopped):
        potomne.run([sys.executable, "-c", f"open({str(marker)!r}, 'w')"], cwd=tmp_path, stop=stop)
    time.sleep(1)
    assert not marker.exists()


@POSIX_ONLY
def test_grupa_z_samymi_zombie_nie_wywraca_konca_polecenia(tmp_path: Path) -> None:
    ready = tmp_path / "potomek-gotowy"
    child = (
        "import os, pathlib, subprocess, sys, time\n"
        "subprocess.Popen([sys.executable, '-c', 'pass'])\n"
        "os.setsid()\n"
        f"time.sleep(1)\npathlib.Path({str(ready)!r}).write_text(str(os.getpid()))\ntime.sleep(600)\n"
    )
    code = (
        "import pathlib, subprocess, sys, time\n"
        f"subprocess.Popen([sys.executable, '-c', {child!r}], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)\n"
        f"while not pathlib.Path({str(ready)!r}).exists():\n    time.sleep(0.05)\n"
        "print('gotowe')\n"
    )

    try:
        done = potomne.run([sys.executable, "-c", code], cwd=tmp_path, timeout=60)
    finally:
        if ready.exists():
            os.kill(int(ready.read_text()), signal.SIGTERM)

    assert (done.returncode, done.stdout) == (0, "gotowe\n")


@POSIX_ONLY
def test_potomek_spoza_drzewa_z_otwartym_wyjsciem_nie_wstrzymuje_wyniku(tmp_path: Path) -> None:
    ready = tmp_path / "potomek-gotowy"
    child = f"import os, pathlib, time\nos.setsid()\npathlib.Path({str(ready)!r}).write_text(str(os.getpid()))\ntime.sleep(600)\n"
    code = (
        "import pathlib, subprocess, sys, time\n"
        f"subprocess.Popen([sys.executable, '-c', {child!r}])\n"
        f"while not pathlib.Path({str(ready)!r}).exists():\n    time.sleep(0.05)\n"
        "print('gotowe')\n"
    )

    started = time.monotonic()
    try:
        done = potomne.run([sys.executable, "-c", code], cwd=tmp_path)
    finally:
        os.kill(int(ready.read_text()), signal.SIGTERM)

    assert (done.returncode, done.stdout) == (0, "gotowe\n")
    assert time.monotonic() - started < 30


@pytest.mark.parametrize("ending", ["koniec bloku", "wyjątek", "zablokowana kopia"])
def test_kopia_commitu_ma_jego_drzewo_i_znika_z_blokiem(tmp_path: Path, ending: str) -> None:
    repo = _repository(tmp_path / "repo")
    seen: tuple[str, int] | None = None

    with contextlib.suppress(RuntimeError), potomne.commit_copy(repo, "HEAD") as copy:
        seen = ((copy / "plik.txt").read_text(encoding="utf-8"), _worktrees(repo))
        if ending == "zablokowana kopia":
            git(repo, "worktree", "lock", str(copy))
        if ending == "wyjątek":
            raise RuntimeError

    assert seen == ("w commicie\n", 2)
    assert (copy.parent.exists(), _worktrees(repo)) == (False, 1)


def _kill(tool: subprocess.Popen[bytes]) -> None:
    tool.kill()


TOOL_STOPS: dict[str, Callable[[subprocess.Popen[bytes]], None]] = {"SIGKILL narzędzia": _kill}
if sys.platform != "win32":

    def _kill_group(tool: subprocess.Popen[bytes]) -> None:
        os.killpg(tool.pid, signal.SIGKILL)

    def _ctrl_c(tool: subprocess.Popen[bytes]) -> None:
        os.killpg(tool.pid, signal.SIGINT)

    TOOL_STOPS |= {"SIGKILL grupy narzędzia": _kill_group, "Ctrl+C": _ctrl_c}


@pytest.mark.parametrize("stop", sorted(TOOL_STOPS))
def test_zabite_narzedzie_nie_zostawia_drzewa_ani_kopii(tmp_path: Path, stop: str) -> None:
    repo = _repository(tmp_path / "repo")
    scratch = tmp_path / "tmp"
    scratch.mkdir()
    beats = tmp_path / "wnuk-zyje"
    code = (
        f"import pathlib, sys\nsys.path.insert(0, {str(TOOLS)!r})\nimport potomne\n"
        f"with potomne.commit_copy(pathlib.Path({str(repo)!r}), 'HEAD') as copy:\n"
        f"    potomne.run({with_grandchild(beats, 'time.sleep(60)')!r}, cwd=copy)\n"
    )
    tool = subprocess.Popen(
        [sys.executable, "-c", code],
        env={**os.environ, "TMPDIR": str(scratch)},
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=sys.platform != "win32",
    )
    try:
        _wait_for(beats.exists)
        assert beats.exists(), "narzędzie nie uruchomiło polecenia"

        TOOL_STOPS[stop](tool)
        tool.wait(timeout=20)
        _wait_for(lambda: not any(scratch.iterdir()), seconds=20)

        assert not beating(beats)
        assert (list(scratch.iterdir()), _worktrees(repo)) == ([], 1)
    finally:
        tool.kill()
        tool.wait()


@POSIX_ONLY
def test_bez_straznika_narzedzie_przerywa_zamiast_dzialac_bez_sprzatania(tmp_path: Path) -> None:
    code = (
        f"import os, pathlib, signal, subprocess, sys\nsys.path.insert(0, {str(TOOLS)!r})\nimport potomne\n"
        "here = pathlib.Path.cwd()\n"
        "potomne.run([sys.executable, '-c', 'pass'], cwd=here)\n"
        "found = subprocess.run(['pgrep', '-P', str(os.getpid()), '-f', 'potomne.py'], capture_output=True, text=True)\n"
        "guard = int(found.stdout.split()[0])\n"
        "os.kill(guard, signal.SIGKILL)\n"
        "os.waitpid(guard, 0)\n"
        "for name, attempt in [('run', lambda: potomne.run([sys.executable, '-c', 'pass'], cwd=here)),\n"
        "                      ('commit_copy', lambda: potomne.commit_copy(here, 'HEAD').__enter__())]:\n"
        "    try:\n"
        "        attempt()\n"
        "        print(name, 'bez błędu')\n"
        "    except OSError as error:\n"
        "        print(name, type(error).__name__, 'strażnik' in str(error))\n"
    )

    answered = subprocess.run(
        [sys.executable, "-c", code], cwd=tmp_path, capture_output=True, text=True, encoding="utf-8", timeout=60
    )

    assert answered.stdout.splitlines() == ["run OSError True", "commit_copy OSError True"], answered.stderr


def test_drzewa_procesow_i_kopie_commitow_narzedzi_buduje_tylko_potomne() -> None:
    sources = [path for path in [*TOOLS.rglob("*.py"), TOOLS / "hooks" / "pre-push"] if path != TOOLS / "potomne.py"]

    found = [
        f"{path.relative_to(TOOLS.parent).as_posix()}:{number}: {line.strip()}"
        for path in sorted(sources)
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1)
        if OWN_TREE_OR_COPY.search(line)
    ]

    assert found == [], "polecenie, które trwa, i kopię commitu narzędzie uruchamia przez potomne.run i potomne.commit_copy"

"""``tools/potomne.py``: drzewo procesów polecenia i kopia commitu nie przeżywają wyniku ani narzędzia.

Macierz przypadków biegnie raz, na interfejsie modułu i na prawdziwych procesach. Narzędzia, które go
używają, mają po jednym teście, że ich procesy giną razem z nimi.
"""

from __future__ import annotations

import ast
from collections.abc import Callable, Iterator, Sequence
import contextlib
import os
from pathlib import Path
import re
import shutil
import signal
import subprocess
import sys
import threading
import time

import pytest

from tests.fixtures.git_repo import commit, git
from tests.fixtures.potomne import TOOLS, beating, potomne, wait_for, with_grandchild, worktrees

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
    wait_for(beats.exists)
    stop.set()
    thread.join(timeout=10)

    assert raised == ["Stopped"]
    assert not beating(beats)
    with pytest.raises(potomne.Stopped):
        potomne.run([sys.executable, "-c", f"open({str(marker)!r}, 'w')"], cwd=tmp_path, stop=stop)
    assert not wait_for(marker.exists, 1)


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
        seen = ((copy / "plik.txt").read_text(encoding="utf-8"), len(worktrees(repo)))
        if ending == "zablokowana kopia":
            git(repo, "worktree", "lock", str(copy))
        if ending == "wyjątek":
            raise RuntimeError

    assert seen == ("w commicie\n", 2)
    assert (copy.exists(), len(worktrees(repo))) == (False, 1)


def test_nieudana_kopia_commitu_niesie_komunikat_gita(tmp_path: Path) -> None:
    repo = _repository(tmp_path / "repo")

    with pytest.raises(subprocess.CalledProcessError) as raised, potomne.commit_copy(repo, "nie-ma-takiego-commitu"):
        pass

    said = raised.value.stderr.strip()
    assert said and said in str(raised.value)
    assert len(worktrees(repo)) == 1


# Atrapa gita zapisuje początek i koniec każdego polecenia, które zmienia .git/worktrees; ``add`` trwa sekundę dłużej.
WORKTREE_LOG = """#!/bin/sh
case "$1 $2" in
"worktree add"|"worktree remove"|"worktree prune")
  echo "start $2" >> "$SHIM_LOG"
  if [ "$2" = add ]; then sleep 1; fi
  "$SHIM_GIT" "$@"; code=$?
  echo "end $2" >> "$SHIM_LOG"
  exit $code;;
esac
exec "$SHIM_GIT" "$@"
"""


def _overlapping(log: list[str]) -> list[str]:
    running: list[str] = []
    found = []
    for line in log:
        state, command = line.split()
        if state == "end":
            running.remove(command)
            continue
        if running:
            found.append(f"{command} w trakcie {', '.join(running)}")
        running.append(command)
    return found


@POSIX_ONLY
def test_kopie_commitu_z_wielu_watkow_nie_zmieniaja_worktree_naraz(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    repo = _repository(tmp_path / "repo")
    log, shim = tmp_path / "git.log", tmp_path / "atrapa" / "git"
    shim.parent.mkdir()
    shim.write_text(WORKTREE_LOG, encoding="utf-8")
    shim.chmod(0o755)
    monkeypatch.setenv("SHIM_GIT", str(shutil.which("git")))
    monkeypatch.setenv("SHIM_LOG", str(log))
    monkeypatch.setenv("PATH", f"{shim.parent}{os.pathsep}{os.environ['PATH']}")
    seen: list[str] = []

    def second_copy() -> None:
        with potomne.commit_copy(repo, "HEAD") as copy:
            seen.append((copy / "plik.txt").read_text(encoding="utf-8"))

    with potomne.commit_copy(repo, "HEAD") as copy:
        seen.append((copy / "plik.txt").read_text(encoding="utf-8"))
        second = threading.Thread(target=second_copy)
        second.start()
        wait_for(lambda: log.read_text(encoding="utf-8").count("start add") == 2, 30)
    second.join(timeout=60)

    assert seen == ["w commicie\n", "w commicie\n"]
    assert _overlapping(log.read_text(encoding="utf-8").splitlines()) == []


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
        wait_for(beats.exists)
        assert beats.exists(), "narzędzie nie uruchomiło polecenia"

        TOOL_STOPS[stop](tool)
        tool.wait(timeout=20)
        wait_for(lambda: not any(scratch.iterdir()), seconds=20)

        assert not beating(beats)
        assert (list(scratch.iterdir()), len(worktrees(repo))) == ([], 1)
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


def _tool_sources() -> list[Path]:
    return sorted(path for path in [*TOOLS.rglob("*.py"), TOOLS / "hooks" / "pre-push"] if path != TOOLS / "potomne.py")


def test_drzewa_procesow_i_kopie_commitow_narzedzi_buduje_tylko_potomne() -> None:
    found = [
        f"{path.relative_to(TOOLS.parent).as_posix()}:{number}: {line.strip()}"
        for path in _tool_sources()
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1)
        if OWN_TREE_OR_COPY.search(line)
    ]

    assert not found, "\n".join(
        [*found, "Polecenie, które trwa, i kopię commitu narzędzie uruchamia przez potomne.run i potomne.commit_copy."]
    )


FAST_PROGRAMS = frozenset({"git", "gh", "ps"})
# Lokalne podpolecenia gita, które kończą się w ułamku sekundy i nie uruchamiają pomocników (sieć, hooki).
FAST_GIT = frozenset(
    {
        "branch",
        "config",
        "diff",
        "for-each-ref",
        "log",
        "ls-files",
        "merge-base",
        "merge-tree",
        "rev-list",
        "rev-parse",
        "show-ref",
        "status",
        "worktree",
    }
)
NIGHT_STREAMS = {
    "tools/hooks/pre-push": "strumień nocy W1 (#290), do zdjęcia po merge'u",
    "tools/setup_worktree.py": "strumień nocy W1 (plik W1 w planie nocy) i #286, do zdjęcia po merge'u",
    "tools/promuj_stabilna.py": "strumień nocy W7 (git push i ls-remote), do zdjęcia po merge'u",
}
SUBPROCESS_LAUNCHES = frozenset({"run", "Popen", "call", "check_call", "check_output", "getoutput", "getstatusoutput"})


def _launches(tree: ast.AST) -> Iterator[ast.Call]:
    from_subprocess = {
        alias.asname or alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module == "subprocess"
        for alias in node.names
    }
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        function = node.func
        if isinstance(function, ast.Attribute) and isinstance(function.value, ast.Name):
            module, name = function.value.id, function.attr
            if (module == "subprocess" and name in SUBPROCESS_LAUNCHES) or (module == "os" and name in {"system", "popen"}):
                yield node
        elif isinstance(function, ast.Name) and function.id in from_subprocess:
            yield node


def _command(call: ast.Call) -> ast.expr | None:
    return call.args[0] if call.args else next((keyword.value for keyword in call.keywords if keyword.arg == "args"), None)


def _program(command: ast.expr | None) -> str | None:
    if not isinstance(command, (ast.List, ast.Tuple)) or not command.elts:
        return None
    head = command.elts[0]
    if isinstance(head, ast.Constant) and isinstance(head.value, str):
        return head.value
    return head.id if isinstance(head, ast.Name) else None


def _git_subcommand(arguments: Sequence[ast.expr]) -> str | ast.Starred | None:
    """Podpolecenie po opcjach ``-C``/``-c``; ``Starred``, gdy przychodzi z argumentów funkcji."""

    position = 0
    while position < len(arguments):
        argument = arguments[position]
        if isinstance(argument, ast.Starred):
            return argument
        if isinstance(argument, ast.Constant) and argument.value in ("-C", "-c"):
            position += 2
            continue
        return argument.value if isinstance(argument, ast.Constant) and isinstance(argument.value, str) else None
    return None


def _slow_launches(source: str) -> Iterator[tuple[int, str, str]]:
    """Wiersz, wywołanie i polecenie każdego uruchomienia spoza szybkich ``git``, ``gh`` i ``ps``.

    Funkcję, która przekazuje gitowi swoje ``*args``, sprawdza się tam, gdzie ją wołają.
    """

    tree = ast.parse(source)
    wrappers: dict[str, int] = {}
    for call in _launches(tree):
        command = _command(call)
        program = _program(command)
        if program not in FAST_PROGRAMS:
            shown = ast.unparse(command.elts[0]) if isinstance(command, (ast.List, ast.Tuple)) else ast.unparse(command or call)
            yield call.lineno, ast.unparse(call.func), shown
        elif program == "git" and isinstance(command, (ast.List, ast.Tuple)):
            subcommand = _git_subcommand(command.elts[1:])
            if isinstance(subcommand, ast.Starred):
                wrappers |= _passing_own_arguments(tree, call, subcommand)
            elif subcommand not in FAST_GIT:
                yield call.lineno, ast.unparse(call.func), f"git {subcommand or '?'}"
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id in wrappers:
            subcommand = _git_subcommand(node.args[wrappers[node.func.id] :])
            if not isinstance(subcommand, ast.Starred) and subcommand not in FAST_GIT:
                yield node.lineno, f"{node.func.id}()", f"git {subcommand or '?'}"


def _passing_own_arguments(tree: ast.Module, call: ast.Call, passed: ast.Starred) -> dict[str, int]:
    """Funkcja z ``call``, która przekazuje gitowi swoje ``*args``, i pozycja pierwszego z nich."""

    return {
        function.name: len(function.args.posonlyargs) + len(function.args.args)
        for function in ast.walk(tree)
        if isinstance(function, (ast.FunctionDef, ast.AsyncFunctionDef))
        and function.args.vararg is not None
        and ast.unparse(passed.value) == function.args.vararg.arg
        and any(node is call for node in ast.walk(function))
    }


def test_polecenia_narzedzi_ktore_trwaja_biegna_przez_potomne_run() -> None:
    found = [
        f"{name}:{number}: {launcher} uruchamia {command} poza potomne.run"
        for path in _tool_sources()
        if (name := path.relative_to(TOOLS.parent).as_posix()) not in NIGHT_STREAMS
        for number, launcher, command in _slow_launches(path.read_text(encoding="utf-8"))
    ]

    assert not found, "\n".join(
        [
            *found,
            "Polecenie, które trwa albo uruchamia własne procesy, uruchom przez potomne.run z tools/potomne.py; "
            "zwykłe subprocess zostaje tylko dla git, gh i ps, a nowe szybkie, lokalne podpolecenie gita dopisz do FAST_GIT.",
        ]
    )

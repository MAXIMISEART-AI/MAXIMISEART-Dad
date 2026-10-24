"""Zwiad #401: zapisuje drzewo procesów, wynik taskkill i znaczniki czasu pomocnika przy każdym powtórzeniu."""

from __future__ import annotations

import ctypes
import json
import os
from pathlib import Path
import subprocess
import sys
import time

import pytest

from rozliczenia.centrum import tool_update
from rozliczenia.centrum.tool_update import ToolClone, UpdateResult

pytestmark = pytest.mark.skipif(sys.platform != "win32", reason="zwiad Windows")

OUT = Path(os.environ.get("ZWIAD_OUT", "zwiad"))
SNAPSHOT = os.environ.get("ZWIAD_SNAPSHOT", "1") == "1"


def _k32():  # type: ignore[no-untyped-def]
    from ctypes import wintypes as w

    class Entry(ctypes.Structure):
        _fields_ = [
            ("dwSize", w.DWORD),
            ("cntUsage", w.DWORD),
            ("th32ProcessID", w.DWORD),
            ("th32DefaultHeapID", ctypes.c_void_p),
            ("th32ModuleID", w.DWORD),
            ("cntThreads", w.DWORD),
            ("th32ParentProcessID", w.DWORD),
            ("pcPriClassBase", w.LONG),
            ("dwFlags", w.DWORD),
            ("szExeFile", w.WCHAR * 260),
        ]

    k32 = ctypes.WinDLL("kernel32", use_last_error=True)  # type: ignore[attr-defined]
    k32.CreateToolhelp32Snapshot.restype = w.HANDLE
    k32.CreateToolhelp32Snapshot.argtypes = [w.DWORD, w.DWORD]
    k32.Process32FirstW.argtypes = [w.HANDLE, ctypes.POINTER(Entry)]
    k32.Process32NextW.argtypes = [w.HANDLE, ctypes.POINTER(Entry)]
    k32.OpenProcess.restype = w.HANDLE
    k32.OpenProcess.argtypes = [w.DWORD, w.BOOL, w.DWORD]
    k32.WaitForSingleObject.argtypes = [w.HANDLE, w.DWORD]
    k32.GetExitCodeProcess.argtypes = [w.HANDLE, ctypes.POINTER(w.DWORD)]
    k32.CloseHandle.argtypes = [w.HANDLE]
    return k32, Entry, w


def snapshot() -> list[tuple[int, int, str]]:
    k32, Entry, _ = _k32()
    handle = k32.CreateToolhelp32Snapshot(2, 0)
    entry = Entry()
    entry.dwSize = ctypes.sizeof(entry)
    rows = []
    ok = k32.Process32FirstW(handle, ctypes.byref(entry))
    while ok:
        rows.append((entry.th32ProcessID, entry.th32ParentProcessID, entry.szExeFile))
        ok = k32.Process32NextW(handle, ctypes.byref(entry))
    k32.CloseHandle(handle)
    return rows


def descendants(rows: list[tuple[int, int, str]], root: int) -> list[tuple[int, int, str]]:
    found = [row for row in rows if row[0] == root]
    frontier = {root}
    while frontier:
        children = [row for row in rows if row[1] in frontier and row not in found and row[0] != row[1]]
        found += children
        frontier = {row[0] for row in children}
    return found


def state(pid: int) -> str:
    k32, _, w = _k32()
    handle = k32.OpenProcess(0x1000 | 0x00100000, False, pid)
    if not handle:
        return f"open-failed:{ctypes.get_last_error()}"  # type: ignore[attr-defined]
    code = w.DWORD()
    k32.GetExitCodeProcess(handle, ctypes.byref(code))
    waited = k32.WaitForSingleObject(handle, 0)
    k32.CloseHandle(handle)
    return f"wait={waited:#x},exit={code.value}"


def fake_git(tmp_path: Path, commit: str, heartbeat: Path) -> Path:
    helper_pid = tmp_path / "helper.pid"
    script_pid = tmp_path / "script.pid"
    helper = (
        "import os, time\n"
        f"open({str(helper_pid)!r}, 'w').write(f'{{os.getpid()}} {{os.getppid()}}')\n"
        "for _ in range(600):\n"
        f"    open({str(heartbeat)!r}, 'a').write(f'{{time.time():.6f}}\\n')\n"
        "    time.sleep(0.05)\n"
    )
    script = tmp_path / "git_ze_stojacym_pobraniem.py"
    script.write_text(
        "import os, subprocess, sys, time\n"
        f"COMMIT = {commit!r}\n"
        "args = [arg for index, arg in enumerate(sys.argv[1:]) if arg != '-c' and sys.argv[index] != '-c']\n"
        "command = args[2] if args[:1] == ['-C'] else args[0]\n"
        "if command == 'fetch':\n"
        f"    open({str(script_pid)!r}, 'w').write(f'{{os.getpid()}} {{os.getppid()}} {{time.time():.6f}}')\n"
        f"    child = subprocess.Popen([sys.executable, '-c', {helper!r}])\n"
        f"    open({str(script_pid)!r}, 'a').write(f' spawned={{child.pid}} {{time.time():.6f}}')\n"
        "    time.sleep(60)\n"
        "print('main' if command == 'symbolic-ref' else COMMIT)\n",
        encoding="utf-8",
    )
    git = tmp_path / "git.cmd"
    git.write_text(f'@"{sys.executable}" "{script}" %*\n', encoding="utf-8")
    return git


@pytest.mark.parametrize("attempt", range(int(os.environ.get("ZWIAD_N", "300"))))
def test_sonda(attempt: int, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Nie podmienia zabijania: po powrocie update() pyta system wprost, czy pomocnik Gita jeszcze żyje."""
    monkeypatch.setattr(tool_update, "_FETCH_TIMEOUT_S", 2.0)
    commit = "1" * 40
    heartbeat = tmp_path / "pomocnik-zyje"
    git = fake_git(tmp_path, commit, heartbeat)
    result = ToolClone(tmp_path, origin="https://example.invalid/narzedzie.git", find_git=lambda: git).update()
    t_return = time.time()
    helper_pid_file = tmp_path / "helper.pid"
    helper = helper_pid_file.read_text() if helper_pid_file.exists() else None
    at_return = state(int(helper.split()[0])) if helper else None
    beats = [float(line) for line in heartbeat.read_text().split()] if heartbeat.exists() else []
    record = {"attempt": attempt, "result_ok": result == UpdateResult("BRAK_POLACZENIA", before=commit, after=None),
              "helper": helper, "at_return": at_return, "beats": len(beats), "t_return": t_return}
    OUT.mkdir(parents=True, exist_ok=True)
    with (OUT / f"{os.environ.get('PYTEST_XDIST_WORKER', 'gw')}.jsonl").open("a", encoding="utf-8") as file:
        file.write(json.dumps(record) + "\n")

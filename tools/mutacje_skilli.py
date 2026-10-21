"""Uruchamia po kolei skrypty mutacji wszystkich skilli weryfikacji, jak zadanie CI mutations.

Skrypt mutacji skilla to ``.agents/skills/<skill>/scripts/check_<co>_mutations.py``: dowodzi, że
sprawdzenie skilla pada na zepsutych wariantach kodu, i kończy się linią ``MUTACJE OK``. Nowy
skrypt o takiej nazwie trafia do CI i do ``tools/ci_lokalnie.py`` bez wpisu w ``ci.yml``.

Skrypt nie może zgubić się po cichu. FAIL dostaje plik ``.py`` w skillu z ``mutation`` w nazwie,
który nie pasuje do wzorca, oraz skrypt mutacji wskazany w ``SKILL.md`` skilla, którego nie ma.
FAIL dostaje też skrypt, który przekroczył limit czasu, skończył się kodem innym niż 0 albo nie
wydrukował na końcu ``MUTACJE OK``. Limit obejmuje też procesy potomne skryptu: po końcu
skryptu albo po limicie runner zabija je razem z nim. Kończy się ``MUTACJE SKILLI OK`` albo
``MUTACJE SKILLI FAIL | <skrypty>``.

    py -3 tools/mutacje_skilli.py                  # Windows
    .venv/bin/python tools/mutacje_skilli.py       # macOS i Linux
"""

from __future__ import annotations

import argparse
import os
from pathlib import Path
import re
import signal
import subprocess
import sys
import threading
import time
from typing import IO

ROOT = Path(__file__).resolve().parents[1]
SKILLS = ROOT / ".agents" / "skills"
PATTERN = "check_*_mutations.py"
# Wywołanie skryptu mutacji w SKILL.md; ścieżka bez ``.agents`` na początku liczy się od folderu skilla.
MENTION = re.compile(r"[\w.\\/-]*scripts[\\/]check_\w+_mutations\.py")
VERDICT = "MUTACJE OK"
# Najdłuższy skrypt trwa w CI od 4 do ponad 8 min; limit łapie zawieszenie, a nie wolny runner.
LIMIT_S = 30 * 60


def _name(path: Path) -> str:
    return path.relative_to(ROOT).as_posix()


def _lost(scripts: list[Path]) -> dict[str, str]:
    """Skrypty mutacji, których runner by nie uruchomił, z powodem."""

    lost = {
        _name(path): f"nazwa spoza wzorca scripts/{PATTERN}"
        for path in SKILLS.glob("*/**/*.py")
        if "mutation" in path.name.lower() and path not in scripts
    }
    for skill_md in SKILLS.glob("*/SKILL.md"):
        for mentioned in set(MENTION.findall(skill_md.read_text(encoding="utf-8"))):
            relative = mentioned.replace("\\", "/")
            base = ROOT if relative.startswith(".agents/") else skill_md.parent
            path = Path(os.path.normpath(base / relative))
            if path not in scripts:
                lost.setdefault(_name(path), f"wskazany w {_name(skill_md)}, a nie ma go pod tą nazwą")
    return lost


def _echo(stream: IO[str], lines: list[str]) -> None:
    for line in stream:
        print(line, end="", flush=True)
        lines.append(line)


class _Tree:
    """Skrypt z jego procesami potomnymi, także tymi, które przeżyły skrypt."""

    def __init__(self, process: subprocess.Popen[str]) -> None:
        self.process = process
        if sys.platform == "win32":
            # Job Object obejmuje potomków także po końcu skryptu, a taskkill /T już ich wtedy nie znajduje.
            import ctypes
            from ctypes import wintypes

            self.kernel32 = kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
            kernel32.CreateJobObjectW.restype = kernel32.OpenProcess.restype = wintypes.HANDLE
            self.job = wintypes.HANDLE(kernel32.CreateJobObjectW(None, None))
            handle = wintypes.HANDLE(kernel32.OpenProcess(0x0101, False, process.pid))  # TERMINATE | SET_QUOTA
            if not self.job.value or not handle.value or not kernel32.AssignProcessToJobObject(self.job, handle):
                raise OSError(ctypes.get_last_error(), "Job Object dla skryptu mutacji")
            kernel32.CloseHandle(handle)

    def kill(self) -> None:
        if sys.platform == "win32":
            self.kernel32.TerminateJobObject(self.job, 1)
            self.kernel32.CloseHandle(self.job)
        else:
            try:
                os.killpg(self.process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
        self.process.wait()


def _run(script: Path, limit_s: float) -> str | None:
    """Uruchamia skrypt z echem wyjścia; zwraca powód porażki albo ``None``."""

    process = subprocess.Popen(
        [sys.executable, str(script)],
        cwd=ROOT,
        env={**os.environ, "PYTHONIOENCODING": "utf-8"},
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
        # Własna grupa procesów, żeby po limicie zabić też procesy potomne skryptu.
        start_new_session=sys.platform != "win32",
    )
    assert process.stdout is not None
    deadline = time.monotonic() + limit_s
    tree = _Tree(process)
    lines: list[str] = []
    reader = threading.Thread(target=_echo, args=(process.stdout, lines), daemon=True)
    reader.start()
    try:
        process.wait(timeout=limit_s)
    except subprocess.TimeoutExpired:
        pass
    tree.kill()
    # Potomek, który uciekł z grupy procesów, trzyma potok otwarty; czekanie na niego też mieści się w limicie.
    reader.join(timeout=max(deadline - time.monotonic(), 5))
    if reader.is_alive() or time.monotonic() > deadline:
        return f"przekroczył limit {limit_s:.0f} s"
    code = process.returncode
    if code != 0:
        return f"kod wyjścia {code}"
    if [line.strip() for line in lines if line.strip()][-1:] != [VERDICT]:
        return f"brak końcowej linii {VERDICT}"
    return None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--limit-s", type=float, default=LIMIT_S, help="Limit czasu jednego skryptu w sekundach.")
    args = parser.parse_args(argv)
    scripts = sorted(SKILLS.glob(f"*/scripts/{PATTERN}"))
    failed = _lost(scripts)
    for name, why in sorted(failed.items()):
        print(f"FAIL {name}: {why}", flush=True)
    if not scripts and not failed:
        print(f"MUTACJE SKILLI FAIL | brak skryptów .agents/skills/*/scripts/{PATTERN}")
        return 1
    # Po kolei: mutacje kilku skilli naraz na czterech rdzeniach runnera przekraczają swoje limity czasu.
    for script in scripts:
        name = _name(script)
        print(f"== {name}", flush=True)
        started = time.monotonic()
        reason = _run(script, args.limit_s)
        elapsed = f"({time.monotonic() - started:.0f} s)"
        print(f"OK   {name} {elapsed}" if reason is None else f"FAIL {name} {elapsed}: {reason}", flush=True)
        if reason is not None:
            failed[name] = reason
    if failed:
        print(f"MUTACJE SKILLI FAIL | {', '.join(sorted(failed))}")
        return 1
    print("MUTACJE SKILLI OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

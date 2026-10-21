"""One measurement at a time on this machine: ``wydajnosc`` waits for a quiet CPU, other runs wait for it.

A measurement (``--feature wydajnosc``) takes ``pomiar.lock`` in a lock directory
shared by every checkout and worktree on the machine, then waits until no other
verification run is registered there and no test run, benchmark or browser drive
is running (on macOS and Linux, read from ``ps``). Every other run registers a
``run-*.pid`` file for its duration and first waits while a measurement holds
the lock. Locks and registrations of a process that died are taken over. Each
side waits at most ``timeout_s`` and then fails with what kept the machine busy.

    python quiet_machine.py --status   # who holds the machine now
"""

from __future__ import annotations

import argparse
from collections.abc import Callable, Iterator
from contextlib import contextmanager
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import uuid

LOCK_DIRECTORY = Path(tempfile.gettempdir()) / "verify-centrum-rozliczen"
MEASUREMENT_LOCK = "pomiar.lock"
WAIT_TIMEOUT_S = 45 * 60
POLL_S = 5.0
REPORT_EVERY_S = 60.0
# Command-line fragments of work that loads the CPU and is not registered in the lock directory.
BUSY_COMMANDS = (
    "pytest",
    "serve_centrum.py",
    "drive_centrum.py",
    "chrome-headless-shell",
    "run_verification.py",
    "_mutations.py",
    "benchmark_przebiegu.py",
)


class MachineBusy(Exception):
    """The machine did not become quiet within the timeout; the message names what kept it busy."""


def _alive(pid: int) -> bool:
    if pid <= 0:
        return False
    if sys.platform == "win32":
        import ctypes

        kernel32 = ctypes.windll.kernel32
        handle = kernel32.OpenProcess(0x1000, False, pid)  # PROCESS_QUERY_LIMITED_INFORMATION
        if not handle:
            return False
        code = ctypes.c_ulong()
        kernel32.GetExitCodeProcess(handle, ctypes.byref(code))
        kernel32.CloseHandle(handle)
        return code.value == 259  # STILL_ACTIVE
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def _owner(path: Path) -> int:
    try:
        return int(path.read_text(encoding="utf-8").strip() or 0)
    except (OSError, ValueError):
        return 0


def busy_commands() -> list[str]:
    """Running commands from ``BUSY_COMMANDS`` other than this process and its ancestors (``ps``; none on Windows)."""

    if sys.platform == "win32":
        return []
    listing = subprocess.run(["ps", "-Ao", "pid=,ppid=,command="], capture_output=True, text=True, check=False)
    parents: dict[int, int] = {}
    commands: dict[int, str] = {}
    for line in listing.stdout.splitlines():
        fields = line.split(None, 2)
        if len(fields) == 3 and fields[0].isdigit() and fields[1].isdigit():
            parents[int(fields[0])] = int(fields[1])
            commands[int(fields[0])] = fields[2]
    own: set[int] = set()
    pid = os.getpid()
    while pid > 1 and pid not in own:
        own.add(pid)
        pid = parents.get(pid, 0)
    return sorted(
        {fragment for pid, command in commands.items() if pid not in own for fragment in BUSY_COMMANDS if fragment in command}
    )


class QuietMachine:
    def __init__(
        self,
        directory: Path = LOCK_DIRECTORY,
        *,
        timeout_s: float = WAIT_TIMEOUT_S,
        poll_s: float = POLL_S,
        busy_processes: Callable[[], list[str]] = busy_commands,
        report_every_s: float | None = REPORT_EVERY_S,
    ) -> None:
        self._directory = directory
        self._timeout_s = timeout_s
        self._poll_s = poll_s
        self._busy_processes = busy_processes
        self._report_every_s = report_every_s

    @contextmanager
    def measurement(self) -> Iterator[float]:
        """Hold the machine for one measurement; yields how many seconds it waited."""

        started = time.monotonic()
        self._wait("pomiar", self._take_lock)
        try:
            self._wait("pomiar", self._quiet)
            yield time.monotonic() - started
        finally:
            (self._directory / MEASUREMENT_LOCK).unlink(missing_ok=True)

    @contextmanager
    def run(self) -> Iterator[float]:
        """Register one verification run for its duration; yields how many seconds it waited for a measurement."""

        started = time.monotonic()
        self._directory.mkdir(parents=True, exist_ok=True)
        marker = self._directory / f"run-{os.getpid()}-{uuid.uuid4().hex[:8]}.pid"
        try:
            # Register first, then look at the lock: a measurement taking the lock now sees this run and waits.
            marker.write_text(str(os.getpid()), encoding="utf-8")
            while self._measurement_holder() is not None:
                marker.unlink(missing_ok=True)
                self._wait("przebieg", self._measurement_holder)
                marker.write_text(str(os.getpid()), encoding="utf-8")
            yield time.monotonic() - started
        finally:
            marker.unlink(missing_ok=True)

    def status(self) -> list[str]:
        holder = self._measurement_holder()
        return ([] if holder is None else [holder]) + self._registered_runs() + self._busy_processes()

    def _measurement_holder(self) -> str | None:
        lock = self._directory / MEASUREMENT_LOCK
        if not lock.exists():
            return None
        pid = _owner(lock)
        if _alive(pid):
            return f"pomiar wydajnosc (pid {pid})"
        lock.unlink(missing_ok=True)
        return None

    def _registered_runs(self) -> list[str]:
        runs = []
        for marker in sorted(self._directory.glob("run-*.pid")):
            pid = _owner(marker)
            if _alive(pid):
                runs.append(f"przebieg weryfikacji Centrum (pid {pid})")
            else:
                marker.unlink(missing_ok=True)
        return runs

    def _take_lock(self) -> str | None:
        """None once this process holds the lock, otherwise who holds it."""

        self._directory.mkdir(parents=True, exist_ok=True)
        if (holder := self._measurement_holder()) is not None:
            return holder
        try:
            descriptor = os.open(self._directory / MEASUREMENT_LOCK, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError:
            return "pomiar wydajnosc (właśnie zaczęty)"
        with os.fdopen(descriptor, "w", encoding="utf-8") as lock:
            lock.write(str(os.getpid()))
        return None

    def _quiet(self) -> str | None:
        busy = self._registered_runs() + self._busy_processes()
        return ", ".join(busy) if busy else None

    def _wait(self, who: str, blocked: Callable[[], str | None]) -> None:
        deadline = time.monotonic() + self._timeout_s
        reported: float | None = None
        while (blocker := blocked()) is not None:
            now = time.monotonic()
            if now >= deadline:
                raise MachineBusy(f"maszyna nie ucichła w {self._timeout_s:.0f} s; zajmuje ją: {blocker}")
            if self._report_every_s is not None and (reported is None or now - reported >= self._report_every_s):
                print(f"MASZYNA ZAJĘTA | {who} czeka na: {blocker}", flush=True)
                reported = now
            time.sleep(self._poll_s)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--status", action="store_true", help="Print what holds the machine now and exit.")
    parser.parse_args(argv)
    busy = QuietMachine().status()
    print("MASZYNA WOLNA" if not busy else "MASZYNA ZAJĘTA | " + ", ".join(busy))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

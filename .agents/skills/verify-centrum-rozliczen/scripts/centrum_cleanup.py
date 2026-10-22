"""Stop the Centrum this verification run started and remove its run root; evidence is never touched.

The server is stopped only when ``<root>/server.json`` names it and its URL
still answers with Centrum's identity, so a reused PID or another program is
never killed. Processes are never killed by name.
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import shutil
import signal
import subprocess
import sys
import time
import urllib.request


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[4]


def _safe_root(value: str) -> Path:
    root = Path(value).expanduser().resolve()
    parent = (_repo_root() / ".verification" / "runs").resolve()
    try:
        root.relative_to(parent)
    except ValueError as exc:
        raise ValueError(f"Cleanup root must be below {parent}") from exc
    if root == parent:
        raise ValueError("Refusing to remove the whole runs directory")
    return root


def _answers_as_centrum(url: str) -> bool:
    try:
        with urllib.request.urlopen(url + "api/health", timeout=2) as response:
            return bool(json.load(response).get("service") == "centrum-rozliczen")
    except (OSError, ValueError):
        return False


def _stop_server(root: Path) -> str:
    server_file = root / "server.json"
    if not server_file.exists():
        return "no server recorded"
    server = json.loads(server_file.read_text(encoding="utf-8"))
    url, pid = str(server["url"]), int(server["pid"])
    if not _answers_as_centrum(url):
        return "recorded server already stopped"
    if sys.platform == "win32":
        subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"], capture_output=True, check=False)
    else:
        os.kill(pid, signal.SIGTERM)
    deadline = time.monotonic() + 10
    while _answers_as_centrum(url):
        if time.monotonic() > deadline:
            raise OSError(f"Centrum at {url} (pid {pid}) did not stop")
        time.sleep(0.1)
    return f"stopped pid {pid}"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--root", required=True, help="Run root below .verification/runs.")
    args = parser.parse_args(argv)
    try:
        root = _safe_root(args.root)
        stopped = _stop_server(root) if root.exists() else "no run root"
        if root.exists():
            shutil.rmtree(root)
    except (OSError, ValueError) as exc:
        print(f"CLEANUP FAILED: {exc}", file=sys.stderr)
        return 1
    print(f"CLEANUP OK | {stopped} | removed={root}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

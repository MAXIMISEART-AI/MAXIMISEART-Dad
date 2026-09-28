"""Remove one disposable verification run without touching its evidence."""

from __future__ import annotations

import argparse
from pathlib import Path
import shutil
import sys


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


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", required=True)
    args = parser.parse_args(argv)
    try:
        root = _safe_root(args.root)
        if root.exists():
            shutil.rmtree(root)
    except (OSError, ValueError) as exc:
        print(f"CLEANUP FAILED: {exc}", file=sys.stderr)
        return 1
    print(f"CLEANUP OK | removed={root}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""Excel safe writer — OneDrive lock-aware + snapshot-before-write.

Phase 2 implementation target. Stub in Phase 0.

Mitigation:
- Check ~$*.xlsx lock files przed write (Rule antipattern)
- Retry 3x (2/5/10 min) per schedule.yaml
- SHA-256 checksum before/after dla detection of concurrent edits
- Auto-snapshot do state/excel-snapshots/ przed každy write
"""
from __future__ import annotations

import hashlib
import shutil
import time
from datetime import datetime
from pathlib import Path


def is_excel_locked(excel_path: Path) -> bool:
    """Detect OneDrive/Excel lock files in same directory."""
    parent = excel_path.parent
    stem = excel_path.stem
    lock_patterns = [
        f"~${stem}.xlsx",
        f".~lock.{excel_path.name}#",
    ]
    for pattern in lock_patterns:
        if (parent / pattern).exists():
            return True
    return False


def snapshot(excel_path: Path, snapshots_dir: Path) -> Path:
    """Copy Excel to snapshots_dir with timestamp. Returns snapshot path."""
    snapshots_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y-%m-%d-%H%M%S")
    snapshot_path = snapshots_dir / f"{excel_path.stem}-{ts}.xlsx"
    shutil.copy2(excel_path, snapshot_path)
    return snapshot_path


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def wait_for_unlock(excel_path: Path, retry_intervals: list[int]) -> bool:
    """Retry loop — returns True if unlocked, False if still locked after all retries."""
    if not is_excel_locked(excel_path):
        return True
    for interval_sec in retry_intervals:
        time.sleep(interval_sec)
        if not is_excel_locked(excel_path):
            return True
    return False

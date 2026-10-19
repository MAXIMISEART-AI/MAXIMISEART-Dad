"""Create a synthetic folder okresów, Rejestr zleceń, and empty settings directory for one Centrum run."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

from openpyxl import Workbook

# Dad's "today" for the run: Monday 19.10.2026, so the last complete period is 06_12_10_2026,
# whose Folder okresu deliberately does not exist.
TODAY = "2026-10-19"
LAST_COMPLETE = "06_12_10_2026"
WORKERS = ("Wykonawca Testowy A", "Wykonawca Testowy B", "Wykonawca Testowy C")
# A synthetic row value inside every workbook. Centrum must never read or show workbook content,
# so this marker must never appear in evidence (centrum_self_test.py checks it).
ROW_MARKER = "CENTRUM-SYN-ROW"


def _workbook(path: Path) -> None:
    workbook = Workbook()
    sheet = workbook.active
    assert sheet is not None
    sheet["A18"] = ROW_MARKER
    workbook.save(path)


def _period_files(periods: Path, token: str) -> Path:
    period_folder = periods / token
    period_folder.mkdir()
    _workbook(period_folder / f"Rozliczenie wew. {token}.xlsx")
    _workbook(period_folder / f"Rozliczenie {token} - zbiorcze.xlsx")
    return period_folder


def create(root: Path) -> dict[str, object]:
    root.mkdir(parents=True)
    (root / "config").mkdir()
    (root / "picker").mkdir()
    periods = root / "INEA"
    periods.mkdir()

    ready = _period_files(periods, "22_28_09_2026")
    workers = ready / "Rozliczenie pracowników 22_28_09_2026"
    workers.mkdir()
    for worker in WORKERS:
        _workbook(workers / f"Rozliczenie 22_28_09_2026 - {worker}.xlsx")
    _period_files(periods, "29_05_09_2026")
    (periods / "15_21_09_2026").mkdir()
    (periods / "Archiwum").mkdir()

    register = root / "ZLECENIA SYNTETYCZNE OD 01_01_2026.xlsx"
    _workbook(register)

    fixture: dict[str, object] = {
        "today": TODAY,
        "periods_directory": str(periods),
        "order_register": str(register),
        "settings": str(root / "config" / "centrum-ustawienia.yaml"),
        # token, Status okresu, number of Rozliczenia pracowników, last complete period
        "board": [
            [LAST_COMPLETE, "no_period_files", 0, True],
            ["29_05_09_2026", "collective_file_prepared", 0, False],
            ["22_28_09_2026", "worker_settlements_ready", len(WORKERS), False],
            ["15_21_09_2026", "no_period_files", 0, False],
        ],
    }
    (root / "fixture.json").write_text(json.dumps(fixture, ensure_ascii=False, indent=2), encoding="utf-8")
    return fixture


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", required=True, help="Run root below .verification/runs; must not exist yet.")
    args = parser.parse_args(argv)
    try:
        fixture = create(Path(args.root))
    except OSError as exc:
        print(f"FIXTURE FAILED: {exc}", file=sys.stderr)
        return 1
    print(f"FIXTURE OK | root={args.root} | today={fixture['today']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

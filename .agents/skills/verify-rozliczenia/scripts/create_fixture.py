"""Create disposable synthetic workbooks for the rozliczenia verification skill."""

from __future__ import annotations

import argparse
from pathlib import Path
import sys

import yaml
from openpyxl import Workbook, load_workbook
from openpyxl.worksheet.worksheet import Worksheet


PERIOD = "08_14_09_2026"
SOURCE_NAME = f"Rozliczenie {PERIOD} - zbiorcze.xlsx"
WORKERS = {
    "adrian.maciejewski": "Adrian Maciejewski",
    "dariusz.nowak2": "Darek Nowak",
    "kamil.frontczak": "Kamil Frontczak",
}


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[4]


def _run_parent() -> Path:
    return (_repo_root() / ".verification" / "runs").resolve()


def _safe_run_root(value: str) -> Path:
    root = Path(value).expanduser().resolve()
    parent = _run_parent()
    try:
        root.relative_to(parent)
    except ValueError as exc:
        raise ValueError(f"Fixture root must be below {parent}") from exc
    if root == parent:
        raise ValueError("Fixture root must be a child of the runs directory")
    return root


def _write_template(path: Path) -> None:
    workbook = Workbook()
    sheet = workbook.active
    if not isinstance(sheet, Worksheet):
        raise ValueError("New workbook does not contain an active worksheet")
    sheet.title = "Sheet1"
    sheet.cell(17, 8).value = "WYKONAWCA"
    sheet.cell(18, 47).value = "=N18"
    sheet.cell(19, 47).value = "=N19"
    sheet.cell(18, 14).value = 0
    sheet.cell(19, 14).value = 0
    workbook.save(path)
    workbook.close()


def _write_source(path: Path) -> None:
    workbook = Workbook()
    sheet = workbook.active
    if not isinstance(sheet, Worksheet):
        raise ValueError("New workbook does not contain an active worksheet")
    sheet.title = "Sheet1"
    sheet.cell(17, 8).value = "WYKONAWCA"
    rows = [
        ("TEST-CITY", "adrian.maciejewski", "SYNTHETIC-1"),
        ("TEST-CITY", "dariusz.nowak2", "SYNTHETIC-2"),
        ("TEST-CITY", "adrian.maciejewski", "SYNTHETIC-3"),
        ("TEST-CITY", "unknown.synthetic", "SYNTHETIC-4"),
    ]
    for row_number, (city, worker, marker) in enumerate(rows, start=18):
        sheet.cell(row_number, 1).value = city
        sheet.cell(row_number, 6).value = marker
        sheet.cell(row_number, 8).value = worker
        sheet.cell(row_number, 14).value = row_number - 17
    workbook.save(path)
    workbook.close()


def _write_mapping(path: Path) -> None:
    path.write_text(
        yaml.safe_dump(
            {"schema_version": 1, "workers": WORKERS},
            allow_unicode=True,
            sort_keys=False,
        ),
        encoding="utf-8",
    )


def create_fixture(root: Path, *, seed_existing: bool, lock_worker: str | None) -> None:
    period_directory = root / PERIOD
    target_directory = period_directory / f"Rozliczenie pracowników {PERIOD}"
    if root.exists() and any(root.iterdir()):
        raise ValueError(f"Fixture root is not empty: {root}")
    target_directory.mkdir(parents=True, exist_ok=False)
    _write_source(period_directory / SOURCE_NAME)
    _write_mapping(root / "worker_mapping.yaml")
    for worker_name in WORKERS.values():
        _write_template(target_directory / f"Rozliczenie {PERIOD} - {worker_name}.xlsx")
    _write_template(target_directory / f"Rozliczenie {PERIOD} -.xlsx")

    if seed_existing:
        target = target_directory / f"Rozliczenie {PERIOD} - Adrian Maciejewski.xlsx"
        workbook = load_workbook(target)
        sheet = workbook.active
        if not isinstance(sheet, Worksheet):
            raise ValueError("Template does not contain an active worksheet")
        sheet["A18"] = "PREEXISTING-SYNTHETIC-VALUE"
        workbook.save(target)
        workbook.close()

    if lock_worker is not None:
        target = target_directory / f"Rozliczenie {PERIOD} - {lock_worker}.xlsx"
        target.with_name(f"~${target.name}").touch()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=str, required=True)
    parser.add_argument("--seed-existing", action="store_true")
    parser.add_argument("--lock-worker", choices=sorted(WORKERS.values()))
    args = parser.parse_args(argv)
    try:
        root = _safe_run_root(args.root)
        root.mkdir(parents=True, exist_ok=False)
        create_fixture(root, seed_existing=args.seed_existing, lock_worker=args.lock_worker)
    except (OSError, ValueError) as exc:
        print(f"FIXTURE FAILED: {exc}", file=sys.stderr)
        return 1
    print(f"FIXTURE_READY root={root} period={PERIOD} templates=4")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

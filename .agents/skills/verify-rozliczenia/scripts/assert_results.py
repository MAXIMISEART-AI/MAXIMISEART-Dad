"""Assert safe, user-visible workbook results without printing row contents."""

from __future__ import annotations

import argparse
from pathlib import Path
import sys

from openpyxl import load_workbook


PERIOD = "08_14_09_2026"


def _path(root: Path, worker: str) -> Path:
    return root / PERIOD / f"Rozliczenie pracowników {PERIOD}" / f"Rozliczenie {PERIOD} - {worker}.xlsx"


def _read_cells(path: Path) -> tuple[object, object, object]:
    workbook = load_workbook(path, data_only=False)
    try:
        sheet = workbook.active
        return sheet["A18"].value, sheet["AU18"].value, sheet["AU19"].value
    finally:
        workbook.close()


def _assert_results(
    root: Path,
    mode: str,
    *,
    seed_existing: bool,
    locked_worker: str | None,
) -> int:
    adrian = _read_cells(_path(root, "Adrian Maciejewski"))
    darek = _read_cells(_path(root, "Darek Nowak"))
    kamil = _read_cells(_path(root, "Kamil Frontczak"))
    placeholder = _read_cells(root / PERIOD / f"Rozliczenie pracowników {PERIOD}" / f"Rozliczenie {PERIOD} -.xlsx")

    errors: list[str] = []
    for name, cells in (
        ("Adrian Maciejewski", adrian),
        ("Darek Nowak", darek),
        ("Kamil Frontczak", kamil),
        ("placeholder", placeholder),
    ):
        if cells[1:] != ("=N18", "=N19"):
            errors.append(f"formula changed for {name}")

    if mode == "dry-run":
        expected_adrian = "PREEXISTING-SYNTHETIC-VALUE" if seed_existing else None
        if adrian[0] != expected_adrian:
            errors.append("dry-run changed the existing Adrian input cell")
        if any(cells[0] is not None for cells in (darek, kamil, placeholder)):
            errors.append("dry-run changed an input cell")
    else:
        expected_adrian = "PREEXISTING-SYNTHETIC-VALUE" if seed_existing else "TEST-CITY"
        expected_darek = None if locked_worker == "Darek Nowak" else "TEST-CITY"
        if adrian[0] != expected_adrian or darek[0] != expected_darek:
            errors.append("mapped rows were not written")
        if kamil[0] is not None or placeholder[0] is not None:
            errors.append("empty or placeholder workbook was changed")
        if locked_worker is not None:
            lock_path = _path(root, locked_worker).with_name(
                f"~${_path(root, locked_worker).name}"
            )
            if not lock_path.exists():
                errors.append("expected lock file is missing")

    if errors:
        for error in errors:
            print(f"ASSERT FAIL: {error}", file=sys.stderr)
        return 1
    print(f"ASSERT OK | mode={mode} | workbooks_checked=4 | formulas_preserved=true")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", required=True, type=Path)
    parser.add_argument("--expect", choices=("dry-run", "run"), required=True)
    parser.add_argument("--seed-existing", action="store_true")
    parser.add_argument("--locked-worker", choices=("Adrian Maciejewski", "Darek Nowak", "Kamil Frontczak"))
    args = parser.parse_args(argv)
    try:
        return _assert_results(
            args.root.expanduser().resolve(),
            args.expect,
            seed_existing=args.seed_existing,
            locked_worker=args.locked_worker,
        )
    except (OSError, ValueError) as exc:
        print(f"ASSERT FAIL: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

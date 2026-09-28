"""Assert safe, user-visible workbook results without printing row contents."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys

from openpyxl import load_workbook
from openpyxl.worksheet.worksheet import Worksheet


PERIOD = "08_14_09_2026"


def _path(root: Path, worker: str) -> Path:
    return root / PERIOD / f"Rozliczenie pracowników {PERIOD}" / f"Rozliczenie {PERIOD} - {worker}.xlsx"


def _read_cells(path: Path) -> tuple[object, object, object]:
    workbook = load_workbook(path, data_only=False)
    try:
        sheet = workbook.active
        if not isinstance(sheet, Worksheet):
            raise ValueError("Workbook does not contain an active worksheet")
        return sheet["A18"].value, sheet["AU18"].value, sheet["AU19"].value
    finally:
        workbook.close()


def _assert_dry_run(root: Path, transcript: Path | None) -> int:
    period_directory = root / PERIOD
    source = period_directory / f"Rozliczenie {PERIOD} - zbiorcze.xlsx"
    placeholder = root / "placeholder.xlsx"
    target_directory = period_directory / f"Rozliczenie pracowników {PERIOD}"
    manifest = json.loads((root / "fixture_manifest.json").read_text(encoding="utf-8"))
    errors: list[str] = []

    for label, path, key in (
        ("source", source, "source_sha256"),
        ("placeholder", placeholder, "placeholder_sha256"),
    ):
        actual_hash = hashlib.sha256(path.read_bytes()).hexdigest()
        if actual_hash != manifest.get(key):
            errors.append(f"dry-run changed {label}")
    if target_directory.exists():
        errors.append("dry-run created the target directory")
    if transcript is None or not transcript.is_file():
        errors.append("dry-run transcript is missing")
    else:
        output = transcript.read_text(encoding="utf-8")
        expected_output = (
            f"Okres rozliczeniowy: {PERIOD}",
            f"Folder rozliczeń pracowników: {target_directory.resolve()}",
            "Plan plików:",
            f"Rozliczenie {PERIOD} - Adrian Maciejewski.xlsx | Wiersze do uzupełnienia: 2",
            f"Rozliczenie {PERIOD} - Darek Nowak.xlsx | Wiersze do uzupełnienia: 1",
            f"Rozliczenie {PERIOD} - Kamil Frontczak.xlsx | "
            "Wiersze do uzupełnienia: 0 | Pusty skoroszyt",
            "Nieznany identyfikator WYKONAWCA",
            "Nic nie zapisano",
        )
        for expected in expected_output:
            if expected not in output:
                errors.append(f"dry-run output is missing {expected}")
        for forbidden in (
            "TEST-CITY",
            "SYNTHETIC-1",
            "SYNTHETIC-2",
            "SYNTHETIC-3",
            "SYNTHETIC-4",
            "unknown.synthetic",
        ):
            if forbidden in output:
                errors.append("dry-run output contains source row content")

    if errors:
        for error in errors:
            print(f"ASSERT FAIL: {error}", file=sys.stderr)
        return 1
    print("ASSERT OK | mode=dry-run | output_folder_absent=true | inputs_unchanged=true | rows_hidden=true")
    return 0


def _assert_results(
    root: Path,
    mode: str,
    *,
    seed_existing: bool,
    locked_worker: str | None,
    transcript: Path | None,
) -> int:
    if mode == "dry-run":
        return _assert_dry_run(root, transcript)

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
    parser.add_argument("--transcript", type=Path)
    args = parser.parse_args(argv)
    try:
        return _assert_results(
            args.root.expanduser().resolve(),
            args.expect,
            seed_existing=args.seed_existing,
            locked_worker=args.locked_worker,
            transcript=args.transcript.expanduser().resolve() if args.transcript else None,
        )
    except (OSError, ValueError) as exc:
        print(f"ASSERT FAIL: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

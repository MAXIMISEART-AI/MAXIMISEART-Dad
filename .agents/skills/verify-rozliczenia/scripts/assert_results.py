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
WORKERS = ("Adrian Maciejewski", "Darek Nowak", "Kamil Frontczak")


def _path(root: Path, worker: str) -> Path:
    return root / PERIOD / f"Rozliczenie pracowników {PERIOD}" / f"Rozliczenie {PERIOD} - {worker}.xlsx"


def _read_cells(path: Path) -> tuple[object, object, object, tuple[str, ...], object, object]:
    workbook = load_workbook(path, data_only=False)
    try:
        sheet = workbook.active
        if not isinstance(sheet, Worksheet):
            raise ValueError("Workbook does not contain an active worksheet")
        return (
            sheet["A18"].value,
            sheet["AU18"].value,
            sheet["AU19"].value,
            tuple(workbook.sheetnames),
            sheet["A17"].fill.fgColor.rgb,
            workbook["Rates"]["B1"].value,
        )
    finally:
        workbook.close()


def _unchanged_inputs(root: Path, manifest: dict[str, object]) -> list[str]:
    period_directory = root / PERIOD
    errors: list[str] = []
    for label, path, key in (
        ("source", period_directory / f"Rozliczenie {PERIOD} - zbiorcze.xlsx", "source_sha256"),
        ("placeholder", root / "placeholder.xlsx", "placeholder_sha256"),
    ):
        actual = hashlib.sha256(path.read_bytes()).hexdigest()
        if actual != manifest.get(key):
            errors.append(f"run changed {label}")
    return errors


def _assert_dry_run(root: Path, transcript: Path | None) -> int:
    period_directory = root / PERIOD
    target_directory = period_directory / f"Rozliczenie pracowników {PERIOD}"
    manifest = json.loads((root / "fixture_manifest.json").read_text(encoding="utf-8"))
    errors = _unchanged_inputs(root, manifest)
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
            f"Problemy: {1 if manifest.get('include_unmapped') else 0}",
            "Nic nie zapisano",
        )
        for expected in expected_output:
            if expected not in output:
                errors.append(f"dry-run output is missing {expected}")
        if manifest.get("include_unmapped") and "Nieznany identyfikator WYKONAWCA" not in output:
            errors.append("dry-run output is missing the unmapped-worker warning")
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
    print(
        "ASSERT OK | mode=dry-run | output_folder_absent=true | "
        "inputs_unchanged=true | rows_hidden=true"
    )
    return 0


def _assert_run(root: Path, transcript: Path | None) -> int:
    target_directory = root / PERIOD / f"Rozliczenie pracowników {PERIOD}"
    manifest = json.loads((root / "fixture_manifest.json").read_text(encoding="utf-8"))
    errors = _unchanged_inputs(root, manifest)
    expected_files = {f"Rozliczenie {PERIOD} - {worker}.xlsx" for worker in WORKERS}
    if not target_directory.is_dir():
        errors.append("published folder is missing")
    elif {path.name for path in target_directory.glob("*.xlsx")} != expected_files:
        errors.append("published folder does not contain exactly the configured workbooks")

    try:
        adrian = _read_cells(_path(root, WORKERS[0]))
        darek = _read_cells(_path(root, WORKERS[1]))
        kamil = _read_cells(_path(root, WORKERS[2]))
        for name, cells in zip(WORKERS, (adrian, darek, kamil)):
            if cells[1:3] != ("=N18", "=N19"):
                errors.append(f"formula changed for {name}")
            if cells[3] != ("Sheet1", "Rates") or cells[4] != "0000AA55" or cells[5] != 17.5:
                errors.append(f"placeholder structure or formatting changed for {name}")
        if adrian[0] != "TEST-CITY" or darek[0] != "TEST-CITY" or kamil[0] is not None:
            errors.append("worker rows were not routed or the empty workbook was changed")
    except (OSError, ValueError, KeyError):
        errors.append("one or more published workbooks cannot be read")

    if transcript is None or not transcript.is_file():
        errors.append("run transcript is missing")
    else:
        output = transcript.read_text(encoding="utf-8")
        if "Status końcowy: OK" not in output or "Zapisane szablony: 2" not in output:
            errors.append("run transcript does not report a successful complete run")
        if any(value in output for value in ("TEST-CITY", "SYNTHETIC-1", "SYNTHETIC-2", "SYNTHETIC-3")):
            errors.append("run transcript contains source row content")

    if errors:
        for error in errors:
            print(f"ASSERT FAIL: {error}", file=sys.stderr)
        return 1
    print("ASSERT OK | mode=run | workbooks_checked=3 | formulas_preserved=true | placeholder_unchanged=true")
    return 0


def _assert_no_publish(root: Path, transcript: Path | None, expected_message: str) -> int:
    period_directory = root / PERIOD
    target_directory = period_directory / f"Rozliczenie pracowników {PERIOD}"
    manifest = json.loads((root / "fixture_manifest.json").read_text(encoding="utf-8"))
    errors = _unchanged_inputs(root, manifest)
    if target_directory.exists():
        errors.append("failed run published the target directory")
    if list(period_directory.glob(f".{target_directory.name}.staging-*")):
        errors.append("failed run left a staging directory")
    if transcript is None or not transcript.is_file():
        errors.append("failed run transcript is missing")
    else:
        output = transcript.read_text(encoding="utf-8")
        if expected_message not in output:
            errors.append("failed run transcript is missing its safe failure message")
        if any(value in output for value in ("TEST-CITY", "SYNTHETIC-1", "SYNTHETIC-2", "SYNTHETIC-3", "unknown.synthetic")):
            errors.append("failed run transcript contains source row content")
    if errors:
        for error in errors:
            print(f"ASSERT FAIL: {error}", file=sys.stderr)
        return 1
    print("ASSERT OK | mode=no-publish | output_folder_absent=true | inputs_unchanged=true")
    return 0


def _assert_existing_output(root: Path, transcript: Path | None) -> int:
    target_directory = root / PERIOD / f"Rozliczenie pracowników {PERIOD}"
    sentinel = target_directory / "existing-synthetic.txt"
    manifest = json.loads((root / "fixture_manifest.json").read_text(encoding="utf-8"))
    errors = _unchanged_inputs(root, manifest)
    if not target_directory.is_dir() or sentinel.read_text(encoding="utf-8") != "preserve":
        errors.append("existing output folder was changed")
    if {path.name for path in target_directory.iterdir()} != {sentinel.name}:
        errors.append("existing output folder gained or lost files")
    if transcript is None or not transcript.is_file():
        errors.append("existing-output transcript is missing")
    elif "Folder docelowy już istnieje" not in transcript.read_text(encoding="utf-8"):
        errors.append("existing-output failure was not reported")
    if errors:
        for error in errors:
            print(f"ASSERT FAIL: {error}", file=sys.stderr)
        return 1
    print("ASSERT OK | mode=existing-output | existing_folder_unchanged=true")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", required=True, type=Path)
    parser.add_argument(
        "--expect",
        choices=("dry-run", "run", "no-publish", "existing-output"),
        required=True,
    )
    parser.add_argument("--expected-message")
    parser.add_argument("--transcript", type=Path)
    args = parser.parse_args(argv)
    root = args.root.expanduser().resolve()
    transcript = args.transcript.expanduser().resolve() if args.transcript else None
    try:
        if args.expect == "dry-run":
            return _assert_dry_run(root, transcript)
        if args.expect == "run":
            return _assert_run(root, transcript)
        if args.expect == "no-publish":
            if not args.expected_message:
                parser.error("--expected-message is required for no-publish")
            return _assert_no_publish(root, transcript, args.expected_message)
        return _assert_existing_output(root, transcript)
    except (OSError, ValueError) as exc:
        print(f"ASSERT FAIL: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

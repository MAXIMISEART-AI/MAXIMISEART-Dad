"""Read-only build and fixture check for the rozliczenia verification skill."""

from __future__ import annotations

import argparse
from pathlib import Path
import sys
import tomllib

from openpyxl import load_workbook
from openpyxl.worksheet._read_only import ReadOnlyWorksheet
from openpyxl.worksheet.worksheet import Worksheet


SCRIPT = Path(__file__).resolve()
REPO_ROOT = SCRIPT.parents[4]
sys.path.insert(0, str(REPO_ROOT / "src"))

from rozliczenia.engine import load_worker_mapping, period_from_source  # noqa: E402
from rozliczenia.template_settlement import (  # noqa: E402
    PlaceholderValidationError,
    validate_placeholder,
)


def _check(root: Path, expected_version: str) -> tuple[str, int]:
    root = root.expanduser().resolve()
    if not root.is_dir():
        raise ValueError(f"missing fixture root: {root}")
    with (REPO_ROOT / "pyproject.toml").open("rb") as stream:
        version = tomllib.load(stream)["project"]["version"]
    if version != expected_version:
        raise ValueError(f"expected version {expected_version}, found {version}")
    if sys.version_info < (3, 11):
        raise ValueError("Python 3.11 or newer is required")

    source = root / "08_14_09_2026" / "Rozliczenie 08_14_09_2026 - zbiorcze.xlsx"
    period = period_from_source(source)
    target_directory = source.parent / f"Rozliczenie pracowników {period}"
    mapping = load_worker_mapping(root / "worker_mapping.yaml")
    if len(mapping) != 3:
        raise ValueError("synthetic mapping must contain three workers")
    if target_directory.exists():
        raise ValueError("target directory must not exist before dry-run")
    validate_placeholder(root / "placeholder.xlsx")

    workbook = load_workbook(source, read_only=True, data_only=False)
    try:
        sheet = workbook.active
        if not isinstance(sheet, (Worksheet, ReadOnlyWorksheet)):
            raise ValueError("source workbook has no active worksheet")
        if sheet["H17"].value != "WYKONAWCA":
            raise ValueError("source H17 is not WYKONAWCA")
    finally:
        workbook.close()

    return period, len(mapping)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", required=True, type=Path)
    parser.add_argument("--expected-version", default="0.1.0")
    args = parser.parse_args(argv)
    try:
        period, template_count = _check(args.root, args.expected_version)
    except (OSError, ValueError, KeyError, TypeError, PlaceholderValidationError) as exc:
        print(f"DOCTOR FAIL: {exc}", file=sys.stderr)
        return 1
    print(
        f"DOCTOR OK | app=MAXIMISEART-Dad | version={args.expected_version} | "
        f"python={sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro} | "
        f"period={period} | workers={template_count} | placeholder=valid | target_absent=true"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

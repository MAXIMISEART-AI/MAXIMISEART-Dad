"""Assert the Przebieg rozliczeń of a chain run on the Plik zbiorczy from Przygotowanie, without printing row contents.

The Plik zbiorczy was written by Przygotowanie pliku zbiorczego and then filled by
the Gotowość step, so its Wiersze danych carry values in all of ``A:AT``. The
checks are generic over the Wzorce, so the same helper serves both the synthetic
and the real Wzorce. Messages name workers, rows, and columns, never a cell value.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys
import zipfile

from openpyxl import load_workbook
from openpyxl.utils import get_column_letter
from openpyxl.workbook.workbook import Workbook
from openpyxl.worksheet.worksheet import Worksheet


PERIOD = "08_14_09_2026"
HEADER_ROW = 17
FIRST_DATA_ROW = 18
INPUT_COLUMNS = 11  # A:K
COPIED_COLUMNS = 46  # A:AT
READINESS_COLUMNS = range(13, 46)  # N:AT as 0-based tuple indices
ROW_MARKER = "PREP-SYN-"
INTERNAL_NAME = f"Rozliczenie wew. {PERIOD}.xlsx"
COLLECTIVE_NAME = f"Rozliczenie {PERIOD} - zbiorcze.xlsx"
TARGET_DIRECTORY_NAME = f"Rozliczenie pracowników {PERIOD}"
WORKER_TEMPLATE = Path("config") / "Wzorzec rozliczenia pracownika.xlsx"
# Zlecenia skuteczne of every Wykonawca in Rejestr order; Adrian's two are split by Kamil's.
EXPECTED_WORKER_ORDERS = {
    "Adrian Testowy": ("PREP-SYN-ZL-2", "PREP-SYN-ZL-7"),
    "Darek Fikcyjny": ("PREP-SYN-ZL-6",),
    "Kamil Syntetyczny": ("PREP-SYN-ZL-4",),
}
EXPECTED_ROWS = sum(len(orders) for orders in EXPECTED_WORKER_ORDERS.values())
UNSUCCESSFUL_ORDER = "PREP-SYN-ZL-3"  # Darek's NIE order, present only in the Rozliczenie wewnętrzne
INPUTS = (
    ("Rejestr zleceń", Path("ZLECENIA INTERMAX OD 08_11_2021.xlsx"), "fixture_manifest.json", "register_sha256"),
    (
        "Wzorzec rozliczenia wewnętrznego",
        Path("config") / "Wzorzec rozliczenia wewnętrznego.xlsx",
        "fixture_manifest.json",
        "internal_template_sha256",
    ),
    (
        "Wzorzec pliku zbiorczego",
        Path("config") / "Wzorzec pliku zbiorczego.xlsx",
        "fixture_manifest.json",
        "collective_template_sha256",
    ),
    ("Wzorzec rozliczenia pracownika", WORKER_TEMPLATE, "fixture_manifest.json", "worker_template_sha256"),
    (
        "Rozliczenie wewnętrzne",
        Path("INEA") / PERIOD / INTERNAL_NAME,
        "readiness_manifest.json",
        "internal_settlement_sha256",
    ),
    ("Plik zbiorczy", Path("INEA") / PERIOD / COLLECTIVE_NAME, "readiness_manifest.json", "collective_file_sha256"),
)

Row = tuple[object, ...]


def _sheet(workbook: Workbook) -> Worksheet:
    sheet = workbook.active
    if not isinstance(sheet, Worksheet):
        raise ValueError("Workbook does not contain an active worksheet")
    return sheet


def _manifest(root: Path, name: str) -> dict[str, object]:
    loaded = json.loads((root / name).read_text(encoding="utf-8"))
    if not isinstance(loaded, dict):
        raise ValueError(f"{name} is not a JSON object")
    return loaded


def _unchanged_inputs(root: Path, errors: list[str]) -> None:
    """Rejestr, all Wzorce, and both period files are byte-identical to before the Przebieg rozliczeń."""

    manifests = {name: _manifest(root, name) for name in ("fixture_manifest.json", "readiness_manifest.json")}
    for label, path, manifest, key in INPUTS:
        if hashlib.sha256((root / path).read_bytes()).hexdigest() != manifests[manifest].get(key):
            errors.append(f"{label} changed")


def _check_metrics(root: Path, expected: list[tuple[str, str]], errors: list[str]) -> None:
    metrics = root / "settlement-metrics.jsonl"
    content = metrics.read_text(encoding="utf-8") if metrics.is_file() else ""
    records = [json.loads(line) for line in content.splitlines() if line.strip()]
    if [(record.get("mode"), record.get("result")) for record in records] != expected:
        errors.append(f"settlement metrics history does not contain exactly {expected}")
    for record in records:
        counters = record.get("counters") or {}
        if record.get("period") != PERIOD or record.get("completed") is not True:
            errors.append("settlement metrics record is not a completed run of the period")
        if (counters.get("templates_total"), counters.get("rows")) != (len(EXPECTED_WORKER_ORDERS), EXPECTED_ROWS):
            errors.append("settlement metrics counters do not match the Plik zbiorczy")
    root_spellings = (str(root), json.dumps(str(root))[1:-1])
    if ROW_MARKER in content or any(spelling in content for spelling in root_spellings):
        errors.append("settlement metrics contain row content or a filesystem path")


def _transcript(path: Path | None, errors: list[str]) -> str:
    if path is None or not path.is_file():
        errors.append("transcript is missing")
        return ""
    output = path.read_text(encoding="utf-8")
    if ROW_MARKER in output:
        errors.append("transcript contains row content")
    return output


def _finish(errors: list[str], success_message: str) -> int:
    if errors:
        for error in errors:
            print(f"ASSERT FAIL: {error}", file=sys.stderr)
        return 1
    print(success_message)
    return 0


def _assert_dry_run(root: Path, transcript: Path | None) -> int:
    errors: list[str] = []
    _unchanged_inputs(root, errors)
    period_directory = root / "INEA" / PERIOD
    if sorted(path.name for path in period_directory.iterdir()) != sorted([INTERNAL_NAME, COLLECTIVE_NAME]):
        errors.append("dry-run added entries to the Folder okresu")
    output = _transcript(transcript, errors)
    expected_lines = [
        f"Okres rozliczeniowy: {PERIOD}",
        f"Folder rozliczeń pracowników: {(period_directory / TARGET_DIRECTORY_NAME).resolve()}",
        "Plan plików:",
        *(
            f"- Rozliczenie {PERIOD} - {name}.xlsx | Wiersze do uzupełnienia: {len(orders)}"
            for name, orders in EXPECTED_WORKER_ORDERS.items()
        ),
        "Problemy: 0",
        "DRY-RUN: Nic nie zapisano",
    ]
    lines = {line.strip() for line in output.splitlines()}
    for expected in expected_lines:
        if expected not in lines:
            errors.append(f"dry-run transcript is missing {expected}")
    _check_metrics(root, [("DRY-RUN", "OK")], errors)
    return _finish(
        errors,
        "ASSERT OK | process=przebieg | source=przygotowanie | mode=dry-run | output_folder_absent=true | "
        "inputs_unchanged=true | plan_reported=true | rows_hidden=true",
    )


def _order_column(sheet: Worksheet) -> int:
    columns = [
        cell.column
        for cell in sheet[HEADER_ROW]
        if isinstance(cell.value, str) and cell.value.strip().casefold() == "numer zl."
    ]
    if len(columns) != 1:
        raise ValueError(f"Plik zbiorczy has {len(columns)} NUMER ZL. headers in row {HEADER_ROW}")
    return columns[0]


def _data_rows(sheet: Worksheet) -> list[tuple[int, Row]]:
    """Wiersze danych with their row numbers: rows from 18 with a value in A:K, as A:AT."""

    return [
        (number, tuple(values))
        for number, values in enumerate(
            sheet.iter_rows(min_row=FIRST_DATA_ROW, max_col=COPIED_COLUMNS, values_only=True),
            start=FIRST_DATA_ROW,
        )
        if any(value is not None for value in values[:INPUT_COLUMNS])
    ]


def _cell_values(workbook: Workbook, skipped_rows: range) -> dict[tuple[str, int, int], object]:
    """Every stored value except the A:AT cells of ``skipped_rows`` on the active sheet."""

    active = workbook.active
    return {
        (sheet.title, cell.row, cell.column): cell.value
        for sheet in workbook.worksheets
        for row in sheet.iter_rows()
        for cell in row
        if cell.value is not None
        and not (sheet is active and cell.row in skipped_rows and cell.column <= COPIED_COLUMNS)
    }


def _external_link_parts(path: Path) -> dict[str, bytes]:
    with zipfile.ZipFile(path) as archive:
        return {name: archive.read(name) for name in archive.namelist() if name.startswith("xl/externalLinks/")}


def _check_worker_file(
    name: str,
    path: Path,
    expected_rows: list[Row],
    template: Workbook,
    template_links: dict[str, bytes],
    readiness_orders: set[object],
    order_index: int,
    errors: list[str],
) -> None:
    workbook = load_workbook(path, data_only=False, keep_links=True)
    try:
        sheet = _sheet(workbook)
        data_rows = _data_rows(sheet)
        written = range(FIRST_DATA_ROW, FIRST_DATA_ROW + len(expected_rows))
        if [number for number, _ in data_rows] != list(written):
            errors.append(f"{name}: Wiersze danych are not exactly rows {written.start}-{written.stop - 1}")
        actual_rows = [values for _, values in data_rows]
        if any(values[order_index] == UNSUCCESSFUL_ORDER for values in actual_rows):
            errors.append(f"{name}: holds a Zlecenie nieskuteczne")
        if [values[order_index] for values in actual_rows] != [values[order_index] for values in expected_rows]:
            errors.append(f"{name}: orders differ from its Zlecenia skuteczne in Plik zbiorczy order")
        for number, (actual, expected) in enumerate(zip(actual_rows, expected_rows), start=FIRST_DATA_ROW):
            differing = [get_column_letter(index + 1) for index, value in enumerate(expected) if actual[index] != value]
            if differing:
                errors.append(f"{name}: row {number} differs from the Plik zbiorczy in {', '.join(differing[:8])}")
            elif expected[order_index] in readiness_orders and any(
                actual[index] in (None, 0) for index in READINESS_COLUMNS
            ):
                errors.append(f"{name}: row {number} lacks the Gotowość entries in N:AT")
        if workbook.sheetnames != template.sheetnames or _cell_values(workbook, written) != _cell_values(
            template, written
        ):
            errors.append(f"{name}: cells outside the Wiersze danych differ from the Wzorzec rozliczenia pracownika")
    finally:
        workbook.close()
    if _external_link_parts(path) != template_links:
        errors.append(f"{name}: xl/externalLinks parts differ from the Wzorzec rozliczenia pracownika")


def _check_worker_files(root: Path, period_directory: Path, target_directory: Path, errors: list[str]) -> None:
    """Every Rozliczenie pracownika against the Plik zbiorczy it was made from and the Wzorzec rozliczenia pracownika."""

    filled_orders = _manifest(root, "readiness_manifest.json").get("filled_orders")
    if not isinstance(filled_orders, list) or not filled_orders:
        raise ValueError("readiness_manifest.json names no filled Wiersze danych")
    readiness_orders = set(filled_orders)
    collective = load_workbook(period_directory / COLLECTIVE_NAME, data_only=False, keep_links=True)
    try:
        collective_sheet = _sheet(collective)
        order_index = _order_column(collective_sheet) - 1
        collective_rows = [values for _, values in _data_rows(collective_sheet)]
    finally:
        collective.close()
    if UNSUCCESSFUL_ORDER in {values[order_index] for values in collective_rows}:
        errors.append("Plik zbiorczy holds a Zlecenie nieskuteczne")
    filled = [values for values in collective_rows if values[order_index] in readiness_orders]
    if len(filled) != len(readiness_orders) or any(
        values[index] in (None, 0) for values in filled for index in READINESS_COLUMNS
    ):
        errors.append("Plik zbiorczy lacks the Gotowość entries in N:AT")

    template_path = root / WORKER_TEMPLATE
    template_links = _external_link_parts(template_path)
    template = load_workbook(template_path, data_only=False, keep_links=True)
    try:
        for name, orders in EXPECTED_WORKER_ORDERS.items():
            expected_rows = [values for values in collective_rows if values[order_index] in orders]
            if tuple(values[order_index] for values in expected_rows) != orders:
                errors.append(f"Plik zbiorczy does not hold the Zlecenia skuteczne of {name} in Rejestr order")
            _check_worker_file(
                name,
                target_directory / f"Rozliczenie {PERIOD} - {name}.xlsx",
                expected_rows,
                template,
                template_links,
                readiness_orders,
                order_index,
                errors,
            )
    finally:
        template.close()


def _assert_run(root: Path, transcript: Path | None) -> int:
    errors: list[str] = []
    _unchanged_inputs(root, errors)
    period_directory = root / "INEA" / PERIOD
    target_directory = period_directory / TARGET_DIRECTORY_NAME
    if sorted(path.name for path in period_directory.iterdir()) != sorted(
        [INTERNAL_NAME, COLLECTIVE_NAME, TARGET_DIRECTORY_NAME]
    ):
        errors.append("Folder okresu does not hold exactly both period files and the Folder rozliczeń pracowników")
    expected_files = {f"Rozliczenie {PERIOD} - {name}.xlsx" for name in EXPECTED_WORKER_ORDERS}
    if not target_directory.is_dir() or {path.name for path in target_directory.iterdir()} != expected_files:
        errors.append("Folder rozliczeń pracowników does not hold exactly one workbook per Wykonawca")
    else:
        _check_worker_files(root, period_directory, target_directory, errors)

    output = _transcript(transcript, errors)
    phases = [output.find(f"Etap: {phase}") for phase in ("Sprawdzanie", "Odczyt danych", "Planowanie", "Zapisywanie")]
    if -1 in phases or phases != sorted(phases):
        errors.append("run transcript does not report the four stages in order")
    if (
        "Status końcowy: OK" not in output
        or f"Zapisane szablony: {len(EXPECTED_WORKER_ORDERS)}" not in output
        or f"Postęp szablonów: {len(EXPECTED_WORKER_ORDERS)}/{len(EXPECTED_WORKER_ORDERS)} (100%)" not in output
        or output.count("| ZAPISANO |") != len(EXPECTED_WORKER_ORDERS)
    ):
        errors.append("run transcript does not report a complete run with every template written")
    _check_metrics(root, [("DRY-RUN", "OK"), ("RUN", "OK")], errors)
    return _finish(
        errors,
        f"ASSERT OK | process=przebieg | source=przygotowanie | mode=run | workbooks_checked={len(expected_files)} | "
        "rows_equal_plik_zbiorczy=A:AT | readiness_carried=true | unsuccessful_absent=true | "
        "wzorzec_preserved=true | external_links_preserved=true | inputs_unchanged=true",
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", required=True, type=Path)
    parser.add_argument("--expect", choices=("dry-run", "run"), required=True)
    parser.add_argument("--transcript", type=Path)
    args = parser.parse_args(argv)
    root = args.root.expanduser().resolve()
    transcript = args.transcript.expanduser().resolve() if args.transcript else None
    try:
        if args.expect == "dry-run":
            return _assert_dry_run(root, transcript)
        return _assert_run(root, transcript)
    except (OSError, ValueError, KeyError, zipfile.BadZipFile) as exc:
        print(f"ASSERT FAIL: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

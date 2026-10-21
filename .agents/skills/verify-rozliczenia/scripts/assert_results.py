"""Assert safe, user-visible workbook results without printing row contents."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys
from typing import Any, NamedTuple

from openpyxl import load_workbook
from openpyxl.worksheet.worksheet import Worksheet


PERIOD = "08_14_09_2026"
ORDER_LINK = "https://przyklad.invalid/zlecenie?caseId=SYNTHETIC-LINK&tw=1&wiersz="
WORKERS = ("Adrian Testowy", "Darek Fikcyjny", "Kamil Syntetyczny")
PHASES = ("Sprawdzanie", "Odczyt danych", "Planowanie", "Zapisywanie")
FILE_PLAN = [
    {"file": f"Rozliczenie {PERIOD} - {worker}.xlsx", "rows": rows} for worker, rows in zip(WORKERS, (2, 1, 0))
]


class WorkbookSnapshot(NamedTuple):
    formula_au18: object
    formula_au19: object
    sheet_names: tuple[str, ...]
    header_fill_rgb: object
    rate_value: object


def _path(root: Path, worker: str) -> Path:
    return root / PERIOD / f"Rozliczenie pracowników {PERIOD}" / f"Rozliczenie {PERIOD} - {worker}.xlsx"


def _read_workbook_snapshot(path: Path) -> WorkbookSnapshot:
    workbook = load_workbook(path, data_only=False)
    try:
        sheet = workbook.active
        if not isinstance(sheet, Worksheet):
            raise ValueError("Workbook does not contain an active worksheet")
        return WorkbookSnapshot(
            sheet["AU18"].value,
            sheet["AU19"].value,
            tuple(workbook.sheetnames),
            sheet["A17"].fill.fgColor.rgb,
            workbook["Rates"]["B1"].value,
        )
    finally:
        workbook.close()


def _read_input_row(path: Path, row_number: int) -> tuple[object, ...]:
    workbook = load_workbook(path, data_only=False)
    try:
        sheet = workbook.active
        if not isinstance(sheet, Worksheet):
            raise ValueError("Workbook does not contain an active worksheet")
        return next(sheet.iter_rows(min_row=row_number, max_row=row_number, max_col=46, values_only=True))
    finally:
        workbook.close()


def _hyperlinks(path: Path) -> dict[str, str | None]:
    workbook = load_workbook(path)
    try:
        sheet = workbook.active
        if not isinstance(sheet, Worksheet):
            raise ValueError("Workbook does not contain an active worksheet")
        return {
            cell.coordinate: cell.hyperlink.target
            for row in sheet.iter_rows()
            for cell in row
            if cell.hyperlink is not None
        }
    finally:
        workbook.close()


def _expected_source_row(worker_id: str, marker: str, quantity: int) -> tuple[object, ...]:
    return (
        "TEST-CITY",
        None,
        None,
        None,
        None,
        marker,
        None,
        worker_id,
        None,
        None,
        None,
        None,
        None,
        quantity,
    ) + (None,) * 32


def _unchanged_inputs(root: Path, manifest: dict[str, object]) -> list[str]:
    period_directory = root / PERIOD
    errors: list[str] = []
    for label, path, key in (
        ("source", period_directory / f"Rozliczenie {PERIOD} - zbiorcze.xlsx", "source_sha256"),
        ("worker template", root / "Wzorzec rozliczenia pracownika.xlsx", "worker_template_sha256"),
    ):
        actual = hashlib.sha256(path.read_bytes()).hexdigest()
        if actual != manifest.get(key):
            errors.append(f"run changed {label}")
    return errors


_ROW_CONTENT = ("TEST-CITY", "SYNTHETIC-1", "SYNTHETIC-2", "SYNTHETIC-3", "SYNTHETIC-4", "unknown.synthetic")


def _check_metrics(root: Path, expected: list[tuple[str, str]], errors: list[str]) -> None:
    """Expect one completed record per (mode, result), with no row content or path."""

    metrics = root / "metrics.jsonl"
    content = metrics.read_text(encoding="utf-8") if metrics.is_file() else ""
    records = [json.loads(line) for line in content.splitlines() if line.strip()]
    if [(record.get("mode"), record.get("result")) for record in records] != expected:
        errors.append(f"metrics history does not contain exactly {expected}")
    for record in records:
        if record.get("period") != PERIOD or record.get("completed") is not True:
            errors.append("metrics record is not a completed run of the period")
    root_spellings = (str(root), json.dumps(str(root))[1:-1])
    if any(value in content for value in _ROW_CONTENT) or any(spelling in content for spelling in root_spellings):
        errors.append("metrics contain row content or a filesystem path")


def _figures(figures: list[dict[str, Any]]) -> list[tuple[str, int]]:
    return [(figure["label"], figure["value"]) for figure in figures]


def _load_result(path: Path | None, errors: list[str]) -> dict[str, Any]:
    if path is None or not path.is_file():
        errors.append("process step evidence is missing")
        return {"progress": {}}
    text = path.read_text(encoding="utf-8")
    if any(value in text for value in _ROW_CONTENT):
        errors.append("process result contains source row content")
    result = json.loads(text)["result"]
    if not isinstance(result, dict):
        errors.append("process step printed no JSON result")
        return {"progress": {}}
    if result["metrics_saved"] is not True:
        errors.append("process result reports its metrics record as not saved")
    return result


def _check_progress(progress: dict[str, Any], errors: list[str]) -> None:
    if [(phase["phase"], phase["state"]) for phase in progress.get("phases", [])] != [
        (phase, "completed") for phase in PHASES
    ]:
        errors.append("run progress does not complete the four stages in order")
    if (progress.get("template_total"), progress.get("templates_completed")) != (3, 3) or _figures(
        progress.get("figures", [])
    ) != [("Wiersze danych", 3), ("Zapisane szablony", 2), ("Puste szablony", 1), ("Problemy", 0)]:
        errors.append("run progress does not report 3/3 templates with two written and one empty")


def _check_stop(result: dict[str, Any], expected_stop: str, expected_what: str | None, errors: list[str]) -> None:
    message = (result.get("stop") or {}).get("message", {})
    code = message.get("code")
    if result.get("result") != "BLAD_KRYTYCZNY" or result.get("summary") is not None or code != expected_stop:
        errors.append(f"run did not stop with {expected_stop} (stopped with {code})")
    elif expected_what is not None and expected_what not in message.get("what", ""):
        errors.append(f"{expected_stop} does not say: {expected_what}")


def _finish_assertion(errors: list[str], success_message: str) -> int:
    if errors:
        for error in errors:
            print(f"ASSERT FAIL: {error}", file=sys.stderr)
        return 1
    print(success_message)
    return 0


def _assert_dry_run(root: Path, result_path: Path | None) -> int:
    period_directory = root / PERIOD
    target_directory = period_directory / f"Rozliczenie pracowników {PERIOD}"
    manifest = json.loads((root / "fixture_manifest.json").read_text(encoding="utf-8"))
    errors = _unchanged_inputs(root, manifest)
    if target_directory.exists():
        errors.append("dry-run created the target directory")
    result = _load_result(result_path, errors)
    unmapped = bool(manifest.get("include_unmapped"))
    expected_summary = {
        "figures": [
            {"label": "Wiersze danych", "value": 3, "unit": "count"},
            {"label": "Planowane szablony", "value": 2, "unit": "count"},
            {"label": "Puste szablony", "value": 1, "unit": "count"},
        ],
        "counts": None,
        "files": [],
        "file_plan": FILE_PLAN,
    }
    if result.get("result") != ("WYMAGA_SPRAWDZENIA" if unmapped else "OK") or result.get("stop") is not None:
        errors.append("dry-run result is not the expected finished result")
    if result.get("summary") != expected_summary:
        errors.append("dry-run plan does not list every worker file with its rows")
    if [warning["code"] for warning in result.get("warnings", [])] != (["BRAK_MAPOWANIA"] if unmapped else []):
        errors.append("dry-run warnings do not match the unmapped workers")
    problems = dict(_figures(result["progress"].get("figures", []))).get("Problemy")
    if problems != (1 if unmapped else 0):
        errors.append(f"dry-run reports {problems} Problemy")
    _check_metrics(root, [("DRY-RUN", "WYMAGA_SPRAWDZENIA" if unmapped else "OK")], errors)

    return _finish_assertion(
        errors,
        "ASSERT OK | mode=dry-run | output_folder_absent=true | "
        "inputs_unchanged=true | rows_hidden=true | metrics_safe=true",
    )


def _assert_run(root: Path, result_path: Path | None) -> int:
    target_directory = root / PERIOD / f"Rozliczenie pracowników {PERIOD}"
    manifest = json.loads((root / "fixture_manifest.json").read_text(encoding="utf-8"))
    errors = _unchanged_inputs(root, manifest)
    expected_files = {f"Rozliczenie {PERIOD} - {worker}.xlsx" for worker in WORKERS}
    if not target_directory.is_dir():
        errors.append("published folder is missing")
    elif {path.name for path in target_directory.glob("*.xlsx")} != expected_files:
        errors.append("published folder does not contain exactly the configured workbooks")

    try:
        adrian = _read_workbook_snapshot(_path(root, WORKERS[0]))
        darek = _read_workbook_snapshot(_path(root, WORKERS[1]))
        kamil = _read_workbook_snapshot(_path(root, WORKERS[2]))
        adrian_file = _path(root, WORKERS[0])
        darek_file = _path(root, WORKERS[1])
        kamil_file = _path(root, WORKERS[2])
        for name, snapshot in zip(WORKERS, (adrian, darek, kamil)):
            if (snapshot.formula_au18, snapshot.formula_au19) != ("=N18", "=N19"):
                errors.append(f"formula changed for {name}")
            if (
                snapshot.sheet_names != ("Sheet1", "Rates")
                or snapshot.header_fill_rgb != "0000AA55"
                or snapshot.rate_value != 17.5
            ):
                errors.append(f"worker template structure or formatting changed for {name}")
        if (
            _read_input_row(adrian_file, 18) != _expected_source_row("adrian.testowy", "SYNTHETIC-1", 1)
            or _read_input_row(adrian_file, 19) != _expected_source_row("adrian.testowy", "SYNTHETIC-3", 3)
            or _read_input_row(darek_file, 18) != _expected_source_row("dariusz.fikcyjny2", "SYNTHETIC-2", 2)
            or _read_input_row(kamil_file, 18) != (None,) * 13 + (0,) + (None,) * 32
        ):
            errors.append("worker rows were not routed or the empty workbook was changed")
        if (
            _hyperlinks(adrian_file) != {"F18": f"{ORDER_LINK}18", "F19": f"{ORDER_LINK}20"}
            or _hyperlinks(darek_file) != {"F18": f"{ORDER_LINK}19"}
            or _hyperlinks(kamil_file) != {}
        ):
            errors.append("order number hyperlinks of the Plik zbiorczy did not reach the worker workbooks")
    except (OSError, ValueError, KeyError):
        errors.append("one or more published workbooks cannot be read")

    result = _load_result(result_path, errors)
    expected_summary = {
        "figures": [
            {"label": "Zapisane szablony", "value": 2, "unit": "count"},
            {"label": "Puste szablony", "value": 1, "unit": "count"},
        ],
        "counts": None,
        "files": [],
        "file_plan": FILE_PLAN,
    }
    if (
        result.get("result") != "OK"
        or result.get("stop") is not None
        or result.get("warnings") != []
        or result.get("summary") != expected_summary
    ):
        errors.append("run result does not report a successful complete run")
    _check_progress(result["progress"], errors)
    _check_metrics(root, [("DRY-RUN", "OK"), ("RUN", "OK")], errors)

    return _finish_assertion(
        errors,
        "ASSERT OK | mode=run | workbooks_checked=3 | "
        "formulas_preserved=true | hyperlinks_equal_plik_zbiorczy=F | worker_template_unchanged=true | "
        "progress_reported=true | metrics_safe=true",
    )


def _assert_no_publish(root: Path, result_path: Path | None, expected_stop: str, expected_what: str | None) -> int:
    period_directory = root / PERIOD
    target_directory = period_directory / f"Rozliczenie pracowników {PERIOD}"
    manifest = json.loads((root / "fixture_manifest.json").read_text(encoding="utf-8"))
    errors = _unchanged_inputs(root, manifest)
    if target_directory.exists():
        errors.append("failed run published the target directory")
    if list(period_directory.glob(f".{target_directory.name}.staging-*")):
        errors.append("failed run left a staging directory")
    _check_stop(_load_result(result_path, errors), expected_stop, expected_what, errors)
    return _finish_assertion(
        errors,
        "ASSERT OK | mode=no-publish | output_folder_absent=true | inputs_unchanged=true",
    )


def _assert_existing_output(root: Path, result_path: Path | None, expected_stop: str, expected_what: str | None) -> int:
    target_directory = root / PERIOD / f"Rozliczenie pracowników {PERIOD}"
    sentinel = target_directory / "existing-synthetic.txt"
    manifest = json.loads((root / "fixture_manifest.json").read_text(encoding="utf-8"))
    errors = _unchanged_inputs(root, manifest)
    if not target_directory.is_dir() or sentinel.read_text(encoding="utf-8") != "preserve":
        errors.append("existing output folder was changed")
    if {path.name for path in target_directory.iterdir()} != {sentinel.name}:
        errors.append("existing output folder gained or lost files")
    _check_stop(_load_result(result_path, errors), expected_stop, expected_what, errors)
    return _finish_assertion(
        errors,
        "ASSERT OK | mode=existing-output | existing_folder_unchanged=true",
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", required=True, type=Path)
    parser.add_argument(
        "--expect",
        choices=("dry-run", "run", "no-publish", "existing-output"),
        required=True,
    )
    parser.add_argument("--expected-stop", help="code of the Komunikat the run stops with (no-publish, existing-output)")
    parser.add_argument("--expected-what", help="text the stop's Komunikat must contain in what happened")
    parser.add_argument("--result", type=Path, help="evidence JSON of the process step")
    args = parser.parse_args(argv)
    root = args.root.expanduser().resolve()
    result_path = args.result.expanduser().resolve() if args.result else None
    try:
        if args.expect == "dry-run":
            return _assert_dry_run(root, result_path)
        if args.expect == "run":
            return _assert_run(root, result_path)
        if not args.expected_stop:
            parser.error(f"--expected-stop is required for {args.expect}")
        if args.expect == "no-publish":
            return _assert_no_publish(root, result_path, args.expected_stop, args.expected_what)
        return _assert_existing_output(root, result_path, args.expected_stop, args.expected_what)
    except (OSError, ValueError, KeyError) as exc:
        print(f"ASSERT FAIL: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

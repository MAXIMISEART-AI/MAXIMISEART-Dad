"""Dad's week through real Microsoft Excel: period files open, Gotowość typed and saved in Excel, then Rozliczenia pracowników.

    .venv/bin/python .agents/skills/verify-skoroszyty-w-excelu/scripts/run_excel_verification.py
    .venv/bin/python .agents/skills/verify-skoroszyty-w-excelu/scripts/run_excel_verification.py --wzorce syntetyczne
    .venv/bin/python .agents/skills/verify-skoroszyty-w-excelu/scripts/run_excel_verification.py --kontrola-naprawy

Prints ``STEP <feature> | <id> | OK`` per checked behaviour, then ``VERIFY OK`` (or ``VERIFY FAIL``,
``VERIFY SKIP``) with the evidence directory. Evidence holds names, counts, addresses, and timings,
never a cell value. No step waits for a human, except the opt-in ``--kontrola-naprawy``.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass, field
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time
import uuid
import zipfile

import excel


SCRIPT = Path(__file__).resolve()
REPO_ROOT = SCRIPT.parents[4]
OTHER_SKILL = REPO_ROOT / ".agents" / "skills" / "verify-rozliczenia" / "scripts"
PROCESS_SCRIPT = REPO_ROOT / "tools" / "uruchom_proces.py"
LOCK = REPO_ROOT / ".verification" / "excel.lock"
PERIOD = "08_14_09_2026"
TEMPLATE_NAMES = (
    "Wzorzec rozliczenia wewnętrznego.xlsx",
    "Wzorzec pliku zbiorczego.xlsx",
    "Wzorzec rozliczenia pracownika.xlsx",
)
HEADER_ROW = 17
FIRST_ROW = 18
LAST_SCANNED_ROW = 60
INPUT_COLUMNS = range(14, 47)  # N:AT, what Dad types
QUANTITY_COLUMNS = range(14, 43)  # N:AP
CALCULATED = "AU{row}:AX{row}"  # amounts; AY looks up the Słownik, which is #N/D without the Słownik itself
FORMULAS = "AU{row}:AY{row}"
FILLED_ORDERS = ("PREP-SYN-ZL-2", "PREP-SYN-ZL-7", "PREP-SYN-ZL-6")
WORKER_ORDERS = {
    "Adrian Testowy": ("PREP-SYN-ZL-2", "PREP-SYN-ZL-7"),
    "Darek Fikcyjny": ("PREP-SYN-ZL-6",),
    "Kamil Syntetyczny": ("PREP-SYN-ZL-4",),
}
# Wyróżnienia of the synthetic Rejestr: ADRES of order 2 yellow with bold dark red, WYKONAWCA of order 4 italic.
HIGHLIGHTS = {
    ("PREP-SYN-ZL-2", "adres"): (0xFFFF00, 0xC00000, True, False),
    ("PREP-SYN-ZL-4", "wykonawca"): (0xFFFFFF, 0x000000, False, True),
}
ROW_MARKER = "PREP-SYN-"


class VerificationFailure(RuntimeError):
    """A step did not end in the state Dad would see."""


def column_letter(number: int) -> str:
    letters = ""
    while number:
        number, rest = divmod(number - 1, 26)
        letters = chr(65 + rest) + letters
    return letters


@dataclass
class Run:
    root: Path
    desk: Path
    evidence: Path
    steps: list[str] = field(default_factory=list)
    observations: dict[str, object] = field(default_factory=dict)

    @property
    def fixture(self) -> Path:
        return self.root / "okres"

    @property
    def config(self) -> Path:
        return self.fixture / "config"

    @property
    def period_folder(self) -> Path:
        return self.fixture / "INEA" / PERIOD

    @property
    def collective_file(self) -> Path:
        return self.period_folder / f"Rozliczenie {PERIOD} - zbiorcze.xlsx"

    @property
    def internal_file(self) -> Path:
        return self.period_folder / f"Rozliczenie wew. {PERIOD}.xlsx"

    def worker_file(self, worker: str) -> Path:
        return self.period_folder / f"Rozliczenie pracowników {PERIOD}" / f"Rozliczenie {PERIOD} - {worker}.xlsx"

    def on_desk(self, path: Path) -> Path:
        """Byte copy of ``path`` on Excel's desk, where Excel opens it without a dialog."""

        copy = self.desk / path.name
        shutil.copyfile(path, copy)
        return copy

    def step(self, feature: str, identifier: str, detail: str = "") -> None:
        line = f"STEP {feature} | {identifier} | OK" + (f" | {detail}" if detail else "")
        self.steps.append(line)
        print(line, flush=True)

    def observe(self, key: str, value: object) -> None:
        self.observations[key] = value

    def write_evidence(self) -> None:
        (self.evidence / "drive.txt").write_text("\n".join(self.steps) + "\n", encoding="utf-8")
        (self.evidence / "excel.json").write_text(
            json.dumps(self.observations, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )


def expect(condition: bool, message: str) -> None:
    if not condition:
        raise VerificationFailure(message)


def _environment() -> dict[str, str]:
    environment = os.environ.copy()
    environment.update({"PYTHONUTF8": "1", "PYTHONIOENCODING": "utf-8", "PYTHONDONTWRITEBYTECODE": "1"})
    return environment


def _python(run: Run, name: str, arguments: list[str], *, json_output: bool = False) -> object:
    """Run a helper or the process script with this Python; record its output and exit code as evidence."""

    completed = subprocess.run(
        [sys.executable, *arguments], cwd=REPO_ROOT, env=_environment(), stdin=subprocess.DEVNULL,
        capture_output=True, text=True, encoding="utf-8", timeout=300, check=False,
    )
    record: dict[str, object] = {"script": Path(arguments[0]).name, "exit_code": completed.returncode}
    if json_output:
        try:
            record["result"] = json.loads(completed.stdout)
        except json.JSONDecodeError:
            record["stdout"] = completed.stdout
        record["stderr"] = completed.stderr
        (run.evidence / f"{name}.json").write_text(json.dumps(record, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    else:
        text = f"exit_code={completed.returncode}\nstdout:\n{completed.stdout}\nstderr:\n{completed.stderr}"
        (run.evidence / f"{name}.txt").write_text(text, encoding="utf-8")
    if completed.returncode != 0:
        print(completed.stdout + completed.stderr, file=sys.stderr)
        raise VerificationFailure(f"{name} exited {completed.returncode}")
    return record.get("result")


def _main_checkout_config() -> Path | None:
    try:
        common = subprocess.run(
            ["git", "rev-parse", "--git-common-dir"], cwd=REPO_ROOT, capture_output=True, text=True, check=True
        ).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return None
    return (REPO_ROOT / common).resolve().parent / "config"


def _real_templates(explicit: Path | None) -> Path | None:
    """``--templates-dir``, else this checkout's ``config/``, else the main checkout's (worktrees lack the Wzorce)."""

    candidates = [explicit] if explicit else [REPO_ROOT / "config", _main_checkout_config()]
    for directory in candidates:
        if directory is not None and all((directory / name).is_file() for name in TEMPLATE_NAMES):
            return directory
    return None


# ---- steps -------------------------------------------------------------------------------------------


def create_fixture(run: Run, real_templates: Path | None) -> None:
    if real_templates is None:
        templates = run.root / "wzorce"
        _python(run, "wzorce", [str(REPO_ROOT / "tools" / "syntetyczne_wzorce.py"), str(templates)])
    else:
        templates = real_templates
    _python(
        run,
        "fixture",
        [
            str(OTHER_SKILL / "create_preparation_fixture.py"),
            "--root", str(run.fixture),
            "--with-worker-template",
            "--templates-from", str(templates),
        ],
    )


def doctor(run: Run) -> None:
    _python(run, "doctor", [str(SCRIPT.parent / "excel_doctor.py"), "--root", str(run.root), "--desk", str(run.desk)])


def preparation(run: Run) -> None:
    result = _python(
        run,
        "przygotowanie",
        [
            str(PROCESS_SCRIPT), "preparation",
            "--register", str(run.fixture / "ZLECENIA INTERMAX OD 08_11_2021.xlsx"),
            "--periods-directory", str(run.fixture / "INEA"),
            "--period", PERIOD,
            "--config", str(run.config / "worker_mapping.yaml"),
            "--internal-template", str(run.config / TEMPLATE_NAMES[0]),
            "--collective-template", str(run.config / TEMPLATE_NAMES[1]),
            "--metrics", str(run.root / "przygotowanie-metrics.jsonl"),
        ],
        json_output=True,
    )
    expect(isinstance(result, dict) and result.get("result") == "OK", "Przygotowanie did not end OK")
    expect(run.collective_file.is_file() and run.internal_file.is_file(), "Przygotowanie left no period files")


def settlement(run: Run) -> None:
    result = _python(
        run,
        "przebieg",
        [
            str(PROCESS_SCRIPT), "settlement",
            "--source", str(run.collective_file),
            "--config", str(run.config / "worker_mapping.yaml"),
            "--worker-template", str(run.config / TEMPLATE_NAMES[2]),
            "--metrics", str(run.root / "przebieg-metrics.jsonl"),
        ],
        json_output=True,
    )
    if not isinstance(result, dict) or result.get("result") != "OK":
        raise VerificationFailure("Przebieg rozliczeń did not end OK")
    figures = {figure["label"]: figure["value"] for figure in result["summary"]["figures"]}
    expect(figures.get("Zapisane szablony") == len(WORKER_ORDERS), "Przebieg did not write three Szablony pracowników")


@dataclass(frozen=True)
class Layout:
    """Columns found by header in row 17, as the processes find them."""

    columns: dict[str, int]

    @property
    def order(self) -> int:
        return self.columns["numer zl."]


def _layout(path: Path) -> Layout:
    headers = [cell.text.strip().casefold() for cell in excel.read(path, f"A{HEADER_ROW}:AT{HEADER_ROW}")[0]]
    columns: dict[str, int] = {}
    for name in ("numer zl.", "adres", "wykonawca"):
        expect(headers.count(name) == 1, f"{path.name}: header {name.upper()} not found once in row {HEADER_ROW}")
        columns[name] = headers.index(name) + 1
    return Layout(columns)


def _order_rows(path: Path, layout: Layout) -> dict[str, int]:
    letter = column_letter(layout.order)
    cells = excel.read(path, f"{letter}{FIRST_ROW}:{letter}{LAST_SCANNED_ROW}")
    return {row[0].text: FIRST_ROW + index for index, row in enumerate(cells) if not row[0].empty}


def _reference(run: Run, name: str) -> tuple[list[str], list[str]]:
    """Link names and row-18 formulas of a Wzorzec as Excel reads them; the Wzorzec is closed again."""

    template = run.on_desk(run.config / name)
    seconds = excel.open_file(template)
    try:
        links = excel.link_names(template)
        formulas = excel.formulas_r1c1(template, FORMULAS.format(row=FIRST_ROW))
    finally:
        excel.close(template)
    run.observe(f"wzorzec:{name}", {"open_seconds": seconds, "links": len(links), "formula_cells": len(formulas)})
    expect(bool(links), f"Excel sees no external link in {name}")
    return links, formulas


def _check_formulas(path: Path, rows: dict[str, int], reference: list[str], *, label: str) -> None:
    """Every Wiersz danych keeps the Wzorzec's formulas, and Excel shows no error in its amounts."""

    for row in rows.values():
        expect(excel.formulas_r1c1(path, FORMULAS.format(row=row)) == reference, f"{label}: row {row} formulas differ from the Wzorzec")
        errors = excel.error_cells(path, CALCULATED.format(row=row))
        expect(errors is None, f"{label}: Excel shows errors in {errors}")


def _check_highlights(path: Path, rows: dict[str, int], layout: Layout, *, label: str) -> int:
    checked = 0
    for (order, header), expected in HIGHLIGHTS.items():
        if order not in rows:
            continue
        address = f"{column_letter(layout.columns[header])}{rows[order]}"
        expect(excel.fill(path, address) == expected, f"{label}: Wyróżnienie in {address} is not what the Rejestr has")
        checked += 1
    return checked


def period_files_open(run: Run, collective_reference: tuple[list[str], list[str]]) -> tuple[Path, Layout]:
    """Feature otwarcie-plikow-okresu: both period files open in Excel without a dialog; the Plik zbiorczy stays open."""

    feature = "otwarcie-plikow-okresu"
    internal = run.on_desk(run.internal_file)
    seconds = excel.open_file(internal)
    excel.close(internal)
    run.observe("otwarcie:rozliczenie-wewnetrzne", {"open_seconds": seconds})
    run.step(feature, "rozliczenie-wewnetrzne-bez-okna", f"open_seconds={seconds}")

    collective = run.on_desk(run.collective_file)
    seconds = excel.open_file(collective)
    run.step(feature, "plik-zbiorczy-bez-okna", f"open_seconds={seconds}")
    links = excel.link_names(collective)
    expect(links == collective_reference[0], "Plik zbiorczy links to other workbooks than its Wzorzec")
    run.step(feature, "plik-zbiorczy-lacze", f"links={len(links)}")
    layout = _layout(collective)
    rows = _order_rows(collective, layout)
    expected_orders = {order for orders in WORKER_ORDERS.values() for order in orders}
    expect(expected_orders <= set(rows), "Plik zbiorczy lacks Zlecenia skuteczne of the Rejestr")
    _check_formulas(collective, rows, collective_reference[1], label="Plik zbiorczy")
    run.step(feature, "plik-zbiorczy-formuly", f"rows={len(rows)}")
    highlights = _check_highlights(collective, rows, layout, label="Plik zbiorczy")
    run.step(feature, "plik-zbiorczy-wyroznienia", f"cells={highlights}")
    run.observe("otwarcie:plik-zbiorczy", {"open_seconds": seconds, "links": len(links), "rows": len(rows)})
    return collective, layout


def _entries(index: int, order: str) -> dict[int, str]:
    """What Dad types into one Wiersz danych: distinct quantities, a charge, remarks; numbers as Excel input."""

    suffix = order.removeprefix("PREP-SYN-ZL-")
    values = {column: str(10 * (index + 1) + column - 13) for column in QUANTITY_COLUMNS}
    values[43] = f"PREP-SYN-OBC-{suffix}"
    values[44] = f"{25.5 + index}"
    values[45] = str(10 + index)
    values[46] = f"PREP-SYN-UWAGI-{suffix}"
    return values


def _matches(cell: excel.Cell, typed: str) -> bool:
    try:
        number = float(typed)
    except ValueError:
        return cell.kind == "s" and cell.text == typed
    return cell.kind == "n" and cell.number == number


def readiness(run: Run, collective: Path, layout: Layout) -> dict[str, list[excel.Cell]]:
    """Feature gotowosc-w-excelu: type N:AT like Dad, save and close in Excel; returns A:AT of every order."""

    feature = "gotowosc-w-excelu"
    rows = _order_rows(collective, layout)
    for index, order in enumerate(FILLED_ORDERS):
        entries = _entries(index, order)
        excel.type_row(collective, f"N{rows[order]}:AT{rows[order]}", [entries[column] for column in INPUT_COLUMNS])
        typed = excel.read(collective, f"N{rows[order]}:AT{rows[order]}")[0]
        differing = [
            f"{column_letter(column)}({cell.kind})"
            for column, cell in zip(INPUT_COLUMNS, typed, strict=True)
            if not _matches(cell, entries[column])
        ]
        expect(not differing, f"Excel holds other values than typed in row {rows[order]}: {', '.join(differing)}")
        amount = excel.read(collective, CALCULATED.format(row=rows[order]))[0][0]
        expect(amount.kind == "n" and amount.number > 0, f"Excel calculated no amount in AU{rows[order]}")
    run.step(feature, "wpisy", f"rows={len(FILLED_ORDERS)} | columns=N:AT | amounts_calculated=true")
    expected = {order: excel.read(collective, f"A{row}:AT{row}")[0] for order, row in rows.items()}
    excel.save(collective)
    excel.close(collective)
    run.step(feature, "zapis-i-zamkniecie", "lock_removed=true")
    expect(collective.read_bytes() != run.collective_file.read_bytes(), "Excel did not write the Plik zbiorczy")
    with zipfile.ZipFile(collective) as archive:
        application = archive.read("docProps/app.xml").decode("utf-8")
        link_parts = [name for name in archive.namelist() if name.startswith("xl/externalLinks/externalLink")]
    expect("Microsoft Macintosh Excel" in application, "the Plik zbiorczy was not last saved by Excel")
    expect(bool(link_parts), "Excel's save dropped the external link of the Plik zbiorczy")
    run.step(feature, "lacze-po-zapisie", f"external_link_parts={len(link_parts)}")
    # Dad saves in his Folder okresu; the desk copy goes back byte for byte.
    shutil.copyfile(collective, run.collective_file)
    digest = hashlib.sha256(run.collective_file.read_bytes()).hexdigest()
    run.observe("gotowosc", {"rows_typed": len(FILLED_ORDERS), "saved_by": "Microsoft Macintosh Excel", "external_link_parts": len(link_parts), "sha256": digest})
    return expected


def worker_files(run: Run, expected: dict[str, list[excel.Cell]], worker_reference: tuple[list[str], list[str]]) -> None:
    """Feature rozliczenia-pracownikow-w-excelu: every Rozliczenie pracownika opens and shows the Gotowość."""

    feature = "rozliczenia-pracownikow-w-excelu"
    for worker, orders in WORKER_ORDERS.items():
        path = run.on_desk(run.worker_file(worker))
        label = f"Rozliczenie {worker}"
        seconds = excel.open_file(path)
        try:
            run.step(feature, "bez-okna", f"{worker} | open_seconds={seconds}")
            expect(excel.link_names(path) == worker_reference[0], f"{label} links to other workbooks than its Wzorzec")
            layout = _layout(path)
            rows = _order_rows(path, layout)
            expect(tuple(rows) == orders, f"{label} holds other Zlecenia or another order than the Plik zbiorczy")
            for order, row in rows.items():
                shown = excel.read(path, f"A{row}:AT{row}")[0]
                differing = [
                    column_letter(column)
                    for column, (left, right) in enumerate(zip(shown, expected[order], strict=True), start=1)
                    if left != right
                ]
                expect(not differing, f"{label} row {row} differs from the Plik zbiorczy in {','.join(differing)}")
            run.step(feature, "wiersze-a-at", f"{worker} | rows={len(rows)}")
            _check_formulas(path, rows, worker_reference[1], label=label)
            for order in set(rows).intersection(FILLED_ORDERS):
                amount = excel.read(path, CALCULATED.format(row=rows[order]))[0][0]
                expect(amount.kind == "n" and amount.number > 0, f"{label}: Excel shows no amount for the Gotowość")
            run.step(feature, "formuly", worker)
            highlights = _check_highlights(path, rows, layout, label=label)
            run.step(feature, "wyroznienia", f"{worker} | cells={highlights}")
            run.observe(f"rozliczenie:{worker}", {"open_seconds": seconds, "rows": len(rows), "highlights": highlights})
        finally:
            excel.close(path)


def repair_control(run: Run) -> None:
    """Feature okno-naprawy: a copy with a broken external link must stop the run as a dialog, not open."""

    feature = "okno-naprawy"
    broken = run.desk / "Zepsute łącze.xlsx"
    with zipfile.ZipFile(run.worker_file("Darek Fikcyjny")) as original, zipfile.ZipFile(broken, "w", zipfile.ZIP_DEFLATED) as copy:
        for info in original.infolist():
            data = original.read(info.filename)
            if info.filename == "xl/externalLinks/externalLink1.xml":
                data = data.replace(b"<sheetDataSet>", b"<sheetDataSet><zepsute>", 1)
            copy.writestr(info, data)
    try:
        excel.open_file(broken, timeout=30)
    except excel.ExcelDialog:
        found = excel.dialogs()
        expect(bool(found), "Excel missed the deadline but shows no dialog")
        run.step(feature, "wykryte", f"dialogs={len(found)} | {found[0].split(' | ')[-1]}")
    else:
        excel.close(broken)
        raise VerificationFailure("Excel opened a workbook with a broken external link without a dialog")
    print("ACTION | W Excelu kliknij „Nie” w oknie o zawartości, która powoduje problem.", flush=True)
    deadline = time.monotonic() + 600
    while time.monotonic() < deadline:
        time.sleep(2)
        if not excel.dialogs():
            run.step(feature, "okno-zamkniete")
            return
    raise VerificationFailure("the repair dialog was not answered within 10 minutes")


# ---- orchestration -----------------------------------------------------------------------------------


def _alive(process_id: int) -> bool:
    try:
        os.kill(process_id, 0)
    except OSError:
        return False
    return True


def _take_lock() -> None:
    """One Excel serves one run: a second run would close or type into the first run's workbooks."""

    LOCK.parent.mkdir(parents=True, exist_ok=True)
    if LOCK.exists():
        holder = LOCK.read_text(encoding="utf-8").strip()
        if holder.isdigit() and _alive(int(holder)):
            raise VerificationFailure(f"another Excel verification (pid {holder}) is running")
    LOCK.write_text(str(os.getpid()), encoding="utf-8")


def _cleanup(run: Run, started_excel: int | None) -> list[str]:
    """Close this run's workbooks, stop the Excel this run started, remove scratch; evidence stays."""

    notes: list[str] = []
    try:
        notes.append(f"closed_workbooks={len(excel.close_under(run.desk))}")
    except excel.ExcelError as exc:
        notes.append(f"close_failed={type(exc).__name__}")
    if started_excel is not None:
        if excel.dialogs() and excel.pid() == started_excel:
            notes.append(f"excel_stopped={str(excel.terminate(started_excel)).lower()}")
        else:
            notes.append(f"excel_quit={str(excel.quit_if_idle()).lower()}")
    elif excel.dialogs():
        notes.append("excel_dialog_left=true (Excel was running before the run; answer the dialog by hand)")
    shutil.rmtree(run.desk, ignore_errors=True)
    completed = subprocess.run(
        [sys.executable, str(OTHER_SKILL / "cleanup.py"), "--root", str(run.root)],
        capture_output=True, text=True, check=False,
    )
    removed = completed.returncode == 0 and not run.root.exists() and not run.desk.exists()
    notes.append(f"scratch_removed={str(removed).lower()}")
    if LOCK.exists() and LOCK.read_text(encoding="utf-8").strip() == str(os.getpid()):
        LOCK.unlink()
    (run.evidence / "cleanup.txt").write_text("\n".join(notes) + "\n", encoding="utf-8")
    return notes


def _hygiene(run: Run) -> None:
    """Evidence names files and counts; it never carries a cell value of the synthetic Rejestr."""

    for path in run.evidence.iterdir():
        expect(ROW_MARKER not in path.read_text(encoding="utf-8"), f"{path.name} carries row content")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--wzorce", choices=("prawdziwe", "syntetyczne"), default="prawdziwe")
    parser.add_argument("--templates-dir", type=Path, help="directory with the three real Wzorce (default: config/)")
    parser.add_argument("--kontrola-naprawy", action="store_true", help="also prove the dialog detector; needs one click")
    args = parser.parse_args(argv)

    run_id = f"excel-{uuid.uuid4().hex[:12]}"
    evidence = REPO_ROOT / ".verification" / "evidence" / run_id
    evidence.mkdir(parents=True)
    run = Run(REPO_ROOT / ".verification" / "runs" / run_id, excel.DESK / run_id, evidence)
    real_templates = None
    if args.wzorce == "prawdziwe":
        real_templates = _real_templates(args.templates_dir)
        if real_templates is None:
            print(f"VERIFY SKIP | wzorce=prawdziwe | no config/ holds all three Wzorce; use --wzorce syntetyczne | evidence={evidence}")
            return 0
    run.observe("excel_version", excel.installed_version())
    run.observe("wzorce", args.wzorce)
    excel_was_running = excel.running()
    run.observe("excel_was_running", excel_was_running)
    started_excel: int | None = None
    outcome = "OK"
    try:
        _take_lock()
        run.root.mkdir(parents=True)
        create_fixture(run, real_templates)
        run.desk.mkdir(parents=True)
        doctor(run)
        preparation(run)
        if not excel_was_running:
            started_excel = excel.launch()
        collective_reference = _reference(run, TEMPLATE_NAMES[1])
        worker_reference = _reference(run, TEMPLATE_NAMES[2])
        collective, layout = period_files_open(run, collective_reference)
        expected = readiness(run, collective, layout)
        settlement(run)
        worker_files(run, expected, worker_reference)
        if args.kontrola_naprawy:
            repair_control(run)
    except (VerificationFailure, excel.ExcelError, subprocess.SubprocessError, OSError) as exc:
        outcome = "FAIL"
        if not excel_was_running and started_excel is None and excel.running():
            started_excel = excel.pid()
        run.observe("failure", f"{type(exc).__name__}: {exc}")
        print(f"VERIFY FAIL | {type(exc).__name__}: {exc}", file=sys.stderr)
    finally:
        run.write_evidence()
        notes = _cleanup(run, started_excel)
    try:
        _hygiene(run)
    except VerificationFailure as exc:
        outcome = "FAIL"
        print(f"VERIFY FAIL | {exc}", file=sys.stderr)
    evidence_kept = (evidence / "drive.txt").is_file()
    print(
        f"VERIFY {outcome} | wzorce={args.wzorce} | steps={len(run.steps)} | {' | '.join(notes)} "
        f"| evidence_kept={str(evidence_kept).lower()} | evidence={evidence}"
    )
    return 0 if outcome == "OK" and evidence_kept else 1


if __name__ == "__main__":
    raise SystemExit(main())

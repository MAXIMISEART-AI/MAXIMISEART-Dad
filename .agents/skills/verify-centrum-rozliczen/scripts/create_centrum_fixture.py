"""Create a synthetic folder okresów, Rejestr zleceń, configuration directory, and metrics files for one Centrum run.

The configuration directory holds what Konfiguracja reads: a synthetic konfiguracja
wykonawców and the three Wzorce, valid for the engine's Sprawdzanie. Centrum's
settings file is written there too, as in Dad's ``config/``. The metrics files
hold a synthetic history in the CLI's schema for Metryki.

The Rejestr zleceń holds orders of the last complete period ``06_12_10_2026``
whose last order is on Saturday, so a RUN of Przygotowanie pliku zbiorczego
asks Dad's decision about the incomplete period. Its order cells carry
``ROW_MARKER``. The Plik zbiorczy of ``29_05_10_2026`` has a Wiersz danych of a
Wykonawca missing from the konfiguracja wykonawców, so a Podgląd bez zapisu of
Przebieg rozliczeń for that period needs checking.
"""

from __future__ import annotations

import argparse
from datetime import datetime
import json
from pathlib import Path
import sys

from openpyxl import Workbook
from openpyxl.worksheet.worksheet import Worksheet
import yaml

# Dad's "today" for the run: Monday 19.10.2026, so the last complete period is 06_12_10_2026,
# whose Folder okresu deliberately does not exist.
TODAY = "2026-10-19"
LAST_COMPLETE = "06_12_10_2026"
# A period whose Plik zbiorczy has a Wiersz danych of a Wykonawca the konfiguracja wykonawców does not know.
NEEDS_CHECK = "29_05_10_2026"
UNKNOWN_WORKER = "wykonawca.spoza.konfiguracji"
WORKERS = ("Wykonawca Testowy A", "Wykonawca Testowy B", "Wykonawca Testowy C")
# A synthetic row value inside every workbook. Centrum must never read or show workbook content,
# so this marker must never appear in evidence (centrum_self_test.py checks it).
ROW_MARKER = "CENTRUM-SYN-ROW"
PHASES = ("Sprawdzanie", "Odczyt danych", "Planowanie", "Zapisywanie")
PREPARATION_COUNTERS = {"period_orders": 9, "successful_orders": 8, "skipped_empty_rows": 1, "warnings": 0}
SETTLEMENT_COUNTERS = {
    "templates_total": 3,
    "templates_completed": 3,
    "rows": 8,
    "written": 3,
    "empty": 0,
    "planned": 3,
    "skipped": 0,
    "issues": 0,
}
# Synthetic history in the CLI's metrics schema (schema_version 1), as the .cmd launchers write it:
# (started_at UTC, mode, period, result, phase times in ms; the total is their sum).
MetricRun = tuple[str, str, str, str, tuple[int, int, int, int]]
PREPARATION_RUNS: tuple[MetricRun, ...] = (
    ("2026-08-25T06:15:00+00:00", "RUN", "18_24_08_2026", "BLAD_KRYTYCZNY", (400, 1300, 0, 0)),
    ("2026-09-01T06:21:00+00:00", "RUN", "25_31_08_2026", "OK", (300, 7100, 900, 2500)),
    ("2026-09-08T06:21:00+00:00", "RUN", "01_07_09_2026", "OK", (300, 7400, 900, 2600)),
    ("2026-09-15T06:21:00+00:00", "RUN", "08_14_09_2026", "OK", (300, 6800, 800, 2500)),
    ("2026-09-22T06:12:00+00:00", "DRY-RUN", "15_21_09_2026", "OK", (300, 6700, 800, 0)),
    ("2026-09-22T06:21:00+00:00", "RUN", "15_21_09_2026", "OK", (400, 7900, 900, 2700)),
    ("2026-09-29T06:12:00+00:00", "DRY-RUN", "22_28_09_2026", "OK", (300, 6900, 900, 0)),
    ("2026-09-29T06:21:00+00:00", "RUN", "22_28_09_2026", "OK", (300, 7100, 900, 2600)),
    ("2026-10-06T06:12:00+00:00", "DRY-RUN", "29_05_10_2026", "OK", (300, 7100, 900, 0)),
    ("2026-10-06T06:21:00+00:00", "RUN", "29_05_10_2026", "OK", (400, 7600, 900, 2700)),
)
SETTLEMENT_RUNS: tuple[MetricRun, ...] = (
    ("2026-09-03T15:46:00+00:00", "RUN", "25_31_08_2026", "OK", (500, 3100, 700, 8000)),
    ("2026-09-10T15:46:00+00:00", "RUN", "01_07_09_2026", "OK", (500, 3000, 700, 7600)),
    ("2026-09-17T15:46:00+00:00", "RUN", "08_14_09_2026", "WYMAGA_SPRAWDZENIA", (500, 3200, 800, 7600)),
    ("2026-09-24T15:40:00+00:00", "DRY-RUN", "15_21_09_2026", "OK", (500, 2100, 700, 0)),
    ("2026-09-24T15:46:00+00:00", "RUN", "15_21_09_2026", "OK", (400, 2900, 700, 7100)),
    ("2026-10-01T15:46:00+00:00", "RUN", "22_28_09_2026", "OK", (500, 3400, 800, 8000)),
)
WORKER_IDS = ("wykonawca.a", "wykonawca.b", "wykonawca.c")
INTERNAL_TEMPLATE = "Wzorzec rozliczenia wewnętrznego.xlsx"
COLLECTIVE_TEMPLATE = "Wzorzec pliku zbiorczego.xlsx"
WORKER_TEMPLATE = "Wzorzec rozliczenia pracownika.xlsx"
# The target headers the engine looks for; in the Wzorzec pliku zbiorczego WYKONAWCA must be in H17.
INTERNAL_HEADERS = (
    "DATA", "MIASTO", "ADRES", "UMOWA", "URZĄDZENIA", "CZYNNOŚCI", "NUMER ZL.", "WYKONAWCA",
    "NUMER UMOWY/ZLECENIA ORANGE", "SKUTECZNE", "CZYNNOŚCI ZREALIZOWANE",
)
COLLECTIVE_HEADERS = (
    "MIASTO", "ADRES", "UMOWA", "URZĄDZENIA", "CZYNNOŚCI", "NUMER ZL.", "DATA", "WYKONAWCA",
    "NUMER UMOWY/ZLECENIA ORANGE", "SKUTECZNE", "CZYNNOŚCI ZREALIZOWANE",
)


REGISTER_HEADERS = (
    "nr zlecenia", "DATA GODZ. POCZ.", "WYKONAWCA", "MIASTO", "adres", "STATUS APLIKACJI", "UMOWA",
    "URZĄDZENIA", "CZYNNOŚCI", "SKUTECZNE", "CZYNNOŚCI ZREALIZOWANE", "NUMER UMOWY/ZLECENIA ORANGE",
)
# (start, worker, SKUTECZNE): one order of the previous period, then 06_12_10_2026 ending on Saturday.
ORDERS = (
    (datetime(2026, 10, 5, 9, 0), "wykonawca.a", "tak"),
    (datetime(2026, 10, 6, 8, 0), "wykonawca.a", "tak"),
    (datetime(2026, 10, 7, 10, 0), "wykonawca.b", "nie"),
    (datetime(2026, 10, 8, 12, 0), "wykonawca.b", "tak"),
    (datetime(2026, 10, 10, 9, 30), "wykonawca.c", "tak"),
)
# What Przygotowanie pliku zbiorczego of LAST_COMPLETE reports for these orders (orders per day from Tuesday).
EXPECTED_PREPARATION = {
    "period_order_count": 4,
    "successful_order_count": 3,
    "skipped_empty_rows": 0,
    "orders_per_day": [1, 1, 1, 0, 1, 0, 0],
}


def _register(path: Path) -> None:
    """A Rejestr zleceń with one data sheet; every order cell with content carries the row marker."""

    workbook = Workbook()
    sheet = workbook.active
    assert isinstance(sheet, Worksheet)
    sheet.title = "ZLECENIA"
    sheet.append(REGISTER_HEADERS)
    for number, (started, worker, successful) in enumerate(ORDERS, start=1):
        content = f"{ROW_MARKER}-{number:03d}"
        values: dict[str, object] = dict.fromkeys(REGISTER_HEADERS, content)
        values.update({"DATA GODZ. POCZ.": started, "WYKONAWCA": worker, "SKUTECZNE": successful})
        sheet.append([values[header] for header in REGISTER_HEADERS])
    workbook.save(path)


def _workbook(path: Path) -> None:
    workbook = Workbook()
    sheet = workbook.active
    assert sheet is not None
    sheet["A18"] = ROW_MARKER
    workbook.save(path)


def _template(path: Path, header_row: int, headers: tuple[str, ...]) -> None:
    """A Wzorzec without orders; the row marker sits on a second sheet the Sprawdzanie never reads."""

    workbook = Workbook()
    sheet = workbook.active
    assert isinstance(sheet, Worksheet)
    for column, header in enumerate(headers, start=1):
        sheet.cell(header_row, column).value = header
    workbook.create_sheet("Stawki")["A1"] = ROW_MARKER
    workbook.save(path)


def _configuration(config: Path) -> dict[str, str]:
    worker_config = config / "worker_mapping.yaml"
    worker_config.write_text(
        yaml.safe_dump(
            {"schema_version": 1, "workers": dict(zip(WORKER_IDS, WORKERS))}, allow_unicode=True, sort_keys=False
        ),
        encoding="utf-8",
    )
    _template(config / INTERNAL_TEMPLATE, 1, INTERNAL_HEADERS)
    _template(config / COLLECTIVE_TEMPLATE, 17, COLLECTIVE_HEADERS)
    _template(config / WORKER_TEMPLATE, 17, COLLECTIVE_HEADERS)
    return {
        "worker_config": str(worker_config),
        "internal_template": str(config / INTERNAL_TEMPLATE),
        "collective_template": str(config / COLLECTIVE_TEMPLATE),
        "worker_template": str(config / WORKER_TEMPLATE),
    }


def _period_files(periods: Path, token: str) -> Path:
    period_folder = periods / token
    period_folder.mkdir()
    _workbook(period_folder / f"Rozliczenie wew. {token}.xlsx")
    _workbook(period_folder / f"Rozliczenie {token} - zbiorcze.xlsx")
    return period_folder


def _collective_file(path: Path, workers: tuple[str, ...]) -> None:
    """A Plik zbiorczy in the engine's layout: headers in row 17, one Wiersz danych per worker id from row 18."""

    workbook = Workbook()
    sheet = workbook.active
    assert isinstance(sheet, Worksheet)
    for column, header in enumerate(COLLECTIVE_HEADERS, start=1):
        sheet.cell(17, column).value = header
    worker_column = COLLECTIVE_HEADERS.index("WYKONAWCA") + 1
    for row, worker in enumerate(workers, start=18):
        for column in range(1, len(COLLECTIVE_HEADERS) + 1):
            sheet.cell(row, column).value = f"{ROW_MARKER}-{row:03d}"
        sheet.cell(row, worker_column).value = worker
    workbook.save(path)


def _metric_record(run: MetricRun, counters: dict[str, int]) -> dict[str, object]:
    started_at, mode, period, result, phases = run
    completed = result != "BLAD_KRYTYCZNY"
    return {
        "schema_version": 1,
        "started_at": started_at,
        "mode": mode,
        "period": period,
        "completed": completed,
        "result": result,
        "total_duration_ms": sum(phases),
        "phase_durations_ms": dict(zip(PHASES, phases)),
        "counters": counters if completed else dict.fromkeys(counters, 0),
    }


def _metrics(root: Path) -> dict[str, object]:
    """Both metrics files with a valid history and one record each that the CLI's reader skips."""

    metrics = root / "metrics"
    metrics.mkdir()
    preparation = metrics / "przygotowanie-pliku-zbiorczego-metrics.jsonl"
    settlement = metrics / "rozliczenia-metrics.jsonl"
    preparation_lines = [json.dumps(_metric_record(run, PREPARATION_COUNTERS)) for run in PREPARATION_RUNS]
    # Przebieg rozliczeń counters in the Przygotowanie file: invalid there, so skipped.
    preparation_lines.append(json.dumps(_metric_record(SETTLEMENT_RUNS[0], SETTLEMENT_COUNTERS)))
    settlement_lines = [json.dumps(_metric_record(run, SETTLEMENT_COUNTERS)) for run in SETTLEMENT_RUNS]
    settlement_lines.append('{"schema_version":1,"started_at":"2026-10-0')  # a torn last line
    preparation.write_text("".join(line + "\n" for line in preparation_lines), encoding="utf-8")
    settlement.write_text("".join(line + "\n" for line in settlement_lines), encoding="utf-8")
    interrupted = PREPARATION_RUNS[0]
    return {
        "preparation": str(preparation),
        "settlement": str(settlement),
        "runs": len(PREPARATION_RUNS) + len(SETTLEMENT_RUNS),
        "oldest": min(run[0] for run in (*PREPARATION_RUNS, *SETTLEMENT_RUNS)),
        # period, then the measured phase times until the interruption
        "interrupted": [interrupted[2], [phase for phase in interrupted[4] if phase]],
    }


def create(root: Path) -> dict[str, object]:
    root.mkdir(parents=True)
    (root / "config").mkdir()
    configuration = _configuration(root / "config")
    (root / "picker").mkdir()
    periods = root / "INEA"
    periods.mkdir()

    ready = _period_files(periods, "22_28_09_2026")
    workers = ready / "Rozliczenie pracowników 22_28_09_2026"
    workers.mkdir()
    for worker in WORKERS:
        _workbook(workers / f"Rozliczenie 22_28_09_2026 - {worker}.xlsx")
    needs_check = _period_files(periods, NEEDS_CHECK)
    _collective_file(needs_check / f"Rozliczenie {NEEDS_CHECK} - zbiorcze.xlsx", ("wykonawca.a", UNKNOWN_WORKER))
    (periods / "15_21_09_2026").mkdir()
    (periods / "Archiwum").mkdir()

    register = root / "ZLECENIA SYNTETYCZNE OD 01_01_2026.xlsx"
    _register(register)

    fixture: dict[str, object] = {
        "today": TODAY,
        "periods_directory": str(periods),
        "order_register": str(register),
        "settings": str(root / "config" / "centrum-ustawienia.yaml"),
        "metrics": _metrics(root),
        # Konfiguracja: the files Centrum checks, and the Wykonawcy in the order of the konfiguracja wykonawców
        "configuration": configuration,
        "workers": list(WORKERS),
        # Przygotowanie pliku zbiorczego of the last complete period from the Rejestr zleceń above
        "preparation": EXPECTED_PREPARATION,
        # Przebieg rozliczeń: one Wiersz danych per Wykonawca after Przygotowanie of the last complete period,
        # and the period whose Podgląd bez zapisu needs checking
        "settlement": {"rows_per_worker": [1, 1, 1], "needs_check": NEEDS_CHECK},
        # token, Status okresu, number of Rozliczenia pracowników, last complete period
        "board": [
            [LAST_COMPLETE, "no_period_files", 0, True],
            ["29_05_10_2026", "collective_file_prepared", 0, False],
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

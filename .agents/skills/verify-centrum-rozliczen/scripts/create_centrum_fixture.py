"""Create a synthetic folder okresów, Rejestr zleceń, Wzorce, and worker config for one Centrum run.

The Rejestr zleceń holds orders of the last complete period ``06_12_10_2026``
whose last order is on Saturday, so a RUN of Przygotowanie pliku zbiorczego
asks Dad's decision about the incomplete period. The settings directory starts
empty. Every workbook cell with order content carries ``ROW_MARKER``.
"""

from __future__ import annotations

import argparse
from datetime import datetime
import json
from pathlib import Path
import sys

from openpyxl import Workbook
import yaml

# Dad's "today" for the run: Monday 19.10.2026, so the last complete period is 06_12_10_2026,
# whose Folder okresu deliberately does not exist.
TODAY = "2026-10-19"
LAST_COMPLETE = "06_12_10_2026"
WORKERS = ("Wykonawca Testowy A", "Wykonawca Testowy B", "Wykonawca Testowy C")
# A synthetic row value inside every workbook. Centrum must never read or show workbook content,
# so this marker must never appear in evidence (centrum_self_test.py checks it).
ROW_MARKER = "CENTRUM-SYN-ROW"


REGISTER_HEADERS = (
    "nr zlecenia", "DATA GODZ. POCZ.", "WYKONAWCA", "MIASTO", "adres", "STATUS APLIKACJI", "UMOWA",
    "URZĄDZENIA", "CZYNNOŚCI", "SKUTECZNE", "CZYNNOŚCI ZREALIZOWANE", "NUMER UMOWY/ZLECENIA ORANGE",
)
INTERNAL_TEMPLATE_HEADERS = (
    "DATA", "MIASTO", "ADRES", "UMOWA", "URZĄDZENIA", "CZYNNOŚCI", "NUMER ZL.", "WYKONAWCA",
    "NUMER UMOWY/ZLECENIA ORANGE", "SKUTECZNE", "CZYNNOŚCI ZREALIZOWANE", "zwrot", "UWAGI",
)
# Row 17 of the Wzorzec pliku zbiorczego; WYKONAWCA in column H, where Przebieg rozliczeń reads it.
COLLECTIVE_TEMPLATE_HEADERS = (
    "MIASTO", "ADRES", "UMOWA", "URZĄDZENIA", "CZYNNOŚCI", "NUMER ZL.", "DATA", "WYKONAWCA",
    "NUMER UMOWY/ZLECENIA ORANGE", "SKUTECZNE", "CZYNNOŚCI ZREALIZOWANE",
)
WORKER_MAPPING = {"wykonawca.a": "Wykonawca Testowy A", "wykonawca.b": "Wykonawca Testowy B"}
# (start, worker, SKUTECZNE): one order of the previous period, then 06_12_10_2026 ending on Saturday.
ORDERS = (
    (datetime(2026, 10, 5, 9, 0), "wykonawca.a", "tak"),
    (datetime(2026, 10, 6, 8, 0), "wykonawca.a", "tak"),
    (datetime(2026, 10, 7, 10, 0), "wykonawca.b", "nie"),
    (datetime(2026, 10, 8, 12, 0), "wykonawca.b", "tak"),
    (datetime(2026, 10, 10, 9, 30), "wykonawca.a", "tak"),
)
# What Przygotowanie pliku zbiorczego of LAST_COMPLETE reports for these orders.
EXPECTED_PREPARATION = {
    "period_order_count": 4,
    "successful_order_count": 3,
    "orders_per_day": [1, 1, 1, 0, 1, 0, 0],
}


def _register(path: Path) -> None:
    workbook = Workbook()
    sheet = workbook.active
    assert sheet is not None
    sheet.title = "ZLECENIA"
    sheet.append(REGISTER_HEADERS)
    for number, (started, worker, successful) in enumerate(ORDERS, start=1):
        content = f"{ROW_MARKER}-{number:03d}"
        values = {
            "nr zlecenia": content,
            "DATA GODZ. POCZ.": started,
            "WYKONAWCA": worker,
            "MIASTO": "MIASTO SYNTETYCZNE",
            "adres": content,
            "STATUS APLIKACJI": "zamknięte",
            "UMOWA": content,
            "URZĄDZENIA": "dekoder",
            "CZYNNOŚCI": "instalacja",
            "SKUTECZNE": successful,
            "CZYNNOŚCI ZREALIZOWANE": "montaż",
            "NUMER UMOWY/ZLECENIA ORANGE": content,
        }
        sheet.append([values[header] for header in REGISTER_HEADERS])
    workbook.save(path)


def _internal_template(path: Path) -> None:
    workbook = Workbook()
    sheet = workbook.active
    assert sheet is not None
    sheet.append(INTERNAL_TEMPLATE_HEADERS)
    workbook.save(path)


def _collective_template(path: Path) -> None:
    workbook = Workbook()
    sheet = workbook.active
    assert sheet is not None
    sheet.title = "Sheet1"
    sheet["A1"] = "STAWKI"
    sheet["N1"] = 17.5
    for column, header in enumerate(COLLECTIVE_TEMPLATE_HEADERS, start=1):
        sheet.cell(17, column).value = header
    for row in range(18, 24):
        for column in range(14, 43):  # N:AP, quantities prepared with zeros
            sheet.cell(row, column).value = 0
    workbook.save(path)


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
    _register(register)
    tools = root / "narzedzie"
    tools.mkdir()
    (tools / "worker_mapping.yaml").write_text(
        yaml.safe_dump({"schema_version": 1, "workers": WORKER_MAPPING}, allow_unicode=True), encoding="utf-8"
    )
    _internal_template(tools / "Wzorzec rozliczenia wewnętrznego.xlsx")
    _collective_template(tools / "Wzorzec pliku zbiorczego.xlsx")

    fixture: dict[str, object] = {
        "today": TODAY,
        "periods_directory": str(periods),
        "order_register": str(register),
        "settings": str(root / "config" / "centrum-ustawienia.yaml"),
        # The tool's own files (worker config, Wzorce, metrics) for this run instead of the repository's.
        "tool_paths": {
            "worker_config": str(tools / "worker_mapping.yaml"),
            "internal_template": str(tools / "Wzorzec rozliczenia wewnętrznego.xlsx"),
            "collective_template": str(tools / "Wzorzec pliku zbiorczego.xlsx"),
            "preparation_metrics": str(tools / ".przygotowanie-pliku-zbiorczego-metrics.jsonl"),
        },
        "preparation": EXPECTED_PREPARATION,
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

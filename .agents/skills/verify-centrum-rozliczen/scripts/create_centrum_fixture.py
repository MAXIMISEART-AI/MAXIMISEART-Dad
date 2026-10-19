"""Create a synthetic folder okresów, Rejestr zleceń, and configuration directory for one Centrum run.

The configuration directory holds what Konfiguracja reads: a synthetic konfiguracja
wykonawców and the three Wzorce, valid for the engine's Sprawdzanie. Centrum's
settings file is written there too, as in Dad's ``config/``.
"""

from __future__ import annotations

import argparse
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
WORKERS = ("Wykonawca Testowy A", "Wykonawca Testowy B", "Wykonawca Testowy C")
# A synthetic row value inside every workbook. Centrum must never read or show workbook content,
# so this marker must never appear in evidence (centrum_self_test.py checks it).
ROW_MARKER = "CENTRUM-SYN-ROW"
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
    _period_files(periods, "29_05_09_2026")
    (periods / "15_21_09_2026").mkdir()
    (periods / "Archiwum").mkdir()

    register = root / "ZLECENIA SYNTETYCZNE OD 01_01_2026.xlsx"
    _workbook(register)

    fixture: dict[str, object] = {
        "today": TODAY,
        "periods_directory": str(periods),
        "order_register": str(register),
        "settings": str(root / "config" / "centrum-ustawienia.yaml"),
        # Konfiguracja: the files Centrum checks, and the Wykonawcy in the order of the konfiguracja wykonawców
        "configuration": configuration,
        "workers": list(WORKERS),
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

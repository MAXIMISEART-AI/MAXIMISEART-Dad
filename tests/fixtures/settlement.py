"""Przebieg rozliczeń w testach: syntetyczne pliki, obserwator postępu i CLI.

Plik zbiorczy, Wzorzec rozliczenia pracownika i konfiguracja wykonawców są
budowane w katalogu tymczasowym. Nie zawierają prawdziwych danych klientów.
"""

from __future__ import annotations

import sys
import time
import types
from io import StringIO
from pathlib import Path

import pytest
import yaml
from openpyxl import Workbook
from openpyxl.styles import PatternFill

from rozliczenia.cli import main
from rozliczenia.domain import ProgressEvent, ProgressObserver
from rozliczenia.progress import ProgressProjection
from rozliczenia.telemetry import MetricsStore
from tests.fixtures.workbooks import active_worksheet

PERIOD = "08_14_09_2026"


NOT_A_PERIOD = "09_15_09_2026"  # wygląda jak token okresu, ale 9 września 2026 to środa


SOURCE_NAME = f"Rozliczenie {PERIOD} - zbiorcze.xlsx"


def write_mapping(path: Path) -> Path:
    path.write_text(
        yaml.safe_dump(
            {
                "schema_version": 1,
                "workers": {
                    "adrian.testowy": "Adrian Testowy",
                    "dariusz.fikcyjny2": "Darek Fikcyjny",
                    "kamil.syntetyczny": "Kamil Syntetyczny",
                },
            },
            allow_unicode=True,
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    return path


def write_template(path: Path) -> None:
    workbook = Workbook()
    sheet = active_worksheet(workbook)
    sheet.title = "Sheet1"
    sheet.cell(17, 8).value = "WYKONAWCA"
    sheet["A17"].fill = PatternFill(fill_type="solid", fgColor="00AA55")
    sheet.cell(18, 47).value = "=N18"
    sheet.cell(19, 47).value = "=N19"
    sheet.cell(18, 14).value = 0
    sheet.cell(19, 14).value = 0
    rates = workbook.create_sheet("Rates")
    rates["A1"] = "synthetic rate"
    rates["B1"] = 17.5
    workbook.save(path)


def write_source(path: Path, *, include_unmapped: bool = True) -> None:
    workbook = Workbook()
    sheet = active_worksheet(workbook)
    sheet.title = "Sheet1"
    sheet.cell(17, 8).value = "WYKONAWCA"
    rows = [
        ("POZNAŃ", "syntetyczny adres 1", "adrian.testowy", "#1"),
        ("POZNAŃ", "syntetyczny adres 2", "dariusz.fikcyjny2", "#2"),
        ("POZNAŃ", "syntetyczny adres 3", "adrian.testowy", "#3"),
    ]
    if include_unmapped:
        rows.append(("POZNAŃ", "syntetyczny adres 4", "andrzej.nieznany2", "#4"))
    for row_number, (city, address, worker, order_number) in enumerate(rows, start=18):
        sheet.cell(row_number, 1).value = city
        sheet.cell(row_number, 2).value = address
        sheet.cell(row_number, 6).value = order_number
        sheet.cell(row_number, 8).value = worker
        sheet.cell(row_number, 14).value = row_number - 17
    workbook.save(path)


def make_fixture(tmp_path: Path, period: str = PERIOD) -> tuple[Path, Path, Path]:
    period_directory = tmp_path / period
    period_directory.mkdir(parents=True)
    target_directory = period_directory / f"Rozliczenie pracowników {period}"
    source_path = period_directory / f"Rozliczenie {period} - zbiorcze.xlsx"
    write_source(source_path, include_unmapped=False)
    config_path = write_mapping(tmp_path / "worker_mapping.yaml")
    write_template(tmp_path / "Wzorzec rozliczenia pracownika.xlsx")
    return source_path, target_directory, config_path


def projected(projection: ProgressProjection) -> ProgressObserver:
    def observer(event: ProgressEvent) -> None:
        projection.update(event)

    return observer


def run_cli(
    source_path: Path,
    config_path: Path,
    metrics_path: Path,
    *extra_args: str,
) -> tuple[int, str]:
    output = StringIO()
    exit_code = main(
        [
            "--source",
            str(source_path),
            "--config",
            str(config_path),
            "--worker-template",
            str(config_path.parent / "Wzorzec rozliczenia pracownika.xlsx"),
            "--metrics",
            str(metrics_path),
            *extra_args,
        ],
        output=output,
    )
    return exit_code, output.getvalue()


def make_preview_fixture(tmp_path: Path) -> tuple[Path, Path, Path]:
    source_path, target_directory, config_path = make_fixture(tmp_path)
    write_source(source_path, include_unmapped=True)
    return source_path, target_directory, config_path


def install_source_dialog(monkeypatch: pytest.MonkeyPatch, *, selected: str, answer_after_s: float = 0) -> list[str]:
    """Zastępuje okno wyboru Pliku zbiorczego (tkinter); zwraca tytuły pokazanych okien."""

    shown: list[str] = []

    class FakeRoot:
        def withdraw(self) -> None:
            pass

        def destroy(self) -> None:
            pass

    def askopenfilename(*, title: str, **_kwargs: object) -> str:
        shown.append(title)
        time.sleep(answer_after_s)
        return selected

    filedialog = types.ModuleType("tkinter.filedialog")
    setattr(filedialog, "askopenfilename", askopenfilename)
    tk_module = types.ModuleType("tkinter")
    setattr(tk_module, "Tk", FakeRoot)
    setattr(tk_module, "filedialog", filedialog)
    monkeypatch.setitem(sys.modules, "tkinter", tk_module)
    monkeypatch.setitem(sys.modules, "tkinter.filedialog", filedialog)
    return shown


def append_completed_records(metrics_path: Path, mode: str, count: int = 5) -> None:
    for sample in range(count):
        MetricsStore(metrics_path).append(
            {
                "schema_version": 1,
                "started_at": f"2026-09-28T00:00:0{sample}+00:00",
                "mode": mode,
                "period": PERIOD,
                "completed": True,
                "result": "OK",
                "total_duration_ms": 1000,
                "phase_durations_ms": {"Sprawdzanie": 1, "Odczyt danych": 1, "Planowanie": 1, "Zapisywanie": 1},
                "counters": {
                    "templates_total": 1,
                    "templates_completed": 1,
                    "rows": 1,
                    "written": 1,
                    "empty": 0,
                    "planned": 0,
                    "skipped": 0,
                    "issues": 0,
                },
            }
        )

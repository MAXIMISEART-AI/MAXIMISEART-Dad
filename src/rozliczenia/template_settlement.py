"""Przetwarzanie pojedynczego Szablonu pracownika."""

from __future__ import annotations

import zipfile
from datetime import date, datetime, time, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Iterable

from openpyxl import load_workbook
from openpyxl.cell.cell import Cell, MergedCell
from openpyxl.cell.rich_text import CellRichText
from openpyxl.utils.exceptions import InvalidFileException
from openpyxl.worksheet.formula import ArrayFormula, DataTableFormula
from openpyxl.workbook.workbook import Workbook
from openpyxl.worksheet.worksheet import Worksheet

from . import workbook_files
from .domain import Issue, WorkerResult


_HEADER_ROW = 17
_DATA_START_ROW = 18
_WORKER_COLUMN = 8  # H
_COPY_COLUMNS = range(1, 47)  # A:AT
_INPUT_CHECK_COLUMNS = range(1, 12)  # A:K
ExcelCellValue = (
    bool
    | int
    | float
    | Decimal
    | str
    | CellRichText
    | date
    | datetime
    | time
    | timedelta
    | DataTableFormula
    | ArrayFormula
    | bytes
    | None
)
ExcelRow = tuple[ExcelCellValue, ...]


class TemplateWriteError(Exception):
    """Błąd właściwego zapisu Szablonu pracownika."""


class PlaceholderValidationError(Exception):
    """Placeholder nie może bezpiecznie posłużyć jako wzór nowych skoroszytów."""


def _is_worker_header(value: object) -> bool:
    return str(value or "").replace("\u00a0", " ").casefold().split() == ["wykonawca"]


def _is_real_value(cell: Cell | MergedCell) -> bool:
    """Pomija formuły szablonu przy wykrywaniu istniejących danych."""

    return cell.value is not None and cell.data_type != "f"


def _target_has_input_data(sheet: Worksheet) -> bool:
    """Sprawdza dane wejściowe A:K, ignorując formuły w szablonie."""

    for row in range(_DATA_START_ROW, sheet.max_row + 1):
        if any(_is_real_value(sheet.cell(row=row, column=column)) for column in _INPUT_CHECK_COLUMNS):
            return True
    return False


def validate_placeholder(path: Path) -> None:
    """Sprawdza Placeholder bez modyfikowania jego zawartości."""

    if not path.is_file():
        raise PlaceholderValidationError("Nie znaleziono Placeholdera.")
    if workbook_files.is_open_in_excel(path):
        raise PlaceholderValidationError("Placeholder jest otwarty lub zablokowany.")
    try:
        workbook = load_workbook(path, read_only=False, data_only=False, keep_links=True)
    except (OSError, InvalidFileException, zipfile.BadZipFile) as exc:
        raise PlaceholderValidationError("Nie można odczytać Placeholdera.") from exc

    try:
        sheet = _active_worksheet(workbook)
        if sheet is None:
            raise PlaceholderValidationError("Placeholder nie zawiera arkusza roboczego.")
        header = sheet.cell(row=_HEADER_ROW, column=_WORKER_COLUMN).value
        if not _is_worker_header(header):
            raise PlaceholderValidationError("Placeholder nie ma nagłówka WYKONAWCA w H:17.")
        if _target_has_input_data(sheet):
            raise PlaceholderValidationError("Placeholder zawiera dane i nie może być użyty jako wzór.")
    finally:
        workbook.close()


def _active_worksheet(workbook: Workbook) -> Worksheet | None:
    sheet = workbook.active
    return sheet if isinstance(sheet, Worksheet) else None


def _write_workbook(path: Path, workbook: Workbook, rows: list[ExcelRow]) -> None:
    sheet = _active_worksheet(workbook)
    if sheet is None:
        raise ValueError("Szablon nie zawiera arkusza roboczego.")
    for destination_row, values in enumerate(rows, start=_DATA_START_ROW):
        for column, value in zip(_COPY_COLUMNS, values):
            sheet.cell(row=destination_row, column=column).value = value

    workbook_files.request_full_recalculation(workbook)
    workbook_files.save_workbook(workbook, path)


def process_template(
    worker_name: str,
    target_path: Path,
    rows: Iterable[ExcelRow],
) -> WorkerResult:
    """Przetwarza jeden Szablon pracownika i zwraca jego bezpieczny wynik."""

    rows = list(rows)
    if workbook_files.is_open_in_excel(target_path):
        issue = Issue("PLIK_ZABLOKOWANY", f"Plik jest otwarty lub zablokowany: {target_path.name}")
        return WorkerResult(worker_name, target_path, 0, "ZABLOKOWANY", (issue,))
    try:
        workbook = load_workbook(target_path, read_only=False, data_only=False, keep_links=True)
        try:
            sheet = _active_worksheet(workbook)
            if sheet is None:
                raise ValueError("Szablon nie zawiera arkusza.")
            header = sheet.cell(row=_HEADER_ROW, column=_WORKER_COLUMN).value
            if not _is_worker_header(header):
                issue = Issue("ZLY_SZABLON", f"Szablon nie ma WYKONAWCA w H:17: {target_path.name}.")
                return WorkerResult(worker_name, target_path, 0, "ZLY_SZABLON", (issue,))
            if _target_has_input_data(sheet):
                issue = Issue("NADPISANIE_ZABLOKOWANE", f"Szablon zawiera już dane: {target_path.name}.")
                return WorkerResult(worker_name, target_path, 0, "ZABLOKOWANY", (issue,))
            if not rows:
                return WorkerResult(worker_name, target_path, 0, "PUSTY_SZABLON")

            try:
                _write_workbook(target_path, workbook, rows)
            except (
                workbook_files.WorkbookSaveError,
                OSError,
                InvalidFileException,
                ValueError,
                zipfile.BadZipFile,
            ) as exc:
                raise TemplateWriteError(f"Nie można zapisać szablonu: {target_path.name}") from exc
            return WorkerResult(worker_name, target_path, len(rows), "ZAPISANO")
        finally:
            workbook.close()
    except (OSError, InvalidFileException, ValueError, zipfile.BadZipFile):
        issue = Issue("BLAD_SZABLONU", f"Nie można obsłużyć szablonu: {target_path.name}.")
        return WorkerResult(worker_name, target_path, 0, "POMINIĘTO", (issue,))

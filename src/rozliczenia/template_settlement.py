"""Przetwarzanie pojedynczego Szablonu pracownika."""

from __future__ import annotations

import os
import tempfile
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
ExternalLinkParts = dict[str, tuple[zipfile.ZipInfo, bytes]]


class _TemplateLockedError(Exception):
    """Szablon pracownika jest otwarty lub zablokowany."""


class TemplateWriteError(Exception):
    """Błąd właściwego zapisu Szablonu pracownika."""


class PlaceholderValidationError(Exception):
    """Placeholder nie może bezpiecznie posłużyć jako wzór nowych skoroszytów."""


def _excel_lock_path(path: Path) -> Path:
    """Zwraca standardowy plik blokady tworzony przez desktopowy Excel."""

    return path.with_name(f"~${path.name}")


def _ensure_unlocked(path: Path) -> None:
    if _excel_lock_path(path).exists():
        raise _TemplateLockedError(f"Plik jest otwarty lub zablokowany: {path.name}")


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
    try:
        _ensure_unlocked(path)
        workbook = load_workbook(path, read_only=False, data_only=False, keep_links=True)
    except _TemplateLockedError as exc:
        raise PlaceholderValidationError("Placeholder jest otwarty lub zablokowany.") from exc
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


def _external_link_parts(path: Path) -> ExternalLinkParts:
    """Pobiera oryginalne relacje zewnętrzne, których openpyxl nie zapisuje 1:1."""

    with zipfile.ZipFile(path, "r") as archive:
        return {
            info.filename: (info, archive.read(info.filename))
            for info in archive.infolist()
            if info.filename.startswith("xl/externalLinks/")
        }


def _restore_external_link_parts(
    path: Path,
    parts: ExternalLinkParts,
) -> None:
    """Przywraca cały fragment externalLinks bez zmiany arkuszy i danych."""

    if not parts:
        return
    file_descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.stem}.links.", suffix=".xlsx", dir=path.parent
    )
    os.close(file_descriptor)
    temporary_path = Path(temporary_name)
    try:
        with zipfile.ZipFile(path, "r") as source, zipfile.ZipFile(temporary_path, "w") as target:
            for info in source.infolist():
                if info.filename.startswith("xl/externalLinks/"):
                    continue
                target.writestr(info, source.read(info.filename))
            for info, data in parts.values():
                target.writestr(info, data)
        os.replace(temporary_path, path)
    finally:
        temporary_path.unlink(missing_ok=True)


def _write_workbook(
    path: Path,
    workbook: Workbook,
    rows: list[ExcelRow],
    external_link_parts: ExternalLinkParts,
) -> None:
    sheet = _active_worksheet(workbook)
    if sheet is None:
        raise ValueError("Szablon nie zawiera arkusza roboczego.")
    for destination_row, values in enumerate(rows, start=_DATA_START_ROW):
        for column, value in zip(_COPY_COLUMNS, values):
            sheet.cell(row=destination_row, column=column).value = value

    calculation = getattr(workbook, "calculation", None)
    if calculation is not None:
        calculation.calcMode = "auto"
        calculation.fullCalcOnLoad = True
        calculation.forceFullCalc = True

    file_descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.stem}.", suffix=".xlsx", dir=path.parent
    )
    os.close(file_descriptor)
    temporary_path = Path(temporary_name)
    try:
        workbook.save(temporary_path)
        _restore_external_link_parts(temporary_path, external_link_parts)
        os.replace(temporary_path, path)
    finally:
        temporary_path.unlink(missing_ok=True)


def process_template(
    worker_name: str,
    target_path: Path,
    rows: Iterable[ExcelRow],
) -> WorkerResult:
    """Przetwarza jeden Szablon pracownika i zwraca jego bezpieczny wynik."""

    rows = list(rows)
    try:
        _ensure_unlocked(target_path)
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
                external_link_parts = _external_link_parts(target_path)
                _write_workbook(target_path, workbook, rows, external_link_parts)
            except (OSError, InvalidFileException, ValueError, zipfile.BadZipFile) as exc:
                raise TemplateWriteError(f"Nie można zapisać szablonu: {target_path.name}") from exc
            return WorkerResult(worker_name, target_path, len(rows), "ZAPISANO")
        finally:
            workbook.close()
    except _TemplateLockedError as exc:
        issue = Issue("PLIK_ZABLOKOWANY", str(exc))
        return WorkerResult(worker_name, target_path, 0, "ZABLOKOWANY", (issue,))
    except (OSError, InvalidFileException, ValueError, zipfile.BadZipFile):
        issue = Issue("BLAD_SZABLONU", f"Nie można obsłużyć szablonu: {target_path.name}.")
        return WorkerResult(worker_name, target_path, 0, "POMINIĘTO", (issue,))

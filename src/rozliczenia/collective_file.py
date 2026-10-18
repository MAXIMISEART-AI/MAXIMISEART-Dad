"""Plik zbiorczy: układ wspólny dla obu procesów i nazwa ``Rozliczenie {okres} - zbiorcze.xlsx``.

Przygotowanie pliku zbiorczego zapisuje Plik zbiorczy w tym układzie, a Przebieg
rozliczeń go czyta i kopiuje Wiersze danych po pozycji kolumn do Szablonów
pracowników. Dlatego ten sam układ mają Wzorzec pliku zbiorczego, Wzorzec rozliczenia pracownika i
Szablony pracowników. Moduł nie zna mapowania Wykonawców. ``CollectiveFileError``
ma bezpieczny komunikat, a każdy proces tłumaczy go na swój błąd.
"""

from __future__ import annotations

import re
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from decimal import Decimal
from pathlib import Path

from openpyxl import load_workbook
from openpyxl.cell.rich_text import CellRichText
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.formula import ArrayFormula, DataTableFormula
from openpyxl.worksheet.worksheet import Worksheet

from .domain import Issue
from .settlement_period import PERIOD_TOKEN_PATTERN
from .workbook_files import UNREADABLE_WORKBOOK_ERRORS

HEADER_ROW = 17
FIRST_DATA_ROW = 18
WORKER_COLUMN = 8  # H
INPUT_COLUMNS = range(1, 12)  # A:K: nagłówki w wierszu 17 i dane wejściowe Wiersza danych
QUANTITY_COLUMNS = range(14, 43)  # N:AP
COPIED_COLUMNS = range(1, 47)  # A:AT: kopiowane z Pliku zbiorczego do Szablonu pracownika

_ExcelCellValue = (
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
ExcelRow = tuple[_ExcelCellValue, ...]

_NAME_PREFIX = "Rozliczenie "
_NAME_SUFFIX = " - zbiorcze.xlsx"
_NAME_PATTERN = re.compile(
    rf"{re.escape(_NAME_PREFIX)}(?P<period>{PERIOD_TOKEN_PATTERN}){re.escape(_NAME_SUFFIX)}"
)
NAME_GLOB = f"{_NAME_PREFIX}*{_NAME_SUFFIX}"  # Plik zbiorczy dowolnego okresu, np. w oknie wyboru pliku


class CollectiveFileError(Exception):
    """Plik zbiorczy albo skoroszyt w jego układzie nie nadaje się do użycia; komunikat jest bezpieczny."""


class LayoutError(CollectiveFileError):
    """Arkusz nie ma nagłówka WYKONAWCA w H17.

    ``worker_column`` to litera kolumny A:K, w której wiersz 17 ma WYKONAWCA,
    albo ``None``, gdy w A17:K17 go nie ma.
    """

    def __init__(self, worker_column: str | None) -> None:
        super().__init__(
            f"W wierszu {HEADER_ROW} nie znaleziono nagłówka WYKONAWCA "
            f"w kolumnie {get_column_letter(WORKER_COLUMN)}."
        )
        self.worker_column = worker_column


@dataclass(frozen=True)
class DataRow:
    """Wiersz danych Pliku zbiorczego z surową wartością WYKONAWCA i wartościami A:AT."""

    worker: _ExcelCellValue
    values: ExcelRow


def _filename(period: str) -> str:
    return f"{_NAME_PREFIX}{period}{_NAME_SUFFIX}"


def path_for_period(period_directory: Path, period: str) -> Path:
    """Plik zbiorczy okresu w Folderze okresu."""

    return period_directory / _filename(period)


def period_from_path(path: Path) -> str:
    """Token okresu z nazwy Pliku zbiorczego leżącego w Folderze okresu o tej samej nazwie."""

    if "Rozliczenie wew." in path.name:
        raise CollectiveFileError("Plik Rozliczenie wew. jest poza zakresem tego procesu.")
    match = _NAME_PATTERN.fullmatch(path.name)
    if match is None:
        raise CollectiveFileError(f"Wybierz plik nazwany dokładnie: {_filename('{dd}_{dd}_{mm}_{rrrr}')}.")
    period = match.group("period")
    if path.parent.name != period:
        raise CollectiveFileError(f"Folder pliku musi nazywać się tak samo jak okres: {period}.")
    return period


def _is_worker_header(value: object) -> bool:
    return str(value or "").casefold().split() == ["wykonawca"]


def check_worker_header(sheet: Worksheet) -> None:
    """Arkusz ma nagłówek WYKONAWCA w H17, bez względu na wielkość liter i spacje.

    Inaczej ``LayoutError`` podaje kolumnę A:K z WYKONAWCA albo jej brak.
    """

    if not _is_worker_header(sheet.cell(row=HEADER_ROW, column=WORKER_COLUMN).value):
        _check_header_values(_header_values(sheet))


def _header_values(sheet: Worksheet) -> Sequence[object]:
    return next(
        sheet.iter_rows(min_row=HEADER_ROW, max_row=HEADER_ROW, max_col=INPUT_COLUMNS[-1], values_only=True), ()
    )


def _check_header_values(header: Sequence[object]) -> None:
    columns = [column for column, value in enumerate(header[: INPUT_COLUMNS[-1]], start=1) if _is_worker_header(value)]
    if WORKER_COLUMN not in columns:
        raise LayoutError(get_column_letter(columns[0]) if columns else None)


def read_data_rows(path: Path) -> tuple[list[DataRow], list[Issue]]:
    """Wiersze danych w kolejności z pliku oraz problemy dla Wierszy danych bez Wykonawcy.

    Wiersz bez wartości w A:K nie jest Wierszem danych i jest pomijany. Plik jest tylko czytany.
    """

    last_copied_column = COPIED_COLUMNS[-1]
    with _stop_if_unreadable(path):
        workbook = load_workbook(path, read_only=True, data_only=False)
    try:
        sheet = workbook.active
        if sheet is None:
            raise CollectiveFileError("Skoroszyt źródłowy nie zawiera arkusza.")
        # Tylko do odczytu arkusz jest parsowany leniwie, więc uszkodzony XML wychodzi dopiero przy czytaniu.
        with _stop_if_unreadable(path):
            header = _header_values(sheet)
        _check_header_values(header)
        with _stop_if_unreadable(path):
            sheet_rows = list(
                sheet.iter_rows(
                    min_row=FIRST_DATA_ROW, max_col=max(last_copied_column, sheet.max_column), values_only=True
                )
            )
    finally:
        workbook.close()

    rows: list[DataRow] = []
    issues: list[Issue] = []
    for number, values in enumerate(sheet_rows, start=FIRST_DATA_ROW):
        if all(value is None for value in values[: INPUT_COLUMNS[-1]]):
            continue
        worker = values[WORKER_COLUMN - 1] if len(values) >= WORKER_COLUMN else None
        if not str(worker or "").split():
            issues.append(Issue("BRAK_WYKONAWCY", f"Wiersz {number} ma dane, ale nie ma wykonawcy w kolumnie H."))
            continue
        rows.append(DataRow(worker, tuple(values[:last_copied_column])))
    return rows, issues


@contextmanager
def _stop_if_unreadable(path: Path) -> Iterator[None]:
    """Błąd uszkodzonego skoroszytu staje się bezpiecznym ``CollectiveFileError``; inne błędy przechodzą."""

    try:
        yield
    except UNREADABLE_WORKBOOK_ERRORS as exc:
        raise CollectiveFileError(
            f"Nie można odczytać Pliku zbiorczego {path.name}. "
            "Sprawdź, czy plik otwiera się w Excelu i nie jest uszkodzony."
        ) from exc

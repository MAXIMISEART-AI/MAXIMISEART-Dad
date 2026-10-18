"""Rejestr zleceń w Przygotowaniu pliku zbiorczego: dostępność i odczyt (etap Odczyt danych).

Rejestr jest tylko czytany. Arkusze ze zleceniami są rozpoznawane po komplecie
wymaganych nagłówków w pierwszym wierszu, a wartości i wyróżnienia komórek są
zwracane w kolejności ``COLUMNS``. Moduł wewnętrzny Przygotowania pliku
zbiorczego; operacją publiczną pozostaje
``collective_preparation.prepare_collective_file()``.
"""

from __future__ import annotations

import zipfile
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from openpyxl import load_workbook
from openpyxl.styles.colors import Color
from openpyxl.styles.fills import Fill
from openpyxl.utils.exceptions import InvalidFileException

from . import preparation_messages as messages
from . import workbook_files
from .engine import normalize_text


@dataclass(frozen=True)
class Column:
    """Kolumna przenoszona z Rejestru zleceń; nagłówek docelowy jest szukany we wzorcach.

    Trzy pary różniące się zapisem są jawne; nagłówek Rejestru nigdy nie zastępuje
    nagłówka docelowego.
    """

    register_header: str
    target_header: str


DATE = Column("DATA GODZ. POCZ.", "DATA")
WORKER = Column("WYKONAWCA", "WYKONAWCA")
SUCCESSFUL = Column("SKUTECZNE", "SKUTECZNE")
COLUMNS: tuple[Column, ...] = (
    DATE,
    Column("MIASTO", "MIASTO"),
    Column("adres", "ADRES"),
    Column("UMOWA", "UMOWA"),
    Column("URZĄDZENIA", "URZĄDZENIA"),
    Column("CZYNNOŚCI", "CZYNNOŚCI"),
    Column("nr zlecenia", "NUMER ZL."),
    WORKER,
    Column("NUMER UMOWY/ZLECENIA ORANGE", "NUMER UMOWY/ZLECENIA ORANGE"),
    SUCCESSFUL,
    Column("CZYNNOŚCI ZREALIZOWANE", "CZYNNOŚCI ZREALIZOWANE"),
)

# Błędy openpyxl przy pliku, który nie jest poprawnym skoroszytem .xlsx.
UNREADABLE_WORKBOOK_ERRORS = (OSError, InvalidFileException, zipfile.BadZipFile, KeyError, ValueError)


@dataclass(frozen=True)
class CellFormat:
    """Wyróżnienia komórki Rejestru przenoszone do plików okresu.

    Krój i rozmiar czcionki celowo nie są tu przechowywane: pochodzą z wzorca.
    """

    fill: Fill | None
    color: Color | None
    bold: bool
    italic: bool
    number_format: str


PLAIN_CELL = CellFormat(fill=None, color=None, bold=False, italic=False, number_format="General")


@dataclass(frozen=True)
class RegisterCell:
    value: object
    format: CellFormat


@dataclass(frozen=True)
class RegisterRow:
    """Wiersz Rejestru z danymi; ``cells`` w kolejności ``COLUMNS``."""

    row_number: int
    cells: tuple[RegisterCell, ...]

    def value(self, column: Column) -> object:
        return self.cells[COLUMNS.index(column)].value


@dataclass(frozen=True)
class RegisterSheet:
    """Arkusz ze zleceniami: wiersze z danymi i numery całkowicie pustych wierszy."""

    name: str
    rows: tuple[RegisterRow, ...]
    empty_rows: tuple[int, ...]


def is_blank(value: object) -> bool:
    return value is None or (isinstance(value, str) and not value.strip())


def header_columns(values: Sequence[object]) -> dict[str, int]:
    """Mapuje znormalizowane nagłówki na numery kolumn (od 1)."""

    return {
        normalize_text(value): column
        for column, value in enumerate(values, start=1)
        if not is_blank(value)
    }


def ensure_register_available(register_path: Path) -> None:
    """Rejestr istnieje i nie jest otwarty w Excelu."""

    workbook_files.ensure_available(
        register_path,
        missing=messages.register_missing,
        open_in_excel=messages.register_open_in_excel,
    )


def read_register(register_path: Path) -> list[RegisterSheet]:
    """Arkusze ze zleceniami; zatrzymanie, gdy Rejestru nie da się odczytać albo nie ma nagłówków."""

    try:
        return _read_register_sheets(register_path)
    except UNREADABLE_WORKBOOK_ERRORS as exc:
        raise messages.register_unreadable(register_path) from exc


def _cell_format(cell: object) -> CellFormat:
    """Wyróżnienia komórki Rejestru; brakująca komórka nie ma żadnych."""

    font = getattr(cell, "font", None)
    fill = getattr(cell, "fill", None)
    number_format = getattr(cell, "number_format", None)
    return CellFormat(
        fill=fill,
        color=font.color if font is not None else None,
        bold=bool(font.b) if font is not None else False,
        italic=bool(font.i) if font is not None else False,
        number_format=number_format or PLAIN_CELL.number_format,
    )


def _missing_headers(header: Sequence[object]) -> list[str]:
    present = set(header_columns(header))
    return [column.register_header for column in COLUMNS if normalize_text(column.register_header) not in present]


def _duplicated_headers(header: Sequence[object]) -> list[str]:
    normalized = [normalize_text(value) for value in header if not is_blank(value)]
    return [
        column.register_header
        for column in COLUMNS
        if normalized.count(normalize_text(column.register_header)) > 1
    ]


def _read_register_sheets(register_path: Path) -> list[RegisterSheet]:
    """Czyta arkusze Rejestru rozpoznane po komplecie wymaganych nagłówków w pierwszym wierszu.

    Arkusze bez większości wymaganych nagłówków (listy, komentarze, ukryte) są pomijane.
    Arkusz z większością, ale nie kompletem nagłówków, wskazuje brakujący nagłówek.
    """

    workbook = load_workbook(register_path, read_only=True, data_only=False)
    sheets: list[RegisterSheet] = []
    closest: tuple[str, list[str]] | None = None  # arkusz z najmniejszą liczbą braków
    try:
        for sheet in workbook.worksheets:
            header = next(sheet.iter_rows(min_row=1, max_row=1, values_only=True), ())
            missing = _missing_headers(header)
            if missing:
                if len(missing) < len(COLUMNS) / 2 and (closest is None or len(missing) < len(closest[1])):
                    closest = (sheet.title, missing)
                continue
            duplicated = _duplicated_headers(header)
            if duplicated:
                raise messages.register_with_duplicated_headers(register_path, sheet.title, duplicated)
            columns = header_columns(header)
            positions = [columns[normalize_text(column.register_header)] for column in COLUMNS]
            rows: list[RegisterRow] = []
            empty_rows: list[int] = []
            for row_number, cells in enumerate(sheet.iter_rows(min_row=2), start=2):
                if all(is_blank(getattr(cell, "value", None)) for cell in cells):
                    empty_rows.append(row_number)
                    continue
                rows.append(
                    RegisterRow(
                        row_number,
                        tuple(
                            RegisterCell(getattr(cells[position - 1], "value", None), _cell_format(cells[position - 1]))
                            if position <= len(cells)
                            else RegisterCell(None, PLAIN_CELL)
                            for position in positions
                        ),
                    )
                )
            sheets.append(RegisterSheet(sheet.title, tuple(rows), tuple(empty_rows)))
    finally:
        workbook.close()
    if sheets:
        return sheets
    if closest is not None:
        raise messages.register_without_headers(register_path, *closest)
    raise messages.register_without_data_sheet(register_path, [column.register_header for column in COLUMNS])

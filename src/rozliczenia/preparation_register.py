"""Rejestr zleceń w Przygotowaniu pliku zbiorczego: dostępność i odczyt (etap Odczyt danych).

Rejestr jest tylko czytany, przez moduł skoroszytu. Arkusze ze zleceniami są rozpoznawane po komplecie
wymaganych nagłówków w pierwszym wierszu, a wartości i wyróżnienia komórek są
zwracane w kolejności ``COLUMNS``. Moduł wewnętrzny Przygotowania pliku
zbiorczego; operacją publiczną pozostaje
``collective_preparation.prepare_collective_file()``.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from openpyxl.styles.colors import Color
from openpyxl.styles.fills import Fill

from . import preparation_messages as messages
from . import workbook_files
from .engine import normalize_text
from .message import StopError
from .workbook_files import FormattedCell, Problem, ReadWorkbook, WorkbookError


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

    try:
        workbook_files.ensure_available(register_path)
    except WorkbookError as error:
        raise _register_stop(register_path, error) from error


def read_register(register_path: Path) -> list[RegisterSheet]:
    """Arkusze ze zleceniami; zatrzymanie, gdy Rejestru nie da się odczytać albo nie ma nagłówków."""

    try:
        with workbook_files.read_workbook(register_path) as workbook:
            return _read_register_sheets(register_path, workbook)
    except WorkbookError as error:
        raise _register_stop(register_path, error) from error


def _register_stop(register_path: Path, error: WorkbookError) -> StopError:
    if error.problem is Problem.MISSING:
        return StopError(messages.register_missing(register_path))
    if error.problem is Problem.OPEN_IN_EXCEL:
        return StopError(messages.register_open_in_excel(register_path))
    return StopError(messages.register_unreadable(register_path))


def _cell_format(cell: FormattedCell) -> CellFormat:
    """Wyróżnienia komórki Rejestru; brakująca komórka nie ma żadnych."""

    font = cell.font
    return CellFormat(
        fill=cell.fill,
        color=font.color if font is not None else None,
        bold=bool(font.b) if font is not None else False,
        italic=bool(font.i) if font is not None else False,
        number_format=cell.number_format or PLAIN_CELL.number_format,
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


def _read_register_sheets(register_path: Path, workbook: ReadWorkbook) -> list[RegisterSheet]:
    """Czyta arkusze Rejestru rozpoznane po komplecie wymaganych nagłówków w pierwszym wierszu.

    Arkusze bez większości wymaganych nagłówków (listy, komentarze, ukryte) są pomijane.
    Arkusz z większością, ale nie kompletem nagłówków, wskazuje brakujący nagłówek.
    """

    sheets: list[RegisterSheet] = []
    closest: tuple[str, list[str]] | None = None  # arkusz z najmniejszą liczbą braków
    for sheet in workbook.sheets():
        header = next(sheet.values(min_row=1, max_row=1), ())
        missing = _missing_headers(header)
        if missing:
            if len(missing) < len(COLUMNS) / 2 and (closest is None or len(missing) < len(closest[1])):
                closest = (sheet.title, missing)
            continue
        duplicated = _duplicated_headers(header)
        if duplicated:
            raise StopError(messages.register_with_duplicated_headers(register_path, sheet.title, duplicated))
        columns = header_columns(header)
        positions = [columns[normalize_text(column.register_header)] for column in COLUMNS]
        rows: list[RegisterRow] = []
        empty_rows: list[int] = []
        for row_number, (values, cells) in enumerate(sheet.formatted_rows(min_row=2, columns=positions), start=2):
            if all(is_blank(value) for value in values):
                empty_rows.append(row_number)
                continue
            rows.append(RegisterRow(row_number, tuple(RegisterCell(cell.value, _cell_format(cell)) for cell in cells)))
        sheets.append(RegisterSheet(sheet.title, tuple(rows), tuple(empty_rows)))
    if sheets:
        return sheets
    if closest is not None:
        raise StopError(messages.register_without_headers(register_path, *closest))
    raise StopError(messages.register_without_data_sheet(register_path, [column.register_header for column in COLUMNS]))

"""Rejestr zleceń w Przygotowaniu pliku zbiorczego: dostępność i odczyt (etap Odczyt danych).

Rejestr jest tylko czytany, przez moduł skoroszytu. Arkusze ze zleceniami są rozpoznawane po komplecie
wymaganych nagłówków w pierwszym wierszu, a wartości, wyróżnienia i Hiperłącza
komórek są zwracane w kolejności ``COLUMNS``. Dla okresu czytane są tylko wiersze
od pierwszego do ostatniego, którego data może leżeć w okresie. Moduł wewnętrzny Przygotowania pliku
zbiorczego; operacją publiczną pozostaje
``collective_preparation.prepare_collective_file()``.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from openpyxl.styles.colors import Color
from openpyxl.styles.fills import Fill
from openpyxl.utils import get_column_letter

from . import preparation_messages as messages
from . import workbook_files
from .hyperlinks import Hyperlink
from .message import StopError
from .settlement_period import SettlementPeriod
from .workbook_files import FormattedCell, Problem, ReadWorkbook, WorkbookError
from .worker_config import normalize_text


@dataclass(frozen=True)
class Column:
    """Kolumna przenoszona z Rejestru zleceń; nagłówek docelowy jest szukany we wzorcach.

    Pary różniące się zapisem są jawne; nagłówek Rejestru nigdy nie zastępuje
    nagłówka docelowego. ``register_header`` to zapis z nowego Rejestru taty;
    kolumna może mieć w Rejestrze drugi przyjmowany zapis ze starszej kopii.
    Nagłówki są porównywane bez względu na wielkość liter, więc zapis różniący
    się tylko nią (``adres``) nie jest osobną alternatywą.
    """

    register_header: str
    target_header: str
    alternative_register_headers: tuple[str, ...] = ()

    @property
    def register_headers(self) -> tuple[str, ...]:
        return (self.register_header, *self.alternative_register_headers)

    @property
    def label(self) -> str:
        """Nagłówek w komunikacie: wszystkie przyjmowane zapisy."""

        return " albo ".join(self.register_headers)


DATE = Column("DATA GODZ. POCZ.", "DATA")
ADDRESS = Column("ADRES", "ADRES")
WORKER = Column("WYKONAWCA", "WYKONAWCA")
SUCCESSFUL = Column("SKUTECZNE", "SKUTECZNE")
COLUMNS: tuple[Column, ...] = (
    DATE,
    Column("MIASTO", "MIASTO"),
    ADDRESS,
    Column("UMOWA", "UMOWA"),
    Column("URZĄDZENIA", "URZĄDZENIA"),
    Column("CZYNNOŚCI", "CZYNNOŚCI"),
    Column("NUMER ZL.", "NUMER ZL.", ("nr zlecenia",)),
    WORKER,
    Column("NUMER UMOWY", "NUMER UMOWY/ZLECENIA ORANGE", ("NUMER UMOWY/ZLECENIA ORANGE",)),
    SUCCESSFUL,
    Column("CZYNNOŚCI ZREALIZOWANE", "CZYNNOŚCI ZREALIZOWANE"),
)


@dataclass(frozen=True)
class CellFormat:
    """Wyróżnienia i format liczby komórki Rejestru przenoszone do plików okresu.

    Krój i rozmiar czcionki celowo nie są tu przechowywane: pochodzą z nagłówka Wzorca (Wygląd Wiersza danych).
    """

    fill: Fill | None
    color: Color | None
    bold: bool
    italic: bool
    number_format: str


@dataclass(frozen=True)
class RegisterCell:
    """Wartość komórki Rejestru z jej Wyróżnieniami i Hiperłączem."""

    value: object
    format: CellFormat
    hyperlink: Hyperlink | None


@dataclass(frozen=True)
class RegisterRow:
    """Wiersz Rejestru z danymi; ``cells`` w kolejności ``COLUMNS``."""

    row_number: int
    cells: tuple[RegisterCell, ...]

    def value(self, column: Column) -> object:
        return self.cells[COLUMNS.index(column)].value


@dataclass(frozen=True)
class RegisterSheet:
    """Arkusz ze zleceniami: wiersze z danymi i numery całkowicie pustych wierszy z odczytanego zakresu."""

    name: str
    rows: tuple[RegisterRow, ...]
    empty_rows: tuple[int, ...]
    _positions: tuple[int, ...]  # numery kolumn ``COLUMNS`` w arkuszu (od 1)

    def column_letter(self, column: Column) -> str:
        """Litera kolumny arkusza z nagłówkiem ``column``, np. ``L`` dla ``SKUTECZNE``."""

        return get_column_letter(self._positions[COLUMNS.index(column)])


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


def read_register(register_path: Path, period: SettlementPeriod | None = None) -> list[RegisterSheet]:
    """Arkusze ze zleceniami; zatrzymanie, gdy Rejestru nie da się odczytać albo nie ma nagłówków.

    Z ``period`` arkusz ma tylko wiersze od pierwszego do ostatniego, którego data
    może leżeć w okresie: Planowanie szuka zleceń okresu i wierszy bez daty tylko
    między pierwszym a ostatnim zleceniem okresu. Bez ``period`` ma wszystkie wiersze.
    """

    try:
        with workbook_files.read_workbook(register_path) as workbook:
            positions = _order_sheet_positions(register_path, workbook)
            if period is None:
                return _read_register_sheets(workbook, positions)
            date_columns = {title: columns[COLUMNS.index(DATE)] for title, columns in positions.items()}
            with workbook.narrowed(date_columns, period.start, period.end) as narrowed:
                return _read_register_sheets(narrowed, positions)
    except WorkbookError as error:
        raise _register_stop(register_path, error) from error


def _register_stop(register_path: Path, error: WorkbookError) -> StopError:
    if error.problem is Problem.MISSING:
        return StopError(messages.register_missing(register_path))
    if error.problem is Problem.OPEN_IN_EXCEL:
        return StopError(messages.register_open_in_excel(register_path))
    if error.problem is Problem.INACCESSIBLE:
        return StopError(messages.register_inaccessible(register_path))
    return StopError(messages.register_unreadable(register_path))


def _cell_format(cell: FormattedCell) -> CellFormat:
    """Wyróżnienia komórki Rejestru; brakująca komórka nie ma żadnych."""

    font = cell.font
    return CellFormat(
        fill=cell.fill,
        color=font.color if font is not None else None,
        bold=bool(font.b) if font is not None else False,
        italic=bool(font.i) if font is not None else False,
        number_format=cell.number_format or "General",
    )


def _register_position(column: Column, columns: dict[str, int]) -> int | None:
    return next(
        (columns[name] for name in map(normalize_text, column.register_headers) if name in columns),
        None,
    )


def _missing_headers(header: Sequence[object]) -> list[str]:
    columns = header_columns(header)
    return [column.label for column in COLUMNS if _register_position(column, columns) is None]


def _duplicated_headers(header: Sequence[object]) -> list[str]:
    """Kolumny, których nagłówek, w dowolnym przyjmowanym zapisie, występuje więcej niż raz."""

    normalized = [normalize_text(value) for value in header if not is_blank(value)]
    return [
        column.label
        for column in COLUMNS
        if sum(normalized.count(name) for name in set(map(normalize_text, column.register_headers))) > 1
    ]


def _order_sheet_positions(register_path: Path, workbook: ReadWorkbook) -> dict[str, list[int]]:
    """Arkusze Rejestru rozpoznane po komplecie wymaganych nagłówków w pierwszym wierszu: tytuł → numery kolumn ``COLUMNS``.

    Arkusze bez większości wymaganych nagłówków (listy, komentarze, ukryte) są pomijane.
    Arkusz z większością, ale nie kompletem nagłówków, wskazuje brakujący nagłówek.
    """

    sheets: dict[str, list[int]] = {}
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
        sheets[sheet.title] = [
            position for column in COLUMNS if (position := _register_position(column, columns)) is not None
        ]
    if sheets:
        return sheets
    if closest is not None:
        raise StopError(messages.register_without_headers(register_path, *closest))
    raise StopError(messages.register_without_data_sheet(register_path, [column.label for column in COLUMNS]))


def _read_register_sheets(workbook: ReadWorkbook, positions: dict[str, list[int]]) -> list[RegisterSheet]:
    """Wiersze z danymi i puste wiersze arkuszy ``positions`` w kolejności skoroszytu."""

    sheets: list[RegisterSheet] = []
    for sheet in workbook.sheets():
        if sheet.title not in positions:
            continue
        columns = positions[sheet.title]
        rows: list[RegisterRow] = []
        empty_rows: list[int] = []
        for row_number, values, cells in sheet.formatted_rows(min_row=2, columns=columns):
            if all(is_blank(value) for value in values):
                empty_rows.append(row_number)
                continue
            rows.append(
                RegisterRow(
                    row_number, tuple(RegisterCell(cell.value, _cell_format(cell), cell.hyperlink) for cell in cells)
                )
            )
        sheets.append(RegisterSheet(sheet.title, tuple(rows), tuple(empty_rows), tuple(columns)))
    return sheets

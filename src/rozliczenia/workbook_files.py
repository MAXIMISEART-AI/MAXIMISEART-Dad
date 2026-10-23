"""Skoroszyty na dysku: otwarcie z jedną klasyfikacją uszkodzeń, układ arkusza i plik z Wzorca.

Każde otwarcie skoroszytu w obu procesach przechodzi przez ten moduł: Plik
zbiorczy (``read_data_rows``) i Rejestr zleceń (``read_workbook``) dają Wiersze
danych z Wyróżnieniami, formatami liczb i Hiperłączami komórek (``DataRow``), a
Wzorzec każdego z trzech plików (``Layout``: Rozliczenie pracownika, Plik zbiorczy,
Rozliczenie wewnętrzne) jest sprawdzany, planowany i wypełniany Wierszami danych
przez ``TemplateFile``. Otwarcie sprawdza dostępność i klasyfikuje każde
uszkodzenie, a problem zgłasza jako ``WorkbookError`` z powodem, przy złym układzie
z jego miejscem. Moduł nie zna Komunikatów: proces tłumaczy powód na Komunikat ze
swojego katalogu.

Moduł jest właścicielem układu arkusza Pliku zbiorczego, wspólnego dla Wzorca
pliku zbiorczego, Wzorca rozliczenia pracownika i Szablonów pracowników:
nagłówek w wierszu 17 z WYKONAWCA w H, Wiersze danych od 18, dane wejściowe
A:K, kolumny wyglądu A:L (``row_look``), ilości N:AP i kolumny Wiersza danych A:AT. Publiczne są etykieta komórki
nagłówka ``WORKER_HEADER`` do treści Komunikatów oraz wiersze i kolumny układu
(``HEADER_ROW``, ``FIRST_DATA_ROW``, ``QUANTITY_COLUMNS``, ``DATA_ROW_COLUMNS``) dla
narzędzi benchmarku w ``tools/``, żeby nie powtarzały układu.
"""

from __future__ import annotations

import os
import re
import tempfile
import zipfile
import zlib
from collections.abc import Callable, Iterator, Mapping, Sequence
from contextlib import contextmanager
from copy import copy
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from decimal import Decimal
from enum import Enum
from io import BytesIO
from pathlib import Path
from typing import IO, TypeVar, cast
from xml.etree.ElementTree import ParseError
from xml.parsers import expat
from xml.parsers.expat import ExpatError

from openpyxl import load_workbook
from openpyxl.cell.cell import Cell, MergedCell
from openpyxl.cell.rich_text import CellRichText
from openpyxl.styles.fills import Fill
from openpyxl.styles.fonts import Font
from openpyxl.utils import get_column_letter
from openpyxl.utils.exceptions import IllegalCharacterError, InvalidFileException
from openpyxl.workbook.workbook import Workbook
from openpyxl.worksheet.cell_range import CellRange, MultiCellRange
from openpyxl.worksheet._read_only import ReadOnlyWorksheet
from openpyxl.worksheet.filters import AutoFilter
from openpyxl.worksheet.formula import ArrayFormula, DataTableFormula
from openpyxl.worksheet.worksheet import Worksheet

from .dated_rows import rows_dated_between
from .highlights import PLAIN, Highlights
from .hyperlinks import Hyperlink, read_sheet_hyperlinks, sheet_part
from .input_rows import rows_with_input
from .row_look import GENERAL, RowLook, wraps
from .template_copy import InvalidValue, Package, SheetLayout, TemplateCopy, UnsupportedShape
from .worker_config import normalize_text


_EXTERNAL_LINKS_PREFIX = "xl/externalLinks/"
# Rozszerzenia skoroszytów, które otwiera openpyxl; inny plik jest nieczytelny jak przy otwieraniu przez openpyxl.
_WORKBOOK_SUFFIXES = (".xlsx", ".xlsm", ".xltx", ".xltm")
_ExternalLinkParts = dict[str, tuple[zipfile.ZipInfo, bytes]]
_WORKBOOK_FILE_ERRORS = (OSError, InvalidFileException, ValueError, zipfile.BadZipFile)

# Błędy openpyxl przy pliku, który nie jest poprawnym skoroszytem .xlsx: przy otwieraniu, a w trybie
# tylko do odczytu także przy czytaniu wierszy, bo arkusz jest wtedy parsowany leniwie. ``IndexError``:
# komórka ze stylem w skoroszycie bez ``xl/styles.xml``. ``ExpatError``: zepsuty XML arkusza przy odczycie
# Wierszy danych (``input_rows``).
_UNREADABLE_WORKBOOK_ERRORS = (
    OSError,
    InvalidFileException,
    zipfile.BadZipFile,
    KeyError,
    IndexError,
    ValueError,
    zlib.error,
    ParseError,
    ExpatError,
)

# Układ arkusza Pliku zbiorczego i Wzorców tej rodziny. Publiczne są tylko liczby, których potrzebują narzędzia
# spoza pakietu (benchmark wpisuje ilości jak tata, generator składa syntetyczne Wzorce kształtu Wzorców taty).
HEADER_ROW = 17
FIRST_DATA_ROW = 18
_WORKER_COLUMN = 8  # H
_INPUT_COLUMNS = range(1, 12)  # A:K: nagłówki w wierszu 17 i dane wejściowe Wiersza danych
_LOOK_COLUMNS = range(1, 13)  # A:L: kolumny wyglądu Wiersza danych
_INTERNAL_LOOK_COLUMNS = range(1, 14)  # A:M Rozliczenia wewnętrznego, z ``zwrot`` i ``UWAGI``
QUANTITY_COLUMNS = range(14, 43)  # N:AP
DATA_ROW_COLUMNS = range(1, 47)  # A:AT: kopiowane z Pliku zbiorczego do Szablonu pracownika


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


class Problem(Enum):
    """Powód, dla którego skoroszytu nie da się użyć."""

    MISSING = "brak pliku"
    OPEN_IN_EXCEL = "otwarty w Excelu"
    INACCESSIBLE = "niedostępny"
    """Plik jest cały, ale system nie oddał jego bajtów, np. zajęty przez inny program albo OneDrive bez sieci."""
    UNREADABLE = "nieczytelny"
    LAYOUT = "zły układ"
    HAS_DATA = "zawiera dane"
    """Wzorzec rozliczenia pracownika ma już wartości w Wierszach danych."""


@dataclass(frozen=True)
class MissingHeader:
    """Nagłówek ``header`` nie stoi na swoim miejscu w wierszu ``row`` arkusza ``sheet``.

    ``found_in``: litera kolumny A:K, w której stoi WYKONAWCA zamiast w H; ``None``: nagłówka w wierszu nie ma.
    """

    sheet: str
    row: int
    header: str
    found_in: str | None = None


@dataclass(frozen=True)
class MergedCells:
    """Komórki ``cells`` arkusza ``sheet``, do których trafiłyby Wiersze danych, są scalone."""

    sheet: str
    cells: str


LayoutFault = MissingHeader | MergedCells


class WorkbookError(Exception):
    """Skoroszytu nie da się użyć; ``problem`` mówi dlaczego, a przy złym układzie (i tylko wtedy) ``fault`` mówi gdzie."""

    def __init__(self, path: Path, problem: Problem, fault: LayoutFault | None = None) -> None:
        super().__init__(f"{problem.value}: {path.name}")
        self.path = path
        self.problem = problem
        self.fault = fault


class WorkbookSaveError(Exception):
    """Skoroszyt nie został zapisany; plik docelowy pozostał bez zmian."""


class ExternalLinksError(WorkbookSaveError):
    """Nie można przygotować ani przywrócić części ``xl/externalLinks/*``."""


@dataclass(frozen=True)
class HeaderCell:
    """Etykieta komórki nagłówka do treści Komunikatów: ``str()`` daje np. ``H17``."""

    column: str
    row: int

    def __str__(self) -> str:
        return f"{self.column}{self.row}"


WORKER_HEADER = HeaderCell(get_column_letter(_WORKER_COLUMN), HEADER_ROW)
_WORKER_LABEL = "WYKONAWCA"


@dataclass(frozen=True)
class _Rules:
    header_row: int
    first_data_row: int
    last_header_column: int | None
    """Ostatnia kolumna nagłówka; ``None``: cały wiersz nagłówka."""
    worker_header: bool
    copy: SheetLayout | None
    recalculate: bool
    look_columns: int
    """Kolumny wyglądu Wiersza danych od A (``row_look``)."""
    period_file: bool
    """Plik okresu z Przygotowania: Sprawdzanie z zarysu Wzorca, wygląd w każdej zapisanej kolumnie i autofiltr
    zawsze idą razem. Inaczej Szablon pracownika: Wzorzec bez danych, sprawdzany też przed każdym plikiem."""


class Layout(Enum):
    """Plik, który powstaje z Wzorca, i wszystko, czym jego zapis różni się od pozostałych."""

    WORKER_SETTLEMENT = _Rules(
        header_row=HEADER_ROW,
        first_data_row=FIRST_DATA_ROW,
        last_header_column=_INPUT_COLUMNS[-1],
        worker_header=True,
        copy=SheetLayout(
            header_row=HEADER_ROW,
            first_data_row=FIRST_DATA_ROW,
            input_columns=_INPUT_COLUMNS[-1],
            data_columns=DATA_ROW_COLUMNS[-1],
            look_columns=_LOOK_COLUMNS[-1],
        ),
        recalculate=True,
        look_columns=_LOOK_COLUMNS[-1],
        period_file=False,
    )
    COLLECTIVE_FILE = _Rules(
        header_row=HEADER_ROW,
        first_data_row=FIRST_DATA_ROW,
        last_header_column=_INPUT_COLUMNS[-1],
        worker_header=True,
        copy=SheetLayout(
            header_row=HEADER_ROW,
            first_data_row=FIRST_DATA_ROW,
            input_columns=_INPUT_COLUMNS[-1],
            data_columns=_INPUT_COLUMNS[-1],
            look_columns=_LOOK_COLUMNS[-1],
            collective_file=True,
        ),
        recalculate=True,
        look_columns=_LOOK_COLUMNS[-1],
        period_file=True,
    )
    INTERNAL_SETTLEMENT = _Rules(
        header_row=1,
        first_data_row=2,
        last_header_column=None,
        worker_header=False,
        copy=None,
        recalculate=False,
        look_columns=_INTERNAL_LOOK_COLUMNS[-1],
        period_file=True,
    )


@dataclass(frozen=True)
class DataRow:
    """Wiersz danych: wartości komórek po kolei, ich Wyróżnienia, formaty liczb i Hiperłącza.

    Daje go odczyt Pliku zbiorczego (pozycje to kolumny A:AT, formaty liczb kolumn wyglądu A:L) i odczyt
    Rejestru zleceń (pozycje w kolejności ``preparation_register.COLUMNS``, czyli kolumn A:K Pliku
    zbiorczego, z formatem liczby każdej). ``number`` to numer wiersza w pliku, z którego go odczytano.
    Klucze ``hyperlinks`` to pozycje od 1; Hiperłącze ma tylko komórka z wartością.
    """

    number: int
    values: ExcelRow
    highlights: tuple[Highlights, ...]
    """Wyróżnienia komórek po pozycji jak ``values``."""
    number_formats: tuple[str, ...]
    """Formaty liczb komórek po pozycji; trafiają do kolumn wyglądu pliku z Wzorca."""
    hyperlinks: Mapping[int, Hyperlink] = field(default_factory=dict)

    @property
    def worker(self) -> _ExcelCellValue:
        """Surowa wartość WYKONAWCA z kolumny H Pliku zbiorczego."""

        return self.values[_WORKER_COLUMN - 1]


def is_open_in_excel(path: Path) -> bool:
    """Rozpoznaje skoroszyt otwarty w desktopowym Excelu po pliku blokady ``~$…``."""

    return path.with_name(f"~${path.name}").exists()


def ensure_available(path: Path) -> None:
    """Skoroszyt jest na dysku i nie jest otwarty w Excelu; inaczej ``WorkbookError``.

    Folder, którego nie da się odczytać (np. brak dostępu), czyni skoroszyt niedostępnym, a nie uszkodzonym.
    """

    try:
        found, open_in_excel = path.is_file(), is_open_in_excel(path)
    except OSError as exc:
        raise WorkbookError(path, Problem.INACCESSIBLE) from exc
    if not found:
        raise WorkbookError(path, Problem.MISSING)
    if open_in_excel:
        raise WorkbookError(path, Problem.OPEN_IN_EXCEL)


_T = TypeVar("_T")


@contextmanager
def _unreadable_as_error(path: Path) -> Iterator[None]:
    """Uszkodzenie skoroszytu zgłoszone przez openpyxl staje się ``WorkbookError``; inne błędy przechodzą."""

    try:
        yield
    except _UNREADABLE_WORKBOOK_ERRORS as exc:
        raise WorkbookError(path, Problem.UNREADABLE) from exc


def _file_bytes(path: Path) -> bytes:
    """Bajty skoroszytu z dysku; błąd systemu plików to ``Problem.INACCESSIBLE``, nie uszkodzenie."""

    try:
        return path.read_bytes()
    except OSError as exc:
        raise WorkbookError(path, Problem.INACCESSIBLE) from exc


def _classified(path: Path, items: Iterator[_T]) -> Iterator[_T]:
    """Elementy leniwego odczytu openpyxl; klasyfikowane jest tylko pobranie elementu."""

    while True:
        with _unreadable_as_error(path):
            try:
                item = next(items)
            except StopIteration:
                return
        yield item


def _open(path: Path, source: Path | IO[bytes], *, read_only: bool) -> Workbook:
    """Skoroszyt ``path`` otwarty przez openpyxl z ``source`` (plik albo jego bajty) z klasyfikacją uszkodzeń."""

    with _unreadable_as_error(path):
        if read_only:
            workbook = load_workbook(source, read_only=True, data_only=False)
        else:
            workbook = load_workbook(source, read_only=False, data_only=False, keep_links=True)
    if not isinstance(workbook.active, (Worksheet, ReadOnlyWorksheet)):
        workbook.close()
        raise WorkbookError(path, Problem.UNREADABLE)
    return workbook


def _is_worker_header(value: object) -> bool:
    return str(value or "").casefold().split() == ["wykonawca"]


def _check_worker_header(path: Path, sheet: str, header: Sequence[object]) -> None:
    """Jedno sprawdzenie nagłówka WYKONAWCA w H17 (bez względu na wielkość liter i spacje) dla wartości A17:K17."""

    columns = [column for column, value in enumerate(header[: _INPUT_COLUMNS[-1]], start=1) if _is_worker_header(value)]
    if _WORKER_COLUMN not in columns:
        found_in = get_column_letter(columns[0]) if columns else None
        raise WorkbookError(path, Problem.LAYOUT, MissingHeader(sheet, HEADER_ROW, _WORKER_LABEL, found_in))


def is_blank(value: object) -> bool:
    return value is None or (isinstance(value, str) and not value.strip())


def header_columns(values: Sequence[object]) -> dict[str, int]:
    """Mapuje znormalizowane nagłówki na numery kolumn (od 1)."""

    return {normalize_text(value): column for column, value in enumerate(values, start=1) if not is_blank(value)}


def read_data_rows(path: Path) -> list[DataRow]:
    """Wiersze danych Pliku zbiorczego z Wyróżnieniami i Hiperłączami komórek w kolejności z pliku; plik jest tylko czytany.

    Wiersz bez wartości w A:K nie jest Wierszem danych i jest pomijany. Brak
    nagłówka WYKONAWCA w H17 to ``WorkbookError`` ze złym układem.

    openpyxl czyta tylko wiersze, które mogą mieć wartości w A:K
    (``input_rows``), a nie każdy z ~10 tys. sformatowanych wierszy Pliku
    zbiorczego; wartości i klasyfikacja uszkodzeń są takie jak przy odczycie
    całego arkusza.
    """

    ensure_available(path)
    content = _file_bytes(path)
    with _unreadable_as_error(path):
        content = rows_with_input(content, _INPUT_COLUMNS[-1])
    workbook = _open(path, BytesIO(content), read_only=True)
    try:
        sheet = cast(Worksheet, workbook.active)  # tylko do odczytu: ReadOnlyWorksheet
        header = next(
            _classified(
                path,
                sheet.iter_rows(min_row=HEADER_ROW, max_row=HEADER_ROW, max_col=_INPUT_COLUMNS[-1], values_only=True),
            ),
            (),
        )
        _check_worker_header(path, sheet.title, header)
        with _unreadable_as_error(path):
            max_column = max(DATA_ROW_COLUMNS[-1], sheet.max_column)
            with zipfile.ZipFile(BytesIO(content)) as archive:
                links = read_sheet_hyperlinks(archive, sheet.title)
        rows: list[DataRow] = []
        last_column = DATA_ROW_COLUMNS[-1]
        highlights = _HighlightsReader()
        for number, cells in enumerate(
            _classified(path, sheet.iter_rows(min_row=FIRST_DATA_ROW, max_col=max_column)), start=FIRST_DATA_ROW
        ):
            values = tuple(cell.value for cell in cells[:last_column])
            if all(value is None for value in values[: _INPUT_COLUMNS[-1]]):
                continue
            with _unreadable_as_error(path):
                row_highlights = tuple(highlights.of(cell) for cell in cells[:last_column])
                number_formats = tuple(getattr(cell, "number_format", None) or GENERAL for cell in cells[: _LOOK_COLUMNS[-1]])
            rows.append(DataRow(number, values, row_highlights, number_formats, links.row(number, values)))
    finally:
        workbook.close()
    return rows


class _HighlightsReader:
    """Wyróżnienia komórek jednego odczytu; komórki o tej samej czcionce i wypełnieniu dzielą jeden obiekt."""

    def __init__(self) -> None:
        self._known: dict[tuple[int, int], Highlights] = {}

    def of(self, cell: object) -> Highlights:
        font, fill = getattr(cell, "font", None), getattr(cell, "fill", None)
        key = (id(font), id(fill))
        found = self._known.get(key)
        if found is None:
            found = self._known[key] = Highlights.of(font, fill)
        return found


class ReadSheet:
    """Arkusz skoroszytu otwartego tylko do odczytu; każdy odczyt komórek jest klasyfikowany.

    ``rows`` to zakres wierszy danych arkusza zawężonego przez ``ReadWorkbook.narrowed``; ``None``: wszystkie wiersze.
    """

    def __init__(self, path: Path, content: bytes, sheet: Worksheet, rows: range | None = None) -> None:
        self._path = path
        self._content = content
        self._sheet = sheet
        self._rows = rows

    @property
    def title(self) -> str:
        return self._sheet.title

    def values(self, min_row: int, max_row: int | None = None) -> Iterator[tuple[object, ...]]:
        return _classified(self._path, self._sheet.iter_rows(min_row=min_row, max_row=max_row, values_only=True))

    def data_rows(self, min_row: int, columns: Sequence[int]) -> Iterator[tuple[tuple[object, ...], DataRow]]:
        """Wartości całego wiersza i Wiersz danych z komórek ``columns`` (od 1) po kolei, od ``min_row`` w dół.

        Wyróżnienia czyta ta sama reguła co w Pliku zbiorczym (``Highlights.of``), a format liczby każdej
        komórki to jej format, ogólny dla brakującej. W arkuszu zawężonym tylko wiersze z jego zakresu.
        """

        return _classified(self._path, self._data_rows(min_row, columns))

    def _data_rows(self, min_row: int, columns: Sequence[int]) -> Iterator[tuple[tuple[object, ...], DataRow]]:
        max_row = None
        if self._rows is not None:
            min_row, max_row = max(min_row, self._rows.start), self._rows.stop - 1
            if min_row > max_row:
                return
        with zipfile.ZipFile(BytesIO(self._content)) as archive:
            links = read_sheet_hyperlinks(archive, self.title)
        highlights = _HighlightsReader()
        for number, cells in enumerate(self._sheet.iter_rows(min_row=min_row, max_row=max_row), start=min_row):
            values = tuple(getattr(cell, "value", None) for cell in cells)
            row_links = links.row(number, values)
            picked = [cells[column - 1] if column <= len(cells) else None for column in columns]
            yield values, DataRow(
                number,
                tuple(getattr(cell, "value", None) for cell in picked),
                tuple(highlights.of(cell) for cell in picked),
                tuple(getattr(cell, "number_format", None) or GENERAL for cell in picked),
                {position: row_links[column] for position, column in enumerate(columns, start=1) if column in row_links},
            )


class ReadWorkbook:
    """Skoroszyt otwarty tylko do odczytu, np. Rejestr zleceń."""

    def __init__(self, path: Path, content: bytes, workbook: Workbook, ranges: Mapping[str, range] | None = None) -> None:
        self._path = path
        self._content = content
        self._workbook = workbook
        self._ranges = ranges or {}

    def sheets(self) -> Iterator[ReadSheet]:
        with _unreadable_as_error(self._path):
            worksheets = list(self._workbook.worksheets)
        for sheet in worksheets:
            yield ReadSheet(self._path, self._content, cast(Worksheet, sheet), self._ranges.get(sheet.title))

    @contextmanager
    def narrowed(self, date_columns: Mapping[str, int], start: datetime, end: datetime) -> Iterator[ReadWorkbook]:
        """Ten skoroszyt z arkuszami ``date_columns`` (tytuł → kolumna daty od 1) zawężonymi do dat z [``start``, ``end``).

        Arkusz zawężony czyta tylko wiersze od pierwszego do ostatniego, którego
        data może leżeć w przedziale (``dated_rows``); wartości, formaty i
        Hiperłącza tych wierszy są takie jak przy odczycie całego arkusza.
        """

        # Liczba dni od początku systemu dat skoroszytu (1900 albo 1904), z dniem zapasu z obu stron: openpyxl
        # zaokrągla część dnia do milisekund. Wiersz zakresu z datą spoza przedziału czytający i tak pomija.
        day = timedelta(days=1)
        epoch = self._workbook.epoch
        low, high = (start - day - epoch) / day, (end + day - epoch) / day
        with _unreadable_as_error(self._path):
            content, ranges = rows_dated_between(self._content, date_columns, low, high)
        workbook = _open(self._path, BytesIO(content), read_only=True)
        try:
            yield ReadWorkbook(self._path, content, workbook, ranges)
        finally:
            workbook.close()


@contextmanager
def read_workbook(path: Path) -> Iterator[ReadWorkbook]:
    """Skoroszyt tylko do odczytu z formatem i Hiperłączami komórek; zamykany przy wyjściu z bloku.

    openpyxl i Hiperłącza czytają te same bajty, odczytane z dysku raz.
    """

    ensure_available(path)
    content = _file_bytes(path)
    workbook = _open(path, BytesIO(content), read_only=True)
    try:
        yield ReadWorkbook(path, content, workbook)
    finally:
        workbook.close()


def _is_value(cell: Cell | MergedCell) -> bool:
    return cell.value is not None and cell.data_type != "f"


def _is_zero(value: object) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and value == 0


@dataclass(frozen=True)
class _Outline:
    """Wzorzec pliku okresu w tym, czego potrzebują Sprawdzanie i Planowanie."""

    title: str
    header: tuple[object, ...]
    """Wartości wiersza nagłówka od kolumny A."""
    merged_ranges: tuple[CellRange, ...]
    """Scalenia aktywnego arkusza w kolejności, w jakiej daje je openpyxl."""
    zero_row_count: int
    """Liczba kolejnych Wierszy danych z zerami w kolumnach ilości N:AP."""


def _read_outline(path: Path, rules: _Rules) -> _Outline:
    """Wzorzec do sprawdzenia bez wczytania każdej komórki; niczego nie zapisuje.

    Pełne wczytanie Wzorca pliku zbiorczego przez openpyxl trwa ~2 s, a Sprawdzanie i Planowanie
    potrzebują tylko nagłówka, scaleń i wierszy z zerami. openpyxl czyta więc tylko te wiersze, a reszta
    arkusza jest sprawdzana tak, żeby Wzorzec, którego pełne wczytanie by się nie udało, był nieczytelny.
    """

    ensure_available(path)
    with _unreadable_as_error(path):
        content = path.read_bytes()
    workbook = _open(path, BytesIO(content), read_only=True)
    try:
        sheet = cast(Worksheet, workbook.active)  # tylko do odczytu: ReadOnlyWorksheet
        header = next(
            _classified(
                path,
                sheet.iter_rows(
                    min_row=rules.header_row, max_row=rules.header_row, max_col=rules.last_header_column, values_only=True
                ),
            ),
            (),
        )
        zero_row_count = 0
        for values in _classified(
            path,
            sheet.iter_rows(
                min_row=rules.first_data_row,
                min_col=QUANTITY_COLUMNS[0],
                max_col=QUANTITY_COLUMNS[-1],
                values_only=True,
            ),
        ):
            if not any(_is_zero(value) for value in values):
                break
            zero_row_count += 1
        with _unreadable_as_error(path):
            # openpyxl nie daje liczby stylów komórek inaczej niż przez atrybut prywatny.
            cell_style_count = len(workbook._cell_styles)  # type: ignore[attr-defined]
            merged_ranges = _merged_ranges(content, sheet.title, cell_style_count)
        return _Outline(sheet.title, header, merged_ranges, zero_row_count)
    finally:
        workbook.close()


_MERGE_CELL = "http://schemas.openxmlformats.org/spreadsheetml/2006/main mergeCell"
_CELL_OR_ROW_STYLE = re.compile(rb'<(?:[\w.-]+:)?(?:c|row)\s[^>]*?\bs="([0-9]+)"')
_COLUMN_STYLE = re.compile(rb'<(?:[\w.-]+:)?col\s[^>]*?\bstyle="([0-9]+)"')


def _merged_ranges(content: bytes, sheet_title: str, cell_style_count: int) -> tuple[CellRange, ...]:
    """Scalenia arkusza z bloku ``<mergeCells>`` za ``</sheetData>``.

    Arkusz musi dać się wczytać w całości jak przy pełnym wczytaniu przez openpyxl: zepsuty XML to
    ``ExpatError``, a styl komórki, wiersza albo kolumny spoza stylów skoroszytu ``IndexError``.
    """

    with zipfile.ZipFile(BytesIO(content)) as archive:
        xml = archive.read(sheet_part(archive, sheet_title))
    styles = [int(index) for pattern in (_CELL_OR_ROW_STYLE, _COLUMN_STYLE) for index in set(pattern.findall(xml))]
    if max(styles, default=0) >= cell_style_count:
        raise IndexError(f"styl {max(styles)} spoza {cell_style_count} stylów skoroszytu")
    references: list[str] = []
    parser = expat.ParserCreate(namespace_separator=" ")
    # Obsługa elementów dopiero za danymi arkusza: wywołanie Pythona dla każdej z ~500 tys. komórek kosztuje.
    tail = max(xml.rfind(b"sheetData"), 0)
    parser.Parse(xml[:tail], False)
    parser.StartElementHandler = lambda name, attributes: (
        references.append(attributes["ref"]) if name == _MERGE_CELL else None
    )
    parser.Parse(xml[tail:], True)
    return tuple(MultiCellRange([CellRange(reference) for reference in references]).ranges)


@dataclass(frozen=True)
class TemplatePlan:
    """Planowanie Wierszy danych we Wzorcu: ile kolejnych Wierszy danych ma zera w N:AP i który wiersz jest za nimi."""

    zero_row_count: int
    first_row_without_zeros: int


class TemplateFile:
    """Wzorzec jednego układu: jego Sprawdzanie, Planowanie i pliki z Wierszami danych (ADR 0008).

    ``headers`` (tylko pliki okresu) to nagłówek docelowy każdej pozycji Wiersza danych, szukany w wierszu
    nagłówka Wzorca bez względu na wielkość liter i spacje; w Rozliczeniu pracownika pozycja ``i`` to kolumna
    ``i`` Wiersza danych A:AT.
    Konstruktor nie czyta dysku. Plik powstaje kopią bajtów Wzorca, gdy kopia przyjmuje kształt Wzorca i
    wierszy, a inaczej przez openpyxl; obie drogi dają ten sam plik. Pierwszy plik czyta bajty Wzorca
    ponownie: Wzorzec zmieniony albo otwarty w Excelu po Sprawdzaniu działa tak, jakby był czytany dopiero
    wtedy, a kolejne pliki powstają z tych samych bajtów. Wzorzec na dysku pozostaje niezmieniony.
    """

    def __init__(self, path: Path, layout: Layout, headers: Sequence[str] = ()) -> None:
        if bool(headers) != layout.value.period_file:
            raise ValueError(f"nagłówki docelowe ma każdy plik okresu i tylko on: {layout.name}")
        self.path = path
        self._rules = layout.value
        self._headers = tuple(headers)
        self._content: bytes | None = None
        self._copy: TemplateCopy | None = None
        self._copy_read = False
        self._read_for_files = False

    def check(self) -> None:
        """Sprawdzanie bez zapisu: ``WorkbookError``, gdy Wzorzec nie może posłużyć jako wzór.

        Powód to brak pliku, otwarcie w Excelu, nieczytelny skoroszyt, brak nagłówka z ``headers`` albo
        WYKONAWCA poza H17 (zły układ z ``MissingHeader``), a we Wzorcu rozliczenia pracownika także
        wartości w Wierszach danych (``HAS_DATA``).
        """

        if self._rules.period_file:
            outline = _read_outline(self.path, self._rules)
            _columns(self.path, outline.title, self._rules, outline.header, self._headers)
            if self._rules.worker_header:
                _check_worker_header(self.path, outline.title, outline.header)
            return
        self._read()
        copy = self._template_copy()
        if copy is not None:
            self._check_settlement_template(copy.title, copy.header, copy.has_input_data)
            return
        with self._openpyxl_workbook() as workbook:
            sheet = _active_worksheet(self.path, workbook)
            self._check_settlement_template(sheet.title, self._header(sheet), self._has_input_data(sheet))

    def plan(self, row_count: int) -> TemplatePlan:
        """Planowanie ``row_count`` Wierszy danych: nagłówki z ``headers`` jak przy Sprawdzaniu, a scalenie w
        komórkach, do których trafią, to zły układ z ``MergedCells``."""

        outline = _read_outline(self.path, self._rules)
        columns = _columns(self.path, outline.title, self._rules, outline.header, self._headers)
        _ensure_unmerged(self.path, outline.title, outline.merged_ranges, self._rules, columns, row_count)
        return TemplatePlan(outline.zero_row_count, self._rules.first_data_row + outline.zero_row_count)

    def create(self, target: Path, rows: Sequence[DataRow]) -> None:
        """Zapisuje atomowo pod ``target`` plik z Wzorca z ``rows`` od pierwszego Wiersza danych.

        Wpisana komórka dostaje Hiperłącze wiersza albo żadne i wartość; w kolumnach wyglądu Wygląd Wiersza
        danych (``row_look``), a dalej Wyróżnienia na czcionce i wypełnieniu komórki Wzorca. Formuły,
        ``calcChain`` kopii, reszta formatowania i ``xl/externalLinks/*`` zostają z Wzorca. ``WorkbookError``,
        gdy Wzorca nie da się już użyć, brak nagłówka albo komórki zapisu pliku okresu są scalone;
        ``WorkbookSaveError``, gdy zapis się nie uda, także przez znak niedozwolony w XML. W obu przypadkach ``target`` nie powstaje.
        """

        if not self._read_for_files:
            self._read()
            self._read_for_files = True
        copy = self._template_copy()
        if copy is not None:
            columns = _columns(self.path, copy.title, self._rules, copy.header, self._headers)
            if not self._rules.period_file:
                self._check_settlement_template(copy.title, copy.header, copy.has_input_data)
            placed = _placed(rows, columns)
            if placed is not None:
                try:
                    package = copy.with_rows(placed)
                except InvalidValue as exc:
                    raise WorkbookSaveError(f"Nie można zapisać skoroszytu: {target.name}") from exc
                except UnsupportedShape:
                    pass
                else:
                    _write_atomically(target, _package_writer(package, target))
                    return
        self._create_with_openpyxl(target, rows)

    def _read(self) -> None:
        """Czyta bajty Wzorca; wczytany Wzorzec zostaje, jeśli plik się nie zmienił."""

        ensure_available(self.path)
        if self.path.suffix.lower() not in _WORKBOOK_SUFFIXES:
            raise WorkbookError(self.path, Problem.UNREADABLE)
        with _unreadable_as_error(self.path):
            content = self.path.read_bytes()
        if content != self._content:
            self._content = content
            self._copy = None
            self._copy_read = False

    def _template_copy(self) -> TemplateCopy | None:
        """Wzorzec do kopii z podmienionymi Wierszami danych; ``None``, gdy jego kształt wymaga openpyxl (ADR 0008)."""

        if not self._copy_read:
            self._copy_read = True
            self._copy = None
            if self._rules.copy is not None:
                try:
                    self._copy = TemplateCopy.of(self._loaded(), self._rules.copy)
                except UnsupportedShape:
                    pass
        return self._copy

    @contextmanager
    def _openpyxl_workbook(self) -> Iterator[Workbook]:
        """Pełne wczytanie Wzorca przez openpyxl z jego klasyfikacją uszkodzeń: jedyna droga Rozliczenia wewnętrznego,
        a dla pozostałych Wzorców droga, gdy kopia nie przyjmuje ich kształtu (ADR 0008)."""

        workbook = _open(self.path, BytesIO(self._loaded()), read_only=False)
        try:
            yield workbook
        finally:
            workbook.close()

    def _create_with_openpyxl(self, target: Path, rows: Sequence[DataRow]) -> None:
        with self._openpyxl_workbook() as workbook:
            sheet = _active_worksheet(self.path, workbook)
            header = self._header(sheet)
            columns = _columns(self.path, sheet.title, self._rules, header, self._headers)
            if self._rules.period_file:
                _ensure_unmerged(self.path, sheet.title, tuple(sheet.merged_cells.ranges), self._rules, columns, len(rows))
            else:
                self._check_settlement_template(sheet.title, header, self._has_input_data(sheet))
            try:
                _write_rows(sheet, self._rules, rows, columns)
            except IllegalCharacterError as exc:
                raise WorkbookSaveError(f"Nie można zapisać skoroszytu: {target.name}") from exc
            if self._rules.recalculate:
                _request_full_recalculation(workbook)
            _save_atomically(workbook, target, _read_external_link_parts(BytesIO(self._loaded()), self.path.name))

    def _header(self, sheet: Worksheet) -> list[object]:
        """Wartości wiersza nagłówka od kolumny A."""

        last_column = self._rules.last_header_column or sheet.max_column
        return [sheet.cell(self._rules.header_row, column).value for column in range(1, last_column + 1)]

    def _has_input_data(self, sheet: Worksheet) -> bool:
        """Wiersze danych mają wartość w A:K; formuły Wzorca nie są danymi."""

        for row in range(self._rules.first_data_row, sheet.max_row + 1):
            if any(_is_value(sheet.cell(row, column)) for column in _INPUT_COLUMNS):
                return True
        return False

    def _check_settlement_template(self, sheet: str, header: Sequence[object], has_input_data: bool) -> None:
        """Kontrole Szablonu pracownika na Wzorcu: WYKONAWCA w H17, potem brak wartości w Wierszach danych."""

        _check_worker_header(self.path, sheet, header)
        if has_input_data:
            raise WorkbookError(self.path, Problem.HAS_DATA)

    def _loaded(self) -> bytes:
        assert self._content is not None, "Wzorzec jest czytany przed użyciem"
        return self._content


def _columns(path: Path, sheet: str, rules: _Rules, header: Sequence[object], headers: Sequence[str]) -> Sequence[int]:
    """Kolumna Wzorca każdej pozycji Wiersza danych: pod nagłówkiem z ``headers``, a bez nich kolumny A:AT."""

    if not headers:
        return DATA_ROW_COLUMNS
    found = header_columns(header)
    columns: list[int] = []
    for target in headers:
        column = found.get(normalize_text(target))
        if column is None:
            raise WorkbookError(path, Problem.LAYOUT, MissingHeader(sheet, rules.header_row, target))
        columns.append(column)
    return columns


def _ensure_unmerged(
    path: Path, sheet: str, merged_ranges: Sequence[CellRange], rules: _Rules, columns: Sequence[int], row_count: int
) -> None:
    """Zły układ z ``MergedCells``, gdy komórki ``row_count`` zapisanych Wierszy danych są scalone."""

    if row_count == 0:
        return
    first_row, last_row = rules.first_data_row, rules.first_data_row + row_count - 1
    last_column = _last_written_column(rules, columns)
    for merged in merged_ranges:
        if merged.min_row <= last_row and merged.max_row >= first_row and merged.min_col <= last_column:
            raise WorkbookError(path, Problem.LAYOUT, MergedCells(sheet, merged.coord))


def _last_written_column(rules: _Rules, columns: Sequence[int]) -> int:
    return max(rules.look_columns, *columns)


def _placed(rows: Sequence[DataRow], columns: Sequence[int]) -> Sequence[DataRow] | None:
    """Wiersze z pozycjami w kolumnach od A, jak je wpisuje kopia; ``None``, gdy ``columns`` nie zajmują kolumn od A."""

    in_order = list(range(1, len(columns) + 1))
    if list(columns) == in_order:
        return rows
    if sorted(columns) != in_order:
        return None
    order = sorted(range(len(columns)), key=columns.__getitem__)
    return [
        DataRow(
            row.number,
            tuple(row.values[index] for index in order),
            tuple(row.highlights[index] for index in order),
            tuple(row.number_formats[index] for index in order),
            {columns[position - 1]: link for position, link in row.hyperlinks.items()},
        )
        for row in rows
    ]


def _write_rows(sheet: Worksheet, rules: _Rules, rows: Sequence[DataRow], columns: Sequence[int]) -> None:
    """Jedyny zapis Wierszy danych przez openpyxl: pozycja ``i`` wiersza trafia do kolumny ``columns[i-1]``.

    Komórka kolumny wyglądu dostaje Wygląd Wiersza danych, a bez pozycji w wierszu sam wygląd i treść Wzorca; w
    pliku okresu wygląd ma każda zapisana kolumna. Dalsze komórki dostają Wyróżnienia na stylu Wzorca. Zapisany
    wiersz traci wysokość z Wzorca.
    """

    last_column = _last_written_column(rules, columns)
    look_columns = last_column if rules.period_file else rules.look_columns
    look = RowLook([cast(Font, sheet.cell(rules.header_row, column).font) for column in range(1, look_columns + 1)])
    positions = {column: position for position, column in enumerate(columns, start=1)}
    for index, row in enumerate(rows):
        number = rules.first_data_row + index
        dimension = sheet.row_dimensions.get(number)  # bez tworzenia wymiaru, którego nie ma we Wzorcu
        if dimension is not None:
            dimension.ht = None
        for column in range(1, last_column + 1):
            cell = sheet.cell(number, column)
            position = positions.get(column)
            if position is None:
                look.cell(column, PLAIN, GENERAL, wrapped=False).apply(cell)
                continue
            value, highlights = row.values[position - 1], row.highlights[position - 1]
            link = row.hyperlinks.get(position)
            # Przed wartością: openpyxl wpisuje adres jako wartość pustej komórki.
            cell.hyperlink = None if link is None else link.address
            cell.value = value
            if column <= look.columns:
                look.cell(column, highlights, row.number_formats[position - 1], wrapped=wraps(value)).apply(cell)
            else:
                cell.font = highlights.font_over(cast(Font, copy(cell.font)))
                cell.fill = highlights.fill_over(cast(Fill, copy(cell.fill)))
    if rules.period_file:
        _set_autofilter(sheet, rules.header_row, len(rows))


def _set_autofilter(sheet: Worksheet, header_row: int, row_count: int) -> None:
    """Autofiltr na nagłówek i faktyczne Wiersze danych; zakres zapisany we Wzorcu jest ignorowany."""

    columns = [column for column, cell in enumerate(sheet[header_row], start=1) if not is_blank(cell.value)]
    first_column, last_column = get_column_letter(min(columns)), get_column_letter(max(columns))
    sheet.auto_filter = AutoFilter(ref=f"{first_column}{header_row}:{last_column}{header_row + row_count}")


def _write_atomically(target: Path, write: Callable[[Path], None]) -> None:
    """``write`` zapisuje skoroszyt do pliku tymczasowego obok ``target``; dopiero potem ``target`` jest podmieniany.

    Nieudany zapis to ``WorkbookSaveError`` (albo błąd zapisu zgłoszony przez ``write``); plik tymczasowy
    nigdy nie zostaje, a ``target`` zmienia się tylko po udanym zapisie całości.
    """

    try:
        file_descriptor, temporary_name = tempfile.mkstemp(
            prefix=f".{target.stem}.", suffix=".xlsx", dir=target.parent
        )
        os.close(file_descriptor)
    except OSError as exc:
        raise WorkbookSaveError(f"Nie można zapisać skoroszytu: {target.name}") from exc
    temporary_path = Path(temporary_name)
    try:
        write(temporary_path)
        try:
            os.replace(temporary_path, target)
        except OSError as exc:
            raise WorkbookSaveError(f"Nie można zapisać skoroszytu: {target.name}") from exc
    finally:
        temporary_path.unlink(missing_ok=True)


def _package_writer(package: Package, target: Path) -> Callable[[Path], None]:
    def write(path: Path) -> None:
        try:
            with path.open("wb") as out:
                package.write(out)
        except OSError as exc:
            raise WorkbookSaveError(f"Nie można zapisać skoroszytu: {target.name}") from exc

    return write


def _active_worksheet(path: Path, workbook: Workbook) -> Worksheet:
    worksheet = workbook.active
    if not isinstance(worksheet, Worksheet):
        raise WorkbookError(path, Problem.UNREADABLE)
    return worksheet


def _request_full_recalculation(workbook: Workbook) -> None:
    """Excel przeliczy formuły przy otwarciu; openpyxl nie zapisuje wyników formuł."""

    calculation = getattr(workbook, "calculation", None)
    if calculation is not None:
        calculation.calcMode = "auto"
        calculation.fullCalcOnLoad = True
        calculation.forceFullCalc = True


def save_workbook(workbook: Workbook, target: Path) -> None:
    """Atomowo zapisuje skoroszyt pod istniejący ``target``, zachowując 1:1 jego odwołania zewnętrzne.

    openpyxl nie zapisuje wiernie części ``xl/externalLinks/*``, więc są one kopiowane bajtowo z
    ``target``. ``target`` zmienia się dopiero po udanym zapisie całości.
    """

    _save_atomically(workbook, target, _read_external_link_parts(target, target.name))


def _read_external_link_parts(source: Path | IO[bytes], name: str) -> _ExternalLinkParts:
    try:
        return _external_link_parts(source)
    except _WORKBOOK_FILE_ERRORS as exc:
        raise ExternalLinksError(f"Nie można odczytać odwołań zewnętrznych: {name}") from exc


def _save_atomically(workbook: Workbook, target: Path, parts: _ExternalLinkParts) -> None:
    """Atomowo zapisuje skoroszyt openpyxl pod ``target`` i przywraca w nim ``parts``."""

    def write(path: Path) -> None:
        try:
            workbook.save(path)
        except _WORKBOOK_FILE_ERRORS as exc:
            raise WorkbookSaveError(f"Nie można zapisać skoroszytu: {target.name}") from exc
        try:
            _restore_external_link_parts(path, parts)
        except _WORKBOOK_FILE_ERRORS as exc:
            raise ExternalLinksError(f"Nie można przywrócić odwołań zewnętrznych: {target.name}") from exc

    _write_atomically(target, write)


def _external_link_parts(source: Path | IO[bytes]) -> _ExternalLinkParts:
    """Pobiera oryginalne relacje zewnętrzne, których openpyxl nie zapisuje 1:1."""

    with zipfile.ZipFile(source, "r") as archive:
        return {
            info.filename: (info, archive.read(info.filename))
            for info in archive.infolist()
            if info.filename.startswith(_EXTERNAL_LINKS_PREFIX)
        }


def _restore_external_link_parts(path: Path, parts: _ExternalLinkParts) -> None:
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
                if info.filename.startswith(_EXTERNAL_LINKS_PREFIX):
                    continue
                target.writestr(info, source.read(info.filename))
            for info, data in parts.values():
                target.writestr(info, data)
        os.replace(temporary_path, path)
    finally:
        temporary_path.unlink(missing_ok=True)

# W6: powtórka kształtu PR #263, bez wpływu na działanie

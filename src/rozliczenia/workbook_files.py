"""Skoroszyty na dysku: otwarcie z jedną klasyfikacją uszkodzeń, układ arkusza i plik z Wzorca.

Każde otwarcie skoroszytu w obu procesach przechodzi przez ten moduł: Plik
zbiorczy (``read_data_rows``, z Wyróżnieniami i Hiperłączami komórek), Rejestr zleceń
(``read_workbook``, z formatem i Hiperłączami komórek), Wzorce do Sprawdzania i dla
Przygotowania pliku zbiorczego (``open_template``, ``file_from_template``) oraz Wzorzec rozliczenia
pracownika, który Przebieg rozliczeń sprawdza i z którego tworzy Rozliczenia
pracowników (``WorkerSettlementTemplate``). Otwarcie
sprawdza dostępność i klasyfikuje każde uszkodzenie, a problem zgłasza jako
``WorkbookError`` z powodem. Moduł nie zna Komunikatów: proces tłumaczy powód
na Komunikat ze swojego katalogu.

Moduł jest właścicielem układu arkusza Pliku zbiorczego, wspólnego dla Wzorca
pliku zbiorczego, Wzorca rozliczenia pracownika i Szablonów pracowników:
nagłówek w wierszu 17 z WYKONAWCA w H, Wiersze danych od 18, dane wejściowe
A:K, ilości N:AP i kolumny Wiersza danych A:AT. Publiczne są etykieta komórki
nagłówka ``WORKER_HEADER`` do treści Komunikatów oraz wiersze i kolumny układu
(``HEADER_ROW``, ``FIRST_DATA_ROW``, ``QUANTITY_COLUMNS``, ``DATA_ROW_COLUMNS``) dla
narzędzi benchmarku w ``tools/``, żeby nie powtarzały układu.
"""

from __future__ import annotations

import os
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
from xml.parsers.expat import ExpatError

from openpyxl import load_workbook
from openpyxl.cell.cell import Cell, MergedCell
from openpyxl.cell.rich_text import CellRichText
from openpyxl.styles.fills import Fill
from openpyxl.styles.fonts import Font
from openpyxl.utils import get_column_letter
from openpyxl.utils.exceptions import InvalidFileException
from openpyxl.workbook.workbook import Workbook
from openpyxl.worksheet._read_only import ReadOnlyWorksheet
from openpyxl.worksheet.formula import ArrayFormula, DataTableFormula
from openpyxl.worksheet.worksheet import Worksheet

from .dated_rows import rows_dated_between
from .highlights import Highlights
from .hyperlinks import Hyperlink, read_sheet_hyperlinks
from .input_rows import rows_with_input
from .template_copy import InvalidValue, Package, SheetLayout, TemplateCopy, UnsupportedShape


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
QUANTITY_COLUMNS = range(14, 43)  # N:AP
DATA_ROW_COLUMNS = range(1, 47)  # A:AT: kopiowane z Pliku zbiorczego do Szablonu pracownika
_WORKER_SETTLEMENT_LAYOUT = SheetLayout(
    header_row=HEADER_ROW,
    first_data_row=FIRST_DATA_ROW,
    input_columns=_INPUT_COLUMNS[-1],
    data_columns=DATA_ROW_COLUMNS[-1],
)


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
    UNREADABLE = "nieczytelny"
    LAYOUT = "zły układ"
    HAS_DATA = "zawiera dane"
    """Wzorzec ma już wartości w Wierszach danych; zgłasza tylko ``WorkerSettlementTemplate``."""


class WorkbookError(Exception):
    """Skoroszytu nie da się użyć; ``problem`` mówi dlaczego.

    Przy złym układzie ``worker_column`` to litera kolumny A:K, w której wiersz
    17 ma WYKONAWCA, albo ``None``, gdy w A17:K17 go nie ma.
    """

    def __init__(self, path: Path, problem: Problem, *, worker_column: str | None = None) -> None:
        super().__init__(f"{problem.value}: {path.name}")
        self.path = path
        self.problem = problem
        self.worker_column = worker_column


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


@dataclass(frozen=True)
class _Rows:
    header_row: int
    first_data_row: int
    last_header_column: int | None  # ``None``: cały wiersz nagłówka


class Layout(Enum):
    """Układ arkusza Wzorca: gdzie jest nagłówek i od którego wiersza są Wiersze danych."""

    COLLECTIVE = _Rows(HEADER_ROW, FIRST_DATA_ROW, _INPUT_COLUMNS[-1])
    """Plik zbiorczy, Wzorzec pliku zbiorczego i Wzorzec rozliczenia pracownika."""
    INTERNAL = _Rows(header_row=1, first_data_row=2, last_header_column=None)
    """Rozliczenie wewnętrzne i jego Wzorzec."""


@dataclass(frozen=True)
class DataRow:
    """Wiersz danych Pliku zbiorczego: numer wiersza, surowa wartość WYKONAWCA, wartości A:AT, Wyróżnienia i Hiperłącza."""

    number: int
    worker: _ExcelCellValue
    values: ExcelRow
    highlights: tuple[Highlights, ...]
    """Wyróżnienia komórek A:AT, po pozycji jak ``values``."""
    hyperlinks: Mapping[int, Hyperlink] = field(default_factory=dict)
    """Hiperłącza komórek A:AT z wartością: kolumna od 1 → Hiperłącze."""


@dataclass(frozen=True)
class FormattedCell:
    """Wartość komórki z wyróżnieniami i Hiperłączem odczytanymi przy otwarciu; brakująca komórka ma same ``None``."""

    value: object
    font: Font | None
    fill: Fill | None
    number_format: str | None
    hyperlink: Hyperlink | None


_EMPTY_CELL = FormattedCell(None, None, None, None, None)


def is_open_in_excel(path: Path) -> bool:
    """Rozpoznaje skoroszyt otwarty w desktopowym Excelu po pliku blokady ``~$…``."""

    return path.with_name(f"~${path.name}").exists()


def ensure_available(path: Path) -> None:
    """Skoroszyt jest na dysku i nie jest otwarty w Excelu; inaczej ``WorkbookError``."""

    if not path.is_file():
        raise WorkbookError(path, Problem.MISSING)
    if is_open_in_excel(path):
        raise WorkbookError(path, Problem.OPEN_IN_EXCEL)


_T = TypeVar("_T")


@contextmanager
def _unreadable_as_error(path: Path) -> Iterator[None]:
    """Uszkodzenie skoroszytu zgłoszone przez openpyxl staje się ``WorkbookError``; inne błędy przechodzą."""

    try:
        yield
    except _UNREADABLE_WORKBOOK_ERRORS as exc:
        raise WorkbookError(path, Problem.UNREADABLE) from exc


def _classified(path: Path, items: Iterator[_T]) -> Iterator[_T]:
    """Elementy leniwego odczytu openpyxl; klasyfikowane jest tylko pobranie elementu."""

    while True:
        with _unreadable_as_error(path):
            try:
                item = next(items)
            except StopIteration:
                return
        yield item


def _load(path: Path) -> Workbook:
    """Skoroszyt ``path`` dostępny na dysku, otwarty przez openpyxl do zapisu."""

    ensure_available(path)
    return _open(path, path, read_only=False)


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


def _check_worker_header(path: Path, header: Sequence[object]) -> None:
    """Jedno sprawdzenie nagłówka WYKONAWCA w H17 (bez względu na wielkość liter i spacje) dla wartości A17:K17."""

    columns = [column for column, value in enumerate(header[: _INPUT_COLUMNS[-1]], start=1) if _is_worker_header(value)]
    if _WORKER_COLUMN not in columns:
        raise WorkbookError(path, Problem.LAYOUT, worker_column=get_column_letter(columns[0]) if columns else None)


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
    with _unreadable_as_error(path):
        content = rows_with_input(path.read_bytes(), _INPUT_COLUMNS[-1])
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
        _check_worker_header(path, header)
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
            rows.append(DataRow(number, values[_WORKER_COLUMN - 1], values, row_highlights, links.row(number, values)))
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

    def formatted_rows(
        self, min_row: int, columns: Sequence[int]
    ) -> Iterator[tuple[int, tuple[object, ...], tuple[FormattedCell, ...]]]:
        """Numer wiersza, wartości całego wiersza i komórki ``columns`` (od 1) z wyróżnieniami i Hiperłączami, od ``min_row`` w dół.

        W arkuszu zawężonym tylko wiersze z jego zakresu.
        """

        return _classified(self._path, self._formatted_rows(min_row, columns))

    def _formatted_rows(
        self, min_row: int, columns: Sequence[int]
    ) -> Iterator[tuple[int, tuple[object, ...], tuple[FormattedCell, ...]]]:
        max_row = None
        if self._rows is not None:
            min_row, max_row = max(min_row, self._rows.start), self._rows.stop - 1
            if min_row > max_row:
                return
        with zipfile.ZipFile(BytesIO(self._content)) as archive:
            links = read_sheet_hyperlinks(archive, self.title)
        for number, cells in enumerate(self._sheet.iter_rows(min_row=min_row, max_row=max_row), start=min_row):
            values = tuple(getattr(cell, "value", None) for cell in cells)
            row_links = links.row(number, values)
            yield number, values, tuple(
                _formatted(cells[column - 1], row_links.get(column)) if column <= len(cells) else _EMPTY_CELL
                for column in columns
            )


def _formatted(cell: object, hyperlink: Hyperlink | None) -> FormattedCell:
    return FormattedCell(
        value=getattr(cell, "value", None),
        font=getattr(cell, "font", None),
        fill=getattr(cell, "fill", None),
        number_format=getattr(cell, "number_format", None),
        hyperlink=hyperlink,
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
    with _unreadable_as_error(path):
        content = path.read_bytes()
    workbook = _open(path, BytesIO(content), read_only=True)
    try:
        yield ReadWorkbook(path, content, workbook)
    finally:
        workbook.close()


class TemplateSheet:
    """Arkusz roboczy Wzorca w jego układzie.

    ``worksheet`` służy formatowaniu wewnątrz bloku. Sprawdzenie nagłówka
    WYKONAWCA, dane wejściowe, zera w kolumnach ilości i wpisanie Wierszy
    danych dotyczą układu Pliku zbiorczego.
    """

    def __init__(self, path: Path, worksheet: Worksheet, layout: Layout) -> None:
        self._path = path
        self._rows = layout.value
        self.worksheet = worksheet

    @property
    def title(self) -> str:
        return self.worksheet.title

    @property
    def header_row(self) -> int:
        return self._rows.header_row

    def header(self) -> list[object]:
        """Wartości wiersza nagłówka od kolumny A."""

        last_column = self._rows.last_header_column or self.worksheet.max_column
        return [self.worksheet.cell(self._rows.header_row, column).value for column in range(1, last_column + 1)]

    def data_row(self, index: int) -> int:
        """Numer wiersza arkusza ``index``-tego (od 0) Wiersza danych."""

        return self._rows.first_data_row + index

    def check_worker_header(self) -> None:
        """Nagłówek WYKONAWCA w H17; inaczej ``WorkbookError`` ze złym układem."""

        _check_worker_header(self._path, self.header())

    def has_input_data(self) -> bool:
        """Wiersze danych mają wartość w A:K; formuły Wzorca nie są danymi."""

        for row in range(self._rows.first_data_row, self.worksheet.max_row + 1):
            if any(_is_value(self.worksheet.cell(row, column)) for column in _INPUT_COLUMNS):
                return True
        return False

    def zero_row_count(self) -> int:
        """Liczba kolejnych Wierszy danych z zerami w kolumnach ilości N:AP."""

        count = 0
        for values in self.worksheet.iter_rows(
            min_row=self._rows.first_data_row,
            min_col=QUANTITY_COLUMNS[0],
            max_col=QUANTITY_COLUMNS[-1],
            values_only=True,
        ):
            if not any(_is_zero(value) for value in values):
                break
            count += 1
        return count

    def write_data_rows(self, rows: Sequence[DataRow]) -> None:
        """Wpisuje Wiersze danych z ich Wyróżnieniami i Hiperłączami po pozycji kolumn A:AT od pierwszego Wiersza danych.

        Krój i rozmiar czcionki, format liczby, obramowanie, wyrównanie i ochrona zostają z komórki Wzorca;
        hiperłącze komórki Wzorca zastępuje Hiperłącze z Wiersza danych albo żadne.
        """

        for index, row in enumerate(rows):
            for column, value, highlights in zip(DATA_ROW_COLUMNS, row.values, row.highlights, strict=True):
                cell = self.worksheet.cell(self.data_row(index), column)
                link = row.hyperlinks.get(column)
                # Przed wartością: openpyxl wpisuje adres jako wartość pustej komórki.
                cell.hyperlink = None if link is None else link.address
                cell.value = value
                cell.font = highlights.font_over(cast(Font, copy(cell.font)))
                cell.fill = highlights.fill_over(cast(Fill, copy(cell.fill)))


def _is_value(cell: Cell | MergedCell) -> bool:
    return cell.value is not None and cell.data_type != "f"


def _is_zero(value: object) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and value == 0


@contextmanager
def open_template(path: Path, layout: Layout) -> Iterator[TemplateSheet]:
    """Wzorzec do sprawdzenia; niczego nie zapisuje."""

    workbook = _load(path)
    try:
        yield _template_sheet(path, workbook, layout)
    finally:
        workbook.close()


@contextmanager
def file_from_template(template: Path, target: Path, layout: Layout, *, recalculate: bool) -> Iterator[TemplateSheet]:
    """Plik z Wzorca: arkusz Wzorca do wypełnienia, zapisany atomowo pod ``target`` przy wyjściu z bloku.

    Odwołania zewnętrzne ``xl/externalLinks/*`` zostają 1:1 z Wzorca;
    ``recalculate`` każe Excelowi przeliczyć formuły przy otwarciu. Przy
    wyjątku w bloku albo nieudanym zapisie ``target`` nie powstaje, a Wzorzec
    zawsze pozostaje niezmieniony.
    """

    workbook = _load(template)
    try:
        yield _template_sheet(template, workbook, layout)
        if recalculate:
            _request_full_recalculation(workbook)
        save_workbook(workbook, target, external_links_from=template)
    finally:
        workbook.close()


class WorkerSettlementTemplate:
    """Wzorzec rozliczenia pracownika wczytany raz na Przebieg rozliczeń.

    Sprawdzanie (``check``) i każde Rozliczenie pracownika (``create_settlement``)
    korzystają z tego samego Wzorca wczytanego do pamięci: kopii części zip
    Wzorca, w której zmieniają się tylko Wiersze danych w XML arkusza (ADR 0008).
    Przy pierwszym Rozliczeniu pracownika plik jest czytany ponownie tylko jako
    bajty; Wzorzec zmieniony albo otwarty w Excelu po Sprawdzaniu jest więc
    traktowany tak, jakby był wczytany dopiero wtedy. Wzorzec, którego kształtu
    kopia nie obsługuje, idzie dawną drogą przez openpyxl. Wzorzec na dysku
    pozostaje niezmieniony.
    """

    def __init__(self, path: Path) -> None:
        self._path = path
        self._content: bytes | None = None
        self._copy: TemplateCopy | None = None
        self._copy_read = False
        self._read_for_settlements = False

    def check(self) -> None:
        """Sprawdzanie Wzorca bez zapisu: ``WorkbookError``, gdy nie może posłużyć jako wzór.

        Powód to brak pliku, otwarcie w Excelu, nieczytelny skoroszyt, brak
        WYKONAWCA w H17 (zły układ) albo wartości w Wierszach danych (``HAS_DATA``).
        """

        self._read()
        copy = self._template_copy()
        if copy is not None:
            _check_settlement_template(self._path, copy.header, copy.has_input_data)
            return
        with self._openpyxl_workbook() as workbook:
            sheet = _template_sheet(self._path, workbook, Layout.COLLECTIVE)
            _check_settlement_template(self._path, sheet.header(), sheet.has_input_data())

    def create_settlement(self, target: Path, rows: Sequence[DataRow]) -> None:
        """Tworzy atomowo pod ``target`` Rozliczenie pracownika z ``rows`` jako Wierszami danych.

        Wiersze danych są wpisywane z Wyróżnieniami i Hiperłączami po pozycji kolumn A:AT od
        wiersza 18; formuły (także wspólne), ``calcChain``, pozostałe
        formatowanie i ``xl/externalLinks/*`` zostają z Wzorca, a Excel
        przeliczy formuły przy otwarciu.

        Wzorca, którego nie da się użyć, nie maskuje wynik: ``WorkbookError``
        (brak, otwarty w Excelu, nieczytelny, bez WYKONAWCA w H17 albo z danymi
        w Wierszach danych). Nieudany zapis to ``WorkbookSaveError``. W obu
        przypadkach ``target`` nie powstaje.
        """

        if not self._read_for_settlements:
            self._read()
            self._read_for_settlements = True
        copy = self._template_copy()
        if copy is not None:
            _check_settlement_template(self._path, copy.header, copy.has_input_data)
            try:
                package = copy.with_rows(rows)
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

        ensure_available(self._path)
        if self._path.suffix.lower() not in _WORKBOOK_SUFFIXES:
            raise WorkbookError(self._path, Problem.UNREADABLE)
        with _unreadable_as_error(self._path):
            content = self._path.read_bytes()
        if content != self._content:
            self._content = content
            self._copy = None
            self._copy_read = False

    def _template_copy(self) -> TemplateCopy | None:
        """Wzorzec do kopii z podmienionymi Wierszami danych; ``None``, gdy jego kształt wymaga openpyxl (ADR 0008)."""

        if not self._copy_read:
            self._copy_read = True
            try:
                self._copy = TemplateCopy.of(self._loaded(), _WORKER_SETTLEMENT_LAYOUT)
            except UnsupportedShape:
                self._copy = None
        return self._copy

    @contextmanager
    def _openpyxl_workbook(self) -> Iterator[Workbook]:
        """Dawna droga (ADR 0008): pełne wczytanie Wzorca przez openpyxl z jego klasyfikacją uszkodzeń."""

        workbook = _open(self._path, BytesIO(self._loaded()), read_only=False)
        try:
            yield workbook
        finally:
            workbook.close()

    def _create_with_openpyxl(self, target: Path, rows: Sequence[DataRow]) -> None:
        with self._openpyxl_workbook() as workbook:
            sheet = _template_sheet(self._path, workbook, Layout.COLLECTIVE)
            _check_settlement_template(self._path, sheet.header(), sheet.has_input_data())
            sheet.write_data_rows(rows)
            _request_full_recalculation(workbook)
            _save_atomically(workbook, target, _read_external_link_parts(BytesIO(self._loaded()), self._path.name))

    def _loaded(self) -> bytes:
        assert self._content is not None, "Wzorzec jest czytany przed użyciem"
        return self._content


def _check_settlement_template(path: Path, header: Sequence[object], has_input_data: bool) -> None:
    """Kontrole Szablonu pracownika na Wzorcu: WYKONAWCA w H17, potem brak wartości w Wierszach danych."""

    _check_worker_header(path, header)
    if has_input_data:
        raise WorkbookError(path, Problem.HAS_DATA)


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


def _template_sheet(path: Path, workbook: Workbook, layout: Layout) -> TemplateSheet:
    worksheet = workbook.active
    if not isinstance(worksheet, Worksheet):
        raise WorkbookError(path, Problem.UNREADABLE)
    return TemplateSheet(path, worksheet, layout)


def _request_full_recalculation(workbook: Workbook) -> None:
    """Excel przeliczy formuły przy otwarciu; openpyxl nie zapisuje wyników formuł."""

    calculation = getattr(workbook, "calculation", None)
    if calculation is not None:
        calculation.calcMode = "auto"
        calculation.fullCalcOnLoad = True
        calculation.forceFullCalc = True


def save_workbook(
    workbook: Workbook,
    target: Path,
    *,
    external_links_from: Path | None = None,
) -> None:
    """Atomowo zapisuje skoroszyt, zachowując 1:1 jego odwołania zewnętrzne.

    openpyxl nie zapisuje wiernie części ``xl/externalLinks/*``, więc są one
    kopiowane bajtowo z ``external_links_from`` (domyślnie z ``target``, który
    musi wtedy istnieć). ``target`` zmienia się dopiero po udanym zapisie całości.
    """

    links_source = external_links_from if external_links_from is not None else target
    _save_atomically(workbook, target, _read_external_link_parts(links_source, links_source.name))


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

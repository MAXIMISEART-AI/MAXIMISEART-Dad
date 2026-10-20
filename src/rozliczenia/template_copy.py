"""Kopia skoroszytu Wzorca z podmienionymi Wierszami danych, bez wczytywania przez openpyxl (ADR 0007).

Moduł jest szczegółem ``workbook_files.WorkerSettlementTemplate`` i nikt poza nim
go nie używa. ``TemplateCopy.of`` czyta bajty Wzorca raz: rozpakowuje części zip,
sprawdza, że każda część XML jest poprawnym XML-em, indeksuje wiersze XML
aktywnego arkusza i liczy kontrole Szablonu pracownika (nagłówek, dane w
Wierszach danych); na tym opiera się Sprawdzanie Wzorca. Arkusz jest kompresowany
raz, w kawałkach od granic wierszy, przy pierwszej kopii. ``TemplateCopy.with_rows``
składa z tego jedną kopię:

- każda część zip poza arkuszem, ``xl/workbook.xml`` i (przy datach) ``xl/styles.xml``
  jest przepisana bajt w bajt razem ze skompresowaną treścią, w tym
  ``xl/externalLinks/*``, ``xl/calcChain.xml`` i ``xl/sharedStrings.xml``;
- w arkuszu zmieniają się tylko wiersze od pierwszego Wiersza danych do ostatniego
  wpisanego: komórki kolumn Wiersza danych dostają wartości tak jak przy wpisaniu
  przez openpyxl (``TemplateSheet.write_data_rows``), a pozostałe komórki, w tym
  formuły, wspólne formuły i style, zostają bajt w bajt; kompresowany jest tylko
  początek arkusza do granicy kawałka za ostatnim wpisanym wierszem, reszta to
  gotowe kawałki z pierwszej kopii;
- ``calcPr`` w ``xl/workbook.xml`` dostaje ``calcMode="auto"``, ``fullCalcOnLoad="1"``
  i ``forceFullCalc="1"``, jak przy zapisie przez openpyxl.

Wzorzec, którego kształtu ten moduł nie obsługuje (np. formuła w kolumnach Wiersza
danych, scalenie w Wierszach danych, XML z prefiksami albo bez atrybutów ``r``,
uszkodzona część XML), zgłasza ``UnsupportedShape``; tak samo wartość, której typu
moduł nie zapisuje. Wtedy ``workbook_files`` sprawdza Wzorzec i tworzy Rozliczenie
pracownika dawną drogą przez openpyxl, z jej klasyfikacją uszkodzeń.
Wartość, której nie da się zapisać w ogóle (znak niedozwolony w XML, data ze
strefą czasową), to ``InvalidValue``.
"""

from __future__ import annotations

import html
import math
import posixpath
import re
import struct
import zipfile
import zlib
from bisect import bisect_left, bisect_right
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from decimal import Decimal
from io import BytesIO
from typing import IO, Final
from xml.etree import ElementTree
from xml.parsers import expat

from openpyxl.cell.cell import ERROR_CODES, ILLEGAL_CHARACTERS_RE
from openpyxl.styles.numbers import (
    BUILTIN_FORMATS,
    BUILTIN_FORMATS_REVERSE,
    FORMAT_DATE_DATETIME,
    FORMAT_DATE_TIME6,
    FORMAT_DATE_TIMEDELTA,
    FORMAT_DATE_YYYYMMDD2,
    is_date_format,
)
from openpyxl.utils.cell import column_index_from_string, get_column_letter, range_boundaries
from openpyxl.utils.datetime import MAC_EPOCH, WINDOWS_EPOCH, to_excel

from .sheet_data import IrregularSheetData, SheetRow, sheet_data_bounds, sheet_rows


class UnsupportedShape(Exception):
    """Wzorca albo wartości nie da się zapisać podmianą wierszy; zapis idzie dawną drogą."""


class InvalidValue(Exception):
    """Wartości Wiersza danych nie da się zapisać w skoroszycie."""


_OFFICE_REL: Final = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
_PACKAGE_REL: Final = "{http://schemas.openxmlformats.org/package/2006/relationships}Relationship"
_MAIN: Final = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
_READ_ERRORS: Final = (
    zipfile.BadZipFile,
    zipfile.LargeZipFile,
    KeyError,
    IndexError,
    ValueError,
    ElementTree.ParseError,
    expat.ExpatError,
    zlib.error,
    struct.error,
    NotImplementedError,
    RuntimeError,
    EOFError,
    OSError,
)

# Wiersze arkusza w jednym kawałku kompresji. Mniejszy kawałek: mniej kompresji przy każdej kopii,
# nieco gorszy stopień kompresji całości.
_ROWS_PER_CHUNK: Final = 64
_COMPRESSION_LEVEL: Final = 6
_MAX_TEXT: Final = 32767  # openpyxl przycina tekst komórki do tej długości

_CELL = re.compile(rb'<c r="([A-Z]{1,3})(\d+)"([^>]*?)(?:/>|>(.*?)</c>)', re.S)
_CELL_WITH_CONTENT = re.compile(rb'<c r="([A-Z]{1,3})\d+"[^>]*(?<!/)>(.*?)</c>', re.S)  # komórka z treścią
_STYLE = re.compile(rb'\ss="(\d+)"')
_TYPE = re.compile(rb'\st="(\w+)"')
_FORMULA = re.compile(rb"<f[\s>/]")
_NON_EMPTY_VALUE = re.compile(rb"<v(?:\s[^>]*)?>[^<]")
_VALUE = re.compile(rb"<v(?:\s[^>]*)?>([^<]*)</v>")
_ATTRIBUTE = re.compile(rb'([\w:.-]+)\s*=\s*(?:"([^"]*)"|\'([^\']*)\')')
_CALC_PR = re.compile(rb"<((?:[\w.-]+:)?)calcPr\b([^>]*?)(\s*/)?>")
_DIMENSION = re.compile(rb'<dimension ref="([A-Z]+\d+(?::[A-Z]+\d+)?)"')
_MERGE = re.compile(rb'<mergeCell ref="([^"]+)"')
_CELL_XFS = re.compile(rb"<cellXfs\b[^>]*>(.*?)</cellXfs>", re.S)
_XF = re.compile(rb"<xf\b[^>]*?(?:/>|>.*?</xf>)", re.S)
_NUM_FMT = re.compile(rb"<numFmt\b([^>]*?)/?>")
_NUM_FMT_ID = re.compile(rb'numFmtId="(\d+)"')
_CALC_FLAGS: Final = ((b"calcMode", b"auto"), (b"fullCalcOnLoad", b"1"), (b"forceFullCalc", b"1"))


@dataclass(frozen=True)
class _Part:
    """Część zip gotowa do przepisania: nagłówek i skompresowana treść."""

    name: bytes
    flags: int
    method: int
    dos_time: int
    dos_date: int
    crc: int
    size: int
    data: Sequence[bytes]

    @property
    def compressed_size(self) -> int:
        return sum(len(chunk) for chunk in self.data)


class Package:
    """Gotowe Rozliczenie pracownika: części zip do zapisania jednym przebiegiem."""

    def __init__(self, parts: Sequence[_Part]) -> None:
        self._parts = parts

    def write(self, out: IO[bytes]) -> None:
        central: list[bytes] = []
        offset = 0
        for part in self._parts:
            version = 20 if part.method == zipfile.ZIP_DEFLATED else 10
            fields = (part.flags, part.method, part.dos_time, part.dos_date, part.crc, part.compressed_size, part.size)
            local = struct.pack("<IHHHHHIIIHH", 0x04034B50, version, *fields, len(part.name), 0) + part.name
            out.write(local)
            for chunk in part.data:
                out.write(chunk)
            central.append(
                struct.pack("<IHHHHHHIIIHHHHHII", 0x02014B50, 20, version, *fields, len(part.name), 0, 0, 0, 0, 0, offset)
                + part.name
            )
            offset += len(local) + part.compressed_size
        directory = b"".join(central)
        out.write(directory)
        out.write(struct.pack("<IHHHHIIH", 0x06054B50, 0, 0, len(central), len(central), len(directory), offset, 0))


@dataclass(frozen=True)
class SheetLayout:
    """Gdzie w arkuszu są nagłówek, Wiersze danych, dane wejściowe i kolumny Wiersza danych (od 1)."""

    header_row: int
    first_data_row: int
    input_columns: int
    data_columns: int


class TemplateCopy:
    """Wzorzec wczytany raz; z niego powstaje dowolnie wiele kopii z Wierszami danych."""

    def __init__(
        self,
        parts: list[_Part | None],
        sheet: _Sheet,
        styles: _Styles,
        header: list[object],
        has_input_data: bool,
    ) -> None:
        self._parts = parts  # ``None``: miejsce arkusza albo stylów, składanych dla każdej kopii
        self._sheet = sheet
        self._styles = styles
        self.header = header
        """Wartości wiersza nagłówka w kolumnach danych wejściowych (od A), jak do sprawdzenia WYKONAWCA."""
        self.has_input_data = has_input_data
        """Wiersze danych Wzorca mają już wartość w kolumnach danych wejściowych; formuły nie są danymi."""

    @classmethod
    def of(cls, content: bytes, layout: SheetLayout) -> TemplateCopy:
        try:
            return _read_template(content, layout)
        except _READ_ERRORS as exc:
            raise UnsupportedShape(type(exc).__name__) from exc

    def with_rows(self, rows: Sequence[Sequence[object]]) -> Package:
        styles = _StyleAdditions(self._styles)
        sheet_part = self._sheet.with_rows(rows, styles)
        styles_part = self._styles.part(styles)
        return Package(
            [
                part if part is not None else sheet_part if index == self._sheet.index else styles_part
                for index, part in enumerate(self._parts)
            ]
        )


# --- wczytanie ---------------------------------------------------------------------------------


def _read_template(content: bytes, layout: SheetLayout) -> TemplateCopy:
    archive = zipfile.ZipFile(BytesIO(content))
    infos = archive.infolist()
    plain = {info.filename: archive.read(info) for info in infos}  # sprawdza CRC każdej części
    _require_well_formed_xml(plain)
    workbook_name = _office_document(plain)
    workbook_rels = _relationships(plain, workbook_name)
    workbook_xml = plain[workbook_name]
    sheet_name, date1904 = _active_sheet(workbook_xml, workbook_rels)
    styles_name = _target_of_type(workbook_rels, "/styles")
    strings_name = _target_of_type(workbook_rels, "/sharedStrings")
    if styles_name is None or styles_name not in plain:
        raise UnsupportedShape("styles")
    shared_strings = _shared_strings(plain[strings_name]) if strings_name in plain else []

    sheet_index = styles_index = -1
    parts: list[_Part | None] = []
    for index, info in enumerate(infos):
        if info.flag_bits & 0x1:
            raise UnsupportedShape("encrypted")
        if info.filename == sheet_name:
            sheet_index = index
            parts.append(None)
        elif info.filename == styles_name:
            styles_index = index
            parts.append(None)
        elif info.filename == workbook_name:
            parts.append(_compressed_part(info, _with_full_recalculation(workbook_xml)))
        else:
            parts.append(_unchanged_part(content, info, plain[info.filename]))
    if sheet_index < 0:
        raise UnsupportedShape("sheet")
    sheet = _Sheet(infos[sheet_index], sheet_index, plain[sheet_name], layout, epoch=MAC_EPOCH if date1904 else WINDOWS_EPOCH)
    styles = _Styles(infos[styles_index], plain[styles_name], _unchanged_part(content, infos[styles_index], plain[styles_name]))
    return TemplateCopy(parts, sheet, styles, sheet.header(shared_strings), sheet.has_input_data)


def _require_well_formed_xml(plain: dict[str, bytes]) -> None:
    """Każda część XML jest poprawnym XML-em; skoroszyt, którego nie przeczyta openpyxl, idzie dawną drogą.

    Kopia czyta arkusz tylko w miejscach, które zmienia, więc np. arkusz urwany za
    Wierszami danych przeszedłby niezauważony; dawna droga klasyfikuje go jak przy
    każdym otwarciu skoroszytu.
    """

    for name, data in plain.items():
        if name.endswith((".xml", ".rels")):
            expat.ParserCreate().Parse(data, True)


def _office_document(plain: dict[str, bytes]) -> str:
    for relationship in ElementTree.fromstring(plain["_rels/.rels"]).iter(_PACKAGE_REL):
        if relationship.get("Type", "").endswith("/officeDocument"):
            return relationship.get("Target", "").lstrip("/")
    raise UnsupportedShape("officeDocument")


def _relationships(plain: dict[str, bytes], part: str) -> dict[str, tuple[str, str]]:
    """Relacje części ``part``: identyfikator → (typ, ścieżka części w zip)."""

    folder, name = posixpath.split(part)
    rels = ElementTree.fromstring(plain[posixpath.join(folder, "_rels", f"{name}.rels")])
    found: dict[str, tuple[str, str]] = {}
    for relationship in rels.iter(_PACKAGE_REL):
        target = relationship.get("Target", "")
        if relationship.get("TargetMode") != "External":
            target = target.lstrip("/") if target.startswith("/") else posixpath.normpath(posixpath.join(folder, target))
        found[relationship.get("Id", "")] = (relationship.get("Type", ""), target)
    return found


def _target_of_type(relationships: dict[str, tuple[str, str]], suffix: str) -> str | None:
    return next((target for kind, target in relationships.values() if kind.endswith(suffix)), None)


def _active_sheet(workbook_xml: bytes, relationships: dict[str, tuple[str, str]]) -> tuple[str, bool]:
    """Część zip aktywnego arkusza (tak jak ``workbook.active`` w openpyxl) i czy skoroszyt liczy daty od 1904."""

    root = ElementTree.fromstring(workbook_xml)
    view = root.find(f"{_MAIN}bookViews/{_MAIN}workbookView")
    active = int(view.get("activeTab", "0")) if view is not None else 0
    sheets = root.findall(f"{_MAIN}sheets/{_MAIN}sheet")
    sheet = sheets[active]
    if sheet.get("state", "visible") != "visible":
        raise UnsupportedShape("hidden active sheet")
    kind, target = relationships[sheet.get(f"{{{_OFFICE_REL}}}id", "")]
    if not kind.endswith("/worksheet"):
        raise UnsupportedShape("chartsheet")
    properties = root.find(f"{_MAIN}workbookPr")
    date1904 = properties is not None and properties.get("date1904", "0").lower() in ("1", "true")
    return target, date1904


def _shared_strings(xml: bytes) -> list[str]:
    return [_plain_text(item) for item in ElementTree.fromstring(xml).iter(f"{_MAIN}si")]


def _plain_text(element: ElementTree.Element) -> str:
    """Tekst ``<si>`` albo ``<is>``: zwykły ``<t>`` albo przebiegi ``<r>``, bez transkrypcji fonetycznej."""

    texts: list[str] = []
    for child in element:
        local = child.tag.rsplit("}", 1)[-1]
        if local == "t":
            texts.append(child.text or "")
        elif local == "r":
            texts.extend(run.text or "" for run in child if run.tag.rsplit("}", 1)[-1] == "t")
    return "".join(texts)


def _with_full_recalculation(workbook_xml: bytes) -> bytes:
    """``calcPr`` z flagami przeliczania takimi jak przy zapisie przez openpyxl; pozostałe atrybuty bez zmian."""

    found = _CALC_PR.search(workbook_xml)
    if found is None:
        raise UnsupportedShape("calcPr")
    attributes = [(match.group(1), match.group(0)) for match in _ATTRIBUTE.finditer(found.group(2))]
    names = [name for name, _ in attributes]
    rendered = [
        next((name + b'="' + value + b'"' for flag, value in _CALC_FLAGS if flag == name), text)
        for name, text in attributes
    ]
    rendered += [flag + b'="' + value + b'"' for flag, value in _CALC_FLAGS if flag not in names]
    tag = b"<" + found.group(1) + b"calcPr " + b" ".join(rendered) + (b"/>" if found.group(3) else b">")
    return workbook_xml[: found.start()] + tag + workbook_xml[found.end() :]


def _dos_stamp(info: zipfile.ZipInfo) -> tuple[int, int]:
    year, month, day, hour, minute, second = info.date_time
    return hour << 11 | minute << 5 | second // 2, (year - 1980) << 9 | month << 5 | day


def _encoded_name(name: str) -> tuple[bytes, int]:
    try:
        return name.encode("ascii"), 0
    except UnicodeEncodeError:
        return name.encode("utf-8"), 0x800


def _unchanged_part(content: bytes, info: zipfile.ZipInfo, data: bytes) -> _Part:
    """Część bez zmian: skompresowana treść z zip Wzorca, a w nieobsługiwanej metodzie kompresji skompresowana na nowo."""

    if info.compress_type in (zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED):
        return _raw_part(content, info)
    return _compressed_part(info, data)


def _raw_part(content: bytes, info: zipfile.ZipInfo) -> _Part:
    """Część przepisana razem ze skompresowaną treścią z zip Wzorca."""

    header = struct.unpack("<IHHHHHIIIHH", content[info.header_offset : info.header_offset + 30])
    if header[0] != 0x04034B50:
        raise UnsupportedShape("local header")
    start = info.header_offset + 30 + header[9] + header[10]
    name, flags = _encoded_name(info.filename)
    dos_time, dos_date = _dos_stamp(info)
    data = content[start : start + info.compress_size]
    return _Part(name, flags, info.compress_type, dos_time, dos_date, info.CRC, info.file_size, [data])


def _compressed_part(info: zipfile.ZipInfo, data: bytes) -> _Part:
    name, flags = _encoded_name(info.filename)
    dos_time, dos_date = _dos_stamp(info)
    compressor = zlib.compressobj(_COMPRESSION_LEVEL, zlib.DEFLATED, -15)
    compressed = compressor.compress(data) + compressor.flush()
    return _Part(name, flags, zipfile.ZIP_DEFLATED, dos_time, dos_date, zlib.crc32(data), len(data), [compressed])


# --- arkusz ------------------------------------------------------------------------------------


_COLUMN_INDEX: dict[bytes, int] = {}


def _column(letters: bytes) -> int:
    index = _COLUMN_INDEX.get(letters)
    if index is None:
        index = _COLUMN_INDEX[letters] = column_index_from_string(letters.decode("ascii"))
    return index


class _Sheet:
    """XML aktywnego arkusza z indeksem wierszy i kawałkami skompresowanymi od granic wierszy."""

    def __init__(self, info: zipfile.ZipInfo, index: int, xml: bytes, layout: SheetLayout, *, epoch: datetime) -> None:
        self.index = index
        self._info = info
        self._xml = xml
        self._layout = layout
        self._epoch = epoch
        self._letters = [get_column_letter(column).encode("ascii") for column in range(1, layout.data_columns + 1)]
        try:
            data_start, data_end = sheet_data_bounds(xml)
            self._rows = sheet_rows(xml, data_start, data_end)
        except IrregularSheetData as exc:
            raise UnsupportedShape(str(exc)) from exc
        self._numbers = [row.number for row in self._rows]
        first = bisect_left(self._numbers, layout.first_data_row)
        self._data_start = self._rows[first].start if first < len(self._rows) else data_end
        self._first_data_index = first
        self._data_end = data_end
        self.has_input_data = _writable_data_rows_have_input(xml, self._data_start, data_end, layout)
        """Jak ``TemplateSheet.has_input_data``: niepusta wartość bez formuły w kolumnach danych wejściowych."""
        self._boundaries = [self._data_start] + [
            row.start for row in self._rows[first + _ROWS_PER_CHUNK :: _ROWS_PER_CHUNK]
        ]
        self._chunks: list[bytes] | None = None  # dopiero przy pierwszej kopii: Sprawdzanie ich nie potrzebuje
        dimension = _DIMENSION.search(xml, 0, data_start)
        self._dimension = None if dimension is None else (dimension.start(1), dimension.end(1), range_boundaries(dimension.group(1).decode("ascii")))

    def header(self, shared_strings: list[str]) -> list[object]:
        values: list[object] = [None] * self._layout.input_columns
        position = bisect_left(self._numbers, self._layout.header_row)
        if position == len(self._rows) or self._rows[position].number != self._layout.header_row:
            return values
        row = self._rows[position]
        for cell in _CELL.finditer(self._xml, row.start, row.end):
            column = _column(cell.group(1))
            if column <= self._layout.input_columns:
                values[column - 1] = _header_value(cell.group(3), cell.group(4), shared_strings)
        return values

    def with_rows(self, rows: Sequence[Sequence[object]], styles: _StyleAdditions) -> _Part:
        xml = self._xml
        first_row = self._layout.first_data_row
        last_row = first_row + len(rows) - 1
        existing = self._rows[self._first_data_index : bisect_right(self._numbers, last_row)]
        by_number = {row.number: row for row in existing}
        region_end = existing[-1].end if existing else self._data_start
        patched = [
            self._patched_row(by_number.get(first_row + index), first_row + index, values, styles)
            for index, values in enumerate(rows)
        ]
        chunk = bisect_left(self._boundaries, region_end)
        tail_start = self._boundaries[chunk] if chunk < len(self._boundaries) else len(xml)
        head = b"".join([self._prefix(last_row if rows else None), *patched, xml[region_end:tail_start]])
        compressor = zlib.compressobj(_COMPRESSION_LEVEL, zlib.DEFLATED, -15)
        if chunk < len(self._boundaries):
            if self._chunks is None:
                self._chunks = _compressed_chunks(xml, self._boundaries)
            compressed = [compressor.compress(head) + compressor.flush(zlib.Z_SYNC_FLUSH), *self._chunks[chunk:]]
        else:
            compressed = [compressor.compress(head) + compressor.flush()]
        crc = zlib.crc32(memoryview(xml)[tail_start:], zlib.crc32(head))
        name, flags = _encoded_name(self._info.filename)
        dos_time, dos_date = _dos_stamp(self._info)
        size = len(head) + len(xml) - tail_start
        return _Part(name, flags, zipfile.ZIP_DEFLATED, dos_time, dos_date, crc, size, compressed)

    def _prefix(self, last_row: int | None) -> bytes:
        """Arkusz do pierwszego Wiersza danych; ``dimension`` obejmuje wpisane wiersze, jeśli wcześniej nie obejmował."""

        prefix = self._xml[: self._data_start]
        if self._dimension is None or last_row is None:
            return prefix
        start, end, (min_column, min_row, max_column, max_row) = self._dimension
        covering = (
            min(min_column or 1, 1),
            min(min_row or 1, self._layout.first_data_row),
            max(max_column or 1, self._layout.data_columns),
            max(max_row or 1, last_row),
        )
        if covering == (min_column, min_row, max_column, max_row):
            return prefix
        reference = f"{get_column_letter(covering[0])}{covering[1]}:{get_column_letter(covering[2])}{covering[3]}"
        return prefix[:start] + reference.encode("ascii") + prefix[end:]

    def _patched_row(self, row: SheetRow | None, number: int, values: Sequence[object], styles: _StyleAdditions) -> bytes:
        cells: dict[int, bytes] = {}
        if row is None:
            start_tag = b'<row r="%d">' % number
        else:
            start_tag, cells = _split_row(self._xml[row.start : row.end], number)
        suffix = b"%d" % number
        written: list[tuple[int, bytes]] = []
        for column, value in enumerate(values[: self._layout.data_columns], start=1):
            written.append((column, self._cell(self._letters[column - 1] + suffix, cells.get(column), value, styles)))
        kept = [(column, cell) for column, cell in cells.items() if column > len(written)]
        return start_tag + b"".join(cell for _, cell in sorted(written + kept)) + b"</row>"

    def _cell(self, reference: bytes, existing: bytes | None, value: object, styles: _StyleAdditions) -> bytes:
        style_match = _STYLE.search(existing[: existing.index(b">")]) if existing is not None else None
        style = int(style_match.group(1)) if style_match else None
        if isinstance(value, str) and value[:_MAX_TEXT] == "":
            value = None
        if value is None:
            if existing is not None and existing.endswith(b"/>"):
                return existing
            return _cell_xml(reference, style, None, b"")
        if isinstance(value, (datetime, date, time, timedelta)):
            if getattr(value, "tzinfo", None) is not None:
                raise InvalidValue("strefa czasowa")
            if not is_date_format(styles.number_format(style)):
                style = styles.with_number_format(style, _date_format(value))
            serial: float = to_excel(value, self._epoch)  # type: ignore[no-untyped-call]
            return _cell_xml(reference, style, b"n", b"<v>" + _number(serial) + b"</v>")
        kind, content = _value_xml(value)
        return _cell_xml(reference, style, kind, content)


def _writable_data_rows_have_input(xml: bytes, data_start: int, data_end: int, layout: SheetLayout) -> bool:
    """Czy Wiersze danych mają już wartość w kolumnach danych wejściowych; jedno przejście po komórkach.

    Kolumny Wiersza danych od pierwszego Wiersza danych nie mogą mieć formuł ani
    scaleń: wpisanie wartości w taką komórkę zmienia ``calcChain`` albo wspólną
    formułę (formuła) lub nie jest możliwe (scalenie); to robi dawna droga przez
    openpyxl (``UnsupportedShape``). Formuły nie są danymi.
    """

    has_input = False
    for cell in _CELL_WITH_CONTENT.finditer(xml, data_start, data_end):
        column = _column(cell.group(1))
        if column > layout.data_columns:
            continue
        content = cell.group(2)
        if _FORMULA.search(content):
            raise UnsupportedShape("formula in data row")
        if not has_input and column <= layout.input_columns:
            has_input = b"<is" in content or _NON_EMPTY_VALUE.search(content) is not None
    for merged in _MERGE.finditer(xml, data_end):
        min_column, min_row, _max_column, max_row = range_boundaries(merged.group(1).decode("ascii"))
        if (min_column or 1) <= layout.data_columns and (max_row or min_row or 1) >= layout.first_data_row:
            raise UnsupportedShape("merged data rows")
    return has_input


def _compressed_chunks(xml: bytes, boundaries: list[int]) -> list[bytes]:
    """Kawałki od każdej granicy do następnej; po każdym pełne opróżnienie, więc kawałek nie sięga wstecz."""

    compressor = zlib.compressobj(_COMPRESSION_LEVEL, zlib.DEFLATED, -15)
    view = memoryview(xml)
    chunks: list[bytes] = []
    for index, start in enumerate(boundaries):
        last = index == len(boundaries) - 1
        end = len(xml) if last else boundaries[index + 1]
        chunks.append(compressor.compress(view[start:end]) + compressor.flush(zlib.Z_FINISH if last else zlib.Z_FULL_FLUSH))
    return chunks


def _split_row(row_xml: bytes, number: int) -> tuple[bytes, dict[int, bytes]]:
    """Znacznik otwierający wiersza i jego komórki według kolumny; inna treść wiersza to ``UnsupportedShape``."""

    tag_end = row_xml.index(b">")
    if row_xml[tag_end - 1 : tag_end] == b"/":
        return row_xml[: tag_end - 1].rstrip() + b">", {}
    body_start, body_end = tag_end + 1, len(row_xml) - len(b"</row>")
    cells: dict[int, bytes] = {}
    position = body_start
    previous = 0
    for cell in _CELL.finditer(row_xml, body_start, body_end):
        column = _column(cell.group(1))
        if row_xml[position : cell.start()].strip() or int(cell.group(2)) != number or column <= previous:
            raise UnsupportedShape("row content")
        cells[column] = cell.group(0)
        position, previous = cell.end(), column
    if row_xml[position:body_end].strip():
        raise UnsupportedShape("row content")
    return row_xml[: tag_end + 1], cells


def _header_value(attributes: bytes, content: bytes | None, shared_strings: list[str]) -> object:
    """Wartość komórki nagłówka na tyle, na ile potrzeba do sprawdzenia WYKONAWCA."""

    if not content:
        return None
    if _FORMULA.search(content):
        return "="
    kind = _TYPE.search(attributes)
    if kind is not None and kind.group(1) == b"inlineStr":
        return _plain_text(ElementTree.fromstring(content[content.index(b"<is") : content.rindex(b"</is>") + 5]))
    value = _VALUE.search(content)
    if value is None:
        return None
    text = html.unescape(value.group(1).decode("utf-8"))
    if kind is not None and kind.group(1) == b"s":
        return shared_strings[int(text)]
    return text


# --- wartości ----------------------------------------------------------------------------------


def _cell_xml(reference: bytes, style: int | None, kind: bytes | None, content: bytes) -> bytes:
    attributes = b'<c r="' + reference + b'"'
    if style is not None:
        attributes += b' s="%d"' % style
    if kind is not None:
        attributes += b' t="' + kind + b'"'
    return attributes + (b">" + content + b"</c>" if content else b"/>")


def _date_format(value: datetime | date | time | timedelta) -> str:
    """Format daty, który openpyxl nadaje komórce z datą bez formatu daty."""

    if isinstance(value, datetime):
        return FORMAT_DATE_DATETIME
    if isinstance(value, date):
        return FORMAT_DATE_YYYYMMDD2
    if isinstance(value, time):
        return FORMAT_DATE_TIME6
    return FORMAT_DATE_TIMEDELTA


def _number(value: int | float | Decimal) -> bytes:
    """Liczba jak w zapisie openpyxl (``safe_string``): 16 cyfr znaczących; NaN i nieskończoność są puste."""

    number = float(value)
    if math.isnan(number) or math.isinf(number):
        return b""
    return ("%.16g" % value).encode("ascii")


def _escaped(text: str) -> bytes:
    try:
        return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").encode("utf-8")
    except UnicodeEncodeError as exc:
        raise InvalidValue("kodowanie") from exc


def _value_xml(value: object) -> tuple[bytes | None, bytes]:
    """Typ i treść komórki dla wartości innej niż pusta i data, jak przy wpisaniu przez openpyxl."""

    if isinstance(value, bool):
        return b"b", b"<v>1</v>" if value else b"<v>0</v>"
    if isinstance(value, (int, float, Decimal)):
        return b"n", b"<v>" + _number(value) + b"</v>"
    if isinstance(value, str):
        text = value[:_MAX_TEXT]
        if ILLEGAL_CHARACTERS_RE.search(text):
            raise InvalidValue("znak niedozwolony w XML")
        if len(text) > 1 and text.startswith("="):
            return None, b"<f>" + _escaped(text[1:]) + b"</f>"
        if text in ERROR_CODES:
            return b"e", b"<v>" + _escaped(text) + b"</v>"
        space = b' xml:space="preserve"' if text != text.strip() else b""
        return b"inlineStr", b"<is><t" + space + b">" + _escaped(text) + b"</t></is>"
    raise UnsupportedShape(type(value).__name__)


# --- style -------------------------------------------------------------------------------------


class _Styles:
    """``xl/styles.xml`` Wzorca: formaty liczb stylów komórek i miejsca na dopisanie stylów dat."""

    def __init__(self, info: zipfile.ZipInfo, xml: bytes, unchanged: _Part) -> None:
        self._info = info
        self.xml = xml
        cell_xfs = _CELL_XFS.search(xml)
        if cell_xfs is None:
            raise UnsupportedShape("cellXfs")
        self.xfs = _XF.findall(cell_xfs.group(1))
        self.custom_formats: dict[int, str] = {}
        for number_format in _NUM_FMT.finditer(xml):
            attributes = {match.group(1): match.group(2) or match.group(3) or b"" for match in _ATTRIBUTE.finditer(number_format.group(1))}
            self.custom_formats[int(attributes[b"numFmtId"])] = html.unescape(attributes[b"formatCode"].decode("utf-8"))
        self._unchanged = unchanged

    def format_id(self, style: int) -> int:
        found = _NUM_FMT_ID.search(self.xfs[style][: self.xfs[style].index(b">")])
        return int(found.group(1)) if found else 0

    def part(self, additions: _StyleAdditions) -> _Part:
        if not additions.xfs:
            return self._unchanged
        xml = self.xml
        cell_xfs = _CELL_XFS.search(xml)
        assert cell_xfs is not None
        close = cell_xfs.end(1)
        xml = xml[:close] + b"".join(additions.xfs) + xml[close:]
        xml = _with_count(xml, b"cellXfs", len(self.xfs) + len(additions.xfs))
        if additions.formats:
            entries = b"".join(
                b'<numFmt numFmtId="%d" formatCode="' % number + html.escape(code).encode("utf-8") + b'"/>'
                for number, code in additions.formats
            )
            count = len(self.custom_formats) + len(additions.formats)
            block = re.search(rb"<numFmts\b[^>]*?(?:/>|>(.*?)</numFmts>)", xml, re.S)
            if block is None:
                root = re.search(rb"<styleSheet\b[^>]*>", xml)
                if root is None:
                    raise UnsupportedShape("styleSheet")
                xml = xml[: root.end()] + b'<numFmts count="%d">' % count + entries + b"</numFmts>" + xml[root.end() :]
            elif block.group(1) is None:
                xml = xml[: block.start()] + b'<numFmts count="%d">' % count + entries + b"</numFmts>" + xml[block.end() :]
            else:
                xml = xml[: block.end(1)] + entries + xml[block.end(1) :]
                xml = _with_count(xml, b"numFmts", count)
        return _compressed_part(self._info, xml)


def _with_count(xml: bytes, tag: bytes, count: int) -> bytes:
    start = re.search(rb"<" + tag + rb"\b[^>]*>", xml)
    assert start is not None
    opening = re.sub(rb'\scount="\d+"', b"", start.group(0))
    opening = opening[: len(tag) + 1] + b' count="%d"' % count + opening[len(tag) + 1 :]
    return xml[: start.start()] + opening + xml[start.end() :]


class _StyleAdditions:
    """Style komórek dopisane dla jednej kopii: komórka z datą bez formatu daty dostaje format jak w openpyxl."""

    def __init__(self, styles: _Styles) -> None:
        self._styles = styles
        self.xfs: list[bytes] = []
        self.formats: list[tuple[int, str]] = []
        self._added: dict[tuple[int | None, str], int] = {}

    def number_format(self, style: int | None) -> str:
        if style is None:
            return "General"
        if style >= len(self._styles.xfs):
            raise UnsupportedShape("style")
        number = self._styles.format_id(style)
        return self._styles.custom_formats.get(number) or BUILTIN_FORMATS.get(number, "General")

    def with_number_format(self, style: int | None, code: str) -> int:
        key = (style, code)
        if key not in self._added:
            number = self._format_id(code)
            if style is None:
                xf = b'<xf numFmtId="%d" fontId="0" fillId="0" borderId="0" xfId="0" applyNumberFormat="1"/>' % number
            else:
                xf = _with_number_format(self._styles.xfs[style], number)
            self._added[key] = len(self._styles.xfs) + len(self.xfs)
            self.xfs.append(xf)
        return self._added[key]

    def _format_id(self, code: str) -> int:
        if code in BUILTIN_FORMATS_REVERSE:
            return int(BUILTIN_FORMATS_REVERSE[code])
        known = {existing: number for number, existing in [*self._styles.custom_formats.items(), *self.formats]}
        if code in known:
            return known[code]
        number = max([163, *self._styles.custom_formats, *(added for added, _ in self.formats)]) + 1
        self.formats.append((number, code))
        return number


def _with_number_format(xf: bytes, number: int) -> bytes:
    tag_end = xf.index(b">")
    tag = xf[:tag_end]
    tag = re.sub(rb'\snumFmtId="\d+"', b"", tag)
    tag = re.sub(rb'\sapplyNumberFormat="\w+"', b"", tag)
    tag = tag.rstrip(b"/ ")
    closing = xf[tag_end:] if not xf[tag_end - 1 : tag_end] == b"/" else b"/>"
    return tag[:3] + b' numFmtId="%d"' % number + tag[3:] + b' applyNumberFormat="1"' + closing


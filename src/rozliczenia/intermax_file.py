"""INTERMAX (Rejestr zleceń) w Uporządkowaniu INTERMAX: fakty arkusza zleceń i zapis dnia podmianą wierszy XML.

``Register.read`` czyta bajty INTERMAX przez jedyne miejsce odczytu bajtów skoroszytu (``workbook_files``) i
znajduje arkusze zleceń po nagłówkach z wiersza 1, tak jak Przygotowanie pliku zbiorczego (``COLUMNS``), z
kolumnami ``AKCJE`` i ``UWAGI``. Arkusz zleceń daje swoje wiersze od dołu jako fakty (``raw_orders.RowFacts``),
bez openpyxl: ~42 tys. wierszy taty to dziesiątki MB XML, a rozpoznanie potrzebuje tylko dołu arkusza.

``save`` zapisuje plan dnia (ADR 0019, wzorem kopii Wzorca z ADR 0008). Zmieniają się tylko:

- w XML arkusza zleceń wiersze pod wierszem, pod którym staje dzień (``RawBlock.anchor``): wiersz zlecenia
  dostaje komórki Surowego zlecenia (w przesuniętym pierwszym wierszu o dwie kolumny w prawo), w kolumnach od
  ``AKCJE`` do ``UWAGI`` z wyglądem reszty INTERMAX, a za ``UWAGI`` takie, jak przyszły; pusty wiersz, który był
  pusty, zostaje bajt w bajt, a wiersz, z którego zlecenie odeszło, znika;
- ``ref`` Hiperłączy z tych wierszy, które idą razem ze swoją komórką, i ``<dimension>``, gdy dzień sięga dalej;
- w ``xl/styles.xml`` czcionki, obramowanie i style komórek dopisane na końcu swoich list.

Każda inna część pliku i każdy bajt nad tymi wierszami zostają. Arkusz, w którego zmienianych wierszach jest
formuła albo zakres (scalenie, formatowanie warunkowe, sprawdzanie poprawności, autofiltr, Hiperłącze na kilka
komórek), to ``UnsupportedShape``. Wynik trafia do pliku tymczasowego obok INTERMAX, zostaje odczytany jeszcze
raz i porównany z oryginałem; różnica to ``WriteMismatch``, a INTERMAX zostaje nietknięty. Dopiero po zgodnym
sprawdzeniu ``before_replace`` (Kopia INTERMAX) i atomowa podmiana.
"""

from __future__ import annotations

import html
import re
import zipfile
from collections.abc import Callable, Iterator, Sequence
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path
from typing import Any, Final, cast
from xml.etree import ElementTree

from openpyxl.styles.borders import Border
from openpyxl.styles.fonts import Font
from openpyxl.styles.numbers import BUILTIN_FORMATS, is_date_format
from openpyxl.utils.cell import column_index_from_string, get_column_letter, range_boundaries
from openpyxl.utils.datetime import MAC_EPOCH, WINDOWS_EPOCH, from_excel

from . import workbook_files
from .preparation_register import COLUMNS, DATE, WORKER
from .raw_orders import SHIFT, CellFacts, DayPlan, OrderColumns, RawBlock, RowFacts
from .row_look import BORDER
from .workbook_files import WorkbookError, header_columns, is_blank
from .workbook_parts import MAIN, OFFICE_REL, IrregularSheetData, SheetData, office_document, relationships
from .workbook_save import write_atomically
from .worker_config import normalize_text

__all__ = ["OrderSheet", "Register", "UnsupportedShape", "WriteMismatch", "save"]

_FIRST: Final = "AKCJE"
_LAST: Final = "UWAGI"
_DATE_FORMAT: Final = 22  # m/d/yy h:mm, format daty uporządkowanych dni
_FACE: Final = "Calibri"
_SIZE: Final = 8
_WORKER_SIZE: Final = 9
_BLACK: Final = "FF000000"
_YELLOW: Final = "FFFF00"

_CELL = re.compile(rb'<c r="([A-Z]{1,3})(\d+)"([^>]*?)(?:/>|>(.*?)</c>)', re.S)
_STYLE = re.compile(rb'\ss="(\d+)"')
_TYPE = re.compile(rb'\st="(\w+)"')
_VALUE = re.compile(rb"<v(?:\s[^>]*)?>([^<]*)</v>")
_TEXT = re.compile(rb"<t(?:\s[^>]*)?>([^<]*)</t>")
_FORMULA = re.compile(rb"<f[\s>/]")
_DIMENSION = re.compile(rb'<dimension ref="([^"]*)"\s*/>')
_HYPERLINK_REF = re.compile(rb'(<hyperlink\b[^>]*?\sref=")([^"]*)(")')
_HYPERLINKS = re.compile(rb"<hyperlinks>.*?</hyperlinks>", re.S)
_RANGES = re.compile(rb'\s(?:ref|sqref)="([^"]*)"')
_STYLE_LISTS: Final = (b"numFmts", b"fonts", b"fills", b"borders", b"cellXfs")


class UnsupportedShape(Exception):
    """Arkusz zleceń ma w zmienianych wierszach kształt, którego zapis nie przenosi (formuła, zakres)."""


class WriteMismatch(Exception):
    """Plik zapisany przed podmianą różni się od oryginału czymś więcej niż uporządkowanym dniem."""


@dataclass(frozen=True)
class _Styles:
    """Style komórek z ``xl/styles.xml``: format liczby, czcionka i wypełnienie każdego stylu."""

    number_formats: tuple[int, ...]
    faces: tuple[tuple[str | None, float | None], ...]
    yellow: tuple[bool, ...]
    date_formats: frozenset[int]
    fonts: tuple[Font, ...]
    borders: tuple[Border, ...]
    xfs: tuple[bytes, ...]

    @classmethod
    def of(cls, xml: bytes) -> _Styles:
        root = ElementTree.fromstring(xml)
        codes = {int(item.get("numFmtId", "0")): item.get("formatCode", "") for item in root.iter(f"{MAIN}numFmt")}
        fonts = [Font.from_tree(cast(Any, font)) for font in root.iterfind(f"{MAIN}fonts/{MAIN}font")]
        borders = [Border.from_tree(cast(Any, border)) or Border() for border in root.iterfind(f"{MAIN}borders/{MAIN}border")]
        fills = [_is_yellow(fill) for fill in root.iterfind(f"{MAIN}fills/{MAIN}fill")]
        xfs = list(root.iterfind(f"{MAIN}cellXfs/{MAIN}xf"))
        block = re.search(rb"<cellXfs\b[^>]*>(.*?)</cellXfs>", xml, re.S)
        raw_xfs = re.findall(rb"<xf\b[^>]*?(?:/>|>.*?</xf>)", block.group(1), re.S) if block else []
        number_formats = tuple(int(xf.get("numFmtId", "0")) for xf in xfs)
        return cls(
            number_formats=number_formats,
            faces=tuple(_face(fonts[int(xf.get("fontId", "0"))]) for xf in xfs),
            yellow=tuple(fills[int(xf.get("fillId", "0"))] for xf in xfs),
            date_formats=frozenset(
                number for number in number_formats if is_date_format(codes.get(number) or BUILTIN_FORMATS.get(number, ""))
            ),
            fonts=tuple(fonts),
            borders=tuple(borders),
            xfs=tuple(raw_xfs),
        )


def _face(font: Font) -> tuple[str | None, float | None]:
    return font.name, None if font.sz is None else float(font.sz)


def _is_yellow(fill: ElementTree.Element) -> bool:
    pattern = fill.find(f"{MAIN}patternFill")
    color = None if pattern is None else pattern.find(f"{MAIN}fgColor")
    solid = pattern is not None and pattern.get("patternType") == "solid"
    return solid and color is not None and color.get("rgb", "").upper().endswith(_YELLOW)


@dataclass(frozen=True)
class _Cell:
    column: int
    attributes: bytes
    content: bytes | None

    @property
    def style(self) -> int:
        found = _STYLE.search(self.attributes)
        return int(found.group(1)) if found else 0

    @property
    def kind(self) -> bytes | None:
        found = _TYPE.search(self.attributes)
        return found.group(1) if found else None

    def xml(self, column: int, row: int, attributes: bytes | None = None) -> bytes:
        reference = get_column_letter(column).encode("ascii") + b"%d" % row
        attributes = self.attributes if attributes is None else attributes
        if self.content is None:
            return b'<c r="' + reference + b'"' + attributes + b"/>"
        return b'<c r="' + reference + b'"' + attributes + b">" + self.content + b"</c>"


def _cells(row_xml: bytes) -> list[_Cell]:
    return [
        _Cell(column_index_from_string(found.group(1).decode("ascii")), found.group(3), found.group(4))
        for found in _CELL.finditer(row_xml)
    ]


@dataclass(frozen=True)
class OrderSheet:
    """Arkusz zleceń INTERMAX: nazwa, część zip i kolumny po nagłówkach z wiersza 1."""

    name: str
    part: str
    columns: OrderColumns
    _register: Register

    def rows_from_bottom(self) -> Iterator[RowFacts]:
        """Wiersze arkusza od ostatniego do drugiego jako fakty dla rozpoznania Surowych zleceń."""

        sheet = self._register._sheet(self.part)
        for row in reversed(sheet.data.rows):
            if row.number < 2:
                return
            yield self._register._facts(row.number, _cells(sheet.xml[row.start : row.end]))


@dataclass(frozen=True)
class _SheetXml:
    xml: bytes
    data: SheetData


class Register:
    """INTERMAX odczytany raz: bajty, części zip, style, teksty wspólne i arkusze zleceń."""

    def __init__(self, path: Path, content: bytes) -> None:
        self.path = path
        self.content = content
        with workbook_files.unreadable_as_error(path):
            archive = zipfile.ZipFile(BytesIO(content))
            self._infos = archive.infolist()
            self._parts = {info.filename: archive.read(info) for info in self._infos}
            workbook = office_document(self._parts) or ""
            rels = relationships(self._parts, workbook)
            root = ElementTree.fromstring(self._parts[workbook])
            styles_part = next(rel.target for rel in rels.values() if rel.kind.endswith("/styles"))
            self._styles_part = styles_part
            self._styles = _Styles.of(self._parts[styles_part])
            strings = next((rel.target for rel in rels.values() if rel.kind.endswith("/sharedStrings")), None)
            self._shared = _shared_strings(self._parts[strings]) if strings else []
            properties = root.find(f"{MAIN}workbookPr")
            self._epoch = MAC_EPOCH if properties is not None and properties.get("date1904") in ("1", "true") else WINDOWS_EPOCH
            self._sheets: dict[str, _SheetXml] = {}
            sheets = [
                (sheet.get("name", ""), rels[sheet.get(f"{{{OFFICE_REL}}}id", "")].target)
                for sheet in root.iter(f"{MAIN}sheet")
            ]
            self.order_sheets = [
                OrderSheet(name, part, columns, self)
                for name, part in sheets
                if (columns := self._order_columns(part)) is not None
            ]

    @classmethod
    def read(cls, path: Path) -> Register:
        """INTERMAX z dysku; ``WorkbookError``, gdy go nie ma, jest otwarty w Excelu, niedostępny albo nieczytelny."""

        return cls(path, workbook_files.workbook_content(path))

    def _sheet(self, part: str) -> _SheetXml:
        if part not in self._sheets:
            xml = self._parts[part]
            try:
                self._sheets[part] = _SheetXml(xml, SheetData.of(xml))
            except IrregularSheetData as error:
                raise UnsupportedShape(str(error)) from error
        return self._sheets[part]

    def _order_columns(self, part: str) -> OrderColumns | None:
        xml = self._parts[part]
        start = xml.find(b'<row r="1"')
        tag_end = xml.find(b">", start)
        if start < 0 or xml[tag_end - 1 : tag_end] == b"/":
            return None
        cells = _cells(xml[start : xml.index(b"</row>", tag_end)])
        header: list[object] = [None] * max((cell.column for cell in cells), default=0)
        for cell in cells:
            header[cell.column - 1] = self._value(cell)
        found = header_columns(header)
        named = {
            column.target_header: next((found[name] for name in map(normalize_text, column.register_headers) if name in found), None)
            for column in COLUMNS
        }
        first, last = found.get(normalize_text(_FIRST)), found.get(normalize_text(_LAST))
        if first is None or last is None or None in named.values():
            return None
        return OrderColumns(first, cast(int, named[DATE.target_header]), cast(int, named[WORKER.target_header]), last)

    def _value(self, cell: _Cell) -> object:
        """Wartość komórki jak w openpyxl (tekst, liczba, data, prawda/fałsz), ``None`` dla pustej."""

        content = cell.content or b""
        kind = cell.kind
        if kind == b"inlineStr":
            text: object = html.unescape(b"".join(_TEXT.findall(content)).decode("utf-8"))
        else:
            found = _VALUE.search(content)
            if found is None:
                return None
            raw = found.group(1).decode("utf-8")
            if kind == b"s":
                text = self._shared[int(raw)]
            elif kind in (b"str", b"e"):
                text = html.unescape(raw)
            elif kind == b"b":
                return raw == "1"
            else:
                number = float(raw)
                if self._styles.number_formats[cell.style] in self._styles.date_formats:
                    return from_excel(number, self._epoch)
                return number
        return None if is_blank(text) else text

    def _facts(self, number: int, cells: Sequence[_Cell]) -> RowFacts:
        styles = self._styles
        return RowFacts(
            number,
            {
                cell.column: CellFacts(self._value(cell), styles.faces[cell.style], styles.yellow[cell.style])
                for cell in cells
            },
        )

    def ordered(self, sheet: OrderSheet, block: RawBlock, plan: DayPlan) -> bytes:
        """Bajty INTERMAX z uporządkowanym dniem; ``UnsupportedShape``, gdy arkusza nie da się tak zapisać."""

        xml = self._sheet(sheet.part)
        looks = _Looks(self._styles, sheet.columns)
        sheet_xml = _ordered_sheet(xml, sheet.columns, block, plan, looks)
        parts = {sheet.part: sheet_xml, self._styles_part: looks.styles(self._parts[self._styles_part])}
        out = BytesIO()
        with zipfile.ZipFile(out, "w") as target:
            for info in self._infos:
                copied = zipfile.ZipInfo(info.filename, info.date_time)
                copied.compress_type = info.compress_type
                copied.external_attr = info.external_attr
                target.writestr(copied, parts.get(info.filename, self._parts[info.filename]))
        return out.getvalue()

    def check(self, written: bytes, sheet: OrderSheet, block: RawBlock, plan: DayPlan) -> None:
        """``WriteMismatch``, gdy ``written`` różni się od INTERMAX czymś więcej niż dniem z ``plan``."""

        try:
            with zipfile.ZipFile(BytesIO(written)) as archive:
                names = [info.filename for info in archive.infolist()]
                parts = {name: archive.read(name) for name in names}
        except (zipfile.BadZipFile, KeyError, OSError, ValueError) as error:
            raise WriteMismatch("zip") from error
        if names != [info.filename for info in self._infos]:
            raise WriteMismatch("części")
        for name in names:
            if name not in (sheet.part, self._styles_part) and parts[name] != self._parts[name]:
                raise WriteMismatch(name)
        if not _styles_kept(self._parts[self._styles_part], parts[self._styles_part]):
            raise WriteMismatch("style")
        _check_sheet(self._sheet(sheet.part), parts[sheet.part], sheet.columns, block, plan)


def _shared_strings(xml: bytes) -> list[str]:
    """Teksty wspólne bez podpowiedzi wymowy (``rPh``): zwykły tekst albo tekst każdego fragmentu."""

    return [
        "".join(text.text or "" for text in [*item.iterfind(f"{MAIN}t"), *item.iterfind(f"{MAIN}r/{MAIN}t")])
        for item in ElementTree.fromstring(xml).iterfind(f"{MAIN}si")
    ]


class _Looks:
    """Style wyglądu reszty INTERMAX dla kolumn zlecenia, dopisane do ``xl/styles.xml`` tylko raz każdy."""

    def __init__(self, styles: _Styles, columns: OrderColumns) -> None:
        self._styles = styles
        self._columns = columns
        self._fonts: list[Font] = []
        self._borders: list[Border] = []
        self._xfs: list[bytes] = []
        self._ids: dict[tuple[int, int], int] = {}

    def style(self, column: int, number_format: int) -> int:
        """Styl komórki kolumny zlecenia ``column``: Calibri 8 (WYKONAWCA 9), czarna, cienka ramka, do lewej i środka."""

        if column == self._columns.date:
            number_format = _DATE_FORMAT
        size = _WORKER_SIZE if column == self._columns.worker else _SIZE
        key = (size, number_format)
        if key not in self._ids:
            font = _index(self._styles.fonts, self._fonts, Font(name=_FACE, sz=size, color=_BLACK, family=2))
            border = _index(self._styles.borders, self._borders, BORDER)
            xf = (
                b'<xf numFmtId="%d" fontId="%d" fillId="0" borderId="%d" xfId="0" applyNumberFormat="1" applyFont="1" '
                b'applyFill="1" applyBorder="1" applyAlignment="1"><alignment horizontal="left" vertical="center"/></xf>'
                % (number_format, font, border)
            )
            if xf in self._styles.xfs:
                self._ids[key] = self._styles.xfs.index(xf)
            else:
                self._xfs.append(xf)
                self._ids[key] = len(self._styles.xfs) + len(self._xfs) - 1
        return self._ids[key]

    def number_format(self, style: int) -> int:
        return self._styles.number_formats[style]

    def styles(self, xml: bytes) -> bytes:
        styles = self._styles
        xml = _appended(xml, b"fonts", [ElementTree.tostring(font.to_tree()) for font in self._fonts], len(styles.fonts))
        borders = [ElementTree.tostring(border.to_tree()) for border in self._borders]
        xml = _appended(xml, b"borders", borders, len(styles.borders))
        return _appended(xml, b"cellXfs", self._xfs, len(styles.xfs))


def _index(existing: Sequence[object], added: list[Any], item: object) -> int:
    if item in existing:
        return list(existing).index(item)
    if item not in added:
        added.append(item)
    return len(existing) + added.index(item)


def _appended(xml: bytes, tag: bytes, entries: Sequence[bytes], existing: int) -> bytes:
    """``entries`` na końcu listy ``tag`` (``existing`` pozycji) w ``xl/styles.xml`` z licznikiem ``count``."""

    if not entries:
        return xml
    block = re.search(rb"<" + tag + rb"\b([^>]*)>(.*?)</" + tag + rb">", xml, re.S)
    if block is None:
        raise UnsupportedShape(tag.decode("ascii"))
    count = existing + len(entries)
    attributes = re.sub(rb'\scount="\d+"', b"", block.group(1))
    opening = b"<" + tag + b' count="%d"' % count + attributes + b">"
    return xml[: block.start()] + opening + block.group(2) + b"".join(entries) + b"</" + tag + b">" + xml[block.end() :]


def _ordered_sheet(sheet: _SheetXml, columns: OrderColumns, block: RawBlock, plan: DayPlan, looks: _Looks) -> bytes:
    xml, data = sheet.xml, sheet.data
    region = [row for row in data.rows if row.number > block.anchor]
    by_number = {row.number: row for row in region}
    raw = {order.row for order in block.orders}
    tail_at = data.end + len(b"</sheetData>")
    _require_writable(xml[tail_at:], block.anchor)
    for number in raw:
        if _FORMULA.search(xml, by_number[number].start, by_number[number].end):
            raise UnsupportedShape("formuła")
    placed = {placement.row: placement for placement in plan.placements}
    last = max([*placed, *(row.number for row in region)])
    rows: list[bytes] = []
    widest = 0
    for number in range(block.anchor + 1, last + 1):
        placement = placed.get(number)
        if placement is not None:
            source = by_number[placement.order.row]
            row_xml, right = _order_row(xml[source.start : source.end], number, placement.order.shifted, columns, looks)
            rows.append(row_xml)
            widest = max(widest, right)
        elif number in by_number and number not in raw:
            rows.append(xml[by_number[number].start : by_number[number].end])
    start = region[0].start if region else data.end
    end = data.rows[-1].end if data.rows else data.end
    head = _with_dimension(xml[:start], last, widest)
    return head + b"".join(rows) + xml[end:tail_at] + _moved_hyperlinks(xml[tail_at:], block, plan)


def _order_row(row_xml: bytes, number: int, shifted: bool, columns: OrderColumns, looks: _Looks) -> tuple[bytes, int]:
    """Wiersz zlecenia ``number`` z komórek Surowego zlecenia i najdalsza kolumna z komórką."""

    offset = SHIFT if shifted else 0
    written: dict[int, bytes] = {}
    for cell in _cells(row_xml):
        column = cell.column + offset
        if columns.first <= column <= columns.last:
            style = looks.style(column, looks.number_format(cell.style))
            attributes = _STYLE.sub(b"", cell.attributes) + b' s="%d"' % style
            written[column] = cell.xml(column, number, attributes)
        else:
            written[column] = cell.xml(column, number)
    for column in range(columns.first, columns.last + 1):
        if column not in written:
            written[column] = _Cell(column, b"", None).xml(column, number, b' s="%d"' % looks.style(column, 0))
    return b'<row r="%d">' % number + b"".join(written[column] for column in sorted(written)) + b"</row>", max(written)


def _with_dimension(head: bytes, last_row: int, last_column: int) -> bytes:
    found = _DIMENSION.search(head)
    if found is None:
        return head
    min_col, min_row, max_col, max_row = range_boundaries(found.group(1).decode("ascii"))
    if (max_row or 0) >= last_row and (max_col or 0) >= last_column:
        return head
    reference = f"{get_column_letter(min_col or 1)}{min_row or 1}:{get_column_letter(max(max_col or 1, last_column))}{max(max_row or 1, last_row)}"
    return head[: found.start(1)] + reference.encode("ascii") + head[found.end(1) :]


def _require_writable(tail: bytes, anchor: int) -> None:
    """Zakresy za ``sheetData`` (poza Hiperłączami) nie sięgają wierszy pod ``anchor``."""

    for found in _RANGES.finditer(_HYPERLINKS.sub(b"", tail)):
        for reference in found.group(1).decode("ascii").split():
            _, _, _, max_row = range_boundaries(reference)
            if max_row is None or max_row > anchor:
                raise UnsupportedShape("zakres")


def _moves(block: RawBlock, plan: DayPlan) -> dict[int, tuple[int, int]]:
    """Wiersz Surowego zlecenia → (przesunięcie kolumn, docelowy wiersz)."""

    return {placement.order.row: (SHIFT if placement.order.shifted else 0, placement.row) for placement in plan.placements}


def _moved_hyperlinks(tail: bytes, block: RawBlock, plan: DayPlan) -> bytes:
    moves = _moves(block, plan)

    def moved(found: re.Match[bytes]) -> bytes:
        reference = found.group(2).decode("ascii")
        min_col, min_row, max_col, max_row = range_boundaries(reference)
        if min_row is None or min_row <= block.anchor:
            return found.group(0)
        if (min_col, min_row) != (max_col, max_row) or min_row not in moves or min_col is None:
            raise UnsupportedShape("Hiperłącze")
        offset, row = moves[min_row]
        return found.group(1) + f"{get_column_letter(min_col + offset)}{row}".encode("ascii") + found.group(3)

    return _HYPERLINK_REF.sub(moved, tail)


def _styles_kept(original: bytes, written: bytes) -> bool:
    """Arkusz stylów ``written`` to ``original`` z wpisami dopisanymi tylko na końcu list."""

    for tag in _STYLE_LISTS:
        pattern = re.compile(rb"<" + tag + rb"\b[^>]*>(.*?)</" + tag + rb">", re.S)
        before, after = pattern.search(original), pattern.search(written)
        if before is None or after is None:
            if before is not after:
                return False
            continue
        if not after.group(1).startswith(before.group(1)):
            return False
        written = written[: after.start()] + before.group(0) + written[after.end() :]
    return written == original


def _check_sheet(original: _SheetXml, written: bytes, columns: OrderColumns, block: RawBlock, plan: DayPlan) -> None:
    try:
        data = SheetData.of(written)
    except IrregularSheetData as error:
        raise WriteMismatch("arkusz") from error
    xml, before = original.xml, original.data
    start = next((row.start for row in before.rows if row.number > block.anchor), before.end)
    new_start = next((row.start for row in data.rows if row.number > block.anchor), data.end)
    if _DIMENSION.sub(b"", xml[:start]) != _DIMENSION.sub(b"", written[:new_start]):
        raise WriteMismatch("wiersze nad dniem")
    tail, new_tail = xml[before.end :], written[data.end :]
    if _moved_hyperlinks(tail, block, plan) != new_tail:
        raise WriteMismatch("ogon arkusza")
    rows = {row.number: row for row in data.rows if row.number > block.anchor}
    sources = {row.number: row for row in before.rows}
    placed = {placement.row: placement for placement in plan.placements}
    for number, row in rows.items():
        cells = _cells(written[row.start : row.end])
        valued = {cell.column: cell for cell in cells if _has_value(cell)}
        placement = placed.get(number)
        if placement is None:
            if valued:
                raise WriteMismatch(f"wiersz {number}")
            continue
        source = sources[placement.order.row]
        offset = SHIFT if placement.order.shifted else 0
        expected = {cell.column + offset: cell for cell in _cells(xml[source.start : source.end])}
        if {column for column, cell in expected.items() if _has_value(cell)} != set(valued):
            raise WriteMismatch(f"wiersz {number}")
        found = {cell.column: cell for cell in cells}
        for column, cell in expected.items():
            new = found.get(column)
            if new is None or new.content != cell.content or new.kind != cell.kind:
                raise WriteMismatch(f"wiersz {number}")
            if not columns.first <= column <= columns.last and new.attributes != cell.attributes:
                raise WriteMismatch(f"wiersz {number}")
    if set(placed) - set(rows):
        raise WriteMismatch("brak zlecenia")


def _has_value(cell: _Cell) -> bool:
    content = cell.content or b""
    return _VALUE.search(content) is not None or b"<is>" in content


def save(
    register: Register,
    sheet: OrderSheet,
    block: RawBlock,
    plan: DayPlan,
    *,
    store: Callable[[Path, bytes], None],
    before_replace: Callable[[], None],
) -> None:
    """Zapisuje dzień w INTERMAX: plik tymczasowy obok, sprawdzenie zapisu, ``before_replace`` i atomowa podmiana.

    ``store`` zapisuje bajty pliku tymczasowego. ``WriteMismatch``, ``UnsupportedShape`` albo wyjątek z
    ``before_replace`` zostawiają INTERMAX nietknięty i bez pliku tymczasowego; nieudana podmiana to
    ``WorkbookSaveError``.
    """

    content = register.ordered(sheet, block, plan)

    def write(temporary: Path) -> None:
        store(temporary, content)
        try:
            written = workbook_files.workbook_content(temporary)
        except WorkbookError as error:
            raise WriteMismatch("odczyt") from error
        register.check(written, sheet, block, plan)
        before_replace()

    write_atomically(register.path, write)

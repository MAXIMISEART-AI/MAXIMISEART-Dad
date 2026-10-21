"""Hiperłącza komórek: adres poza skoroszytem, który komórka otwiera po kliknięciu (GLOSSARY „Hiperłącze”).

Przygotowanie pliku zbiorczego przenosi je z komórek Rejestru zleceń do obu
plików okresu, a Przebieg rozliczeń z każdej komórki A:AT Wiersza danych Pliku
zbiorczego do tej samej komórki Rozliczenia pracownika. Każdy zapis zastępuje
nimi hiperłącza komórek Wzorca w zapisywanych wierszach.

``read_sheet_hyperlinks`` czyta Hiperłącza jednego arkusza z bajtów skoroszytu:
blok ``<hyperlinks>``, który w schemacie arkusza leży za ``</sheetData>``, i
relacje arkusza, bez parsowania wierszy. Skoroszyt otwarty przez openpyxl tylko
do odczytu (Plik zbiorczy, Rejestr zleceń) hiperłączy nie daje.

Hiperłączem jest tylko odnośnik ``r:id`` do relacji ``…/hyperlink`` z
``TargetMode="External"``; jego adres to ``Target``, a przy ``location`` także
``#location``. Odnośnik do miejsca w tym samym skoroszycie (samo ``location``),
brak części relacji albo brak relacji o tym ``Id`` nie dają Hiperłącza. Zakres
``F18:F20`` daje Hiperłącze każdej komórce, a przy kilku odnośnikach do jednej
komórki wygrywa ostatni w pliku, jak w openpyxl. Komórka bez wartości nie niesie
Hiperłącza: openpyxl wpisałby adres jako jej wartość.

Adres to treść wiersza (np. numer sprawy klienta), więc ``repr`` go nie pokazuje.
"""

from __future__ import annotations

import posixpath
import re
import zipfile
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Final
from xml.etree import ElementTree

from openpyxl.utils.cell import range_boundaries

_MAIN: Final = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
_OFFICE_REL: Final = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
_PACKAGE_REL: Final = "{http://schemas.openxmlformats.org/package/2006/relationships}Relationship"
_ROOT: Final = re.compile(rb"<((?:[\w.-]+:)?)worksheet\b[^>]*>")
_BLOCK: Final = re.compile(rb"<((?:[\w.-]+:)?)hyperlinks\b[^>]*?(/?)>")
_LAST_ROW: Final = 1_048_576
_LAST_COLUMN: Final = 16_384


@dataclass(frozen=True)
class Hyperlink:
    """Hiperłącze komórki: adres poza skoroszytem."""

    address: str = field(repr=False)


_NONE: Final[Mapping[int, Hyperlink]] = MappingProxyType({})


@dataclass(frozen=True)
class _Range:
    min_column: int
    min_row: int
    max_column: int
    max_row: int
    order: int
    link: Hyperlink


class SheetHyperlinks:
    """Hiperłącza jednego arkusza: pojedyncze komórki po wierszu, zakresy po granicach, z kolejnością w pliku."""

    def __init__(self, cells: dict[int, dict[int, tuple[int, Hyperlink]]], ranges: list[_Range]) -> None:
        self._cells = cells
        self._ranges = ranges

    def row(self, number: int, values: Sequence[object]) -> Mapping[int, Hyperlink]:
        """Hiperłącza wiersza ``number`` o wartościach ``values`` (od kolumny A): kolumna od 1 → Hiperłącze."""

        found = self._cells.get(number)
        if found is None and not self._ranges:
            return _NONE
        candidates = dict(found or {})
        for span in self._ranges:
            if span.min_row <= number <= span.max_row:
                for column in range(span.min_column, min(span.max_column, len(values)) + 1):
                    if column not in candidates or candidates[column][0] < span.order:
                        candidates[column] = (span.order, span.link)
        links = {
            column: link
            for column, (_, link) in candidates.items()
            if column <= len(values) and values[column - 1] not in (None, "")
        }
        return links or _NONE


NO_HYPERLINKS: Final = SheetHyperlinks({}, [])


def read_sheet_hyperlinks(archive: zipfile.ZipFile, sheet_title: str) -> SheetHyperlinks:
    """Hiperłącza arkusza ``sheet_title`` skoroszytu ``archive``.

    Zepsuty XML bloku albo relacji to ``ElementTree.ParseError``, brakująca część skoroszytu ``KeyError``.
    """

    part = _sheet_part(archive, sheet_title)
    xml = archive.read(part)
    root = _ROOT.search(xml)
    block = _BLOCK.search(xml, max(xml.rfind(b"sheetData"), 0))
    if root is None or block is None or block.group(2):
        return NO_HYPERLINKS
    closing = b"</" + block.group(1) + b"hyperlinks>"
    end = xml.find(closing, block.end())
    if end < 0:
        raise ElementTree.ParseError("hyperlinks")
    document = root.group(0) + xml[block.start() : end + len(closing)] + b"</" + root.group(1) + b"worksheet>"
    elements = ElementTree.fromstring(document).iter(f"{_MAIN}hyperlink")
    targets = _external_hyperlinks(archive, part)
    cells: dict[int, dict[int, tuple[int, Hyperlink]]] = {}
    ranges: list[_Range] = []
    for order, element in enumerate(elements):
        target = targets.get(element.get(f"{{{_OFFICE_REL}}}id", ""))
        bounds = _bounds(element.get("ref", ""))
        if target is None or bounds is None:
            continue
        location = element.get("location")
        link = Hyperlink(target + f"#{location}" if location else target)
        min_column, min_row, max_column, max_row = bounds
        if (min_column, min_row) == (max_column, max_row):
            cells.setdefault(min_row, {})[min_column] = (order, link)
        else:
            ranges.append(_Range(min_column, min_row, max_column, max_row, order, link))
    return SheetHyperlinks(cells, ranges)


def _bounds(reference: str) -> tuple[int, int, int, int] | None:
    try:
        min_column, min_row, max_column, max_row = range_boundaries(reference)
    except (TypeError, ValueError):
        return None
    return min_column or 1, min_row or 1, max_column or _LAST_COLUMN, max_row or _LAST_ROW


def _sheet_part(archive: zipfile.ZipFile, title: str) -> str:
    """Część zip arkusza o nazwie ``title`` według ``workbook.xml`` i jego relacji."""

    package = ElementTree.fromstring(archive.read("_rels/.rels"))
    workbook = next(
        (
            relationship.get("Target", "").lstrip("/")
            for relationship in package.iter(_PACKAGE_REL)
            if relationship.get("Type", "").endswith("/officeDocument")
        ),
        "",
    )
    sheets = ElementTree.fromstring(archive.read(workbook)).iter(f"{_MAIN}sheet")
    identifier = next((sheet.get(f"{{{_OFFICE_REL}}}id", "") for sheet in sheets if sheet.get("name") == title), "")
    return _relationships(archive, workbook)[identifier][1]


def _relationships(archive: zipfile.ZipFile, part: str) -> dict[str, tuple[ElementTree.Element, str]]:
    """Relacje części ``part``: identyfikator → (relacja, ścieżka celu w zip albo adres zewnętrzny)."""

    folder, name = posixpath.split(part)
    rels = posixpath.join(folder, "_rels", f"{name}.rels")
    if rels not in archive.namelist():
        return {}
    found: dict[str, tuple[ElementTree.Element, str]] = {}
    for relationship in ElementTree.fromstring(archive.read(rels)).iter(_PACKAGE_REL):
        target = relationship.get("Target", "")
        if relationship.get("TargetMode") != "External":
            target = target.lstrip("/") if target.startswith("/") else posixpath.normpath(posixpath.join(folder, target))
        found[relationship.get("Id", "")] = (relationship, target)
    return found


def _external_hyperlinks(archive: zipfile.ZipFile, part: str) -> dict[str, str]:
    return {
        identifier: target
        for identifier, (relationship, target) in _relationships(archive, part).items()
        if relationship.get("Type", "").endswith("/hyperlink") and relationship.get("TargetMode") == "External"
    }

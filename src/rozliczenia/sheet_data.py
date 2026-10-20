"""Wiersze ``<sheetData>`` arkusza w kształcie, który zapisują Excel i openpyxl.

Moduł jest szczegółem ``input_rows`` i ``template_copy`` i nikt poza nimi go nie
używa. Oba czytają XML arkusza bez parsera, po granicach wierszy, więc oba
przyjmują tylko ten sam kształt: jeden ``<sheetData>``, każdy wiersz i każda
komórka z ``r`` jako pierwszym atrybutem, wiersze rosnąco po numerze i bez
komentarzy ani CDATA w danych arkusza. Inny kształt to ``IrregularSheetData``:
``input_rows`` zostawia wtedy arkusz w całości, a ``template_copy`` oddaje zapis
openpyxl.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Final

_ROW_START: Final = re.compile(rb'<row r="(\d+)"')
_WITHOUT_LEADING_R: Final = re.compile(rb'<(?:c|row)(?=[\s>/])(?! r=")')


class IrregularSheetData(Exception):
    """``<sheetData>`` spoza kształtu, który zapisują Excel i openpyxl."""


@dataclass(frozen=True)
class SheetRow:
    """Wiersz arkusza: numer i granice jego elementu ``<row>`` w XML arkusza."""

    number: int
    start: int
    end: int


def sheet_data_bounds(xml: bytes) -> tuple[int, int]:
    """Początek treści i koniec jedynego ``<sheetData>``: od za ``<sheetData>`` do ``</sheetData>``."""

    start = xml.find(b"<sheetData>")
    end = xml.find(b"</sheetData>")
    if start < 0 or end < start or xml.count(b"<sheetData") != 1:
        raise IrregularSheetData("sheetData")
    return start + len(b"<sheetData>"), end


def sheet_rows(xml: bytes, start: int, end: int) -> list[SheetRow]:
    """Wiersze ``<row>`` między ``start`` a ``end`` (treść ``<sheetData>``) w kolejności z pliku."""

    if xml.find(b"<!", start, end) >= 0:
        raise IrregularSheetData("komentarz albo CDATA")
    if _WITHOUT_LEADING_R.search(xml, start, end):
        raise IrregularSheetData("r")
    rows: list[SheetRow] = []
    for match in _ROW_START.finditer(xml, start, end):
        number = int(match.group(1))
        if rows and number <= rows[-1].number:
            raise IrregularSheetData("kolejność wierszy")
        tag_end = xml.index(b">", match.end())
        row_end = tag_end + 1 if xml[tag_end - 1 : tag_end] == b"/" else xml.index(b"</row>", tag_end) + len(b"</row>")
        rows.append(SheetRow(number, match.start(), row_end))
    return rows

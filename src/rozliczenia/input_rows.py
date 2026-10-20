"""Skoroszyt zawężony do wierszy, które mogą mieć dane wejściowe, do szybkiego odczytu Wierszy danych.

Moduł jest szczegółem ``workbook_files.read_data_rows`` i nikt poza nim go nie
używa. Plik zbiorczy ma ~10 tys. sformatowanych wierszy, a dane tylko w kilkuset;
openpyxl czytałby każdą komórkę każdego wiersza. ``rows_with_input`` składa z
bajtów skoroszytu taki sam skoroszyt, w którego arkuszach zostają tylko wiersze,
które mogą być Wierszami danych albo nagłówkiem, i wiersze z formułą główną
wspólnej formuły. Wartości komórek dalej odczytuje openpyxl, więc są takie same
jak przy odczycie całego arkusza (typy, daty, teksty wspólne i wbudowane, formuły).

Pominięty wiersz nie ma wartości w kolumnach danych wejściowych: każda jego
komórka w tych kolumnach jest pustym elementem ``<c …/>``, a openpyxl czyta taki
wiersz tak samo jak brakujący. Formuła główna wspólnej formuły zostaje, bo
openpyxl rozwija z niej formuły zależne w dalszych wierszach.

Arkusz spoza kształtu, który zapisuje Excel i openpyxl (wiersz albo komórka bez
``r`` jako pierwszego atrybutu, wiersze nie po kolei, komentarz albo CDATA w
danych arkusza, XML z prefiksami), zostaje w całości. Pominięte wiersze nie są czytane przez openpyxl, więc XML arkusza jest
najpierw sprawdzany parserem expat, żeby zepsuty arkusz dalej był nieczytelny
(``xml.parsers.expat.ExpatError``).
"""

from __future__ import annotations

import re
import zipfile
from bisect import bisect_right
from io import BytesIO
from typing import Final
from xml.parsers import expat

from openpyxl.utils import get_column_letter

from .sheet_data import IrregularSheetData, sheet_data_bounds, sheet_rows

_WORKSHEET: Final = re.compile(rb"\s*(?:<\?xml[^>]*\?>\s*)?<worksheet[\s>]")
_SHARED_FORMULA_MASTER: Final = re.compile(rb'<f\b[^>]*\bt="shared"[^>]*(?<!/)>')


def rows_with_input(content: bytes, input_columns: int) -> bytes:
    """Skoroszyt ``content`` (.xlsx) z arkuszami zawężonymi do wierszy, które mogą mieć dane w kolumnach 1..``input_columns``.

    Pozostałe części są przepisane bez zmian. Uszkodzenie skoroszytu zgłaszają
    ``zipfile`` (np. ``BadZipFile``), ``zlib`` albo ``expat`` (``ExpatError``).
    """

    letters = b"|".join(get_column_letter(column).encode("ascii") for column in range(1, input_columns + 1))
    with_input = re.compile(rb'<c r="(?:' + letters + rb')[0-9]+"[^>]*(?<!/)>')
    reduced = BytesIO()
    with zipfile.ZipFile(BytesIO(content)) as archive, zipfile.ZipFile(reduced, "w", zipfile.ZIP_STORED) as target:
        for info in archive.infolist():
            data = archive.read(info)
            if _WORKSHEET.match(data):
                data = _sheet_rows_with_input(data, with_input)
            target.writestr(info.filename, data)
    return reduced.getvalue()


def _sheet_rows_with_input(xml: bytes, with_input: re.Pattern[bytes]) -> bytes:
    """XML arkusza tylko z wierszami, w których ``with_input`` znajduje komórkę z treścią, i z formułami głównymi."""

    try:
        body_start, end = sheet_data_bounds(xml)
        starts = [row.start for row in sheet_rows(xml, body_start, end)]
    except IrregularSheetData:
        return xml
    kept = {
        bisect_right(starts, found.start()) - 1
        for pattern in (with_input, _SHARED_FORMULA_MASTER)
        for found in pattern.finditer(xml, body_start, end)
    }
    _ensure_well_formed(xml)
    bounds = [*starts, end]
    rows = [xml[bounds[index] : bounds[index + 1]] for index in sorted(kept) if index >= 0]
    return b"".join([xml[:body_start], *rows, xml[end:]])


def _ensure_well_formed(xml: bytes) -> None:
    """Cały XML arkusza jest poprawny, także w wierszach, których openpyxl już nie przeczyta."""

    expat.ParserCreate().Parse(xml, True)

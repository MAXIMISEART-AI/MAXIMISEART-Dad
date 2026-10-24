"""Skoroszyt zawężony do wierszy z datą z przedziału, do szybkiego odczytu zleceń okresu z Rejestru zleceń.

Moduł jest szczegółem ``workbook_files.ReadWorkbook.narrowed`` i nikt poza nim go
nie używa. Rejestr zleceń ma dziesiątki tysięcy wierszy od 2021 r., a okres
kilkaset; openpyxl czytałby każdą komórkę każdego wiersza. ``rows_dated_between``
składa z bajtów skoroszytu taki sam skoroszyt, w którego wskazanych arkuszach
zostają wiersze od pierwszego do ostatniego wiersza z liczbą z przedziału w
kolumnie daty i wiersze z formułą główną wspólnej formuły; nagłówki czytający
bierze wcześniej z całego skoroszytu. Wartości komórek dalej odczytuje openpyxl,
więc są takie same jak przy odczycie całego arkusza.

openpyxl daje datę tylko z liczby w komórce bez typu albo z ``t="n"`` (ze stylem
daty), więc wiersz, którego data leży w przedziale, ma w kolumnie daty liczbę z
przedziału. Zakres od pierwszej do ostatniej takiej liczby zawiera więc każdy
taki wiersz i wszystkie wiersze między nimi. Liczba bez stylu daty albo wartość
zapamiętana przy formule może zakres tylko poszerzyć.

Arkusz spoza kształtu z ``sheet_data``, z komórką daty typu ``d`` (data tekstem
ISO, której Excel nie zapisuje) albo z wartością liczbową, której nie da się
przeczytać bez parsera XML, zostaje w całości. Pominięte wiersze nie są czytane
przez openpyxl, więc XML arkusza jest najpierw sprawdzany parserem expat, żeby
zepsuty arkusz dalej był nieczytelny (``xml.parsers.expat.ExpatError``).
"""

from __future__ import annotations

import re
import zipfile
from bisect import bisect_right
from collections.abc import Mapping
from contextlib import suppress
from io import BytesIO
from typing import Final
from xml.parsers import expat

from openpyxl.utils import get_column_letter

from .hyperlinks import sheet_part
from .sheet_data import IrregularSheetData, sheet_data_bounds, sheet_rows

_SHARED_FORMULA_MASTER: Final = re.compile(rb'<f\b[^>]*\bt="shared"[^>]*(?<!/)>')
_TYPE: Final = re.compile(rb"""\st=["']([^"']*)["']""")
_VALUE: Final = re.compile(rb"<v\b[^>]*>([^<]*)</v>")
_NUMBER_TYPES: Final = (None, b"n")


def rows_dated_between(
    content: bytes, date_columns: Mapping[str, int], low: float, high: float
) -> tuple[bytes, dict[str, range]]:
    """Skoroszyt ``content`` (.xlsx) z arkuszami ``date_columns`` (tytuł → kolumna daty od 1) zawężonymi do zakresu dat.

    Zakres arkusza to wiersze od pierwszego do ostatniego z liczbą z [``low``,
    ``high``] w kolumnie daty; zwracany jest dla każdego zawężonego arkusza (pusty,
    gdy żadna komórka daty nie ma takiej liczby). Arkusz bez zwróconego zakresu
    zostaje w całości, a pozostałe części są przepisane bez zmian. Uszkodzenie
    skoroszytu zgłaszają ``zipfile`` (np. ``BadZipFile``), ``zlib``, brak części
    ``KeyError`` albo ``expat`` (``ExpatError``).
    """

    reduced = BytesIO()
    ranges: dict[str, range] = {}
    with zipfile.ZipFile(BytesIO(content)) as archive, zipfile.ZipFile(reduced, "w", zipfile.ZIP_STORED) as target:
        narrowed = {sheet_part(archive, title): (title, column) for title, column in date_columns.items()}
        for info in archive.infolist():
            data = archive.read(info)
            if info.filename in narrowed:
                title, column = narrowed[info.filename]
                with suppress(IrregularSheetData):
                    data, ranges[title] = _sheet_rows_dated(data, column, low, high)
            target.writestr(info.filename, data)
    return reduced.getvalue(), ranges


def _sheet_rows_dated(xml: bytes, column: int, low: float, high: float) -> tuple[bytes, range]:
    """XML arkusza z zakresem dat w kolumnie ``column`` i formułami głównymi oraz ten zakres wierszy."""

    body_start, end = sheet_data_bounds(xml)
    rows = sheet_rows(xml, body_start, end)
    letter = get_column_letter(column).encode("ascii")
    date_cell = re.compile(rb'<c r="' + letter + rb'(\d+)"([^>]*)(?<!/)>(.*?)</c>', re.DOTALL)
    dated = [
        int(found.group(1))
        for found in date_cell.finditer(xml, body_start, end)
        if _is_number_between(found.group(2), found.group(3), low, high)
    ]
    _ensure_well_formed(xml)
    kept_range = range(min(dated), max(dated) + 1) if dated else range(0)
    kept = {index for index, row in enumerate(rows) if row.number in kept_range}
    starts = [row.start for row in rows]
    kept.update(bisect_right(starts, found.start()) - 1 for found in _SHARED_FORMULA_MASTER.finditer(xml, body_start, end))
    kept_rows = [xml[rows[index].start : rows[index].end] for index in sorted(kept)]
    return b"".join([xml[:body_start], *kept_rows, xml[end:]]), kept_range


def _is_number_between(attributes: bytes, content: bytes, low: float, high: float) -> bool:
    """Komórka z liczbą z [``low``, ``high``]: tylko taką openpyxl może odczytać jako datę z przedziału."""

    found_type = _TYPE.search(attributes)
    cell_type = found_type.group(1) if found_type else None
    if cell_type == b"d":
        raise IrregularSheetData("data tekstem ISO")
    if cell_type not in _NUMBER_TYPES:
        return False
    value = _VALUE.search(content)
    if value is None:
        return False
    try:
        number = float(value.group(1))
    except ValueError:
        raise IrregularSheetData("wartość liczbowa") from None
    return low <= number <= high


def _ensure_well_formed(xml: bytes) -> None:
    """Cały XML arkusza jest poprawny, także w wierszach, których openpyxl już nie przeczyta."""

    expat.ParserCreate().Parse(xml, True)

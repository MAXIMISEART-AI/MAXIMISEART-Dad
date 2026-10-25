"""Syntetyczny INTERMAX (Rejestr zleceń) w kształcie pliku taty dla testów Uporządkowania INTERMAX.

Arkusz zleceń ma nagłówki od ``AKCJE`` (B) do ``UWAGI`` (O) w wierszu 1 i kolumny z aplikacji za nimi do AK,
zamrożony nagłówek, uporządkowane dni w Calibri 8 (WYKONAWCA Calibri 9) z datą ``m/d/yy h:mm`` i cienką ramką,
opcjonalny żółty wiersz B:N, a na dole Surowe zlecenia z wyglądem z aplikacji (Roboto 4, białe i szare tła) z
pierwszym wierszem przesuniętym o dwie kolumny w lewo i Hiperłączem w ``NUMER ZL.``. Obok są ukryty arkusz,
lista i komentarze. Wartości są syntetyczne.
"""

from __future__ import annotations

import zipfile
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from openpyxl import Workbook, load_workbook
from openpyxl.styles import Border, Font, PatternFill, Side
from openpyxl.worksheet.worksheet import Worksheet

ORDER_SHEET = "ZLECENIA OD 06_2025"
HEADERS = (
    "AKCJE",
    "DATA GODZ. POCZ.",
    "MIASTO",
    "ADRES",
    "UMOWA",
    "URZĄDZENIA",
    "CZYNNOŚCI",
    "NUMER ZL.",
    "WYKONAWCA",
    "NUMER UMOWY",
    "SKUTECZNE",
    "CZYNNOŚCI ZREALIZOWANE",
    "ZWROT",
    "UWAGI",
)
FIRST = 2  # B: AKCJE
DATE = 3  # C
NUMBER = 9  # I: NUMER ZL.
WORKER = 10  # J
LAST = 15  # O: UWAGI
APP_LAST = 37  # AK: ostatnia kolumna z aplikacji
DATE_FORMAT = "m/d/yy h:mm"
_THIN = Side(style="thin")
_BORDER = Border(left=_THIN, right=_THIN, top=_THIN, bottom=_THIN)
_APP_FONT = Font(name="Roboto", sz=4, b=True, color="FF333333")
_APP_FILLS = (PatternFill("solid", fgColor="FFFFFFFF"), PatternFill("solid", fgColor="FFD9D9D9"))
YELLOW = PatternFill("solid", fgColor="FFFFFF00")


@dataclass(frozen=True)
class Order:
    """Zlecenie syntetyczne: chwila, Wykonawca i numer, z którego powstają pozostałe wartości wiersza."""

    when: datetime
    worker: str
    number: int

    def values(self) -> dict[int, object]:
        """Wartości kolumn od B do AK na swoim miejscu (nieprzesunięte)."""

        values: dict[int, object] = {
            DATE: self.when,
            4: "Miasto",
            5: f"Ulica {self.number}",
            6: "Umowa",
            7: "Instalacja",
            8: "INEA",
            NUMBER: f"ZL-{self.number}",
            WORKER: self.worker,
            11: f"UM-{self.number}",
        }
        values.update({column: f"APP{column}-{self.number}" for column in range(LAST + 1, APP_LAST + 1)})
        return values

    @property
    def link(self) -> str:
        return f"https://example.invalid/zlecenie/{self.number}"


@dataclass(frozen=True)
class Layout:
    """Gdzie fixture postawiła wiersze: ostatni uporządkowany, żółty i pierwszy Surowy."""

    last_ordered: int
    yellow: int | None
    first_raw: int
    raw: tuple[Order, ...]


@dataclass
class Intermax:
    """Opis syntetycznego INTERMAX do zapisania przez ``write``."""

    ordered: Sequence[Order] = field(
        default_factory=lambda: (
            Order(datetime(2026, 10, 19, 9), "anna.kowalska", 1),
            Order(datetime(2026, 10, 19, 12), "anna.kowalska", 2),
            Order(datetime(2026, 10, 20, 8), "jan.nowak", 3),
        )
    )
    raw: Sequence[Order] = field(
        default_factory=lambda: (
            Order(datetime(2026, 10, 26, 14), "jan.nowak", 101),
            Order(datetime(2026, 10, 26, 10), "anna.kowalska", 102),
            Order(datetime(2026, 10, 26, 16), "anna.kowalska", 103),
            Order(datetime(2026, 10, 26, 8), "jan.nowak", 104),
            Order(datetime(2026, 10, 26, 10), "anna.kowalska", 105),
            Order(datetime(2026, 10, 26, 9), "bartek.zielinski", 106),
        )
    )
    yellow: bool = True
    shifted: bool = True
    gap: int = 3
    """Puste wiersze między ostatnim uporządkowanym (albo żółtym) wierszem a wklejeniem."""

    def write(self, path: Path) -> Layout:
        workbook = Workbook()
        hidden = workbook.active
        assert isinstance(hidden, Worksheet)
        hidden.title = "Arkusz1"
        hidden.sheet_state = "hidden"
        sheet = workbook.create_sheet(ORDER_SHEET)
        workbook.active = 1
        sheet.freeze_panes = "A2"
        for column, header in enumerate(HEADERS, start=FIRST):
            sheet.cell(1, column, header).font = Font(name="Calibri", sz=11, b=True)
        for column, header in enumerate(("BOS", "TYP", "STATUS 1"), start=LAST + 1):
            sheet.cell(1, column, header)
        row = 2
        for order in self.ordered:
            for column, value in order.values().items():
                cell = sheet.cell(row, column, value)
                if column <= LAST:
                    cell.font = Font(name="Calibri", sz=9 if column == WORKER else 8)
                    cell.border = _BORDER
                if column == DATE:
                    cell.number_format = DATE_FORMAT
            row += 1
        last_ordered = row - 1
        yellow = None
        if self.yellow:
            yellow = last_ordered + 2
            for column in range(FIRST, LAST):
                sheet.cell(yellow, column).fill = YELLOW
            row = yellow + 1
        else:
            row = last_ordered + 1
        first_raw = row + self.gap
        for index, order in enumerate(self.raw):
            shift = 2 if self.shifted and index == 0 else 0
            number = first_raw + index
            for column in range(1, APP_LAST + 1):
                cell = sheet.cell(number, column)
                cell.font = _APP_FONT
                cell.fill = _APP_FILLS[index % 2]
            for column, value in order.values().items():
                cell = sheet.cell(number, column - shift, value)
                if column == DATE:
                    cell.number_format = DATE_FORMAT
                if column == NUMBER:
                    cell.hyperlink = order.link
        lists = workbook.create_sheet("LISTA OD 08.11.2021.")
        lists["A1"] = "lista"
        notes = workbook.create_sheet("komentarze")
        notes["B1"] = "komentarz"
        workbook.save(path)
        return Layout(last_ordered, yellow, first_raw, tuple(self.raw))


def parts(path: Path) -> dict[str, bytes]:
    """Części zip skoroszytu po nazwie, rozpakowane."""

    with zipfile.ZipFile(path) as archive:
        return {name: archive.read(name) for name in archive.namelist()}


def order_rows(path: Path, first: int, last: int) -> list[tuple[object, ...] | None]:
    """Wiersze arkusza zleceń od ``first`` do ``last``: wartości B:AK albo ``None`` dla pustego wiersza."""

    sheet = load_workbook(path).worksheets[1]
    rows: list[tuple[object, ...] | None] = []
    for number in range(first, last + 1):
        values = tuple(sheet.cell(number, column).value for column in range(1, APP_LAST + 1))
        rows.append(None if all(value is None for value in values) else values)
    return rows

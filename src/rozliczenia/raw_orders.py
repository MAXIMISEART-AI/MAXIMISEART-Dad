"""Surowe zlecenia na dole arkusza zleceń Rejestru zleceń: rozpoznanie i plan dnia, czyste funkcje faktów arkusza.

Rozpoznanie (``recognize``) dostaje wiersze arkusza zleceń od dołu i oddaje blok Surowych zleceń (``RawBlock``)
albo ``None``, gdy na dole arkusza nie ma wierszy z wyglądem z aplikacji. Wiersz uporządkowany ma w kolumnach zlecenia (od ``AKCJE`` do
``UWAGI``, bez ``WYKONAWCA``, którą tata pisze też Calibri 9) choć jedną komórkę z wartością w Calibri 8; wiersz z
wartościami bez niej ma wygląd z aplikacji. Blok to wiersze z wartościami pod ostatnim uporządkowanym wierszem.
Pierwszy wiersz bloku jest przesunięty o dwie kolumny w lewo, gdy w ``DATA GODZ. POCZ.`` nie ma daty, a dwie
kolumny w lewo jest. Miejsce dnia wyznacza żółty wiersz, którym tata oddziela dni: najniższy pusty wiersz między
ostatnim uporządkowanym a blokiem, w którym co najmniej połowa kolumn zlecenia ma żółte wypełnienie. Kolumna bez
komórki ma wypełnienie stylu wiersza: u taty żółty wiersz to zwykle styl całego wiersza bez żadnej komórki.

Plan dnia (``plan_day``) z bloku wyznacza docelowe wiersze zleceń: jeden pusty wiersz pod żółtym wierszem albo
10 pustych pod ostatnim uporządkowanym zleceniem, segmenty Wykonawców w kolejności alfabetycznej z jednym
pustym wierszem między nimi, w segmencie od najwcześniejszej godziny, a przy tej samej godzinie w kolejności z
aplikacji. Fakty nie zawierają treści wierszy poza datą i Wykonawcą potrzebnymi do kolejności.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import date, datetime
from itertools import groupby
from typing import Final

from .worker_config import normalize_text

SHIFT: Final = 2
"""O tyle kolumn w lewo przychodzi pierwszy wiersz wklejenia."""
_ORDERED_FACE: Final = ("Calibri", 8.0)
_BLANK_ROWS_WITHOUT_YELLOW: Final = 10


class UndatedOrder(ValueError):
    """Surowe zlecenie bez daty z godziną w ``DATA GODZ. POCZ.``, więc nie ma miejsca w dniu."""


@dataclass(frozen=True)
class OrderColumns:
    """Kolumny arkusza zleceń (od 1) po nagłówkach z wiersza 1: kolumny zlecenia od ``first`` do ``last`` (UWAGI)."""

    first: int
    date: int
    worker: int
    last: int


@dataclass(frozen=True)
class CellFacts:
    """Komórka arkusza: wartość (``None``: pusta), krój i rozmiar czcionki oraz żółte wypełnienie."""

    value: object
    face: tuple[str | None, float | None]
    yellow: bool


@dataclass(frozen=True)
class RowFacts:
    """Wiersz arkusza: numer, komórki po kolumnie od 1 (tylko te, które są w pliku) i żółte wypełnienie stylu wiersza."""

    number: int
    cells: Mapping[int, CellFacts]
    yellow: bool = False

    def value(self, column: int) -> object:
        cell = self.cells.get(column)
        return None if cell is None else cell.value

    @property
    def blank(self) -> bool:
        return all(cell.value is None for cell in self.cells.values())


@dataclass(frozen=True)
class RawOrder:
    """Surowe zlecenie: wiersz arkusza, przesunięcie pierwszego wiersza, data z godziną i Wykonawca."""

    row: int
    shifted: bool
    when: datetime
    worker: str


@dataclass(frozen=True)
class RawBlock:
    """Blok Surowych zleceń w kolejności z aplikacji i wiersz, pod którym staje dzień.

    ``last_ordered`` to ostatni uporządkowany wiersz, a bez niego nagłówek. ``anchor`` to żółty wiersz
    (``under_yellow``) albo ``last_ordered``. Zmieniają się tylko wiersze pod ``anchor``. ``blank_row`` to
    najwyższy pusty, nieżółty wiersz pod ``last_ordered`` (u taty przygotowana siatka), jeśli jest w pliku.
    """

    orders: tuple[RawOrder, ...]
    anchor: int
    under_yellow: bool
    last_ordered: int
    blank_row: int | None


@dataclass(frozen=True)
class Placement:
    """Surowe zlecenie na docelowym wierszu dnia."""

    order: RawOrder
    row: int


@dataclass(frozen=True)
class DayPlan:
    """Uporządkowany dzień: zlecenia na docelowych wierszach, po kolei; reszta wierszy pod ``anchor`` jest pusta."""

    day: date
    placements: tuple[Placement, ...]
    worker_count: int


def recognize(rows_from_bottom: Iterable[RowFacts], columns: OrderColumns) -> RawBlock | None:
    """Blok Surowych zleceń z wierszy arkusza zleceń od ostatniego w górę (bez nagłówka); ``None``, gdy ich nie ma."""

    raw: list[RowFacts] = []
    yellow: int | None = None
    blank: int | None = None
    anchor = 1
    for row in rows_from_bottom:
        if row.blank:
            if not _is_yellow(row, columns):
                blank = row.number
            elif yellow is None:
                yellow = row.number
            continue
        if _is_ordered(row, columns):
            anchor = row.number
            break
        yellow = None
        raw.append(row)
    if not raw:
        return None
    raw.reverse()
    first, *rest = raw
    shifted = _is_date(first.value(columns.date - SHIFT)) and not _is_date(first.value(columns.date))
    orders = [_order(first, columns, shifted), *(_order(row, columns, False) for row in rest)]
    return RawBlock(tuple(orders), yellow if yellow is not None else anchor, yellow is not None, anchor, blank)


def plan_day(block: RawBlock) -> DayPlan:
    """Docelowe wiersze dnia: segmenty Wykonawców alfabetycznie, w segmencie po godzinie, z jednym pustym między nimi."""

    def worker_key(order: RawOrder) -> str:
        return normalize_text(order.worker)

    ordered = sorted(block.orders, key=lambda order: (worker_key(order), order.when))
    row = block.anchor + (2 if block.under_yellow else _BLANK_ROWS_WITHOUT_YELLOW + 1)
    placements: list[Placement] = []
    segments = 0
    for _, segment in groupby(ordered, key=worker_key):
        if segments:
            row += 1
        segments += 1
        for order in segment:
            placements.append(Placement(order, row))
            row += 1
    return DayPlan(min(order.when for order in block.orders).date(), tuple(placements), segments)


def _order(row: RowFacts, columns: OrderColumns, shifted: bool) -> RawOrder:
    offset = SHIFT if shifted else 0
    when = row.value(columns.date - offset)
    if not isinstance(when, datetime):
        # Zatrzymanie z wierszem i kolumną dla taty dostaje osobna zmiana (#469); do tego czasu nic się nie zapisuje.
        raise UndatedOrder(row.number)
    return RawOrder(row.number, shifted, when, str(row.value(columns.worker - offset) or ""))


def _is_date(value: object) -> bool:
    return isinstance(value, datetime)


def _order_cells(row: RowFacts, columns: OrderColumns) -> list[CellFacts]:
    return [
        cell
        for column, cell in row.cells.items()
        if columns.first <= column <= columns.last and column != columns.worker and cell.value is not None
    ]


def _is_ordered(row: RowFacts, columns: OrderColumns) -> bool:
    return any(cell.face == _ORDERED_FACE for cell in _order_cells(row, columns))


def _is_yellow(row: RowFacts, columns: OrderColumns) -> bool:
    span = range(columns.first, columns.last + 1)
    yellow = sum(1 for column in span if (cell.yellow if (cell := row.cells.get(column)) is not None else row.yellow))
    return 2 * yellow >= len(span)

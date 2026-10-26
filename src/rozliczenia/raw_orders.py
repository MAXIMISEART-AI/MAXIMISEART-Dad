"""Surowe zlecenia na dole arkusza zleceń Rejestru zleceń: rozpoznanie i plan dnia, czyste funkcje faktów arkusza.

Rozpoznanie (``recognize``) dostaje wiersze arkusza zleceń od dołu i oddaje blok Surowych zleceń (``RawBlock``),
przeszkodę, przez którą bloku nie da się uporządkować (``Obstacle``), albo ``None``, gdy na dole arkusza nie ma
wierszy z wyglądem z aplikacji ani nie ma ich nad ostatnimi uporządkowanymi wierszami. Wiersz uporządkowany ma w
kolumnach zlecenia (od ``AKCJE`` do ``UWAGI``, bez ``WYKONAWCA``, którą tata pisze też Calibri 9) choć jedną
komórkę z wartością w Calibri 8; wiersz z wartościami bez niej ma wygląd z aplikacji. Blok to wiersze z
wartościami pod ostatnim uporządkowanym wierszem. Pierwszy wiersz bloku jest przesunięty o dwie kolumny w lewo,
gdy w ``DATA GODZ. POCZ.`` nie ma daty; gdy data stoi na miejscu (ktoś przesunął wiersz ręcznie), wiersz się nie
przesuwa. Miejsce dnia wyznacza żółty wiersz, którym tata oddziela dni: najniższy pusty wiersz między
ostatnim uporządkowanym a blokiem, w którym co najmniej połowa kolumn zlecenia ma żółte wypełnienie. Kolumna bez
komórki ma wypełnienie stylu wiersza: u taty żółty wiersz to zwykle styl całego wiersza bez żadnej komórki.

Przeszkody: wiersz z wyglądem z aplikacji nad uporządkowanym wierszem, Surowe zlecenie bez daty z godziną albo bez
Wykonawcy, blok z więcej niż jednego dnia i dzień, który już jest uporządkowany. Pierwsza i ostatnia wymagają
przeglądu nad blokiem: od ostatniego uporządkowanego wiersza w górę, aż ``_EARLIER_ROWS`` kolejnych uporządkowanych
wierszy ma dzień wcześniejszy niż dzień bloku (bez bloku: niż dzień ostatniego uporządkowanego wiersza z datą).
Pojedyncze wcześniejsze dni (usterka z poprzedniego dnia dopisana pod dniem) nie kończą przeglądu. Dzień jest już
uporządkowany, gdy w przeglądzie stoją dwa kolejne uporządkowane wiersze z jego datą albo jeden, pod którym nie ma
wiersza wcześniejszego dnia: zlecenie na jutro wpisane w dzisiejszym dniu nie czyni jutra uporządkowanym.

Plan dnia (``plan_day``) z bloku wyznacza docelowe wiersze zleceń: jeden pusty wiersz pod żółtym wierszem albo
10 pustych pod ostatnim uporządkowanym zleceniem, segmenty Wykonawców w kolejności alfabetycznej z jednym
pustym wierszem między nimi, w segmencie od najwcześniejszej godziny, a przy tej samej godzinie w kolejności z
aplikacji. Fakty nie zawierają treści wierszy poza datą i Wykonawcą potrzebnymi do kolejności.
"""

from __future__ import annotations

from collections.abc import Iterable, Iterator, Mapping
from dataclasses import dataclass
from datetime import date, datetime
from itertools import chain, groupby
from typing import Final

from .worker_config import normalize_text

SHIFT: Final = 2
"""O tyle kolumn w lewo przychodzi pierwszy wiersz wklejenia."""
_ORDERED_FACE: Final = ("Calibri", 8.0)
_BLANK_ROWS_WITHOUT_YELLOW: Final = 10
_EARLIER_ROWS: Final = 10
"""Tyle kolejnych uporządkowanych wierszy z wcześniejszym dniem kończy przegląd nad blokiem."""


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
    yellow: bool

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
class AboveOrdered:
    """Wiersz z wyglądem z aplikacji (``row``) nad uporządkowanym wierszem (``ordered_row``, najbliższym pod nim)."""

    row: int
    ordered_row: int


@dataclass(frozen=True)
class Undated:
    """Surowe zlecenie bez daty z godziną: wiersz i kolumna (od 1), w której jej szukano."""

    row: int
    column: int


@dataclass(frozen=True)
class WithoutWorker:
    """Surowe zlecenie bez Wykonawcy: wiersz i kolumna (od 1), w której go szukano."""

    row: int
    column: int


@dataclass(frozen=True)
class SeveralDays:
    """Blok Surowych zleceń z więcej niż jednego dnia: dni po kolei i wiersze bloku od ``first_row`` do ``last_row``."""

    days: tuple[date, ...]
    first_row: int
    last_row: int


@dataclass(frozen=True)
class DayOrdered:
    """Dzień bloku Surowych zleceń jest już uporządkowany nad blokiem; blok to wiersze od ``first_row`` do ``last_row``."""

    day: date
    first_row: int
    last_row: int


Obstacle = AboveOrdered | Undated | WithoutWorker | SeveralDays | DayOrdered
"""Przeszkoda, przez którą Surowych zleceń nie da się bezpiecznie uporządkować."""


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


def recognize(rows_from_bottom: Iterable[RowFacts], columns: OrderColumns) -> RawBlock | Obstacle | None:
    """Blok Surowych zleceń z wierszy arkusza zleceń od ostatniego w górę (bez nagłówka), przeszkoda albo ``None``.

    ``None``: ani na dole arkusza, ani nad ostatnimi uporządkowanymi wierszami nie ma wierszy z wyglądem z aplikacji.
    """

    rows = iter(rows_from_bottom)
    raw: list[RowFacts] = []
    yellow: int | None = None
    blank: int | None = None
    ordered: RowFacts | None = None
    for row in rows:
        if row.blank:
            if not _is_yellow(row, columns):
                blank = row.number
            elif yellow is None:
                yellow = row.number
            continue
        if _is_ordered(row, columns):
            ordered = row
            break
        yellow = None
        raw.append(row)
    raw.reverse()
    found = [_order(row, columns, index == 0 and not _is_date(row.value(columns.date))) for index, row in enumerate(raw)]
    orders = [order for order in found if isinstance(order, RawOrder)]
    days = sorted({order.when.date() for order in orders})
    above, ordered_days = (None, set[date]()) if ordered is None else _above(ordered, rows, columns, days[0] if days else None)
    if above is not None:
        return above
    if not raw:
        return None
    missing = next((order for order in found if not isinstance(order, RawOrder)), None)
    if missing is not None:
        return missing
    if len(days) > 1:
        return SeveralDays(tuple(days), raw[0].number, raw[-1].number)
    if days[0] in ordered_days:
        return DayOrdered(days[0], raw[0].number, raw[-1].number)
    anchor = 1 if ordered is None else ordered.number
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


def _order(row: RowFacts, columns: OrderColumns, shifted: bool) -> RawOrder | Undated | WithoutWorker:
    offset = SHIFT if shifted else 0
    when = row.value(columns.date - offset)
    if not isinstance(when, datetime):
        return Undated(row.number, columns.date - offset)
    worker = row.value(columns.worker - offset)
    if worker is None:
        return WithoutWorker(row.number, columns.worker - offset)
    return RawOrder(row.number, shifted, when, str(worker))


def _above(
    first: RowFacts, rows: Iterator[RowFacts], columns: OrderColumns, day: date | None
) -> tuple[AboveOrdered | None, set[date]]:
    """Przegląd od ostatniego uporządkowanego wiersza ``first`` w górę: wiersz z wyglądem z aplikacji nad nim i dni.

    Dni to uporządkowane dni przeglądu: dzień dwóch kolejnych wierszy z datą albo wiersza, pod którym nie ma
    wcześniejszego dnia. Przegląd kończy ``_EARLIER_ROWS`` kolejnych wierszy z dniem wcześniejszym niż ``day`` (bez
    niego: dzień pierwszego wiersza z datą).
    """

    below = first.number
    days: set[date] = set()
    earlier = 0
    previous: date | None = None
    lowest: date | None = None
    for row in chain([first], rows):
        if row.blank:
            continue
        if not _is_ordered(row, columns):
            return AboveOrdered(row.number, below), days
        below = row.number
        when = row.value(columns.date)
        if not isinstance(when, datetime):
            continue
        if day is None:
            day = when.date()
        lowest = when.date() if lowest is None else min(lowest, when.date())
        if when.date() in (previous, lowest):
            days.add(when.date())
        previous = when.date()
        if when.date() < day:
            earlier += 1
            if earlier == _EARLIER_ROWS:
                break
        else:
            earlier = 0
    return None, days


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

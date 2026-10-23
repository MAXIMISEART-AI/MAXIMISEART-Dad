"""Treść Wiersza danych, która może opuścić komputer taty: reguła prywatności Kontroli ilości (ADR 0013, ADR 0015).

To jedyny typ z treścią komórek Pliku zbiorczego, który przeżywa silnik Przebiegu rozliczeń, i jedyne miejsce,
które wylicza dozwolone kolumny: UMOWA, URZĄDZENIA i CZYNNOŚCI (po nagłówku z wiersza 17, pod którym zapisuje je
Przygotowanie), dzień tygodnia i godzina z DATA oraz N:AP (po pozycji, jak kopiuje je Przebieg). Adres, numery
zlecenia i umowy, Wykonawca, data dzienna, CZYNNOŚCI ZREALIZOWANE i reszta A:AT nie mają pola, więc nie da się ich
wysłać przez ten typ. Tekst wpisany przez tatę w komórce ilości też nie przechodzi: zostaje z niego „nieliczbowa”.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from decimal import Decimal
from typing import Final, Literal

from openpyxl.utils import get_column_letter

from .preparation_register import ACTIVITIES, CONTRACT, DATE, DEVICES, Column
from .quantity_rules import OrderContent, WeekTime
from .workbook_files import QUANTITY_COLUMNS, cell_datetime, is_blank
from .worker_config import normalize_text

NON_NUMERIC: Final = "nieliczbowa"
TataValue = int | Literal["nieliczbowa"]
"""Ilość taty: liczba (pusta komórka, 0 i ``"0"`` to 0; ``"2"`` i ``2.0`` to 2) albo „nieliczbowa” (formuła, słowo, 1.5)."""

N_AP: Final[tuple[str, ...]] = tuple(get_column_letter(column) for column in QUANTITY_COLUMNS)
_INPUTS: Final[tuple[Column, ...]] = (CONTRACT, DEVICES, ACTIVITIES, DATE)


@dataclass(frozen=True)
class OrderFacts:
    """Wiersz danych po filtrze prywatności."""

    contract: str
    """``UMOWA``; pusta komórka to ``""``."""
    devices: str
    """``URZĄDZENIA``, dokładny tekst."""
    activities: str
    """``CZYNNOŚCI`` (kolumna wejścia, nigdy ``CZYNNOŚCI ZREALIZOWANE``)."""
    time: WeekTime | None
    """Dzień tygodnia i godzina z ``DATA``; ``None``, gdy ``DATA`` nie jest datą."""
    quantities: Mapping[str, TataValue]
    """Litera kolumny N:AP → ilość taty, tylko różna od 0."""

    def quantity(self, column: str) -> TataValue:
        return self.quantities.get(column, 0)

    def content(self) -> OrderContent | None:
        """Treść zlecenia dla Reguł ilości; ``None`` bez dnia tygodnia i godziny."""

        if self.time is None:
            return None
        return OrderContent(contract=self.contract, devices=self.devices, activities=self.activities, started=self.time)


@dataclass(frozen=True)
class MissingHeaders:
    """W wierszu 17 Pliku zbiorczego nie ma nagłówka kolumny wejścia, więc nie wiadomo, gdzie ją czytać."""

    headers: tuple[str, ...]


CollectiveOrders = tuple[OrderFacts, ...] | MissingHeaders


def collective_orders(header: Mapping[str, int], rows: Sequence[Sequence[object]]) -> CollectiveOrders:
    """Dozwolona treść każdego Wiersza danych.

    ``header``: znormalizowany nagłówek wiersza 17 → kolumna od 1; ``rows``: wartości A:AT po pozycji.
    """

    names = [normalize_text(column.target_header) for column in _INPUTS]
    missing = tuple(column.target_header for column, name in zip(_INPUTS, names, strict=True) if name not in header)
    if missing:
        return MissingHeaders(missing)
    contract, devices, activities, started = (header[name] for name in names)
    return tuple(
        OrderFacts(
            contract=_text(row[contract - 1]),
            devices=_text(row[devices - 1]),
            activities=_text(row[activities - 1]),
            time=_week_time(row[started - 1]),
            quantities=_quantities(row),
        )
        for row in rows
    )


def tata_value(cell: object) -> TataValue:
    """Decyzja 11: puste i 0 to 0, liczba całkowita (także tekstem albo jako float) to ta liczba, reszta „nieliczbowa”."""

    if is_blank(cell):
        return 0
    if isinstance(cell, bool):
        return NON_NUMERIC
    if isinstance(cell, int):
        return cell
    if isinstance(cell, float):
        return int(cell) if cell.is_integer() else NON_NUMERIC
    if isinstance(cell, Decimal):
        return int(cell) if cell.is_finite() and cell == cell.to_integral_value() else NON_NUMERIC
    if isinstance(cell, str):
        return _number_text(cell.strip())
    return NON_NUMERIC


def _number_text(text: str) -> TataValue:
    try:
        return int(text)
    except ValueError:
        pass
    try:
        number = float(text.replace(",", "."))
    except ValueError:
        return NON_NUMERIC
    return int(number) if number.is_integer() else NON_NUMERIC


def _text(value: object) -> str:
    return "" if value is None else str(value)


def _week_time(value: object) -> WeekTime | None:
    started = cell_datetime(value)
    return None if started is None else WeekTime.of(started)


def _quantities(row: Sequence[object]) -> dict[str, TataValue]:
    values = {letter: tata_value(row[column - 1]) for letter, column in zip(N_AP, QUANTITY_COLUMNS, strict=True)}
    return {letter: value for letter, value in values.items() if value != 0}

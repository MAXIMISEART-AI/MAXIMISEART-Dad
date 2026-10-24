"""Plik zbiorczy w Przebiegu rozliczeń: Wiersze danych z Wykonawcą, numery wierszy bez niego i treść dozwolona.

Skoroszyt czyta moduł skoroszytu (``workbook_files``), właściciel układu
arkusza; jego ``WorkbookError`` przechodzi do procesu, który tłumaczy go na
Komunikat. Moduł nie zna mapowania Wykonawców ani nazw plików okresu
(``period_folder``). Z tego samego odczytu każdy Wiersz danych, także bez
Wykonawcy, przechodzi przez filtr prywatności (``order_facts``) dla Kontroli ilości.
Ten sam odczyt i filtr dają Ilości do uzupełnienia (``read_numbered_orders``), także z pliku otwartego w Excelu.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from . import workbook_files
from .order_facts import CollectiveOrders, MissingHeaders, collective_orders
from .quantities_to_fill import NumberedOrder
from .workbook_files import DataRow


@dataclass(frozen=True)
class CollectiveRows:
    rows: list[DataRow]
    """Wiersze danych z Wykonawcą w kolejności z pliku."""
    without_worker: list[int]
    """Numery Wierszy danych bez Wykonawcy w kolejności z pliku."""
    orders: CollectiveOrders
    """Dozwolona treść każdego Wiersza danych odczytu."""


def read_data_rows(path: Path) -> CollectiveRows:
    """Wiersze danych Pliku zbiorczego jednym odczytem; plik jest tylko czytany."""

    read = workbook_files.read_data_rows(path)
    rows: list[DataRow] = []
    without_worker: list[int] = []
    for row in read.rows:
        if not str(row.worker or "").split():
            without_worker.append(row.number)
            continue
        rows.append(row)
    return CollectiveRows(rows, without_worker, collective_orders(read.header, [row.values for row in read.rows]))


def read_numbered_orders(path: Path) -> tuple[NumberedOrder, ...] | MissingHeaders:
    """Dozwolona treść każdego Wiersza danych z jego numerem wiersza; plik jest tylko czytany.

    Plik otwarty w Excelu też jest czytany: jego ostatnia zapisana wersja (ADR 0016).
    """

    read = workbook_files.read_data_rows(path, despite_excel_lock=True)
    orders = collective_orders(read.header, [row.values for row in read.rows])
    if isinstance(orders, MissingHeaders):
        return orders
    return tuple(NumberedOrder(row.number, order) for row, order in zip(read.rows, orders, strict=True))

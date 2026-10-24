"""Plik zbiorczy w Przebiegu rozliczeń: Wiersze danych z Wykonawcą, numery wierszy bez niego i treść dozwolona.

Skoroszyt czyta moduł skoroszytu (``workbook_files``), właściciel układu
arkusza; jego ``WorkbookError`` przechodzi do procesu, który tłumaczy go na
Komunikat. Moduł nie zna mapowania Wykonawców ani nazw plików okresu
(``period_folder``). Z tego samego odczytu każdy Wiersz danych, także bez
Wykonawcy, przechodzi przez filtr prywatności (``order_facts``) dla Kontroli ilości.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from . import workbook_files
from .order_facts import CollectiveOrders, collective_orders
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

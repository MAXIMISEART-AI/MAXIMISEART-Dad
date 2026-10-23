"""Plik zbiorczy w Przebiegu rozliczeń: Wiersze danych z Wykonawcą, problemy wierszy bez niego i treść dozwolona.

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
from .domain import Issue
from .order_facts import CollectiveOrders, collective_orders
from .workbook_files import WORKER_HEADER, DataRow


@dataclass(frozen=True)
class CollectiveRows:
    rows: list[DataRow]
    """Wiersze danych z Wykonawcą w kolejności z pliku."""
    issues: list[Issue]
    """Problemy Wierszy danych bez Wykonawcy."""
    orders: CollectiveOrders
    """Dozwolona treść każdego Wiersza danych odczytu."""


def read_data_rows(path: Path) -> CollectiveRows:
    """Wiersze danych Pliku zbiorczego jednym odczytem; plik jest tylko czytany."""

    read = workbook_files.read_data_rows(path)
    rows: list[DataRow] = []
    issues: list[Issue] = []
    for row in read.rows:
        if not str(row.worker or "").split():
            issues.append(
                Issue("BRAK_WYKONAWCY", f"Wiersz {row.number} ma dane, ale nie ma wykonawcy w kolumnie {WORKER_HEADER.column}.")
            )
            continue
        rows.append(row)
    return CollectiveRows(rows, issues, collective_orders(read.header, [row.values for row in read.rows]))

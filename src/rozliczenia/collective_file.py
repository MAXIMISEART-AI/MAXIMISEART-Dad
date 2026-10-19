"""Plik zbiorczy w Przebiegu rozliczeń: Wiersze danych z Wykonawcą i problemy wierszy bez niego.

Skoroszyt czyta moduł skoroszytu (``workbook_files``), właściciel układu
arkusza; jego ``WorkbookError`` przechodzi do procesu, który tłumaczy go na
Komunikat. Moduł nie zna mapowania Wykonawców ani nazw plików okresu
(``period_folder``).
"""

from __future__ import annotations

from pathlib import Path

from . import workbook_files
from .domain import Issue
from .workbook_files import WORKER_HEADER, DataRow


def read_data_rows(path: Path) -> tuple[list[DataRow], list[Issue]]:
    """Wiersze danych z Wykonawcą w kolejności z pliku oraz problemy dla Wierszy danych bez Wykonawcy.

    Plik jest tylko czytany.
    """

    rows: list[DataRow] = []
    issues: list[Issue] = []
    for row in workbook_files.read_data_rows(path):
        if not str(row.worker or "").split():
            issues.append(
                Issue("BRAK_WYKONAWCY", f"Wiersz {row.number} ma dane, ale nie ma wykonawcy w kolumnie {WORKER_HEADER.column}.")
            )
            continue
        rows.append(row)
    return rows, issues

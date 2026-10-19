"""Status okresu: etap okresu rozliczeniowego wynikający z plików w jego Folderze okresu (GLOSSARY).

Status wynika tylko z obecności Pliku zbiorczego i Folderu rozliczeń
pracowników, których nazwy zna silnik; treści skoroszytów się nie czyta.
Status nie zastępuje Gotowości.
"""

from __future__ import annotations

from pathlib import Path
from typing import Literal

from . import collective_file
from .engine import worker_settlements_directory

PeriodStatus = Literal["no_period_files", "collective_file_prepared", "worker_settlements_ready"]


def period_status(period_directory: Path, period: str) -> PeriodStatus:
    """Status okresu ``period`` z plików w ``period_directory`` (Folder okresu, który może nie istnieć)."""

    if worker_settlements_directory(period_directory, period).is_dir():
        return "worker_settlements_ready"
    if collective_file.path_for_period(period_directory, period).is_file():
        return "collective_file_prepared"
    return "no_period_files"

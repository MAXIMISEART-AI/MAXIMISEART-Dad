"""Status okresu: etap okresu rozliczeniowego wynikający z plików w jego Folderze okresu (GLOSSARY).

Status wynika tylko z obecności Pliku zbiorczego i Folderu rozliczeń
pracowników, których ścieżki zna ``PeriodFolder``; treści skoroszytów się nie
czyta. Status nie zastępuje Gotowości.
"""

from __future__ import annotations

from typing import Literal

from .period_folder import PeriodFolder

PeriodStatus = Literal["no_period_files", "collective_file_prepared", "worker_settlements_ready"]


def period_status(folder: PeriodFolder) -> PeriodStatus:
    """Status okresu z plików w Folderze okresu ``folder``, który może nie istnieć."""

    if folder.worker_settlements.is_dir():
        return "worker_settlements_ready"
    if folder.collective_file.is_file():
        return "collective_file_prepared"
    return "no_period_files"

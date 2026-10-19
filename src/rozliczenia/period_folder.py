"""Folder okresu: nazwy i ścieżki plików okresu oraz okres zapisany w ścieżce Pliku zbiorczego (GLOSSARY).

To jedyne miejsce, które zna nazwy w Folderze okresu: Rozliczenia
wewnętrznego, Pliku zbiorczego, Folderu rozliczeń pracowników i Rozliczenia
pracownika. ``PeriodFolder`` powstaje tylko z folderu okresów i sprawdzonego
``SettlementPeriod`` albo ze ścieżki Pliku zbiorczego, którą moduł sam
sprawdza, więc niesprawdzony token nie trafia do nazw. ``PeriodFolderError``
ma bezpieczny komunikat, a każdy proces tłumaczy go na swoje zatrzymanie.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from .settlement_period import PERIOD_TOKEN_PATTERN, SettlementPeriod, parse_period_token

# ``{token}`` to token okresu, ``{worker}`` nazwa Wykonawcy.
_INTERNAL_SETTLEMENT = "Rozliczenie wew. {token}.xlsx"
_COLLECTIVE_FILE = "Rozliczenie {token} - zbiorcze.xlsx"
_WORKER_SETTLEMENTS = "Rozliczenie pracowników {token}"
_WORKER_SETTLEMENT = "Rozliczenie {token} - {worker}.xlsx"

_INTERNAL_SETTLEMENT_MARK = _INTERNAL_SETTLEMENT.partition(" {token}")[0]  # Rozliczenie wew. dowolnego okresu
_COLLECTIVE_FILE_PREFIX, _, _COLLECTIVE_FILE_SUFFIX = _COLLECTIVE_FILE.partition("{token}")
_COLLECTIVE_FILE_NAME = re.compile(
    rf"{re.escape(_COLLECTIVE_FILE_PREFIX)}(?P<token>{PERIOD_TOKEN_PATTERN}){re.escape(_COLLECTIVE_FILE_SUFFIX)}"
)

COLLECTIVE_FILE_PATTERN = _COLLECTIVE_FILE.format(token="*")
"""Plik zbiorczy dowolnego okresu, np. w oknie wyboru pliku."""

WorkerNameCheck = Literal["fine", "invalid", "too_long"]
_FORBIDDEN_IN_FILE_NAME = frozenset('<>:"/\\|?*')
_MAX_FILE_NAME_CODE_UNITS = 255  # Windows liczy nazwę pliku w jednostkach UTF-16
_ANY_TOKEN = "00_00_00_0000"  # każdy token okresu ma tę długość


class PeriodFolderError(Exception):
    """Ścieżka nie jest Plikiem zbiorczym w swoim Folderze okresu.

    ``message`` to bezpieczny komunikat dla taty (bez ścieżki i tekstu wyjątku).
    """

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


@dataclass(frozen=True)
class PeriodFolder:
    """Folder okresu ``period`` w folderze okresów i ścieżki jego plików, które mogą jeszcze nie istnieć."""

    periods_directory: Path
    period: SettlementPeriod

    @classmethod
    def from_collective_file(cls, path: Path) -> PeriodFolder:
        """Folder okresu Pliku zbiorczego ``path``, czyli jego folder nadrzędny.

        Sprawdza dokładną nazwę pliku, okres od wtorku do poniedziałku i to, że
        folder nadrzędny nazywa się jak okres; inaczej ``PeriodFolderError``.
        """

        if _INTERNAL_SETTLEMENT_MARK in path.name:
            raise PeriodFolderError("Plik Rozliczenie wew. jest poza zakresem tego procesu.")
        match = _COLLECTIVE_FILE_NAME.fullmatch(path.name)
        if match is None:
            example = _COLLECTIVE_FILE.format(token="{dd}_{dd}_{mm}_{rrrr}")
            raise PeriodFolderError(f"Wybierz plik nazwany dokładnie: {example}.")
        token = match.group("token")
        try:
            period = parse_period_token(token)
        except ValueError:
            raise PeriodFolderError(
                f"Okres {token} w nazwie pliku nie jest okresem od wtorku do poniedziałku "
                "(przykład okresu: 08_14_09_2026)."
            ) from None
        if path.parent.name != token:
            raise PeriodFolderError(f"Folder pliku musi nazywać się tak samo jak okres: {token}.")
        return cls(path.parent.parent, period)

    @property
    def directory(self) -> Path:
        return self.periods_directory / self.period.token

    @property
    def internal_settlement(self) -> Path:
        return self.directory / _INTERNAL_SETTLEMENT.format(token=self.period.token)

    @property
    def collective_file(self) -> Path:
        return self.directory / _COLLECTIVE_FILE.format(token=self.period.token)

    @property
    def worker_settlements(self) -> Path:
        """Folder rozliczeń pracowników."""

        return self.directory / _WORKER_SETTLEMENTS.format(token=self.period.token)

    def worker_settlement(self, worker_name: str) -> Path:
        """Rozliczenie pracownika Wykonawcy ``worker_name`` w Folderze rozliczeń pracowników."""

        return self.worker_settlements / _WORKER_SETTLEMENT.format(token=self.period.token, worker=worker_name)

    def count_worker_settlements(self) -> int:
        """Liczba Rozliczeń pracowników w istniejącym Folderze rozliczeń pracowników.

        Pomija pliki blokady Excela, pliki ukryte i Wzorzec rozliczenia pracownika bez nazwy wykonawcy.
        """

        prefix, suffix = _WORKER_SETTLEMENT.format(token=self.period.token, worker="\0").split("\0")
        return sum(
            1
            for entry in self.worker_settlements.iterdir()
            if entry.is_file()
            and entry.name.startswith(prefix)
            and entry.name.endswith(suffix)
            and len(entry.name) > len(prefix) + len(suffix)
        )


def check_worker_name(worker_name: str) -> WorkerNameCheck:
    """Czy nazwa Wykonawcy może być nazwą pliku Rozliczenia pracownika.

    ``invalid``: znak niedozwolony w Windows, znak sterujący albo kropka lub
    spacja na końcu. ``too_long``: pełna nazwa Rozliczenia pracownika ma ponad
    255 jednostek UTF-16 albo nie da się jej zapisać w UTF-16.
    """

    if (
        any(character in _FORBIDDEN_IN_FILE_NAME or ord(character) < 32 for character in worker_name)
        or worker_name.endswith((".", " "))
    ):
        return "invalid"
    file_name = _WORKER_SETTLEMENT.format(token=_ANY_TOKEN, worker=worker_name)
    try:
        code_units = len(file_name.encode("utf-16-le")) // 2
    except UnicodeEncodeError:
        return "too_long"
    return "fine" if code_units <= _MAX_FILE_NAME_CODE_UNITS else "too_long"

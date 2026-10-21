"""Folder okresu: nazwy i ścieżki plików okresu, okres ze ścieżki Pliku zbiorczego i Status okresu (GLOSSARY).

To jedyne miejsce, które zna nazwy w Folderze okresu: Rozliczenia
wewnętrznego, Pliku zbiorczego, Folderu rozliczeń pracowników i Rozliczenia
pracownika. ``PeriodFolder`` powstaje tylko z folderu okresów i sprawdzonego
``SettlementPeriod`` albo ze ścieżki Pliku zbiorczego, którą moduł sam
sprawdza, więc niesprawdzony token nie trafia do nazw. ``PeriodFolderError``
ma bezpieczny komunikat, a każdy proces tłumaczy go na swoje zatrzymanie.
Moduł sprawdza też, czy nazwa Wykonawcy może być nazwą pliku
(``check_worker_name``), bo zna format nazwy Rozliczenia pracownika.

Status okresu wynika z tej samej obserwacji plików co flagi istnienia
(``PeriodFolder.observe``), więc nie może się z nimi rozjechać; treści
skoroszytów się nie czyta. Status nie zastępuje Gotowości.

Folder okresów ma jeden z dwóch układów. W płaskim Foldery okresu leżą w nim
bezpośrednio, a brakujący Folder okresu powstaje przy zapisie. W układzie
folderów taty leżą w ``Rozliczenia {rok}\\{miesiąc}\\INEA``; miesiąc to cykl
rozliczeniowy taty, nie kalendarz, więc Folder okresu jest szukany, a nie
wyliczany (``locate_period_folder``). Tata zakłada go sam; brak albo ten sam
okres w dwóch miesiącach to ``PeriodFolderLookupError``. Folder okresów
wskazany wewnątrz ``Rozliczenia {rok}`` (np. ``INEA`` jednego miesiąca) to ten
sam układ liczony od folderu nad ``Rozliczenia {rok}``, więc brakujący Folder
okresu nie powstaje w złym miesiącu.
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

# Układ folderów taty: Rozliczenia {rok}\{miesiąc}\INEA\{token}.
_YEAR_FOLDER = re.compile(r"Rozliczenia \d{4}")
_MONTH_PERIODS_FOLDER = "INEA"

PeriodStatus = Literal["no_period_files", "collective_file_prepared", "worker_settlements_ready"]
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


class PeriodFolderLookupError(Exception):
    """W układzie folderów taty Folderu okresu nie ma (``locations`` puste) albo jest w kilku miesiącach.

    ``locations`` to foldery ``INEA`` z Folderem okresu, w kolejności lat i miesięcy.
    """

    def __init__(self, periods_directory: Path, period: SettlementPeriod, locations: tuple[Path, ...]) -> None:
        super().__init__(period.token)
        self.periods_directory = periods_directory
        self.period = period
        self.locations = locations


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
        return self.directory / collective_file_name(self.period)

    @property
    def worker_settlements(self) -> Path:
        """Folder rozliczeń pracowników."""

        return self.directory / _WORKER_SETTLEMENTS.format(token=self.period.token)

    def worker_settlement(self, worker_name: str) -> Path:
        """Rozliczenie pracownika Wykonawcy ``worker_name`` w Folderze rozliczeń pracowników."""

        return self.worker_settlements / _WORKER_SETTLEMENT.format(token=self.period.token, worker=worker_name)

    def observe(self) -> PeriodFolderObservation:
        """Jeden odczyt plików Folderu okresu, który może nie istnieć."""

        has_worker_settlements = self.worker_settlements.is_dir()
        return PeriodFolderObservation(
            period_folder_exists=self.directory.is_dir(),
            internal_settlement_exists=self.internal_settlement.is_file(),
            collective_file_exists=self.collective_file.is_file(),
            worker_settlements_folder_exists=has_worker_settlements,
            worker_settlement_count=self._count_worker_settlements() if has_worker_settlements else 0,
        )

    def _count_worker_settlements(self) -> int:
        """Pomija pliki blokady Excela, pliki ukryte i Wzorzec rozliczenia pracownika bez nazwy wykonawcy."""

        prefix, suffix = _WORKER_SETTLEMENT.format(token=self.period.token, worker="\0").split("\0")
        return sum(
            1
            for entry in self.worker_settlements.iterdir()
            if entry.is_file()
            and entry.name.startswith(prefix)
            and entry.name.endswith(suffix)
            and len(entry.name) > len(prefix) + len(suffix)
        )


def collective_file_name(period: SettlementPeriod) -> str:
    """Nazwa Pliku zbiorczego okresu; nie zależy od folderu okresów."""

    return _COLLECTIVE_FILE.format(token=period.token)


@dataclass(frozen=True)
class PeriodFolderObservation:
    """Pliki Folderu okresu w chwili jednego odczytu i Status okresu wyliczony z tych samych flag."""

    period_folder_exists: bool
    internal_settlement_exists: bool
    collective_file_exists: bool
    worker_settlements_folder_exists: bool
    worker_settlement_count: int

    @property
    def status(self) -> PeriodStatus:
        if self.worker_settlements_folder_exists:
            return "worker_settlements_ready"
        if self.collective_file_exists:
            return "collective_file_prepared"
        return "no_period_files"


def period_status_label(status: PeriodStatus) -> str:
    """Nazwa Statusu okresu z GLOSSARY."""

    # Status okresu bez nazwy mypy zgłasza jako brakujący return.
    match status:
        case "no_period_files":
            return "Brak plików okresu"
        case "collective_file_prepared":
            return "Plik zbiorczy przygotowany"
        case "worker_settlements_ready":
            return "Rozliczenia pracowników gotowe"


def _month_periods_folders(periods_directory: Path) -> list[Path]:
    """Foldery ``INEA`` miesięcy w ``Rozliczenia {rok}``, w kolejności lat i miesięcy.

    Puste w układzie płaskim i gdy folderu okresów nie ma.
    """

    if not periods_directory.is_dir():
        return []
    years = sorted(entry for entry in periods_directory.iterdir() if entry.is_dir() and _YEAR_FOLDER.fullmatch(entry.name))
    return [
        month / _MONTH_PERIODS_FOLDER
        for year in years
        for month in sorted(year.iterdir())
        if (month / _MONTH_PERIODS_FOLDER).is_dir()
    ]


def _layout_root(periods_directory: Path) -> Path:
    """Folder, od którego liczy się układ folderów okresów.

    Folder okresów wewnątrz ``Rozliczenia {rok}`` (np. ``INEA`` jednego miesiąca)
    oznacza folder nad ``Rozliczenia {rok}``, gdy ten ma foldery ``INEA``
    miesięcy. Inaczej to sam folder okresów.
    """

    if _month_periods_folders(periods_directory):
        return periods_directory
    for directory in (periods_directory, *periods_directory.parents):
        if _YEAR_FOLDER.fullmatch(directory.name) and _month_periods_folders(directory.parent):
            return directory.parent
    return periods_directory


def _period_folder_parents(periods_directory: Path) -> list[Path]:
    """Foldery, w których leżą Foldery okresu: sam folder okresów i foldery ``INEA`` miesięcy."""

    return [periods_directory, *_month_periods_folders(periods_directory)]


def month_folder_label(periods_directory: Path, month_periods_folder: Path) -> str:
    """Folder ``INEA`` miesiąca względem folderu okresów, np. ``Rozliczenia 2026\\06_Czerwiec_2026\\INEA``.

    Sam folder okresów, gdy Folder okresu leży też bezpośrednio w nim, to jego nazwa.
    """

    return "\\".join(month_periods_folder.relative_to(periods_directory).parts) or periods_directory.name


def locate_period_folder(periods_directory: Path, period: SettlementPeriod) -> PeriodFolder:
    """Folder okresu ``period`` w istniejącym folderze okresów.

    W układzie płaskim Folder okresu może jeszcze nie istnieć. W układzie
    folderów taty musi istnieć dokładnie w jednym miejscu; inaczej
    ``PeriodFolderLookupError`` z folderem okresów liczonym od ``_layout_root``.
    """

    periods_directory = _layout_root(periods_directory)
    month_folders = _month_periods_folders(periods_directory)
    found = tuple(parent for parent in (periods_directory, *month_folders) if (parent / period.token).is_dir())
    if len(found) == 1:
        return PeriodFolder(found[0], period)
    if found or month_folders:
        raise PeriodFolderLookupError(periods_directory, period, found)
    return PeriodFolder(periods_directory, period)


def find_period_folders(periods_directory: Path) -> list[PeriodFolder]:
    """Foldery okresu w istniejącym folderze okresów: tylko foldery, których nazwa jest tokenem okresu.

    Okres z Folderem okresu w kilku miejscach występuje raz, w pierwszym z nich.
    """

    folders: dict[SettlementPeriod, PeriodFolder] = {}
    for parent in _period_folder_parents(_layout_root(periods_directory)):
        for entry in parent.iterdir():
            if not entry.is_dir():
                continue
            try:
                period = parse_period_token(entry.name)
            except ValueError:
                continue
            folders.setdefault(period, PeriodFolder(parent, period))
    return list(folders.values())


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

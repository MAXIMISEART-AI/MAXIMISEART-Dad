"""Plik zbiorczy na żywo dla stron Uzupełnienia (#419, ADR 0016): znacznik zapisu i ostatni dobry odczyt.

Przeglądarka co kilka sekund pyta o znacznik zapisu (``saved_version``), który daje ``stat`` bez otwierania
skoroszytu, a pełny widok pobiera dopiero po jego zmianie. Gdy odczyt się nie uda (synchronizacja OneDrive, zapis
Excela), ``LastGoodReads`` oddaje przez ``SHOWN_FAILING_AFTER_S`` ostatni dobry odczyt pliku z jego godziną, a dopiero
potem porażkę, którą strona pokazuje jako Komunikat. Ostatni dobry odczyt jest tylko w pamięci procesu Centrum i
zmienia tylko to, co strona pokazuje podczas porażki: źródłem stanu dalej jest zapisany Plik zbiorczy.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from pathlib import Path
import threading
from typing import Final, Generic, TypeVar

SHOWN_FAILING_AFTER_S: Final = 60.0

T = TypeVar("T")


def saved_version(path: Path) -> str | None:
    """Znacznik zapisu pliku: czas zmiany i rozmiar z ``stat``; ``None``, gdy pliku nie widać."""

    try:
        status = path.stat()
    except OSError:
        return None
    return f"{status.st_mtime_ns}-{status.st_size}"


@dataclass(frozen=True)
class GoodRead(Generic[T]):
    """Odczyt pliku w wersji ``version`` z ``read_at``; ``retrying``: późniejsze próby się nie udały."""

    value: T
    version: str | None
    read_at: datetime
    retrying: bool = False


@dataclass(frozen=True)
class Failing(Generic[T]):
    """Nieudany odczyt: ``kept`` to ostatni dobry do pokazania zamiast porażki, ``None``: pora na Komunikat.

    ``first``: pierwsza próba serii nieudanych, jedyna, która trafia do dziennika.
    """

    kept: GoodRead[T] | None
    first: bool


@dataclass
class _File(Generic[T]):
    last: GoodRead[T] | None = None
    failing_since: float | None = None


class LastGoodReads(Generic[T]):
    """Ostatni dobry odczyt każdego pliku na czas serii nieudanych prób, mierzonej zegarem ``clock`` w sekundach."""

    def __init__(self, *, clock: Callable[[], float]) -> None:
        self._clock = clock
        self._lock = threading.Lock()
        self._files: dict[Path, _File[T]] = {}

    def succeeded(self, path: Path, value: T, version: str | None) -> GoodRead[T]:
        """Dobry odczyt ``path`` w wersji ``version`` (znacznik sprzed odczytu) kończy serię nieudanych prób."""

        with self._lock:
            file = self._files.setdefault(path, _File())
            file.last = GoodRead(value, version, datetime.now(timezone.utc))
            file.failing_since = None
            return file.last

    def failed(self, path: Path) -> Failing[T]:
        """Nieudany odczyt ``path``: ostatni dobry przez ``SHOWN_FAILING_AFTER_S`` od pierwszej porażki serii."""

        with self._lock:
            file = self._files.setdefault(path, _File())
            now = self._clock()
            first = file.failing_since is None
            if file.failing_since is None:
                file.failing_since = now
            if file.last is not None and now - file.failing_since < SHOWN_FAILING_AFTER_S:
                return Failing(replace(file.last, retrying=True), first)
            return Failing(None, first)

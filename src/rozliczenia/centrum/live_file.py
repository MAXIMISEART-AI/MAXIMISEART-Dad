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
# Strona ponawia nieudany odczyt co 3 s; dłuższa cisza znaczy, że nikt nie patrzył (ukryta karta, inna strona).
RETRY_GAP_S: Final = 15.0

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


@dataclass(frozen=True)
class _Series:
    """Seria nieudanych prób odczytu od ``since`` do ostatniej próby ``last`` (sekundy zegara Centrum).

    Seria trwa, dopóki strona ponawia odczyt. Przerwa dłuższa niż ``RETRY_GAP_S`` kończy serię, która jeszcze
    pokazywała ostatni dobry odczyt: nikt nie widział, czy plik w tym czasie wrócił. Seria z Komunikatem trwa aż do
    dobrego odczytu, bo po Komunikacie strona sama przestaje czytać, dopóki znacznik zapisu się nie zmieni.
    """

    since: float
    last: float

    def shows_message(self, at: float) -> bool:
        return at - self.since >= SHOWN_FAILING_AFTER_S

    def continues_at(self, now: float) -> bool:
        return now - self.last <= RETRY_GAP_S or self.shows_message(self.last)


@dataclass
class _File(Generic[T]):
    last: GoodRead[T] | None = None
    failing: _Series | None = None


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
            file.failing = None
            return file.last

    def failed(self, path: Path) -> Failing[T]:
        """Nieudany odczyt ``path``: ostatni dobry przez ``SHOWN_FAILING_AFTER_S`` od pierwszej porażki serii."""

        with self._lock:
            file = self._files.setdefault(path, _File())
            now = self._clock()
            ongoing = file.failing if file.failing is not None and file.failing.continues_at(now) else None
            file.failing = _Series(since=now if ongoing is None else ongoing.since, last=now)
            if file.last is not None and not file.failing.shows_message(now):
                return Failing(replace(file.last, retrying=True), ongoing is None)
            return Failing(None, ongoing is None)

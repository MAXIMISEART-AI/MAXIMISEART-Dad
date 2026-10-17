"""Okres rozliczeniowy: token ``dd_dd_mm_rrrr`` i ostatni pełny okres przed danym dniem.

Token zawiera dzień wtorku, dzień poniedziałku oraz miesiąc i rok poniedziałku,
jak zapis zakresu dat ``08–14.09.2026``. Okres od wtorku 29 września do
poniedziałku 5 października 2026 ma więc token ``29_05_10_2026``. Każdy okres ma
dokładnie jeden token, więc jeden Folder okresu.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime, timedelta

_TOKEN = re.compile(r"^(\d{2})_(\d{2})_(\d{2})_(\d{4})$")
_TUESDAY = 1


@dataclass(frozen=True)
class SettlementPeriod:
    """Okres rozliczeniowy od wtorku do poniedziałku."""

    tuesday: date

    def __post_init__(self) -> None:
        if self.tuesday.weekday() != _TUESDAY:
            raise ValueError("Okres rozliczeniowy zaczyna się we wtorek.")

    @property
    def monday(self) -> date:
        return self.tuesday + timedelta(days=6)

    @property
    def token(self) -> str:
        monday = self.monday
        return f"{self.tuesday.day:02d}_{monday.day:02d}_{monday.month:02d}_{monday.year:04d}"

    @property
    def start(self) -> datetime:
        """Wtorek 00:00."""

        return datetime(self.tuesday.year, self.tuesday.month, self.tuesday.day)

    @property
    def end(self) -> datetime:
        """Następny wtorek 00:00, wyłącznie."""

        return self.start + timedelta(days=7)


def parse_period_token(token: str) -> SettlementPeriod:
    """Okres z tokenu; ``ValueError``, gdy token nie opisuje okresu od wtorku do poniedziałku."""

    match = _TOKEN.fullmatch(token)
    if match is None:
        raise ValueError("Token okresu ma postać dd_dd_mm_rrrr.")
    _, monday_day, month, year = (int(part) for part in match.groups())
    period = SettlementPeriod(date(year, month, monday_day) - timedelta(days=6))
    if period.token != token:
        raise ValueError("Token okresu nie opisuje okresu od wtorku do poniedziałku.")
    return period


def last_complete_period(today: date) -> SettlementPeriod:
    """Ostatni pełny okres zakończony przed ``today``; okres kończący się dziś nie jest pełny."""

    days_since_previous_monday = today.weekday() or 7
    return SettlementPeriod(today - timedelta(days=days_since_previous_monday + 6))

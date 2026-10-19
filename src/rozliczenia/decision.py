"""Decyzja taty w trakcie silnika i rozmowa, w której proces o nią pyta.

Proces (np. Przygotowanie pliku zbiorczego) sam składa Decyzję i sam
zatrzymuje się po odmowie; rozmówca rdzenia Uruchomienia procesu (terminal albo
Centrum rozliczeń) tylko ją pokazuje i zwraca zgodę taty. Moduł zależy tylko
od biblioteki standardowej i od ``message`` (który sam używa tylko biblioteki
standardowej), żeby moduły procesu nie zależały od rdzenia Uruchomienia
procesu.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Protocol

from .message import Message

__all__ = ["Conversation", "Decision"]


@dataclass(frozen=True)
class Decision:
    """Pytanie do taty w trakcie silnika: tytuł, Komunikat, liczby z etykietami i pytanie.

    Każdy rozmówca pokazuje te same części po swojemu, bez parsowania linii.
    """

    title: str
    message: Message
    counts_title: str
    counts: Sequence[tuple[str, int]]
    question: str


class Conversation(Protocol):
    """Rozmowa z tatą w trakcie silnika: tylko jego Decyzja.

    ``confirm`` pokazuje Decyzję i zwraca zgodę taty (``True``). Czas czekania
    na nią nie wlicza się do ``Czas uruchomienia`` ani do metryk.
    ``continue_hint`` mówi, jak u tego rozmówcy wyraża się zgodę, do
    Komunikatu po odmowie (np. „przy pytaniu wpisz t”).
    """

    @property
    def continue_hint(self) -> str: ...

    def confirm(self, decision: Decision) -> bool: ...

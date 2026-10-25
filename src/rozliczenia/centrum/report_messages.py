"""Katalog Komunikatów Zgłoszenia: Zgłoszenie do Maksa nie zapisało się w kolejce Skrzynki.

Brak klucza, odmowa klucza i brak sieci nie mają Komunikatu: Zgłoszenie czeka w kolejce i wychodzi samo, a karta
mówi, na co czeka. Komunikat jest tylko wtedy, gdy nie udało się zapisać samego pliku kolejki. Instrukcja taty
cytuje „Co się stało” każdego Komunikatu (``tests/test_instrukcja_taty.py``).
"""

from __future__ import annotations

from pathlib import Path

from rozliczenia.message import Message


def not_queued(queue: Path) -> Message:
    """Zgłoszenia nie udało się zapisać w folderze kolejki ``queue``: nic go nie wyśle."""

    return Message(
        code="ZGLOSZENIE_NIEZAPISANE",
        what="Nie udało się zapisać Zgłoszenia na tym komputerze, więc nie pójdzie do Maksa.",
        where=f"folder {queue.name}",
        action="Kliknij „Spróbuj ponownie”. Jeśli to nie pomoże, rozwiń „Co zostanie wysłane”, skopiuj treść i "
        "prześlij ją Maksowi mailem.",
    )

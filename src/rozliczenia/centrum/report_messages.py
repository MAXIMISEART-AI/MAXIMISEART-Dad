"""Katalog Komunikatów Zgłoszenia: Zgłoszenie do Maksa nie wyszło i czeka w pliku na tym komputerze.

Każdy Komunikat wskazuje zapisany plik Zgłoszenia, który tata może przesłać
Maksowi mailem, i mówi, kiedy kliknąć „Spróbuj ponownie”; gdy i zapis pliku się
nie udał, każe przesłać treść z podglądu. Instrukcja taty cytuje „Co się stało”
każdego Komunikatu (``tests/test_instrukcja_taty.py``).
"""

from __future__ import annotations

from pathlib import Path

from rozliczenia.message import Message, file_label


def key_missing(saved: Path) -> Message:
    """Na komputerze taty nie ma klucza do Zgłoszeń: Zgłoszenie jest tylko w pliku ``saved``."""

    return Message(
        code="ZGLOSZENIE_BEZ_KLUCZA",
        what="Nie wysłano Zgłoszenia: na tym komputerze nie ma klucza do Zgłoszeń.",
        where=file_label(saved),
        action="Prześlij ten plik Maksowi mailem. Gdy Maks wpisze klucz do Zgłoszeń, kliknij „Spróbuj ponownie”.",
    )


def key_refused(saved: Path) -> Message:
    """Skrzynka Zgłoszeń odmówiła klucza (wygasł albo jest nieważny)."""

    return Message(
        code="ZGLOSZENIE_ODMOWA",
        what="Nie wysłano Zgłoszenia: klucz do Zgłoszeń wygasł albo jest nieważny.",
        where=file_label(saved),
        action="Prześlij ten plik Maksowi mailem i powiedz mu o kluczu do Zgłoszeń. "
        "Gdy Maks go wymieni, kliknij „Spróbuj ponownie”.",
    )


def box_unreachable(saved: Path) -> Message:
    """Skrzynka Zgłoszeń nie odpowiedziała: brak internetu albo GitHub chwilowo nie działa."""

    return Message(
        code="ZGLOSZENIE_BRAK_POLACZENIA",
        what="Nie wysłano Zgłoszenia: brak połączenia z GitHubem.",
        where=file_label(saved),
        action="Sprawdź internet i kliknij „Spróbuj ponownie”. Jeśli to nie pomoże, prześlij ten plik Maksowi mailem.",
    )


def not_saved(saved: Path) -> Message:
    """Zgłoszenia nie wysłano, a zapis w pliku ``saved`` też się nie udał (np. folder Zgłoszeń niedostępny)."""

    return Message(
        code="ZGLOSZENIE_NIEZAPISANE",
        what="Nie wysłano Zgłoszenia i nie udało się zapisać go w pliku na tym komputerze.",
        where=file_label(saved),
        action="Rozwiń „Co zostanie wysłane”, skopiuj treść i prześlij ją Maksowi mailem.",
    )

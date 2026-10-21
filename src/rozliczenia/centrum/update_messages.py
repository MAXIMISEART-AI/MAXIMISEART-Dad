"""Katalog Komunikatów Aktualizacji narzędzia: aktualizacja się nie udała.

Kody porażek zwraca moduł ``tool_update``; treść dla taty jest tylko tutaj
(``message_of``). Każdy Komunikat mówi, że narzędzie działa dalej w wersji
sprzed kliknięcia, a „Co zrobić” wprost, czy spróbować ponownie, czy przekazać
go osobie utrzymującej narzędzie. „Gdzie” nie ma ścieżek. Instrukcja taty
cytuje „Co się stało” każdego Komunikatu (``tests/test_instrukcja_taty.py``).
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Final

from rozliczenia.centrum.tool_update import LIBRARIES_FAILED, UNEXPECTED
from rozliczenia.message import Message

_TOOL: Final = "narzędzie na tym komputerze"
_STILL_WORKS: Final = "Narzędzie działa dalej w poprzedniej wersji."


def unexpected_failure() -> Message:
    """Porażka, której nikt nie przewidział; ani wyjście Gita, ani treść wyjątku nie trafiają do taty."""

    return Message(
        code=UNEXPECTED,
        what="Nie udało się zaktualizować narzędzia z nieoczekiwanego powodu.",
        where=_TOOL,
        action=(
            f"{_STILL_WORKS} Kliknij „Zaktualizuj narzędzie” jeszcze raz. "
            "Jeśli komunikat wraca, przekaż go osobie utrzymującej narzędzie."
        ),
    )


def libraries_failed() -> Message:
    """Nowa wersja zmieniła biblioteki, a ich instalacja się nie udała; klon wrócił do wersji sprzed kliknięcia."""

    return Message(
        code=LIBRARIES_FAILED,
        what="Nie udało się zainstalować bibliotek nowej wersji narzędzia.",
        where=_TOOL,
        action=(
            f"{_STILL_WORKS} Kliknij „Zaktualizuj narzędzie” jeszcze raz. "
            "Jeśli komunikat wraca, przekaż go osobie utrzymującej narzędzie."
        ),
    )


_BY_CODE: Final[Mapping[str, Callable[[], Message]]] = {
    UNEXPECTED: unexpected_failure,
    LIBRARIES_FAILED: libraries_failed,
}


def message_of(code: str) -> Message:
    """Komunikat porażki o kodzie ``code`` z ``tool_update``; nieznany kod to porażka nieoczekiwana."""

    return _BY_CODE.get(code, unexpected_failure)()

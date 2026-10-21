"""Katalog Komunikatów Aktualizacji narzędzia: aktualizacja się nie udała.

Kody porażek zwraca moduł ``tool_update``; treść dla taty jest tylko tutaj
(``message_of``). Każdy Komunikat mówi, że narzędzie działa dalej w wersji
sprzed kliknięcia, a „Co zrobić” wprost, czy spróbować ponownie, czy przekazać
sprawę Maksowi przyciskiem „Wyślij do Maksa” (Zgłoszenie przy Komunikacie).
Wyjątkiem jest nieudane cofnięcie (``rollback_failed``): wtedy narzędzie może
nie działać, więc Komunikat każe nie ponawiać aktualizacji (ADR 0010: bez
ścieżki zapasowej).
„Gdzie” nie ma ścieżek. Instrukcja taty
cytuje „Co się stało” każdego Komunikatu (``tests/test_instrukcja_taty.py``).
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Final

from rozliczenia.centrum.tool_update import (
    LIBRARIES_FAILED,
    LOCAL_CHANGES,
    LOGIN,
    NO_CONNECTION,
    NEW_VERSION_FAILED,
    NO_GIT,
    OTHER_BRANCH,
    ROLLBACK_FAILED,
    UNEXPECTED,
)
from rozliczenia.message import Message

_TOOL: Final = "narzędzie na tym komputerze"
_STILL_WORKS: Final = "Narzędzie działa dalej w poprzedniej wersji."
_TO_MAKS: Final = f"{_STILL_WORKS} Przekaż sprawę Maksowi: kliknij „Wyślij do Maksa”."
_NOT_UPDATED: Final = "Nie zaktualizowano narzędzia:"


def no_git() -> Message:
    """Centrum nie znalazło Gita for Windows ani w ``PATH``, ani w znanych miejscach instalacji."""

    return Message(code=NO_GIT, what=f"{_NOT_UPDATED} na tym komputerze nie ma Gita.", where=_TOOL, action=_TO_MAKS)


def no_connection() -> Message:
    """GitHub nie odpowiedział: brak internetu albo limit czasu; tata spróbuje ponownie."""

    return Message(
        code=NO_CONNECTION,
        what=f"{_NOT_UPDATED} brak połączenia z GitHubem.",
        where=_TOOL,
        action=f"{_STILL_WORKS} Sprawdź internet i kliknij „Zaktualizuj narzędzie” jeszcze raz.",
    )


def login_required() -> Message:
    """GitHub poprosił o logowanie (publiczne repozytorium tego nie robi); Git nie pytał taty o nic."""

    return Message(code=LOGIN, what=f"{_NOT_UPDATED} GitHub prosi o logowanie.", where=_TOOL, action=_TO_MAKS)


def other_branch() -> Message:
    """Klon taty nie stoi na gałęzi `main`, więc przesunięcie do przodu nie wchodzi w grę."""

    return Message(
        code=OTHER_BRANCH,
        what=f"{_NOT_UPDATED} na tym komputerze jest inna gałąź narzędzia niż main.",
        where=_TOOL,
        action=_TO_MAKS,
    )


def local_changes() -> Message:
    """Lokalne commity, zmienione śledzone pliki albo nieśledzony plik, który nowa wersja by nadpisała."""

    return Message(
        code=LOCAL_CHANGES,
        what=f"{_NOT_UPDATED} ma zmiany zrobione na tym komputerze.",
        where=_TOOL,
        action=_TO_MAKS,
    )


def unexpected_failure() -> Message:
    """Porażka, której nikt nie przewidział; ani wyjście Gita, ani treść wyjątku nie trafiają do taty."""

    return Message(
        code=UNEXPECTED,
        what="Nie udało się zaktualizować narzędzia z nieoczekiwanego powodu.",
        where=_TOOL,
        action=(
            f"{_STILL_WORKS} Kliknij „Zaktualizuj narzędzie” jeszcze raz. "
            "Jeśli komunikat wraca, kliknij „Wyślij do Maksa”."
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
            "Jeśli komunikat wraca, kliknij „Wyślij do Maksa”."
        ),
    )


def new_version_failed() -> Message:
    """Nowa wersja nie odpowiedziała po ponownym starcie; opiekun cofnął narzędzie do wersji sprzed kliknięcia."""

    return Message(
        code=NEW_VERSION_FAILED,
        what="Nowa wersja narzędzia nie wystartowała.",
        where=_TOOL,
        action=_TO_MAKS,
    )


def rollback_failed() -> Message:
    """Klon miał wrócić do wersji sprzed kliknięcia, ale cofnięcie się nie udało: narzędzie może nie działać."""

    return Message(
        code=ROLLBACK_FAILED,
        what="Aktualizacja narzędzia się nie udała i nie dało się przywrócić poprzedniej wersji.",
        where=_TOOL,
        action=(
            "Nie klikaj „Zaktualizuj narzędzie” ponownie. Przekaż sprawę Maksowi: kliknij „Wyślij do Maksa”."
        ),
    )


_BY_CODE: Final[Mapping[str, Callable[[], Message]]] = {
    NO_GIT: no_git,
    NO_CONNECTION: no_connection,
    LOGIN: login_required,
    OTHER_BRANCH: other_branch,
    LOCAL_CHANGES: local_changes,
    UNEXPECTED: unexpected_failure,
    LIBRARIES_FAILED: libraries_failed,
    NEW_VERSION_FAILED: new_version_failed,
    ROLLBACK_FAILED: rollback_failed,
}


def message_of(code: str) -> Message:
    """Komunikat porażki o kodzie ``code`` z ``tool_update``; nieznany kod to porażka nieoczekiwana."""

    return _BY_CODE.get(code, unexpected_failure)()

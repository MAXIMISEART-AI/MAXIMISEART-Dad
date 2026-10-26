"""Katalog Komunikatów Uporządkowania INTERMAX dla taty.

Każda fabryka zwraca Komunikat (``message.Message``) w trzech częściach: co się stało, gdzie, co zrobić.
Zatrzymanie to ``raise StopError(fabryka(...))``. Komunikaty wskazują tylko plik, folder i arkusz, bez adresów,
numerów zleceń, numerów umów i loginów Wykonawców.
"""

from __future__ import annotations

from pathlib import Path

from .message import REPORT_TO_MAINTAINER, Message, file_label, folder_label
from .workbook_files import Problem, WorkbookError

_PROCESS = "Uporządkowanie INTERMAX"
_UNCHANGED = "INTERMAX nie został zmieniony."


def register_unusable(error: WorkbookError) -> Message:
    """INTERMAX, którego nie da się użyć; ``error`` mówi dlaczego."""

    match error.problem:
        case Problem.MISSING:
            return _register_missing(error.path)
        case Problem.OPEN_IN_EXCEL:
            return register_open(error.path)
        case Problem.INACCESSIBLE:
            return _register_inaccessible(error.path)
        case Problem.UNREADABLE | Problem.LAYOUT | Problem.HAS_DATA:
            return _register_unreadable(error.path)


def _register_missing(register: Path) -> Message:
    return Message(
        code="BRAK_INTERMAX",
        what=f"Nie znaleziono INTERMAX. {_UNCHANGED}",
        where=file_label(register),
        action="Wybierz w Ustawieniach właściwy plik INTERMAX i uruchom ponownie.",
    )


def register_open(register: Path) -> Message:
    """INTERMAX jest otwarty w Excelu: plik blokady obok albo odmowa podmiany pliku."""

    return Message(
        code="INTERMAX_OTWARTY",
        dad_file="order_register",
        what=f"INTERMAX jest otwarty w Excelu. {_UNCHANGED}",
        where=file_label(register),
        action=(
            "Zapisz i zamknij INTERMAX w Excelu, potem uruchom ponownie. Jeśli Excel jest zamknięty, a komunikat "
            f"wraca, usuń z tego samego folderu pozostawiony plik ~${register.name} i uruchom ponownie."
        ),
    )


def _register_inaccessible(register: Path) -> Message:
    return Message(
        code="NIEDOSTEPNY_INTERMAX",
        dad_file="order_register",
        what=(
            "Nie można teraz odczytać INTERMAX. Plik może być zajęty przez inny program albo czekać na pobranie "
            f"z OneDrive. {_UNCHANGED}"
        ),
        where=file_label(register),
        action=(
            "Poczekaj, aż OneDrive skończy synchronizację, i sprawdź, czy INTERMAX otwiera się w Excelu. Zamknij go "
            "i uruchom ponownie. Jeśli błąd wraca, przekaż ten komunikat osobie utrzymującej narzędzie."
        ),
    )


def _register_unreadable(register: Path) -> Message:
    return Message(
        code="NIECZYTELNY_INTERMAX",
        dad_file="order_register",
        what=f"Nie można odczytać INTERMAX jako skoroszytu Excela. {_UNCHANGED}",
        where=file_label(register),
        action=(
            "Otwórz INTERMAX w Excelu i sprawdź, czy się otwiera. Jeśli tak, zapisz go, zamknij i uruchom ponownie. "
            "Jeśli błąd wraca, przekaż ten komunikat osobie utrzymującej narzędzie."
        ),
    )


def no_order_sheet(register: Path) -> Message:
    """Żaden arkusz INTERMAX nie ma w wierszu 1 nagłówków zleceń od ``AKCJE`` do ``UWAGI``."""

    return Message(
        code="BRAK_ARKUSZA_ZLECEN",
        dad_file="order_register",
        what=f"W INTERMAX nie ma arkusza zleceń z nagłówkami od AKCJE do UWAGI w wierszu 1. {_UNCHANGED}",
        where=file_label(register),
        action="Sprawdź nagłówki arkusza zleceń w wierszu 1 i uruchom ponownie.",
    )


def no_raw_orders(register: Path, sheet: str) -> Message:
    """Na dole arkusza zleceń nie ma Surowych zleceń; nic nie zapisano."""

    return Message(
        code="BRAK_SUROWYCH_ZLECEN",
        dad_file="order_register",
        what=f"Na dole arkusza zleceń nie ma wklejonych zleceń do uporządkowania. {_UNCHANGED}",
        where=f"{file_label(register)}, arkusz {sheet}",
        action="Wklej zlecenia dnia z aplikacji na dół arkusza zleceń, zapisz i zamknij INTERMAX i uruchom ponownie.",
    )


def unsupported_shape(register: Path, sheet: str) -> Message:
    """Wklejone zlecenia mają kształt, którego zapis nie przenosi (formuła, scalenie, zakres)."""

    return Message(
        code="NIEOBSLUGIWANY_UKLAD_INTERMAX",
        what=f"Wklejone zlecenia mają układ, którego narzędzie nie porządkuje. {_UNCHANGED}",
        where=f"{file_label(register)}, arkusz {sheet}",
        action=REPORT_TO_MAINTAINER,
    )


def write_check_failed(register: Path) -> Message:
    """Sprawdzenie zapisu wykryło różnicę poza uporządkowanym dniem; INTERMAX nie został podmieniony."""

    return Message(
        code="ZAPIS_INTERMAX_NIEZGODNY",
        what=f"Sprawdzenie zapisu wykazało różnicę, więc zapis został odrzucony. {_UNCHANGED}",
        where=file_label(register),
        action=REPORT_TO_MAINTAINER,
    )


def copy_failed(directory: Path) -> Message:
    """Nie powstała Kopia INTERMAX, więc INTERMAX nie został podmieniony."""

    return Message(
        code="KOPIA_INTERMAX_NIEUDANA",
        what=f"Nie udało się zrobić Kopii INTERMAX. {_UNCHANGED}",
        where=folder_label(directory),
        action=(
            "Sprawdź, czy na dysku jest wolne miejsce, i uruchom ponownie. "
            "Jeśli błąd wraca, przekaż ten komunikat osobie utrzymującej narzędzie."
        ),
    )


def old_copies_kept(directory: Path) -> Message:
    """Ostrzeżenie: INTERMAX jest uporządkowany, ale starsze Kopie INTERMAX nie zostały usunięte."""

    return Message(
        code="STARE_KOPIE_INTERMAX",
        what="INTERMAX został uporządkowany, ale nie udało się usunąć starszych Kopii INTERMAX.",
        where=folder_label(directory),
        action=(
            "Nie musisz nic robić teraz. Jeśli któraś Kopia INTERMAX jest otwarta w Excelu, zamknij ją. "
            "Jeśli komunikat wraca, przekaż go osobie utrzymującej narzędzie."
        ),
    )


def unexpected_failure() -> Message:
    """Nieprzewidziany błąd; treść wyjątku nie trafia do taty."""

    return Message(
        code="BLAD_NIEOCZEKIWANY",
        what=f"Wystąpił nieoczekiwany błąd. {_UNCHANGED}",
        where=_PROCESS,
        action="Uruchom ponownie. Jeśli błąd wraca, przekaż to osobie utrzymującej narzędzie.",
    )


def summary_not_shown() -> Message:
    """INTERMAX jest uporządkowany, ale podsumowania nie dało się pokazać."""

    return Message(
        code="BLAD_PODSUMOWANIA",
        what="INTERMAX został uporządkowany, ale nie udało się pokazać podsumowania.",
        where=_PROCESS,
        action="Nie uruchamiaj ponownie. Sprawdź INTERMAX i przekaż ten komunikat osobie utrzymującej narzędzie.",
    )


def plan_not_shown() -> Message:
    """Uporządkowanie nie ma podglądu bez zapisu; rdzeń wymaga Komunikatu na każdy rodzaj zakończenia."""

    return Message(
        code="BLAD_PLANU",
        what=f"Nie udało się pokazać planu. {_UNCHANGED}",
        where=_PROCESS,
        action=REPORT_TO_MAINTAINER,
    )

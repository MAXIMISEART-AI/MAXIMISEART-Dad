"""Katalog komunikatów Przygotowania pliku zbiorczego dla taty.

Każdy komunikat ma trzy części: co się stało, gdzie, co zrobić. Komunikaty są
po polsku, bez żargonu i treści exceptionów oraz bez adresów, numerów zleceń i
treści wierszy. Wskazują wyłącznie plik, arkusz, nagłówek albo numer wiersza.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class PreparationMessage:
    """Bezpieczny komunikat zatrzymania albo ostrzeżenia."""

    code: str
    what: str
    where: str
    action: str

    @property
    def text(self) -> str:
        return f"Co się stało: {self.what}\nGdzie: {self.where}\nCo zrobić: {self.action}"


class PreparationError(Exception):
    """Zatrzymanie Przygotowania pliku zbiorczego; żaden plik nie został utworzony."""

    def __init__(self, message: PreparationMessage) -> None:
        super().__init__(message.text)
        self.message = message


def _folder_label(directory: Path) -> str:
    return f"{directory.parent.name}\\{directory.name}" if directory.parent.name else directory.name


def period_file_exists(period_directory: Path, filename: str) -> PreparationError:
    """Nienadpisywanie: plik okresu już istnieje w Folderze okresu."""

    return PreparationError(
        PreparationMessage(
            code="PLIK_OKRESU_ISTNIEJE",
            what="Plik tego okresu już istnieje, więc nie został nadpisany. Nie utworzono żadnego pliku.",
            where=f"folder {_folder_label(period_directory)}, plik {filename}",
            action=(
                "Sprawdź, czy wybrano właściwy okres. Jeśli plik ma powstać od nowa, "
                "przenieś albo usuń istniejący plik i uruchom ponownie."
            ),
        )
    )


def invalid_period_token(token: str) -> PreparationError:
    """Token okresu nie opisuje przedziału od wtorku do poniedziałku."""

    return PreparationError(
        PreparationMessage(
            code="ZLY_TOKEN_OKRESU",
            what="Okres nie ma postaci dd_dd_mm_rrrr od wtorku do poniedziałku.",
            where=f"okres {token!r}",
            action="Wpisz okres jak w nazwie folderu, np. 08_14_09_2026 (wtorek 8, poniedziałek 14 września 2026).",
        )
    )


def unreadable_worker_config(config_path: Path) -> PreparationError:
    """Konfiguracja wykonawców nie daje się odczytać."""

    return PreparationError(
        PreparationMessage(
            code="ZLA_KONFIGURACJA_WYKONAWCOW",
            what="Nie można odczytać konfiguracji wykonawców.",
            where=f"plik {config_path.name}",
            action="Przekaż to osobie utrzymującej narzędzie.",
        )
    )


def template_without_header(template_path: Path, sheet: str, header: str) -> PreparationError:
    """Wzorzec nie ma oczekiwanego nagłówka."""

    return PreparationError(
        PreparationMessage(
            code="ZLY_WZORZEC",
            what=f"We wzorcu brakuje nagłówka {header}.",
            where=f"plik {template_path.name}, arkusz {sheet}",
            action="Przekaż to osobie utrzymującej narzędzie.",
        )
    )


def register_without_data_sheet(register_path: Path) -> PreparationError:
    """Żaden arkusz Rejestru nie ma kompletu wymaganych nagłówków w pierwszym wierszu."""

    return PreparationError(
        PreparationMessage(
            code="BRAK_ARKUSZA_ZLECEN",
            what="W Rejestrze zleceń nie znaleziono arkusza ze wszystkimi wymaganymi nagłówkami w pierwszym wierszu.",
            where=f"plik {register_path.name}",
            action="Sprawdź nagłówki w pierwszym wierszu arkusza ze zleceniami i uruchom ponownie.",
        )
    )


def write_failed(period_directory: Path) -> PreparationError:
    """Zapis lub publikacja plików okresu nie powiodły się."""

    return PreparationError(
        PreparationMessage(
            code="BLAD_ZAPISU",
            what="Nie udało się zapisać plików okresu. Nie utworzono żadnego pliku.",
            where=f"folder {_folder_label(period_directory)}",
            action=(
                "Sprawdź, czy folder jest dostępny i czy pliki okresu nie są otwarte, "
                "i uruchom ponownie. Jeśli błąd wraca, przekaż to osobie utrzymującej narzędzie."
            ),
        )
    )


def unexpected_failure() -> PreparationMessage:
    """Nieprzewidziany błąd; treść exceptiona nie trafia do taty."""

    return PreparationMessage(
        code="BLAD_NIEOCZEKIWANY",
        what="Wystąpił nieoczekiwany błąd. Nie utworzono żadnego pliku.",
        where="Przygotowanie pliku zbiorczego",
        action="Uruchom ponownie. Jeśli błąd wraca, przekaż to osobie utrzymującej narzędzie.",
    )

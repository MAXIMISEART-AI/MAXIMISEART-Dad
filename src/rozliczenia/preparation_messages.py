"""Katalog komunikatów Przygotowania pliku zbiorczego dla taty.

Każdy komunikat ma trzy części: co się stało, gdzie, co zrobić. Komunikaty są
po polsku, bez żargonu i treści exceptionów oraz bez adresów, numerów zleceń i
treści wierszy. Wskazują wyłącznie plik, arkusz, nagłówek albo numer wiersza.
"""

from __future__ import annotations

from collections.abc import Sequence
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


_LISTED_ROWS = 10


def _rows_label(row_numbers: Sequence[int]) -> str:
    """Numery wierszy Rejestru; przy długiej liście tylko pierwsze i liczba pozostałych."""

    if len(row_numbers) == 1:
        return f"wiersz {row_numbers[0]}"
    listed = ", ".join(str(row) for row in row_numbers[:_LISTED_ROWS])
    rest = len(row_numbers) - _LISTED_ROWS
    return f"wiersze {listed}" + (f" i {rest} kolejnych" if rest > 0 else "")


def _register_location(register_path: Path, sheet: str) -> str:
    return f"plik {register_path.name}, arkusz {sheet}"


def rows_without_date(register_path: Path, sheet: str, row_numbers: Sequence[int]) -> PreparationError:
    """Wiersz z danymi bez poprawnej daty leży między pierwszym a ostatnim zleceniem okresu."""

    subject = "jest wiersz z danymi" if len(row_numbers) == 1 else "są wiersze z danymi"
    return PreparationError(
        PreparationMessage(
            code="WIERSZ_BEZ_DATY",
            what=(
                f"Między zleceniami okresu {subject} bez poprawnej daty w kolumnie DATA GODZ. POCZ. "
                "Nie utworzono żadnego pliku."
            ),
            where=f"{_register_location(register_path, sheet)}, {_rows_label(row_numbers)}",
            action=(
                "Wpisz poprawną datę w kolumnie DATA GODZ. POCZ. we wskazanych wierszach Rejestru zleceń "
                "albo wyczyść wiersz, jeśli jest zbędny. Zapisz i zamknij Rejestr, i uruchom ponownie."
            ),
        )
    )


def invalid_successful_values(register_path: Path, sheet: str, row_numbers: Sequence[int]) -> PreparationError:
    """Zlecenie okresu ma puste ``SKUTECZNE`` albo wartość inną niż ``tak``/``nie``."""

    subject = "Zlecenie okresu ma" if len(row_numbers) == 1 else "Zlecenia okresu mają"
    return PreparationError(
        PreparationMessage(
            code="ZLE_SKUTECZNE",
            what=(
                f"{subject} puste albo nieznane SKUTECZNE (dozwolone: tak, nie). "
                "Nie utworzono żadnego pliku."
            ),
            where=f"{_register_location(register_path, sheet)}, {_rows_label(row_numbers)}",
            action=(
                "Wpisz tak albo nie w kolumnie SKUTECZNE we wskazanych wierszach Rejestru zleceń. "
                "Zapisz i zamknij Rejestr, i uruchom ponownie."
            ),
        )
    )


def unknown_workers(
    register_path: Path,
    sheet: str,
    config_path: Path,
    workers: Sequence[tuple[str, Sequence[int]]],
) -> PreparationError:
    """Zlecenie skuteczne ma wykonawcę spoza konfiguracji wykonawców Przebiegu rozliczeń.

    ``workers`` to pary: identyfikator wykonawcy i numery wierszy Rejestru z tym wykonawcą.
    """

    identifiers = ", ".join(identifier for identifier, _ in workers)
    subject = (
        "Zlecenie skuteczne ma wykonawcę"
        if len(workers) == 1 and len(workers[0][1]) == 1
        else "Zlecenia skuteczne mają wykonawców"
    )
    rows = "; ".join(f"{identifier}: {_rows_label(row_numbers)}" for identifier, row_numbers in workers)
    return PreparationError(
        PreparationMessage(
            code="NIEZNANY_WYKONAWCA",
            what=f"{subject} spoza konfiguracji wykonawców: {identifiers}. Nie utworzono żadnego pliku.",
            where=f"{_register_location(register_path, sheet)}, {rows}",
            action=(
                f"Dopisz identyfikator wykonawcy do konfiguracji wykonawców ({config_path.name}), "
                "tej samej co w Przebiegu rozliczeń, albo popraw WYKONAWCA we wskazanych wierszach "
                "Rejestru zleceń. Zapisz i zamknij Rejestr, i uruchom ponownie."
            ),
        )
    )


def no_period_orders(register_path: Path, sheet: str, period: str) -> PreparationError:
    """W Rejestrze nie ma żadnego zlecenia z wybranego okresu."""

    return PreparationError(
        PreparationMessage(
            code="BRAK_ZLECEN_OKRESU",
            what="W Rejestrze zleceń nie ma żadnego zlecenia z tego okresu. Nie utworzono żadnego pliku.",
            where=f"{_register_location(register_path, sheet)}, okres {period}",
            action=(
                "Sprawdź, czy wybrano właściwy okres i czy eksport zleceń do Rejestru został "
                "zrobiony i zapisany, i uruchom ponownie."
            ),
        )
    )


def too_few_zero_rows(
    collective_filename: str,
    successful_count: int,
    zero_row_count: int,
    first_row_without_zeros: int,
) -> PreparationMessage:
    """Ostrzeżenie: Zleceń skutecznych jest więcej niż wierszy Wzorca pliku zbiorczego z zerami."""

    last_row = first_row_without_zeros + successful_count - zero_row_count - 1
    rows = (
        f"wiersz {last_row}"
        if last_row == first_row_without_zeros
        else f"wiersze {first_row_without_zeros}–{last_row}"
    )
    return PreparationMessage(
        code="MALO_WIERSZY_Z_ZERAMI",
        what=(
            f"Zleceń skutecznych: {successful_count}, wierszy przygotowanych zerami we Wzorcu pliku "
            f"zbiorczego: {zero_row_count}. Dolne wiersze Pliku zbiorczego nie mają zer w kolumnach ilości."
        ),
        where=f"plik {collective_filename}, {rows}",
        action=(
            "Uzupełnij ilości w tych wierszach ręcznie. Jeśli zdarza się to często, przekaż to "
            "osobie utrzymującej narzędzie, żeby dodała wiersze z zerami we Wzorcu pliku zbiorczego."
        ),
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

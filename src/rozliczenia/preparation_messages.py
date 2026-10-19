"""Katalog komunikatów Przygotowania pliku zbiorczego dla taty.

Każdy komunikat ma trzy części: co się stało, gdzie, co zrobić. Komunikaty są
po polsku, bez żargonu i treści wyjątków oraz bez adresów, numerów zleceń i
treści wierszy. Wskazują wyłącznie plik, arkusz, nagłówek albo numer wiersza.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from openpyxl.utils import get_column_letter

from . import collective_file


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
    """Zatrzymanie Przygotowania pliku zbiorczego; żaden plik nie został utworzony, chyba że komunikat wskazuje pozostawiony plik."""

    def __init__(self, message: PreparationMessage) -> None:
        super().__init__(message.text)
        self.message = message


def _folder_label(directory: Path) -> str:
    return f"{directory.parent.name}\\{directory.name}" if directory.parent.name else directory.name


def _file_label(path: Path) -> str:
    return f"plik {path.name}, folder {path.parent.name}" if path.parent.name else f"plik {path.name}"


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
            action=(
                "Wpisz okres jak w nazwie folderu, np. 08_14_09_2026 (wtorek 8, poniedziałek 14 września 2026). "
                "Na przełomie miesięcy miesiąc i rok są z wtorku, np. 27_02_10_2026 "
                "(wtorek 27 października – poniedziałek 2 listopada 2026)."
            ),
        )
    )


def register_not_selected() -> PreparationError:
    """Okno wyboru pliku Rejestru zleceń zostało zamknięte bez wyboru."""

    return PreparationError(
        PreparationMessage(
            code="NIE_WYBRANO_REJESTRU",
            what="Nie wybrano pliku Rejestru zleceń. Nie utworzono żadnego pliku.",
            where="okno wyboru pliku Rejestru zleceń",
            action="Uruchom ponownie i wybierz plik ZLECENIA INTERMAX OD 08_11_2021.xlsx.",
        )
    )


def periods_directory_not_selected() -> PreparationError:
    """Okno wyboru folderu okresów zostało zamknięte bez wyboru."""

    return PreparationError(
        PreparationMessage(
            code="NIE_WYBRANO_FOLDERU_OKRESOW",
            what="Nie wybrano folderu okresów. Nie utworzono żadnego pliku.",
            where="okno wyboru folderu okresów",
            action="Uruchom ponownie i wybierz folder z poprzednimi tygodniami, np. INEA.",
        )
    )


def period_not_entered() -> PreparationError:
    """Tata nie potwierdził proponowanego okresu ani nie wpisał innego."""

    return PreparationError(
        PreparationMessage(
            code="NIE_PODANO_OKRESU",
            what="Nie potwierdzono okresu ani nie wpisano innego. Nie utworzono żadnego pliku.",
            where="pytanie o okres",
            action="Uruchom ponownie i naciśnij Enter, aby potwierdzić proponowany okres, albo wpisz inny.",
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


_REPORT_TO_MAINTAINER = "Przekaż ten komunikat osobie utrzymującej narzędzie."


def template_missing(template_path: Path) -> PreparationError:
    """Wzorzec rozliczenia wewnętrznego albo Wzorzec pliku zbiorczego nie istnieje."""

    return PreparationError(
        PreparationMessage(
            code="BRAK_WZORCA",
            what="Nie znaleziono wzorca, z którego powstają pliki okresu. Nie utworzono żadnego pliku.",
            where=_file_label(template_path),
            action=_REPORT_TO_MAINTAINER,
        )
    )


def template_open_in_excel(template_path: Path) -> PreparationError:
    """Wzorzec ma obok plik blokady Excela ``~$…``; narzędzie go nie usuwa."""

    return PreparationError(
        PreparationMessage(
            code="WZORZEC_OTWARTY",
            what="Wzorzec jest otwarty w Excelu. Nie utworzono żadnego pliku.",
            where=_file_label(template_path),
            action=(
                "Zamknij wzorzec w Excelu bez zapisywania zmian i uruchom ponownie. "
                "Jeśli Excel jest zamknięty, a komunikat wraca, usuń z tego samego folderu "
                f"pozostawiony plik ~${template_path.name} i uruchom ponownie."
            ),
        )
    )


def template_unreadable(template_path: Path) -> PreparationError:
    """Wzorzec nie daje się odczytać jako skoroszyt .xlsx."""

    return PreparationError(
        PreparationMessage(
            code="USZKODZONY_WZORZEC",
            what=(
                "Nie można odczytać wzorca. Plik jest uszkodzony "
                "albo nie jest skoroszytem .xlsx. Nie utworzono żadnego pliku."
            ),
            where=_file_label(template_path),
            action=_REPORT_TO_MAINTAINER,
        )
    )


def template_without_header(template_path: Path, sheet: str, row: int, header: str) -> PreparationError:
    """Wzorzec nie ma oczekiwanego nagłówka, więc nie wiadomo, gdzie wpisać zlecenia."""

    return PreparationError(
        PreparationMessage(
            code="ZLY_WZORZEC",
            what=(
                f"We wzorcu brakuje nagłówka {header}, więc nie wiadomo, gdzie wpisać zlecenia. "
                "Nie utworzono żadnego pliku."
            ),
            where=f"plik {template_path.name}, arkusz {sheet}, wiersz {row}",
            action=_REPORT_TO_MAINTAINER,
        )
    )


def template_with_worker_outside_h(template_path: Path, sheet: str, column: str) -> PreparationError:
    """Wzorzec pliku zbiorczego ma WYKONAWCA poza H17, a Przebieg rozliczeń czyta Wykonawcę z H17."""

    worker_column = get_column_letter(collective_file.WORKER_COLUMN)
    header_row = collective_file.HEADER_ROW
    return PreparationError(
        PreparationMessage(
            code="WYKONAWCA_POZA_H",
            what=(
                f"Wzorzec pliku zbiorczego ma nagłówek WYKONAWCA w kolumnie {column} "
                f"zamiast w {worker_column} (wiersz {header_row}). Nie utworzono żadnego pliku."
            ),
            where=f"plik {template_path.name}, arkusz {sheet}, wiersz {header_row}",
            action=f"Przenieś WYKONAWCA do kolumny {worker_column} we wzorcu i uruchom ponownie.",
        )
    )


def template_with_merged_cells(template_path: Path, sheet: str, cell_range: str) -> PreparationError:
    """Komórki wzorca, do których trafiają zlecenia, są scalone."""

    return PreparationError(
        PreparationMessage(
            code="SCALONE_KOMORKI_WZORCA",
            what=(
                "We wzorcu są scalone komórki tam, gdzie trafiają zlecenia, więc nie można ich wpisać. "
                "Nie utworzono żadnego pliku."
            ),
            where=f"plik {template_path.name}, arkusz {sheet}, komórki {cell_range}",
            action=_REPORT_TO_MAINTAINER,
        )
    )


def register_missing(register_path: Path) -> PreparationError:
    """Rejestr zleceń nie istnieje pod wskazaną ścieżką."""

    return PreparationError(
        PreparationMessage(
            code="BRAK_REJESTRU",
            what="Nie znaleziono Rejestru zleceń. Nie utworzono żadnego pliku.",
            where=_file_label(register_path),
            action="Wybierz właściwy plik Rejestru zleceń i uruchom ponownie.",
        )
    )


def register_open_in_excel(register_path: Path) -> PreparationError:
    """Rejestr zleceń ma obok plik blokady Excela ``~$…``; narzędzie go nie usuwa."""

    return PreparationError(
        PreparationMessage(
            code="REJESTR_OTWARTY",
            what="Rejestr zleceń jest otwarty w Excelu. Nie utworzono żadnego pliku.",
            where=_file_label(register_path),
            action=(
                "Zapisz i zamknij Rejestr zleceń w Excelu, potem uruchom ponownie. "
                "Jeśli Excel jest zamknięty, a komunikat wraca, usuń z tego samego folderu "
                f"pozostawiony plik ~${register_path.name} i uruchom ponownie."
            ),
        )
    )


def register_unreadable(register_path: Path) -> PreparationError:
    """Rejestr zleceń nie daje się odczytać jako skoroszyt .xlsx."""

    return PreparationError(
        PreparationMessage(
            code="USZKODZONY_REJESTR",
            what=(
                "Nie można odczytać Rejestru zleceń. Plik jest uszkodzony "
                "albo nie jest skoroszytem .xlsx. Nie utworzono żadnego pliku."
            ),
            where=_file_label(register_path),
            action=(
                "Sprawdź, czy Rejestr zleceń otwiera się w Excelu i jest zapisany jako .xlsx, "
                "zamknij go i uruchom ponownie. Jeśli błąd wraca, przekaż to osobie utrzymującej narzędzie."
            ),
        )
    )


def _header_list(headers: Sequence[str]) -> str:
    return ", ".join(headers)


def register_without_headers(register_path: Path, sheet: str, headers: Sequence[str]) -> PreparationError:
    """Arkusz ze zleceniami nie ma w pierwszym wierszu wszystkich wymaganych nagłówków."""

    single = len(headers) == 1
    noun = "wymaganego nagłówka" if single else "wymaganych nagłówków"
    fix = "nagłówek" if single else "nagłówki"
    return PreparationError(
        PreparationMessage(
            code="BRAK_NAGLOWKA_REJESTRU",
            what=f"W Rejestrze zleceń brakuje {noun} {_header_list(headers)}. Nie utworzono żadnego pliku.",
            where=f"plik {register_path.name}, arkusz {sheet}, wiersz 1",
            action=(
                f"Dopisz albo popraw {fix} {_header_list(headers)} w pierwszym wierszu arkusza ze zleceniami, "
                "zapisz i zamknij Rejestr zleceń i uruchom ponownie."
            ),
        )
    )


def register_with_duplicated_headers(register_path: Path, sheet: str, headers: Sequence[str]) -> PreparationError:
    """Wymagany nagłówek występuje w pierwszym wierszu arkusza ze zleceniami więcej niż raz."""

    single = len(headers) == 1
    return PreparationError(
        PreparationMessage(
            code="POWTORZONY_NAGLOWEK_REJESTRU",
            what=(
                f"W Rejestrze zleceń {'nagłówek' if single else 'nagłówki'} {_header_list(headers)} "
                f"{'występuje' if single else 'występują'} więcej niż raz, "
                "więc nie wiadomo, z której kolumny brać dane. Nie utworzono żadnego pliku."
            ),
            where=f"plik {register_path.name}, arkusz {sheet}, wiersz 1",
            action=(
                f"Zostaw {'nagłówek' if single else 'każdy z nagłówków'} {_header_list(headers)} "
                "tylko w jednej kolumnie, zapisz i zamknij Rejestr zleceń i uruchom ponownie."
            ),
        )
    )


def register_without_data_sheet(register_path: Path, required_headers: Sequence[str]) -> PreparationError:
    """Żaden arkusz Rejestru nie ma wymaganych nagłówków w pierwszym wierszu."""

    return PreparationError(
        PreparationMessage(
            code="BRAK_ARKUSZA_ZLECEN",
            what=(
                "W Rejestrze zleceń nie znaleziono arkusza ze zleceniami, czyli arkusza "
                "z wymaganymi nagłówkami w pierwszym wierszu. Nie utworzono żadnego pliku."
            ),
            where=f"plik {register_path.name}",
            action=(
                "Sprawdź, czy wybrano właściwy plik Rejestru zleceń. Pierwszy wiersz arkusza "
                f"ze zleceniami musi zawierać nagłówki: {_header_list(required_headers)}."
            ),
        )
    )


def period_orders_in_many_sheets(register_path: Path, sheets: Sequence[str], period: str) -> PreparationError:
    """Zlecenia okresu leżą w więcej niż jednym arkuszu ze zleceniami."""

    return PreparationError(
        PreparationMessage(
            code="ZLECENIA_W_WIELU_ARKUSZACH",
            what=(
                "Zlecenia tego okresu są w więcej niż jednym arkuszu Rejestru zleceń, "
                "więc nie wiadomo, który arkusz jest właściwy. Nie utworzono żadnego pliku."
            ),
            where=f"plik {register_path.name}, arkusze {', '.join(sheets)}, okres {period}",
            action=(
                "Zostaw zlecenia tego okresu tylko w jednym arkuszu, "
                "zapisz i zamknij Rejestr zleceń i uruchom ponownie."
            ),
        )
    )


def periods_directory_missing(periods_directory: Path) -> PreparationError:
    """Wybrany folder okresów nie istnieje; narzędzie go nie zakłada."""

    return PreparationError(
        PreparationMessage(
            code="BRAK_FOLDERU_OKRESOW",
            what="Nie znaleziono folderu okresów. Nie utworzono żadnego pliku.",
            where=f"folder {_folder_label(periods_directory)}",
            action=(
                "Wybierz istniejący folder okresów, w którym są foldery poprzednich tygodni, "
                "i uruchom ponownie."
            ),
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


INCOMPLETE_PERIOD = "NIEPELNY_OKRES"
# Dzień tygodnia w dopełniaczu, z przyimkiem (``date.weekday()``: 0 = poniedziałek).
_FROM_WEEKDAY = ("z poniedziałku", "z wtorku", "ze środy", "z czwartku", "z piątku", "z soboty", "z niedzieli")


def incomplete_period(
    register_path: Path, sheet: str, period: str, last_order_day: date, monday: date
) -> PreparationMessage:
    """Ostrzeżenie: ostatnie zlecenie okresu jest sprzed poniedziałku okresu."""

    return PreparationMessage(
        code=INCOMPLETE_PERIOD,
        what=(
            f"Ostatnie zlecenie okresu jest {_FROM_WEEKDAY[last_order_day.weekday()]} {last_order_day:%d.%m.%Y}, "
            f"a okres kończy się w poniedziałek {monday:%d.%m.%Y}. Rejestr zleceń może nie mieć jeszcze "
            "wszystkich zleceń tego okresu."
        ),
        where=f"{_register_location(register_path, sheet)}, okres {period}",
        action=(
            "Sprawdź liczby zleceń na dzień. Jeśli brakuje zleceń, przerwij, uzupełnij eksport w Rejestrze "
            "zleceń, zapisz go i uruchom ponownie. Jeśli okres jest pełny, kontynuuj."
        ),
    )


def incomplete_period_refused(period: str, continue_hint: str) -> PreparationError:
    """Tata nie zgodził się kontynuować po ostrzeżeniu o niepełnym okresie.

    ``continue_hint`` mówi, jak u rozmówcy wyraża się zgodę, np. „przy pytaniu wpisz t”.
    """

    return PreparationError(
        PreparationMessage(
            code="PRZERWANO_NIEPELNY_OKRES",
            what="Przerwano z powodu niepełnego okresu, zgodnie z odpowiedzią. Nie utworzono żadnego pliku.",
            where=f"okres {period}",
            action=(
                "Uzupełnij eksport zleceń w Rejestrze zleceń, zapisz go, zamknij i uruchom ponownie. "
                f"Jeśli okres jest pełny, {continue_hint}."
            ),
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


def write_failed_with_file_left(period_directory: Path, filename: str) -> PreparationError:
    """Publikacja nie powiodła się, a już opublikowanego pliku okresu nie udało się usunąć."""

    return PreparationError(
        PreparationMessage(
            code="BLAD_ZAPISU_POZOSTAL_PLIK",
            what="Zapisano tylko jeden z dwóch plików okresu i nie udało się go usunąć.",
            where=f"folder {_folder_label(period_directory)}, plik {filename}",
            action=(
                "Usuń wskazany plik, bo bez drugiego pliku okresu jest niepełny, i uruchom ponownie. "
                "Jeśli nie daje się go usunąć, odczekaj chwilę. Jeśli błąd wraca, przekaż komunikat "
                "osobie utrzymującej narzędzie."
            ),
        )
    )


def unexpected_failure() -> PreparationMessage:
    """Nieprzewidziany błąd; treść wyjątku nie trafia do taty."""

    return PreparationMessage(
        code="BLAD_NIEOCZEKIWANY",
        what="Wystąpił nieoczekiwany błąd. Nie utworzono żadnego pliku.",
        where="Przygotowanie pliku zbiorczego",
        action="Uruchom ponownie. Jeśli błąd wraca, przekaż to osobie utrzymującej narzędzie.",
    )


def summary_not_shown(*, warns_against_rerun: bool = False) -> PreparationMessage:
    """Pliki okresu powstały, ale podsumowania nie dało się pokazać; treść wyjątku nie trafia do taty.

    W terminalu „nie uruchamiaj ponownie” mówi tabela w instrukcji. Gdzie tata
    nie zagląda do tabeli (Centrum rozliczeń), ``warns_against_rerun`` dopisuje
    to do „Co zrobić”.
    """

    check = "Sprawdź Folder okresu i przekaż ten komunikat osobie utrzymującej narzędzie."
    return PreparationMessage(
        code="BLAD_PODSUMOWANIA",
        what="Pliki okresu powstały, ale nie udało się pokazać podsumowania.",
        where="Przygotowanie pliku zbiorczego",
        action=f"Nie uruchamiaj ponownie: oba pliki okresu już są. {check}" if warns_against_rerun else check,
    )


def plan_not_shown() -> PreparationMessage:
    """DRY-RUN skończył się, ale planu nie dało się pokazać; nic nie zapisano."""

    return PreparationMessage(
        code="BLAD_PLANU",
        what="Nie udało się pokazać planu. Nic nie zapisano.",
        where="Przygotowanie pliku zbiorczego",
        action="Przekaż ten komunikat osobie utrzymującej narzędzie.",
    )

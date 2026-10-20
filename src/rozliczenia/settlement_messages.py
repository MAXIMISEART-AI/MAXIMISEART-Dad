"""Katalog Komunikatów Przebiegu rozliczeń: zatrzymania i problemy z podsumowania dla taty.

Każda fabryka zwraca Komunikat (``message.Message``) w trzech częściach: co się
stało, gdzie, co zrobić. Zatrzymanie to ``raise StopError(fabryka(...))``.
Części nie zawierają pełnych ścieżek ani treści wierszy: wskazują tylko nazwę
pliku, folder okresu, kolumnę albo Wykonawcę z konfiguracji wykonawców.

Terminal pokazuje zatrzymanie jedną linią po „Nie wykonano: ”, bez zmian od
pierwszej wersji (``Message.terminal_line``, ADR 0004). Ta linia może
zawierać pełną ścieżkę i nie trafia do Centrum rozliczeń, które pokazuje trzy
części.
"""

from __future__ import annotations

from pathlib import Path
from typing import Final

from .domain import Issue
from .message import REPORT_TO_MAINTAINER, Message, file_label, folder_label
from .period_folder import PeriodFolderLookupError, month_folder_label
from .workbook_files import WORKER_HEADER
from .worker_config import WorkerConfigError

_NOTHING_CREATED: Final = "Nie utworzono żadnego pliku pracownika."
_RETRY: Final = "Uruchom ponownie. Jeśli błąd wraca, przekaż ten komunikat osobie utrzymującej narzędzie."
_PREVIEW_PROBLEMS: Final = "Uruchom Podgląd bez zapisu: lista problemów pokaże wiersze."
_SAVE_AND_RETRY: Final = "Potem zapisz i zamknij Plik zbiorczy w Excelu i uruchom ponownie."


def collective_file_not_selected() -> Message:
    """Tylko terminal: tata zamknął okno wyboru Pliku zbiorczego."""

    return Message(
        code="NIE_WYBRANO_PLIKU_ZBIORCZEGO",
        what=f"Nie wybrano Pliku zbiorczego. {_NOTHING_CREATED}",
        where="okno wyboru pliku",
        action="Uruchom ponownie i wybierz Plik zbiorczy okresu.",
        terminal_line="Nie wybrano pliku zbiorczego.",
    )


def period_not_entered() -> Message:
    """Tylko terminal: tata nie potwierdził proponowanego okresu ani nie wpisał innego."""

    return Message(
        code="NIE_PODANO_OKRESU",
        what=f"Nie potwierdzono okresu ani nie wpisano innego. {_NOTHING_CREATED}",
        where="pytanie o okres",
        action="Uruchom ponownie i naciśnij Enter, aby potwierdzić proponowany okres, albo wpisz inny.",
        terminal_line="Nie podano okresu.",
    )


def invalid_period_token(token: str) -> Message:
    """Tylko terminal: wpisany okres nie opisuje przedziału od wtorku do poniedziałku; pytanie wraca."""

    return Message(
        code="ZLY_TOKEN_OKRESU",
        what="Okres nie ma postaci dd_dd_mm_rrrr od wtorku do poniedziałku.",
        where=f"okres {token!r}",
        action=(
            "Wpisz okres jak w nazwie folderu, np. 08_14_09_2026 (wtorek 8, poniedziałek 14 września 2026). "
            "Na przełomie miesięcy miesiąc i rok są z poniedziałku, np. 27_02_11_2026 "
            "(wtorek 27 października – poniedziałek 2 listopada 2026)."
        ),
    )


def period_folder_lookup_problem(error: PeriodFolderLookupError) -> Message:
    """Tylko terminal: w układzie folderów taty Folderu okresu nie ma albo jest w kilku miesiącach."""

    token = error.period.token
    if not error.locations:
        return Message(
            code="BRAK_FOLDERU_OKRESU",
            what=f"Nie znaleziono folderu {token} w żadnym folderze miesiąca. {_NOTHING_CREATED}",
            where=f"foldery INEA w folderze {error.periods_directory.name}",
            action=f"Najpierw przygotuj plik zbiorczy okresu {token} w jego folderze i uruchom ponownie.",
            terminal_line=f"Nie znaleziono folderu {token} w żadnym folderze miesiąca.",
        )
    months = ", ".join(month_folder_label(error.periods_directory, location) for location in error.locations)
    return Message(
        code="POWTORZONY_FOLDER_OKRESU",
        what=f"Folder {token} jest w więcej niż jednym folderze miesiąca. {_NOTHING_CREATED}",
        where=months,
        action=f"Zostaw folder {token} tylko w jednym folderze miesiąca: drugi usuń albo zmień mu nazwę. Potem uruchom ponownie.",
        terminal_line=f"Folder {token} jest w więcej niż jednym folderze miesiąca: {months}.",
    )


def collective_file_missing(source: Path) -> Message:
    return Message(
        code="BRAK_PLIKU_ZBIORCZEGO",
        what=f"Nie znaleziono Pliku zbiorczego tego okresu. {_NOTHING_CREATED}",
        where=file_label(source),
        action=(
            "Sprawdź, czy Plik zbiorczy leży w Folderze okresu pod tą nazwą, i uruchom ponownie. "
            "Jeśli okresu jeszcze nie przygotowano, najpierw przygotuj plik zbiorczy."
        ),
        terminal_line=f"Nie znaleziono pliku źródłowego: {source}",
    )


def collective_file_open(source: Path) -> Message:
    """Plik zbiorczy ma obok plik blokady Excela ``~$…``."""

    return Message(
        code="PLIK_ZBIORCZY_OTWARTY",
        what=f"Plik zbiorczy jest otwarty w Excelu. {_NOTHING_CREATED}",
        where=file_label(source),
        action=(
            "Zapisz i zamknij Plik zbiorczy w Excelu i uruchom ponownie. Jeśli Excel jest zamknięty, "
            f"a komunikat wraca, usuń z tego samego folderu pozostawiony plik ~${source.name} i uruchom ponownie."
        ),
        terminal_line=f"Plik jest otwarty lub zablokowany: {source.name}",
    )


def collective_file_invalid(source: Path, detail: str) -> Message:
    """Nazwa, folder albo układ Pliku zbiorczego.

    ``detail`` to ``message`` z ``PeriodFolderError`` albo opis problemu z odczytem, nie tekst wyjątku.
    """

    return Message(
        code="ZLY_PLIK_ZBIORCZY",
        what=f"Plik zbiorczy nie nadaje się do Przebiegu rozliczeń. {detail}",
        where=file_label(source),
        action=f"Popraw Plik zbiorczy w Excelu. {_SAVE_AND_RETRY} Jeśli błąd wraca, {REPORT_TO_MAINTAINER.lower()}",
        terminal_line=detail,
    )


def collective_file_unreadable(source: Path) -> Message:
    """Plik zbiorczy nie daje się odczytać jako skoroszyt .xlsx."""

    return collective_file_invalid(
        source,
        f"Nie można odczytać Pliku zbiorczego {source.name}. Sprawdź, czy plik otwiera się w Excelu i nie jest uszkodzony.",
    )


def collective_file_without_worker_header(source: Path) -> Message:
    """Plik zbiorczy nie ma nagłówka WYKONAWCA w H17, skąd Przebieg rozliczeń czyta Wykonawcę."""

    return collective_file_invalid(
        source, f"W wierszu {WORKER_HEADER.row} nie znaleziono nagłówka WYKONAWCA w kolumnie {WORKER_HEADER.column}."
    )


def worker_settlements_exist(target_directory: Path) -> Message:
    """Nienadpisywanie: Folder rozliczeń pracowników okresu już istnieje."""

    return Message(
        code="FOLDER_ROZLICZEN_ISTNIEJE",
        what=f"Folder rozliczeń pracowników tego okresu już istnieje, więc nie został nadpisany. {_NOTHING_CREATED}",
        where=folder_label(target_directory),
        action=(
            "Sprawdź, czy wybrano właściwy okres. Rozliczenia pracowników tego okresu już są w Folderze okresu. "
            "Jeśli trzeba je utworzyć od nowa, najpierw przenieś ten folder poza Folder okresu i uruchom ponownie."
        ),
        terminal_line=f"Folder docelowy już istnieje: {target_directory.name}.",
    )


def worker_config_problem(config_path: Path, error: WorkerConfigError) -> Message:
    """Konfiguracji wykonawców nie da się użyć; ``error.detail`` nie zawiera ścieżki."""

    terminal_lines = {
        "unreadable": f"Nie można odczytać konfiguracji: {config_path}",
        "not_utf8": f"Konfiguracja nie jest zapisana w UTF-8: {config_path}",
        "not_yaml": f"Niepoprawny YAML konfiguracji: {config_path}",
        "invalid": error.detail,
    }
    return Message(
        code="ZLA_KONFIGURACJA_WYKONAWCOW",
        what=f"Konfiguracja wykonawców jest niepoprawna. {error.detail}",
        where=file_label(config_path),
        action=REPORT_TO_MAINTAINER,
        terminal_line=terminal_lines[error.reason],
    )


def worker_template_invalid(template_path: Path, detail: str) -> Message:
    """Wzorzec rozliczenia pracownika nie przeszedł Sprawdzania; ``detail`` to ``WorkerTemplateValidationError.message``."""

    return Message(
        code="ZLY_WZORZEC_PRACOWNIKA",
        what=f"Nie można użyć Wzorca rozliczenia pracownika. {detail}",
        where=file_label(template_path),
        action=(
            "Jeśli Wzorzec jest otwarty w Excelu, zamknij go bez zapisywania zmian i uruchom ponownie. "
            f"W innym wypadku {REPORT_TO_MAINTAINER.lower()}"
        ),
        terminal_line=detail,
    )


def unmapped_worker(source: Path) -> Message:
    """RUN: WYKONAWCA z Pliku zbiorczego nie ma wpisu w konfiguracji wykonawców."""

    return Message(
        code="NIEZNANY_WYKONAWCA",
        what=(
            "W Pliku zbiorczym jest WYKONAWCA, którego nie ma w konfiguracji wykonawców. "
            f"{_NOTHING_CREATED}"
        ),
        where=f"{file_label(source)}, kolumna H",
        action=(
            f"{_PREVIEW_PROBLEMS} Popraw WYKONAWCĘ w kolumnie H albo poproś osobę utrzymującą narzędzie "
            f"o dopisanie Wykonawcy do konfiguracji wykonawców. {_SAVE_AND_RETRY}"
        ),
        terminal_line="WYKONAWCA bez mapowania; folder wynikowy nie został opublikowany.",
    )


def rows_without_worker(source: Path) -> Message:
    """RUN: Wiersz danych bez WYKONAWCY."""

    return Message(
        code="WIERSZE_BEZ_WYKONAWCY",
        what=f"Nie wszystkie Wiersze danych Pliku zbiorczego mają WYKONAWCĘ. {_NOTHING_CREATED}",
        where=f"{file_label(source)}, kolumna H",
        action=f"{_PREVIEW_PROBLEMS} Wpisz WYKONAWCĘ w kolumnie H tych wierszy. {_SAVE_AND_RETRY}",
        terminal_line="Nie wszystkie wiersze danych mają przypisanego WYKONAWCĘ; folder wynikowy nie został opublikowany.",
    )


def worker_file_failed(target_directory: Path, worker_name: str) -> Message:
    return Message(
        code="BLAD_SZABLONU_PRACOWNIKA",
        what=f"Nie udało się przygotować skoroszytu pracownika {worker_name}. {_NOTHING_CREATED}",
        where=folder_label(target_directory),
        action=_RETRY,
        terminal_line=f"Nie udało się przygotować skoroszytu pracownika {worker_name}; folder wynikowy nie został opublikowany.",
    )


def worker_files_not_copied(template_path: Path) -> Message:
    return Message(
        code="BLAD_KOPII_WZORCA",
        what=f"Nie można utworzyć skoroszytów z Wzorca rozliczenia pracownika. {_NOTHING_CREATED}",
        where=file_label(template_path),
        action=_RETRY,
        terminal_line="Nie można utworzyć skoroszytów z Wzorca rozliczenia pracownika; folder wynikowy nie został opublikowany.",
    )


def publish_failed(target_directory: Path) -> Message:
    return Message(
        code="BLAD_PUBLIKACJI",
        what=f"Nie można opublikować gotowego Folderu rozliczeń pracowników. {_NOTHING_CREATED}",
        where=folder_label(target_directory),
        action=f"Sprawdź, czy Folder okresu jest dostępny. {_RETRY}",
        terminal_line="Nie można opublikować gotowego folderu rozliczeń pracowników.",
    )


def write_failed(target_directory: Path) -> Message:
    return Message(
        code="BLAD_ZAPISU",
        what=f"Nie można przygotować Folderu rozliczeń pracowników. {_NOTHING_CREATED}",
        where=folder_label(target_directory),
        action=f"Sprawdź, czy Folder okresu jest dostępny. {_RETRY}",
        terminal_line="Nie można przygotować folderu rozliczeń pracowników; folder wynikowy nie został opublikowany.",
    )


def unexpected_failure() -> Message:
    """Nieprzewidziany błąd; treść wyjątku nie trafia do taty."""

    return Message(
        code="BLAD_NIEOCZEKIWANY",
        what=f"Wystąpił nieoczekiwany błąd. {_NOTHING_CREATED}",
        where="Przebieg rozliczeń",
        action=_RETRY,
        terminal_line=(
            "Wystąpił nieoczekiwany błąd; folder rozliczeń pracowników nie został opublikowany. "
            "Uruchom ponownie; jeśli błąd wraca, przekaż to osobie utrzymującej narzędzie."
        ),
    )


def summary_not_shown() -> Message:
    """Folder rozliczeń pracowników powstał, ale podsumowania nie dało się pokazać."""

    return Message(
        code="BLAD_PODSUMOWANIA",
        what="Rozliczenia pracowników powstały, ale nie udało się pokazać podsumowania.",
        where="Przebieg rozliczeń",
        action=(
            "Nie uruchamiaj ponownie: Folder rozliczeń pracowników już jest. "
            "Sprawdź Folder okresu i przekaż ten komunikat osobie utrzymującej narzędzie."
        ),
        terminal_line=(
            "Rozliczenia pracowników powstały, ale nie udało się pokazać podsumowania. "
            "Sprawdź Folder okresu i przekaż ten komunikat osobie utrzymującej narzędzie."
        ),
    )


def plan_not_shown() -> Message:
    """DRY-RUN skończył się, ale planu nie dało się pokazać; nic nie zapisano."""

    return Message(
        code="BLAD_PLANU",
        what="Nie udało się pokazać planu. Nic nie zapisano.",
        where="Przebieg rozliczeń",
        action=REPORT_TO_MAINTAINER,
        terminal_line=f"Nie udało się pokazać planu. DRY-RUN: Nic nie zapisano. {REPORT_TO_MAINTAINER}",
    )


_ISSUE_ACTIONS: Final[dict[str, str]] = {
    "BRAK_MAPOWANIA": (
        "Popraw WYKONAWCĘ w kolumnie H albo poproś osobę utrzymującą narzędzie o dopisanie Wykonawcy "
        f"do konfiguracji wykonawców. {_SAVE_AND_RETRY}"
    ),
    "BRAK_WYKONAWCY": f"Wpisz WYKONAWCĘ w kolumnie H tego wiersza. {_SAVE_AND_RETRY}",
}


def issue_message(issue: Issue, source: Path) -> Message:
    """Problem z podsumowania (wynik „Wymaga sprawdzenia”) w trzech częściach; „Co się stało” to linia terminala."""

    return Message(
        code=issue.code,
        what=issue.message,
        where=file_label(source),
        action=_ISSUE_ACTIONS.get(issue.code, REPORT_TO_MAINTAINER),
    )

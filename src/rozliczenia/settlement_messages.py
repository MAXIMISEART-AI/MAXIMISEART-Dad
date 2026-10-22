"""Katalog Komunikatów Przebiegu rozliczeń: zatrzymania i problemy z podsumowania dla taty.

Każda fabryka zwraca Komunikat (``message.Message``) w trzech częściach: co się
stało, gdzie, co zrobić. Zatrzymanie to ``raise StopError(fabryka(...))``.
Części nie zawierają pełnych ścieżek ani treści wierszy: wskazują tylko nazwę
pliku, folder okresu, kolumnę albo Wykonawcę z konfiguracji wykonawców.
"""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from typing import Final

from .domain import Issue
from .message import REPORT_TO_MAINTAINER, Message, file_label, folder_label
from .workbook_files import WORKER_HEADER
from .worker_config import WorkerConfigError

_NOTHING_CREATED: Final = "Nie utworzono żadnego pliku pracownika."
_STAGING_LEFT: Final = "Pliki pracowników zostały w folderze tymczasowym, którego nie udało się usunąć."
_RETRY: Final = "Uruchom ponownie. Jeśli błąd wraca, przekaż ten komunikat osobie utrzymującej narzędzie."
_PREVIEW_PROBLEMS: Final = "Uruchom Podgląd bez zapisu: lista problemów pokaże wiersze."
_SAVE_AND_RETRY: Final = "Potem zapisz i zamknij Plik zbiorczy w Excelu i uruchom ponownie."


def collective_file_missing(source: Path) -> Message:
    return Message(
        code="BRAK_PLIKU_ZBIORCZEGO",
        what=f"Nie znaleziono Pliku zbiorczego tego okresu. {_NOTHING_CREATED}",
        where=file_label(source),
        action=(
            "Sprawdź, czy Plik zbiorczy leży w Folderze okresu pod tą nazwą, i uruchom ponownie. "
            "Jeśli okresu jeszcze nie przygotowano, najpierw przygotuj plik zbiorczy."
        ),
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
    )


def collective_file_inaccessible(source: Path) -> Message:
    """System nie oddał bajtów Pliku zbiorczego (np. zajęty przez inny program albo OneDrive bez sieci); to nie uszkodzenie."""

    return Message(
        code="NIEDOSTEPNY_PLIK_ZBIORCZY",
        what=(
            "Nie można teraz odczytać Pliku zbiorczego. Plik może być zajęty przez inny program "
            f"albo czekać na pobranie z OneDrive. {_NOTHING_CREATED}"
        ),
        where=file_label(source),
        action=(
            "Poczekaj, aż OneDrive skończy synchronizację, i sprawdź, czy Plik zbiorczy otwiera się w Excelu. "
            f"Zamknij go i uruchom ponownie. Jeśli błąd wraca, {REPORT_TO_MAINTAINER.lower()}"
        ),
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
            "Jeśli trzeba je utworzyć od nowa, najpierw przenieś Folder rozliczeń pracowników poza Folder okresu i uruchom ponownie."
        ),
    )


def worker_config_problem(config_path: Path, error: WorkerConfigError) -> Message:
    """Konfiguracji wykonawców nie da się użyć; ``error.detail`` nie zawiera ścieżki."""

    return Message(
        code="ZLA_KONFIGURACJA_WYKONAWCOW",
        what=f"Konfiguracja wykonawców jest niepoprawna. {error.detail}",
        where=file_label(config_path),
        action=REPORT_TO_MAINTAINER,
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
    )


def rows_without_worker(source: Path) -> Message:
    """RUN: Wiersz danych bez WYKONAWCY."""

    return Message(
        code="WIERSZE_BEZ_WYKONAWCY",
        what=f"Nie wszystkie Wiersze danych Pliku zbiorczego mają WYKONAWCĘ. {_NOTHING_CREATED}",
        where=f"{file_label(source)}, kolumna H",
        action=f"{_PREVIEW_PROBLEMS} Wpisz WYKONAWCĘ w kolumnie H tych wierszy. {_SAVE_AND_RETRY}",
    )


def worker_file_failed(target_directory: Path, worker_name: str) -> Message:
    return Message(
        code="BLAD_SZABLONU_PRACOWNIKA",
        what=f"Nie udało się przygotować skoroszytu pracownika {worker_name}. {_NOTHING_CREATED}",
        where=folder_label(target_directory),
        action=_RETRY,
    )


def worker_files_not_copied(template_path: Path) -> Message:
    return Message(
        code="BLAD_KOPII_WZORCA",
        what=f"Nie można utworzyć skoroszytów z Wzorca rozliczenia pracownika. {_NOTHING_CREATED}",
        where=file_label(template_path),
        action=_RETRY,
    )


def publish_failed(target_directory: Path) -> Message:
    return Message(
        code="BLAD_PUBLIKACJI",
        what=f"Nie można opublikować gotowego Folderu rozliczeń pracowników. {_NOTHING_CREATED}",
        where=folder_label(target_directory),
        action=f"Sprawdź, czy Folder okresu jest dostępny. {_RETRY}",
    )


def write_failed(target_directory: Path) -> Message:
    return Message(
        code="BLAD_ZAPISU",
        what=f"Nie można przygotować Folderu rozliczeń pracowników. {_NOTHING_CREATED}",
        where=folder_label(target_directory),
        action=f"Sprawdź, czy Folder okresu jest dostępny. {_RETRY}",
    )


def staging_left(message: Message, staging_name: str) -> Message:
    """Zatrzymanie ``message``, po którym w Folderze okresu został folder tymczasowy z plikami pracowników.

    Folderu nie dało się usunąć, np. bo jego pliki trzyma OneDrive.
    """

    return replace(
        message,
        what=message.what.replace(_NOTHING_CREATED, _STAGING_LEFT),
        action=(
            f"Usuń z Folderu okresu folder {staging_name}, bo nie jest Folderem rozliczeń pracowników. "
            f"Jeśli nie daje się go usunąć, odczekaj chwilę. {message.action}"
        ),
    )


def unexpected_failure() -> Message:
    """Nieprzewidziany błąd; treść wyjątku nie trafia do taty."""

    return Message(
        code="BLAD_NIEOCZEKIWANY",
        what=f"Wystąpił nieoczekiwany błąd. {_NOTHING_CREATED}",
        where="Przebieg rozliczeń",
        action=_RETRY,
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
    )


def plan_not_shown() -> Message:
    """DRY-RUN skończył się, ale planu nie dało się pokazać; nic nie zapisano."""

    return Message(
        code="BLAD_PLANU",
        what="Nie udało się pokazać planu. Nic nie zapisano.",
        where="Przebieg rozliczeń",
        action=REPORT_TO_MAINTAINER,
    )


_ISSUE_ACTIONS: Final[dict[str, str]] = {
    "BRAK_MAPOWANIA": (
        "Popraw WYKONAWCĘ w kolumnie H albo poproś osobę utrzymującą narzędzie o dopisanie Wykonawcy "
        f"do konfiguracji wykonawców. {_SAVE_AND_RETRY}"
    ),
    "BRAK_WYKONAWCY": f"Wpisz WYKONAWCĘ w kolumnie H tego wiersza. {_SAVE_AND_RETRY}",
}


def issue_message(issue: Issue, source: Path) -> Message:
    """Problem z podsumowania (wynik „Wymaga sprawdzenia”) w trzech częściach."""

    return Message(
        code=issue.code,
        what=issue.message,
        where=file_label(source),
        action=_ISSUE_ACTIONS.get(issue.code, REPORT_TO_MAINTAINER),
    )

"""Katalog zatrzymań Przebiegu rozliczeń: linia terminala i ten sam komunikat w trzech częściach dla Centrum.

Terminal pokazuje jedną linię (``str(error)``, po „Nie wykonano: ”), bez
zmian od pierwszej wersji. Centrum rozliczeń pokazuje każde zatrzymanie w
trzech częściach (``error.message``): co się stało, gdzie, co zrobić. Części
nie zawierają pełnych ścieżek ani treści wierszy: wskazują tylko nazwę pliku,
folder okresu, kolumnę albo Wykonawcę z konfiguracji wykonawców.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Final

from .domain import Issue

_NOTHING_CREATED: Final = "Nie utworzono żadnego pliku pracownika."
_REPORT_TO_MAINTAINER: Final = "Przekaż ten komunikat osobie utrzymującej narzędzie."
_RETRY: Final = "Uruchom ponownie. Jeśli błąd wraca, przekaż ten komunikat osobie utrzymującej narzędzie."
_PREVIEW_PROBLEMS: Final = "Uruchom Podgląd bez zapisu: lista problemów pokaże wiersze."
_SAVE_AND_RETRY: Final = "Potem zapisz i zamknij Plik zbiorczy w Excelu i uruchom ponownie."


@dataclass(frozen=True)
class SettlementMessage:
    """Zatrzymanie albo problem Przebiegu rozliczeń w trzech częściach."""

    code: str
    what: str
    where: str
    action: str

    @property
    def text(self) -> str:
        return f"Co się stało: {self.what}\nGdzie: {self.where}\nCo zrobić: {self.action}"


class SettlementError(Exception):
    """Błąd uniemożliwiający bezpieczne rozpoczęcie albo dokończenie Przebiegu rozliczeń.

    ``str(error)`` to linia terminala; ``message`` to ten sam komunikat w trzech częściach.
    """

    def __init__(self, line: str, message: SettlementMessage) -> None:
        super().__init__(line)
        self.message = message


def _file_label(path: Path) -> str:
    return f"plik {path.name}, folder {path.parent.name}" if path.parent.name else f"plik {path.name}"


def _folder_label(directory: Path) -> str:
    return f"folder {directory.parent.name}\\{directory.name}" if directory.parent.name else f"folder {directory.name}"


def collective_file_not_selected() -> SettlementError:
    """Tylko terminal: tata zamknął okno wyboru Pliku zbiorczego."""

    return SettlementError(
        "Nie wybrano pliku zbiorczego.",
        SettlementMessage(
            code="NIE_WYBRANO_PLIKU_ZBIORCZEGO",
            what=f"Nie wybrano Pliku zbiorczego. {_NOTHING_CREATED}",
            where="okno wyboru pliku",
            action="Uruchom ponownie i wybierz Plik zbiorczy okresu.",
        ),
    )


def collective_file_missing(source: Path) -> SettlementError:
    return SettlementError(
        f"Nie znaleziono pliku źródłowego: {source}",
        SettlementMessage(
            code="BRAK_PLIKU_ZBIORCZEGO",
            what=f"Nie znaleziono Pliku zbiorczego tego okresu. {_NOTHING_CREATED}",
            where=_file_label(source),
            action=(
                "Sprawdź, czy Plik zbiorczy leży w Folderze okresu pod tą nazwą, i uruchom ponownie. "
                "Jeśli okresu jeszcze nie przygotowano, najpierw przygotuj plik zbiorczy."
            ),
        ),
    )


def collective_file_open(source: Path) -> SettlementError:
    """Plik zbiorczy ma obok plik blokady Excela ``~$…``."""

    return SettlementError(
        f"Plik jest otwarty lub zablokowany: {source.name}",
        SettlementMessage(
            code="PLIK_ZBIORCZY_OTWARTY",
            what=f"Plik zbiorczy jest otwarty w Excelu. {_NOTHING_CREATED}",
            where=_file_label(source),
            action=(
                "Zapisz i zamknij Plik zbiorczy w Excelu i uruchom ponownie. Jeśli Excel jest zamknięty, "
                f"a komunikat wraca, usuń z tego samego folderu pozostawiony plik ~${source.name} i uruchom ponownie."
            ),
        ),
    )


def collective_file_invalid(source: Path, detail: str) -> SettlementError:
    """Nazwa, folder albo układ Pliku zbiorczego; ``detail`` to ``CollectiveFileError.message``, nie tekst wyjątku."""

    return SettlementError(
        detail,
        SettlementMessage(
            code="ZLY_PLIK_ZBIORCZY",
            what=f"Plik zbiorczy nie nadaje się do Przebiegu rozliczeń. {detail}",
            where=_file_label(source),
            action=f"Popraw Plik zbiorczy w Excelu. {_SAVE_AND_RETRY} Jeśli błąd wraca, {_REPORT_TO_MAINTAINER.lower()}",
        ),
    )


def worker_settlements_exist(target_directory: Path) -> SettlementError:
    """Nienadpisywanie: Folder rozliczeń pracowników okresu już istnieje."""

    return SettlementError(
        f"Folder docelowy już istnieje: {target_directory.name}.",
        SettlementMessage(
            code="FOLDER_ROZLICZEN_ISTNIEJE",
            what=f"Folder rozliczeń pracowników tego okresu już istnieje, więc nie został nadpisany. {_NOTHING_CREATED}",
            where=_folder_label(target_directory),
            action=(
                "Sprawdź, czy wybrano właściwy okres. Rozliczenia pracowników tego okresu już są w Folderze okresu. "
                "Jeśli trzeba je utworzyć od nowa, najpierw przenieś ten folder poza Folder okresu i uruchom ponownie."
            ),
        ),
    )


def _worker_config(config_path: Path, line: str, detail: str) -> SettlementError:
    return SettlementError(
        line,
        SettlementMessage(
            code="ZLA_KONFIGURACJA_WYKONAWCOW",
            what=f"Konfiguracja wykonawców jest niepoprawna. {detail}",
            where=_file_label(config_path),
            action=_REPORT_TO_MAINTAINER,
        ),
    )


def worker_config_unreadable(config_path: Path) -> SettlementError:
    return _worker_config(
        config_path, f"Nie można odczytać konfiguracji: {config_path}", "Nie można odczytać pliku konfiguracji."
    )


def worker_config_not_yaml(config_path: Path) -> SettlementError:
    return _worker_config(
        config_path, f"Niepoprawny YAML konfiguracji: {config_path}", "Plik nie jest poprawnym YAML."
    )


def worker_config_invalid(config_path: Path, detail: str) -> SettlementError:
    """Treść konfiguracji wykonawców łamie jej reguły; ``detail`` nie zawiera ścieżki."""

    return _worker_config(config_path, detail, detail)


def worker_template_invalid(template_path: Path, detail: str) -> SettlementError:
    """Wzorzec rozliczenia pracownika nie przeszedł Sprawdzania; ``detail`` to ``WorkerTemplateValidationError.message``."""

    return SettlementError(
        detail,
        SettlementMessage(
            code="ZLY_WZORZEC_PRACOWNIKA",
            what=f"Nie można użyć Wzorca rozliczenia pracownika. {detail}",
            where=_file_label(template_path),
            action=(
                "Jeśli Wzorzec jest otwarty w Excelu, zamknij go bez zapisywania zmian i uruchom ponownie. "
                f"W innym wypadku {_REPORT_TO_MAINTAINER.lower()}"
            ),
        ),
    )


def unmapped_worker(source: Path) -> SettlementError:
    """RUN: WYKONAWCA z Pliku zbiorczego nie ma wpisu w konfiguracji wykonawców."""

    return SettlementError(
        "WYKONAWCA bez mapowania; folder wynikowy nie został opublikowany.",
        SettlementMessage(
            code="NIEZNANY_WYKONAWCA",
            what=(
                "W Pliku zbiorczym jest WYKONAWCA, którego nie ma w konfiguracji wykonawców. "
                f"{_NOTHING_CREATED}"
            ),
            where=f"{_file_label(source)}, kolumna H",
            action=(
                f"{_PREVIEW_PROBLEMS} Popraw WYKONAWCĘ w kolumnie H albo poproś osobę utrzymującą narzędzie "
                f"o dopisanie Wykonawcy do konfiguracji wykonawców. {_SAVE_AND_RETRY}"
            ),
        ),
    )


def rows_without_worker(source: Path) -> SettlementError:
    """RUN: Wiersz danych bez WYKONAWCY."""

    return SettlementError(
        "Nie wszystkie wiersze danych mają przypisanego WYKONAWCĘ; folder wynikowy nie został opublikowany.",
        SettlementMessage(
            code="WIERSZE_BEZ_WYKONAWCY",
            what=f"Nie wszystkie Wiersze danych Pliku zbiorczego mają WYKONAWCĘ. {_NOTHING_CREATED}",
            where=f"{_file_label(source)}, kolumna H",
            action=f"{_PREVIEW_PROBLEMS} Wpisz WYKONAWCĘ w kolumnie H tych wierszy. {_SAVE_AND_RETRY}",
        ),
    )


def worker_file_failed(target_directory: Path, worker_name: str) -> SettlementError:
    return SettlementError(
        f"Nie udało się przygotować skoroszytu pracownika {worker_name}; folder wynikowy nie został opublikowany.",
        SettlementMessage(
            code="BLAD_SZABLONU_PRACOWNIKA",
            what=f"Nie udało się przygotować skoroszytu pracownika {worker_name}. {_NOTHING_CREATED}",
            where=_folder_label(target_directory),
            action=_RETRY,
        ),
    )


def worker_files_not_copied(template_path: Path) -> SettlementError:
    return SettlementError(
        "Nie można utworzyć skoroszytów z Wzorca rozliczenia pracownika; folder wynikowy nie został opublikowany.",
        SettlementMessage(
            code="BLAD_KOPII_WZORCA",
            what=f"Nie można utworzyć skoroszytów z Wzorca rozliczenia pracownika. {_NOTHING_CREATED}",
            where=_file_label(template_path),
            action=_RETRY,
        ),
    )


def publish_failed(target_directory: Path) -> SettlementError:
    return SettlementError(
        "Nie można opublikować gotowego folderu rozliczeń pracowników.",
        SettlementMessage(
            code="BLAD_PUBLIKACJI",
            what=f"Nie można opublikować gotowego Folderu rozliczeń pracowników. {_NOTHING_CREATED}",
            where=_folder_label(target_directory),
            action=f"Sprawdź, czy Folder okresu jest dostępny. {_RETRY}",
        ),
    )


def write_failed(target_directory: Path) -> SettlementError:
    return SettlementError(
        "Nie można przygotować folderu rozliczeń pracowników; folder wynikowy nie został opublikowany.",
        SettlementMessage(
            code="BLAD_ZAPISU",
            what=f"Nie można przygotować Folderu rozliczeń pracowników. {_NOTHING_CREATED}",
            where=_folder_label(target_directory),
            action=f"Sprawdź, czy Folder okresu jest dostępny. {_RETRY}",
        ),
    )


def unexpected_failure() -> SettlementMessage:
    """Nieprzewidziany błąd; treść wyjątku nie trafia do taty."""

    return SettlementMessage(
        code="BLAD_NIEOCZEKIWANY",
        what=f"Wystąpił nieoczekiwany błąd. {_NOTHING_CREATED}",
        where="Przebieg rozliczeń",
        action=_RETRY,
    )


def summary_not_shown() -> SettlementMessage:
    """Folder rozliczeń pracowników powstał, ale podsumowania nie dało się pokazać."""

    return SettlementMessage(
        code="BLAD_PODSUMOWANIA",
        what="Rozliczenia pracowników powstały, ale nie udało się pokazać podsumowania.",
        where="Przebieg rozliczeń",
        action=(
            "Nie uruchamiaj ponownie: Folder rozliczeń pracowników już jest. "
            "Sprawdź Folder okresu i przekaż ten komunikat osobie utrzymującej narzędzie."
        ),
    )


def plan_not_shown() -> SettlementMessage:
    """DRY-RUN skończył się, ale planu nie dało się pokazać; nic nie zapisano."""

    return SettlementMessage(
        code="BLAD_PLANU",
        what="Nie udało się pokazać planu. Nic nie zapisano.",
        where="Przebieg rozliczeń",
        action=_REPORT_TO_MAINTAINER,
    )


_ISSUE_ACTIONS: Final[dict[str, str]] = {
    "BRAK_MAPOWANIA": (
        "Popraw WYKONAWCĘ w kolumnie H albo poproś osobę utrzymującą narzędzie o dopisanie Wykonawcy "
        f"do konfiguracji wykonawców. {_SAVE_AND_RETRY}"
    ),
    "BRAK_WYKONAWCY": f"Wpisz WYKONAWCĘ w kolumnie H tego wiersza. {_SAVE_AND_RETRY}",
}


def issue_message(issue: Issue, source: Path) -> SettlementMessage:
    """Problem z podsumowania (wynik „Wymaga sprawdzenia”) w trzech częściach; „Co się stało” to linia terminala."""

    return SettlementMessage(
        code=issue.code,
        what=issue.message,
        where=_file_label(source),
        action=_ISSUE_ACTIONS.get(issue.code, _REPORT_TO_MAINTAINER),
    )

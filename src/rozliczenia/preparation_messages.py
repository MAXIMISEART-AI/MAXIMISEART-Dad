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

"""Instrukcja dla taty a katalogi Komunikatów.

Każdy katalog (Przygotowanie pliku zbiorczego, Przebieg rozliczeń, start
Centrum rozliczeń) ma w ``docs/tata-instrukcja.md`` swoją sekcję z tabelą,
której wiersze cytują faktyczną treść „Co się stało”. Jeden zestaw sprawdzeń
obejmuje każdy katalog: nowy katalog dostaje wszystkie sprawdzenia, gdy tylko
trafi do ``CATALOGS``. Zmiana treści Komunikatu bez poprawki instrukcji psuje
test.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import date
import inspect
from pathlib import Path
import re
from types import ModuleType

import pytest

from rozliczenia import preparation_messages as messages
from rozliczenia import settlement_messages
from rozliczenia.centrum import start_problems
from rozliczenia.domain import Issue
from rozliczenia.message import Message
from rozliczenia.worker_config import WorkerConfigError


INSTRUCTION = Path(__file__).resolve().parents[1] / "docs" / "tata-instrukcja.md"
QUOTED = re.compile(r"„([^”]+)”")
# Pełna ścieżka zaczyna się literą dysku (C:\Dane, C:/Dane) albo jest ścieżką sieciową
# (\\nas\Wspolne, //nas/Wspolne); „//” po dwukropku to adres, nie ścieżka.
FULL_PATH = re.compile(r"(?<![A-Za-z])[A-Za-z]:[\\/]|(?<![:\\/])(?:\\\\|//)[^\\/\s]")

REGISTER = Path("C:/Dane/ZLECENIA INTERMAX OD 08_11_2021.xlsx")
PERIODS = Path("C:/Dane/INEA")
PERIOD_DIRECTORY = PERIODS / "08_14_09_2026"
TEMPLATE = Path("C:/Narzedzie/config/Wzorzec pliku zbiorczego.xlsx")
CONFIG = Path("//nas/Wspolne/Narzedzie/config/worker_mapping.yaml")
SHEET = "ZLECENIA"
PERIOD = "08_14_09_2026"
SOURCE = PERIOD_DIRECTORY / f"Rozliczenie {PERIOD} - zbiorcze.xlsx"
WORKER_SETTLEMENTS = PERIOD_DIRECTORY / f"Rozliczenie pracowników {PERIOD}"
WORKER_TEMPLATE = Path("C:/Narzedzie/config/Wzorzec rozliczenia pracownika.xlsx")
UNREADABLE_CONFIG = WorkerConfigError("unreadable", "Nie można odczytać pliku konfiguracji.")
CONFIG_NOT_YAML = WorkerConfigError("not_yaml", "Plik nie jest poprawnym YAML.")
INVALID_CONFIG = WorkerConfigError("invalid", "Nieobsługiwana wersja konfiguracji.")
# Foldery nad folderem config z próbek; żaden Komunikat ich nie pokazuje.
ABOVE_CONFIG = frozenset({"Wspolne", "Narzedzie"})

Samples = Mapping[str, Sequence[Callable[[], Message]]]

# Każda fabryka katalogu z przykładowymi argumentami; warianty liczby pojedynczej i mnogiej osobno.
PREPARATION_SAMPLES: Samples = {
    "period_file_exists": [lambda: messages.period_file_exists(PERIOD_DIRECTORY, f"Rozliczenie wew. {PERIOD}.xlsx")],
    "invalid_period_token": [lambda: messages.invalid_period_token("08_14_9_2026")],
    "register_not_selected": [messages.register_not_selected],
    "periods_directory_not_selected": [messages.periods_directory_not_selected],
    "period_not_entered": [messages.period_not_entered],
    "worker_config_invalid": [
        lambda: messages.worker_config_invalid(CONFIG, UNREADABLE_CONFIG),
        lambda: messages.worker_config_invalid(CONFIG, CONFIG_NOT_YAML),
        lambda: messages.worker_config_invalid(CONFIG, INVALID_CONFIG),
    ],
    "template_missing": [lambda: messages.template_missing(TEMPLATE)],
    "template_open_in_excel": [lambda: messages.template_open_in_excel(TEMPLATE)],
    "template_unreadable": [lambda: messages.template_unreadable(TEMPLATE)],
    "template_without_header": [lambda: messages.template_without_header(TEMPLATE, "Sheet1", 17, "WYKONAWCA")],
    "template_with_worker_outside_h": [lambda: messages.template_with_worker_outside_h(TEMPLATE, "Sheet1", "G")],
    "template_with_merged_cells": [lambda: messages.template_with_merged_cells(TEMPLATE, "Sheet1", "B19:C20")],
    "register_missing": [lambda: messages.register_missing(REGISTER)],
    "register_open_in_excel": [lambda: messages.register_open_in_excel(REGISTER)],
    "register_unreadable": [lambda: messages.register_unreadable(REGISTER)],
    "register_without_headers": [
        lambda: messages.register_without_headers(REGISTER, SHEET, ["SKUTECZNE"]),
        lambda: messages.register_without_headers(REGISTER, SHEET, ["SKUTECZNE", "WYKONAWCA"]),
    ],
    "register_with_duplicated_headers": [
        lambda: messages.register_with_duplicated_headers(REGISTER, SHEET, ["adres"]),
        lambda: messages.register_with_duplicated_headers(REGISTER, SHEET, ["adres", "UMOWA"]),
    ],
    "register_without_data_sheet": [lambda: messages.register_without_data_sheet(REGISTER, ["DATA GODZ. POCZ."])],
    "period_orders_in_many_sheets": [
        lambda: messages.period_orders_in_many_sheets(REGISTER, ["ZLECENIA", "ZLECENIA 2"], PERIOD)
    ],
    "periods_directory_missing": [lambda: messages.periods_directory_missing(PERIODS)],
    "rows_without_date": [
        lambda: messages.rows_without_date(REGISTER, SHEET, [7]),
        lambda: messages.rows_without_date(REGISTER, SHEET, [7, 9]),
    ],
    "invalid_successful_values": [
        lambda: messages.invalid_successful_values(REGISTER, SHEET, [4]),
        lambda: messages.invalid_successful_values(REGISTER, SHEET, [4, 6]),
    ],
    "unknown_workers": [
        lambda: messages.unknown_workers(REGISTER, SHEET, CONFIG, [("nowy.wykonawca", [4])]),
        lambda: messages.unknown_workers(REGISTER, SHEET, CONFIG, [("nowy.wykonawca", [4, 9]), ("", [6])]),
    ],
    "no_period_orders": [lambda: messages.no_period_orders(REGISTER, SHEET, PERIOD)],
    "too_few_zero_rows": [
        lambda: messages.too_few_zero_rows(f"Rozliczenie {PERIOD} - zbiorcze.xlsx", 7, 6, 24),
        lambda: messages.too_few_zero_rows(f"Rozliczenie {PERIOD} - zbiorcze.xlsx", 9, 6, 24),
    ],
    "incomplete_period": [
        lambda: messages.incomplete_period(REGISTER, SHEET, PERIOD, date(2026, 9, 12), date(2026, 9, 14))
    ],
    "incomplete_period_refused": [
        lambda: messages.incomplete_period_refused(PERIOD, "przy pytaniu wpisz t"),
        lambda: messages.incomplete_period_refused(PERIOD, "przy decyzji wybierz „Kontynuuj”"),
    ],
    "write_failed": [lambda: messages.write_failed(PERIOD_DIRECTORY)],
    "write_failed_with_file_left": [
        lambda: messages.write_failed_with_file_left(PERIOD_DIRECTORY, f"Rozliczenie wew. {PERIOD}.xlsx")
    ],
    "unexpected_failure": [messages.unexpected_failure],
    "summary_not_shown": [messages.summary_not_shown],
    "plan_not_shown": [messages.plan_not_shown],
}

SETTLEMENT_SAMPLES: Samples = {
    "collective_file_missing": [lambda: settlement_messages.collective_file_missing(SOURCE)],
    "collective_file_open": [lambda: settlement_messages.collective_file_open(SOURCE)],
    "collective_file_invalid": [
        lambda: settlement_messages.collective_file_invalid(
            SOURCE, "Plik Rozliczenie wew. jest poza zakresem tego procesu."
        )
    ],
    "collective_file_unreadable": [lambda: settlement_messages.collective_file_unreadable(SOURCE)],
    "collective_file_without_worker_header": [
        lambda: settlement_messages.collective_file_without_worker_header(SOURCE)
    ],
    "worker_settlements_exist": [lambda: settlement_messages.worker_settlements_exist(WORKER_SETTLEMENTS)],
    "worker_config_invalid": [
        lambda: settlement_messages.worker_config_invalid(CONFIG, UNREADABLE_CONFIG),
        lambda: settlement_messages.worker_config_invalid(CONFIG, CONFIG_NOT_YAML),
        lambda: settlement_messages.worker_config_invalid(CONFIG, INVALID_CONFIG),
    ],
    "worker_template_invalid": [
        lambda: settlement_messages.worker_template_invalid(
            WORKER_TEMPLATE, "Wzorzec rozliczenia pracownika jest otwarty lub zablokowany."
        )
    ],
    "unmapped_worker": [lambda: settlement_messages.unmapped_worker(SOURCE)],
    "rows_without_worker": [lambda: settlement_messages.rows_without_worker(SOURCE)],
    "worker_file_failed": [lambda: settlement_messages.worker_file_failed(WORKER_SETTLEMENTS, "Wykonawca Testowy")],
    "worker_files_not_copied": [lambda: settlement_messages.worker_files_not_copied(WORKER_TEMPLATE)],
    "publish_failed": [lambda: settlement_messages.publish_failed(WORKER_SETTLEMENTS)],
    "write_failed": [lambda: settlement_messages.write_failed(WORKER_SETTLEMENTS)],
    "unexpected_failure": [settlement_messages.unexpected_failure],
    "summary_not_shown": [settlement_messages.summary_not_shown],
    "plan_not_shown": [settlement_messages.plan_not_shown],
    "issue_message": [
        lambda: settlement_messages.issue_message(
            Issue("BRAK_MAPOWANIA", "Nieznany identyfikator WYKONAWCA; sprawdź konfigurację pracowników."), SOURCE
        ),
        lambda: settlement_messages.issue_message(
            Issue("BRAK_WYKONAWCY", "Wiersz 19 ma dane, ale nie ma wykonawcy w kolumnie H."), SOURCE
        ),
    ],
}

START_SAMPLES: Samples = {
    "port_taken": [lambda: start_problems.port_taken(47811)],
    "other_version_running": [lambda: start_problems.other_version_running(47811, "0.0.9")],
    "missing_library": [lambda: start_problems.missing_library("fastapi")],
    "unexpected_start_failure": [start_problems.unexpected_start_failure],
}


@dataclass(frozen=True)
class Catalog:
    """Katalog Komunikatów, jego sekcja w instrukcji i próbki każdej fabryki.

    ``terminal_only`` to fabryki, których Komunikatu tata nie widzi poza
    terminalem, więc instrukcja ich nie cytuje. ``hidden_folders`` to foldery
    ze ścieżek próbek leżące wyżej niż folder nadrzędny wskazywanego pliku albo
    folderu; trzy części Komunikatu ich nie pokazują.
    """

    module: ModuleType
    section: str
    samples: Samples
    terminal_only: frozenset[str] = frozenset()
    hidden_folders: frozenset[str] = ABOVE_CONFIG

    def factories(self) -> set[str]:
        return {
            name
            for name, function in inspect.getmembers(self.module, inspect.isfunction)
            if function.__module__ == self.module.__name__ and not name.startswith("_")
        }

    def messages(self) -> list[Message]:
        return [sample() for samples in self.samples.values() for sample in samples]


CATALOGS = {
    # Folder Dane i folder okresów INEA legalnie widać jako folder nadrzędny Rejestru zleceń i folderu okresu.
    "przygotowanie-pliku-zbiorczego": Catalog(messages, "### Komunikat → co zrobić", PREPARATION_SAMPLES),
    "przebieg-rozliczen": Catalog(
        settlement_messages,
        "### Komunikat w Centrum rozliczeń → co zrobić",
        SETTLEMENT_SAMPLES,
        # Tylko terminal: w Centrum Plik zbiorczy wynika z okresu, więc okna wyboru pliku nie ma.
        terminal_only=frozenset({"collective_file_not_selected"}),
        # Przebieg wskazuje najwyżej folder okresu, więc folderów nad nim nie widać.
        hidden_folders=ABOVE_CONFIG | {"Dane", "INEA"},
    ),
    "start-centrum-rozliczen": Catalog(start_problems, "### Komunikaty startu Centrum rozliczeń", START_SAMPLES),
}

each_catalog = pytest.mark.parametrize("catalog", CATALOGS.values(), ids=CATALOGS.keys())


def _instruction_fragments(section: str) -> list[str]:
    """Cytaty „…” z pierwszej kolumny tabel w sekcji instrukcji, razem z jej podsekcjami."""

    lines = INSTRUCTION.read_text(encoding="utf-8").splitlines()
    start = lines.index(section)
    level = section.split(" ", 1)[0]
    fragments: list[str] = []
    for line in lines[start + 1 :]:
        if line.startswith("#") and len(line.split(" ", 1)[0]) <= len(level):
            break
        if not line.startswith("|") or set(line) <= {"|", "-", " ", ":"}:
            continue
        first_cell = line.strip("|").split("|", 1)[0]
        fragments.extend(QUOTED.findall(first_cell))
    return fragments


@each_catalog
def test_probki_pokrywaja_kazda_fabryke_katalogu(catalog: Catalog) -> None:
    assert set(catalog.samples) | catalog.terminal_only == catalog.factories()


@each_catalog
def test_instrukcja_taty_objasnia_kazdy_komunikat_katalogu(catalog: Catalog) -> None:
    fragments = _instruction_fragments(catalog.section)
    unexplained = sorted(
        {message.code for message in catalog.messages() if not any(f in message.what for f in fragments)}
    )

    assert unexplained == []


@each_catalog
def test_kazdy_cytat_instrukcji_wskazuje_dokladnie_jeden_kod(catalog: Catalog) -> None:
    codes_per_fragment = {
        fragment: {message.code for message in catalog.messages() if fragment in message.what}
        for fragment in _instruction_fragments(catalog.section)
    }

    assert {fragment: codes for fragment, codes in codes_per_fragment.items() if len(codes) != 1} == {}


@each_catalog
def test_kazdy_kod_katalogu_ma_dokladnie_jeden_cytat_instrukcji(catalog: Catalog) -> None:
    """Jeden kod to jeden Komunikat: jego warianty objaśnia ten sam, jedyny cytat instrukcji.

    Razem z ``test_kazdy_cytat_instrukcji_wskazuje_dokladnie_jeden_kod`` pilnuje,
    że dwie fabryki o różnej treści nie dzielą kodu w obrębie katalogu.
    """

    fragments = _instruction_fragments(catalog.section)
    fragments_per_code: dict[str, set[str]] = {}
    for message in catalog.messages():
        fragments_per_code.setdefault(message.code, set()).update(f for f in fragments if f in message.what)

    assert {code: found for code, found in fragments_per_code.items() if len(found) != 1} == {}


@each_catalog
def test_komunikaty_katalogu_nie_maja_pelnych_sciezek(catalog: Catalog) -> None:
    shown = {
        message.code: part
        for message in catalog.messages()
        for part in (message.what, message.where, message.action)
        if FULL_PATH.search(part) or any(folder in part for folder in catalog.hidden_folders)
    }

    assert shown == {}

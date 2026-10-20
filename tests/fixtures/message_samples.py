"""Próbki każdej fabryki katalogów Komunikatów, z syntetycznymi ścieżkami komputera taty.

Wspólne dla testu instrukcji taty i testu rodzaju Zatrzymania: każdy katalog
ma tu wszystkie swoje fabryki, warianty liczby pojedynczej i mnogiej osobno.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from datetime import date
from pathlib import Path

from rozliczenia import preparation_messages as messages
from rozliczenia import settlement_messages
from rozliczenia.centrum import diagnosis_messages, start_problems
from rozliczenia.domain import Issue
from rozliczenia.message import Message
from rozliczenia.period_folder import PeriodFolderLookupError
from rozliczenia.settlement_period import parse_period_token
from rozliczenia.template_settlement import WorkerTemplateValidationError, validate_worker_template
from rozliczenia.worker_config import WorkerConfigError

REGISTER = Path("C:/Dane/ZLECENIA INTERMAX OD 08_11_2021.xlsx")
PERIODS = Path("C:/Dane/INEA")
PERIOD_DIRECTORY = PERIODS / "08_14_09_2026"
DAD_PERIODS = Path("C:/Users/tata/OneDrive/Załączniki")
JUNE = DAD_PERIODS / "Rozliczenia 2026" / "06_Czerwiec_2026" / "INEA"
JULY = DAD_PERIODS / "Rozliczenia 2026" / "07_Lipiec_2026" / "INEA"
PARSED_PERIOD = parse_period_token("08_14_09_2026")
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


def _missing_worker_template_detail() -> str:
    """Treść ze Sprawdzania Wzorca rozliczenia pracownika, którego nie ma pod ścieżką ``WORKER_TEMPLATE``."""

    try:
        validate_worker_template(WORKER_TEMPLATE)
    except WorkerTemplateValidationError as error:
        return error.message
    raise AssertionError("Sprawdzanie przyjęło nieistniejący Wzorzec rozliczenia pracownika.")


# Każda fabryka katalogu z przykładowymi argumentami; warianty liczby pojedynczej i mnogiej osobno.
PREPARATION_SAMPLES: Samples = {
    "period_file_exists": [lambda: messages.period_file_exists(PERIOD_DIRECTORY, f"Rozliczenie wew. {PERIOD}.xlsx")],
    "invalid_period_token": [lambda: messages.invalid_period_token("08_14_9_2026")],
    "register_not_selected": [messages.register_not_selected],
    "periods_directory_not_selected": [messages.periods_directory_not_selected],
    "period_not_entered": [messages.period_not_entered],
    "worker_config_problem": [
        lambda: messages.worker_config_problem(CONFIG, UNREADABLE_CONFIG),
        lambda: messages.worker_config_problem(CONFIG, CONFIG_NOT_YAML),
        lambda: messages.worker_config_problem(CONFIG, INVALID_CONFIG),
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
    "period_folder_lookup_problem": [
        lambda: messages.period_folder_lookup_problem(PeriodFolderLookupError(DAD_PERIODS, PARSED_PERIOD, ())),
        lambda: messages.period_folder_lookup_problem(
            PeriodFolderLookupError(DAD_PERIODS, PARSED_PERIOD, (JUNE, JULY))
        ),
    ],
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
    "worker_config_problem": [
        lambda: settlement_messages.worker_config_problem(CONFIG, UNREADABLE_CONFIG),
        lambda: settlement_messages.worker_config_problem(CONFIG, CONFIG_NOT_YAML),
        lambda: settlement_messages.worker_config_problem(CONFIG, INVALID_CONFIG),
    ],
    "worker_template_invalid": [
        lambda: settlement_messages.worker_template_invalid(
            WORKER_TEMPLATE, "Wzorzec rozliczenia pracownika jest otwarty lub zablokowany."
        ),
        lambda: settlement_messages.worker_template_invalid(WORKER_TEMPLATE, _missing_worker_template_detail()),
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

DIAGNOSIS_SAMPLES: Samples = {
    "cause_not_found": [diagnosis_messages.cause_not_found],
    "period_file_open": [lambda: diagnosis_messages.period_file_open(PERIOD_DIRECTORY / f"Rozliczenie wew. {PERIOD}.xlsx")],
    "unexpected_failure_logged": [diagnosis_messages.unexpected_failure_logged],
}

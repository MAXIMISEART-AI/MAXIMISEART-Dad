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
from rozliczenia.centrum import diagnosis_messages, report_messages, start_problems, update_messages
from rozliczenia.centrum.tool_update import LIBRARIES_FAILED, NEW_VERSION_FAILED, ROLLBACK_FAILED, UNEXPECTED
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
CONFIG_NOT_UTF8 = WorkerConfigError("not_utf8", "Plik nie jest zapisany w kodowaniu UTF-8.")
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
    "invalid_period_token": [lambda: messages.invalid_period_token("08_14_9_2026")],
    "period_file_exists": [lambda: messages.period_file_exists(PERIOD_DIRECTORY, f"Rozliczenie wew. {PERIOD}.xlsx")],
    "worker_config_problem": [
        lambda: messages.worker_config_problem(CONFIG, UNREADABLE_CONFIG),
        lambda: messages.worker_config_problem(CONFIG, CONFIG_NOT_UTF8),
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
    "register_inaccessible": [lambda: messages.register_inaccessible(REGISTER)],
    "register_unreadable": [lambda: messages.register_unreadable(REGISTER)],
    "register_without_headers": [
        lambda: messages.register_without_headers(REGISTER, SHEET, ["SKUTECZNE"]),
        lambda: messages.register_without_headers(REGISTER, SHEET, ["SKUTECZNE", "WYKONAWCA"]),
    ],
    "register_with_duplicated_headers": [
        lambda: messages.register_with_duplicated_headers(REGISTER, SHEET, ["ADRES"]),
        lambda: messages.register_with_duplicated_headers(REGISTER, SHEET, ["ADRES", "UMOWA"]),
    ],
    "register_without_data_sheet": [lambda: messages.register_without_data_sheet(REGISTER, ["DATA GODZ. POCZ."])],
    "period_orders_in_many_sheets": [
        lambda: messages.period_orders_in_many_sheets(REGISTER, ["ZLECENIA", "ZLECENIA 2"], PERIOD)
    ],
    "periods_directory_missing": [lambda: messages.periods_directory_missing(PERIODS)],
    "folder_inaccessible": [lambda: messages.folder_inaccessible(PERIODS)],
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
        lambda: messages.invalid_successful_values(REGISTER, SHEET, "L", [4], []),
        lambda: messages.invalid_successful_values(REGISTER, SHEET, "L", [4, 5, 9], [messages.CellContent(6, "???")]),
        lambda: messages.invalid_successful_values(REGISTER, SHEET, "L", [], [messages.CellContent(n, "tsk") for n in range(2, 14)]),
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
    "unknown_devices": [
        lambda: messages.unknown_devices(f"Rozliczenie {PERIOD} - zbiorcze.xlsx", [19]),
        lambda: messages.unknown_devices(f"Rozliczenie {PERIOD} - zbiorcze.xlsx", list(range(18, 30))),
    ],
    "rows_from_description": [
        lambda: messages.rows_from_description(f"Rozliczenie {PERIOD} - zbiorcze.xlsx", [20]),
        lambda: messages.rows_from_description(f"Rozliczenie {PERIOD} - zbiorcze.xlsx", [20, 21, 23]),
    ],
    "columns_from_description": [lambda: messages.columns_from_description(f"Rozliczenie {PERIOD} - zbiorcze.xlsx")],
    "incomplete_period": [
        lambda: messages.incomplete_period(REGISTER, SHEET, PERIOD, date(2026, 9, 12), date(2026, 9, 14))
    ],
    "incomplete_period_refused": [
        lambda: messages.incomplete_period_refused(
            PERIOD, "uruchom proces w Centrum rozliczeń i przy decyzji wybierz „Kontynuuj”"
        ),
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
    "collective_file_inaccessible": [lambda: settlement_messages.collective_file_inaccessible(SOURCE)],
    "collective_file_unreadable": [lambda: settlement_messages.collective_file_unreadable(SOURCE)],
    "collective_file_without_worker_header": [
        lambda: settlement_messages.collective_file_without_worker_header(SOURCE)
    ],
    "worker_settlements_exist": [lambda: settlement_messages.worker_settlements_exist(WORKER_SETTLEMENTS)],
    "worker_config_problem": [
        lambda: settlement_messages.worker_config_problem(CONFIG, UNREADABLE_CONFIG),
        lambda: settlement_messages.worker_config_problem(CONFIG, CONFIG_NOT_UTF8),
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
    "staging_left": [
        lambda: settlement_messages.staging_left(
            settlement_messages.publish_failed(WORKER_SETTLEMENTS), f".{WORKER_SETTLEMENTS.name}.staging-"
        ),
        lambda: settlement_messages.staging_left(
            settlement_messages.worker_file_failed(WORKER_SETTLEMENTS, "Wykonawca Testowy"),
            f".{WORKER_SETTLEMENTS.name}.staging-",
        ),
        lambda: settlement_messages.staging_left(
            settlement_messages.worker_settlements_exist(WORKER_SETTLEMENTS),
            f".{WORKER_SETTLEMENTS.name}.staging-",
        ),
    ],
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
    "other_version_running": [lambda: start_problems.other_version_running(47811, "3c1d0a9")],
    "missing_library": [lambda: start_problems.missing_library("fastapi")],
    "unexpected_start_failure": [start_problems.unexpected_start_failure],
    "not_started_after_update": [start_problems.not_started_after_update],
    "update_finishing": [start_problems.update_finishing],
}

DIAGNOSIS_SAMPLES: Samples = {
    "cause_not_found": [diagnosis_messages.cause_not_found],
    "newer_tool_version": [diagnosis_messages.newer_tool_version],
    "file_only_in_cloud": [lambda: diagnosis_messages.file_only_in_cloud(SOURCE)],
    "period_file_open": [lambda: diagnosis_messages.period_file_open(PERIOD_DIRECTORY / f"Rozliczenie wew. {PERIOD}.xlsx")],
}

UNSENT_REPORT = Path("C:/Narzedzie/config/zgloszenia") / f"Zgłoszenie BLAD_PLANU {PERIOD}.md"

REPORT_SAMPLES: Samples = {
    "key_missing": [lambda: report_messages.key_missing(UNSENT_REPORT)],
    "key_refused": [lambda: report_messages.key_refused(UNSENT_REPORT)],
    "box_unreachable": [lambda: report_messages.box_unreachable(UNSENT_REPORT)],
    "not_saved": [lambda: report_messages.not_saved(UNSENT_REPORT.parent)],
}

UPDATE_SAMPLES: Samples = {
    "no_git": [update_messages.no_git],
    "no_connection": [update_messages.no_connection],
    "login_required": [update_messages.login_required],
    "other_branch": [update_messages.other_branch],
    "local_changes": [update_messages.local_changes],
    "unexpected_failure": [update_messages.unexpected_failure],
    "libraries_failed": [update_messages.libraries_failed],
    "new_version_failed": [update_messages.new_version_failed],
    "rollback_failed": [update_messages.rollback_failed],
    "message_of": [
        lambda: update_messages.message_of(UNEXPECTED),
        lambda: update_messages.message_of(LIBRARIES_FAILED),
        lambda: update_messages.message_of(NEW_VERSION_FAILED),
        lambda: update_messages.message_of(ROLLBACK_FAILED),
        lambda: update_messages.message_of("NIEZNANY_KOD"),
    ],
}

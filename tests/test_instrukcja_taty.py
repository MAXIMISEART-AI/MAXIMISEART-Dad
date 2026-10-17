"""Instrukcja dla taty a katalog komunikatów Przygotowania pliku zbiorczego.

Tabela „komunikat → co zrobić” w ``docs/tata-instrukcja.md`` ma wiersz dla
każdego zatrzymania i ostrzeżenia, a jej wiersze cytują faktyczną treść „Co się
stało” z katalogu. Zmiana treści komunikatu bez poprawki instrukcji psuje test.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import date
import inspect
from pathlib import Path
import re

from rozliczenia import preparation_messages as messages
from rozliczenia.preparation_messages import PreparationError, PreparationMessage


INSTRUCTION = Path(__file__).resolve().parents[1] / "docs" / "tata-instrukcja.md"
MESSAGES_SECTION = "### Komunikat → co zrobić"
QUOTED = re.compile(r"„([^”]+)”")

REGISTER = Path("C:/Dane/ZLECENIA INTERMAX OD 08_11_2021.xlsx")
PERIODS = Path("C:/Dane/INEA")
PERIOD_DIRECTORY = PERIODS / "08_14_09_2026"
TEMPLATE = Path("C:/Narzedzie/config/Wzorzec pliku zbiorczego.xlsx")
CONFIG = Path("C:/Narzedzie/config/worker_mapping.yaml")
SHEET = "ZLECENIA"
PERIOD = "08_14_09_2026"

# Każda fabryka katalogu z przykładowymi argumentami; warianty liczby pojedynczej i mnogiej osobno.
CATALOG_SAMPLES: dict[str, list[Callable[[], PreparationError | PreparationMessage]]] = {
    "period_file_exists": [lambda: messages.period_file_exists(PERIOD_DIRECTORY, f"Rozliczenie wew. {PERIOD}.xlsx")],
    "invalid_period_token": [lambda: messages.invalid_period_token("08_14_9_2026")],
    "register_not_selected": [messages.register_not_selected],
    "periods_directory_not_selected": [messages.periods_directory_not_selected],
    "period_not_entered": [messages.period_not_entered],
    "unreadable_worker_config": [lambda: messages.unreadable_worker_config(CONFIG)],
    "template_missing": [lambda: messages.template_missing(TEMPLATE)],
    "template_open_in_excel": [lambda: messages.template_open_in_excel(TEMPLATE)],
    "template_unreadable": [lambda: messages.template_unreadable(TEMPLATE)],
    "template_without_header": [lambda: messages.template_without_header(TEMPLATE, "Sheet1", 17, "WYKONAWCA")],
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
    "incomplete_period_refused": [lambda: messages.incomplete_period_refused(PERIOD)],
    "write_failed": [lambda: messages.write_failed(PERIOD_DIRECTORY)],
    "unexpected_failure": [messages.unexpected_failure],
}


def _catalog_factories() -> set[str]:
    return {
        name
        for name, function in inspect.getmembers(messages, inspect.isfunction)
        if function.__module__ == messages.__name__ and not name.startswith("_")
    }


def _catalog_messages() -> list[PreparationMessage]:
    result: list[PreparationMessage] = []
    for samples in CATALOG_SAMPLES.values():
        for sample in samples:
            produced = sample()
            result.append(produced.message if isinstance(produced, PreparationError) else produced)
    return result


def _instruction_fragments() -> list[str]:
    """Cytaty „…” z pierwszej kolumny tabel w sekcji komunikatów instrukcji."""

    lines = INSTRUCTION.read_text(encoding="utf-8").splitlines()
    start = lines.index(MESSAGES_SECTION)
    level = MESSAGES_SECTION.split(" ", 1)[0]
    fragments: list[str] = []
    for line in lines[start + 1 :]:
        if line.startswith("#") and len(line.split(" ", 1)[0]) <= len(level):
            break
        if not line.startswith("|") or set(line) <= {"|", "-", " ", ":"}:
            continue
        first_cell = line.strip("|").split("|", 1)[0]
        fragments.extend(QUOTED.findall(first_cell))
    return fragments


def test_catalog_samples_cover_every_preparation_message_factory() -> None:
    assert set(CATALOG_SAMPLES) == _catalog_factories()


def test_instrukcja_taty_explains_every_zatrzymanie_and_ostrzezenie() -> None:
    fragments = _instruction_fragments()
    unexplained = sorted(
        {message.code for message in _catalog_messages() if not any(f in message.what for f in fragments)}
    )

    assert unexplained == []


def test_instrukcja_taty_quotes_only_actual_message_texts() -> None:
    catalog = _catalog_messages()
    codes_per_fragment = {
        fragment: {message.code for message in catalog if fragment in message.what}
        for fragment in _instruction_fragments()
    }

    assert {fragment: codes for fragment, codes in codes_per_fragment.items() if len(codes) != 1} == {}
    assert len(codes_per_fragment) == len(set().union(*codes_per_fragment.values()))

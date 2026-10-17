from __future__ import annotations

from datetime import datetime
from pathlib import Path

from openpyxl import Workbook, load_workbook
import pytest

from rozliczenia.collective_preparation import PreparationError, PreparationSummary, prepare_collective_file
from rozliczenia.workbook_files import ExternalLinksError
import rozliczenia.workbook_files as workbook_files

from tests.collective_preparation_fixtures import (
    COLLECTIVE_FILE_NAME,
    COLLECTIVE_TEMPLATE_ZERO_ROWS,
    INTERNAL_SETTLEMENT_NAME,
    INTERNAL_TEMPLATE_HEADERS,
    PERIOD,
    PreparationFixture,
    RegisterRow,
    make_preparation_fixture,
    register_order,
)
from tests.test_settlement_engine import active_worksheet, external_link_parts


def run_preparation(fixture: PreparationFixture, period: str = PERIOD) -> PreparationSummary:
    return prepare_collective_file(
        fixture.register_path,
        fixture.periods_directory,
        period,
        fixture.config_path,
        internal_template_path=fixture.internal_template_path,
        collective_template_path=fixture.collective_template_path,
    )


def sheet_rows(path: Path, *, min_row: int, max_col: int) -> list[tuple[object, ...]]:
    workbook = load_workbook(path)
    try:
        sheet = active_worksheet(workbook)
        return list(sheet.iter_rows(min_row=min_row, max_col=max_col, values_only=True))
    finally:
        workbook.close()


def internal_row(number: int, started: datetime, successful: str, worker: str) -> tuple[object, ...]:
    return (
        started,
        "POZNAŃ",
        f"syntetyczny adres SYN-{number:03d}",
        f"UM-SYN-{number:03d}",
        "dekoder",
        "instalacja",
        f"ZL-SYN-{number:03d}",
        worker,
        f"OR-SYN-{number:03d}",
        successful,
        "montaż",
        None,
        None,
    )


def test_rozliczenie_wewnetrzne_contains_exactly_period_orders_in_register_order(tmp_path: Path) -> None:
    fixture = make_preparation_fixture(tmp_path)

    run_preparation(fixture)

    assert sheet_rows(fixture.internal_settlement_path, min_row=2, max_col=len(INTERNAL_TEMPLATE_HEADERS)) == [
        internal_row(2, datetime(2026, 9, 8, 0, 0), "tak", "adrian.maciejewski"),
        internal_row(3, datetime(2026, 9, 9, 10, 30), "NIE", "dariusz.nowak2"),
        internal_row(4, datetime(2026, 9, 12, 12, 0), " Tak ", "kamil.frontczak"),
        internal_row(6, datetime(2026, 9, 14, 18, 30), "TAK", "dariusz.nowak2"),
    ]


def collective_row(number: int, started: datetime, successful: str, worker: str) -> tuple[object, ...]:
    return (
        "POZNAŃ",
        f"syntetyczny adres SYN-{number:03d}",
        f"UM-SYN-{number:03d}",
        "dekoder",
        "instalacja",
        f"ZL-SYN-{number:03d}",
        started,
        worker,
        f"OR-SYN-{number:03d}",
        successful,
        "montaż",
    )


def cell_values(path: Path, *, min_row: int, max_row: int, min_col: int, max_col: int) -> list[tuple[object, ...]]:
    workbook = load_workbook(path)
    try:
        sheet = active_worksheet(workbook)
        return list(
            sheet.iter_rows(min_row=min_row, max_row=max_row, min_col=min_col, max_col=max_col, values_only=True)
        )
    finally:
        workbook.close()


def test_plik_zbiorczy_contains_exactly_zlecenia_skuteczne_from_row_18(tmp_path: Path) -> None:
    fixture = make_preparation_fixture(tmp_path)

    run_preparation(fixture)

    assert cell_values(fixture.collective_file_path, min_row=18, max_row=24, min_col=1, max_col=11) == [
        collective_row(2, datetime(2026, 9, 8, 0, 0), "tak", "adrian.maciejewski"),
        collective_row(4, datetime(2026, 9, 12, 12, 0), " Tak ", "kamil.frontczak"),
        collective_row(6, datetime(2026, 9, 14, 18, 30), "TAK", "dariusz.nowak2"),
        *[(None,) * 11] * 4,
    ]


def test_plik_zbiorczy_keeps_wzorzec_rows_1_to_17_quantities_and_formulas(tmp_path: Path) -> None:
    fixture = make_preparation_fixture(tmp_path)

    run_preparation(fixture)

    template, created = fixture.collective_template_path, fixture.collective_file_path
    assert cell_values(created, min_row=1, max_row=17, min_col=1, max_col=47) == cell_values(
        template, min_row=1, max_row=17, min_col=1, max_col=47
    )
    assert cell_values(created, min_row=18, max_row=30, min_col=12, max_col=47) == cell_values(
        template, min_row=18, max_row=30, min_col=12, max_col=47
    )
    assert cell_values(created, min_row=18, max_row=18, min_col=14, max_col=14) == [(0,)]
    assert cell_values(created, min_row=18, max_row=18, min_col=47, max_col=47) == [("=N18*$N$1",)]
    workbook = load_workbook(created)
    try:
        assert workbook["Rates"]["B1"].value == 17.5
    finally:
        workbook.close()


def test_plik_zbiorczy_keeps_every_external_link_of_wzorzec(tmp_path: Path) -> None:
    fixture = make_preparation_fixture(tmp_path)
    expected_parts = external_link_parts(fixture.collective_template_path)

    run_preparation(fixture)

    assert expected_parts
    assert external_link_parts(fixture.collective_file_path) == expected_parts


def test_przygotowanie_leaves_rejestr_and_wzorce_byte_identical(tmp_path: Path) -> None:
    fixture = make_preparation_fixture(tmp_path)
    inputs = (fixture.register_path, fixture.internal_template_path, fixture.collective_template_path)
    before = [path.read_bytes() for path in inputs]

    run_preparation(fixture)

    assert [path.read_bytes() for path in inputs] == before


def test_summary_reports_counts_and_file_names_without_client_data(tmp_path: Path) -> None:
    fixture = make_preparation_fixture(tmp_path)

    summary = run_preparation(fixture)

    assert summary.period == PERIOD
    assert summary.period_order_count == 4
    assert summary.successful_order_count == 3
    assert summary.skipped_empty_rows == 3
    assert summary.warnings == []
    assert summary.internal_settlement_file == fixture.internal_settlement_path
    assert summary.collective_file == fixture.collective_file_path
    assert sorted(path.name for path in fixture.period_directory.iterdir()) == [
        COLLECTIVE_FILE_NAME,
        INTERNAL_SETTLEMENT_NAME,
    ]
    assert "SYN-" not in repr(summary)


def test_existing_empty_folder_okresu_is_allowed(tmp_path: Path) -> None:
    fixture = make_preparation_fixture(tmp_path)
    fixture.period_directory.mkdir()

    run_preparation(fixture)

    assert fixture.internal_settlement_path.is_file()
    assert fixture.collective_file_path.is_file()


@pytest.mark.parametrize("existing_name", [INTERNAL_SETTLEMENT_NAME, COLLECTIVE_FILE_NAME])
def test_nienadpisywanie_stops_when_period_file_exists(tmp_path: Path, existing_name: str) -> None:
    fixture = make_preparation_fixture(tmp_path)
    fixture.period_directory.mkdir()
    existing = fixture.period_directory / existing_name
    existing.write_bytes(b"reczne poprawki taty")

    with pytest.raises(PreparationError) as raised:
        run_preparation(fixture)

    message = str(raised.value)
    assert message == (
        "Co się stało: Plik tego okresu już istnieje, więc nie został nadpisany. "
        "Nie utworzono żadnego pliku.\n"
        f"Gdzie: folder INEA\\{PERIOD}, plik {existing_name}\n"
        "Co zrobić: Sprawdź, czy wybrano właściwy okres. Jeśli plik ma powstać od nowa, "
        "przenieś albo usuń istniejący plik i uruchom ponownie."
    )
    assert raised.value.message.code == "PLIK_OKRESU_ISTNIEJE"
    assert [path.name for path in fixture.period_directory.iterdir()] == [existing_name]
    assert existing.read_bytes() == b"reczne poprawki taty"
    assert [path.name for path in fixture.periods_directory.iterdir()] == [PERIOD]


def test_failed_save_of_second_file_publishes_neither_file_nor_folder_okresu(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fixture = make_preparation_fixture(tmp_path)
    real_save = workbook_files.save_workbook
    saved: list[str] = []

    def save_first_then_fail(workbook: Workbook, target: Path, *, external_links_from: Path | None = None) -> None:
        if saved:
            raise ExternalLinksError("wymuszony błąd")
        saved.append(target.name)
        real_save(workbook, target, external_links_from=external_links_from)

    monkeypatch.setattr(workbook_files, "save_workbook", save_first_then_fail)

    with pytest.raises(PreparationError) as raised:
        run_preparation(fixture)

    assert saved == [INTERNAL_SETTLEMENT_NAME]
    assert raised.value.message.code == "BLAD_ZAPISU"
    assert "wymuszony" not in str(raised.value)
    assert list(fixture.periods_directory.iterdir()) == []


@pytest.mark.parametrize("token", ["8_14_09_2026", "09_15_09_2026", "08_15_09_2026", "okres"])
def test_invalid_period_token_stops_before_reading_rejestr(tmp_path: Path, token: str) -> None:
    fixture = make_preparation_fixture(tmp_path)

    with pytest.raises(PreparationError) as raised:
        run_preparation(fixture, token)

    assert raised.value.message.code == "ZLY_TOKEN_OKRESU"
    assert list(fixture.periods_directory.iterdir()) == []


@pytest.mark.parametrize("token", ["29_05_09_2026", "29_05_10_2026"])
def test_period_crossing_months_accepts_month_of_tuesday_or_monday(tmp_path: Path, token: str) -> None:
    rows: list[RegisterRow] = [
        register_order(1, datetime(2026, 9, 28, 23, 59)),
        register_order(2, datetime(2026, 9, 29, 8, 0)),
        register_order(3, datetime(2026, 10, 5, 23, 59)),
        register_order(4, datetime(2026, 10, 6, 0, 0)),
    ]
    fixture = make_preparation_fixture(tmp_path, rows)

    summary = run_preparation(fixture, token)

    assert summary.period_order_count == 2
    assert (fixture.periods_directory / token / f"Rozliczenie wew. {token}.xlsx").is_file()


REGISTER_NAME = "ZLECENIA INTERMAX OD 08_11_2021.xlsx"


def stop_message(fixture: PreparationFixture) -> PreparationError:
    """Uruchamia Przygotowanie, oczekuje zatrzymania i sprawdza, że nic nie powstało."""

    with pytest.raises(PreparationError) as raised:
        run_preparation(fixture)
    assert list(fixture.periods_directory.iterdir()) == []
    assert "SYN-" not in str(raised.value)
    return raised.value


def test_row_without_date_between_period_orders_stops_with_register_row_numbers(tmp_path: Path) -> None:
    undated = register_order(90, datetime(2026, 9, 9, 8, 0))
    undated["DATA GODZ. POCZ."] = "środa rano"
    blank_date = register_order(91, datetime(2026, 9, 9, 9, 0))
    blank_date["DATA GODZ. POCZ."] = None
    rows: list[RegisterRow] = [
        register_order(2, datetime(2026, 9, 8, 8, 0)),
        undated,
        None,
        blank_date,
        register_order(3, datetime(2026, 9, 10, 8, 0)),
    ]
    fixture = make_preparation_fixture(tmp_path, rows)

    error = stop_message(fixture)

    assert error.message.code == "WIERSZ_BEZ_DATY"
    assert str(error) == (
        "Co się stało: Między zleceniami okresu są wiersze z danymi bez poprawnej daty "
        "w kolumnie DATA GODZ. POCZ. Nie utworzono żadnego pliku.\n"
        f"Gdzie: plik {REGISTER_NAME}, arkusz ZLECENIA, wiersze 3, 5\n"
        "Co zrobić: Wpisz poprawną datę w kolumnie DATA GODZ. POCZ. we wskazanych wierszach Rejestru "
        "zleceń albo wyczyść wiersz, jeśli jest zbędny. Zapisz i zamknij Rejestr, i uruchom ponownie."
    )


def test_rows_without_date_outside_period_orders_do_not_stop(tmp_path: Path) -> None:
    note_before = register_order(90, datetime(2026, 9, 1))
    note_before["DATA GODZ. POCZ."] = "uwaga"
    note_after = register_order(91, datetime(2026, 9, 1))
    note_after["DATA GODZ. POCZ."] = "uwaga"
    rows: list[RegisterRow] = [
        note_before,
        register_order(2, datetime(2026, 9, 8, 8, 0)),
        None,
        register_order(3, datetime(2026, 9, 10, 8, 0)),
        note_after,
    ]
    fixture = make_preparation_fixture(tmp_path, rows)

    summary = run_preparation(fixture)

    assert summary.period_order_count == 2
    assert summary.skipped_empty_rows == 1


def test_period_without_orders_stops(tmp_path: Path) -> None:
    rows: list[RegisterRow] = [
        register_order(1, datetime(2026, 9, 7, 15, 0)),
        None,
        register_order(5, datetime(2026, 9, 15, 0, 0)),
    ]
    fixture = make_preparation_fixture(tmp_path, rows)

    error = stop_message(fixture)

    assert error.message.code == "BRAK_ZLECEN_OKRESU"
    assert str(error) == (
        "Co się stało: W Rejestrze zleceń nie ma żadnego zlecenia z tego okresu. Nie utworzono żadnego pliku.\n"
        f"Gdzie: plik {REGISTER_NAME}, arkusz ZLECENIA, okres {PERIOD}\n"
        "Co zrobić: Sprawdź, czy wybrano właściwy okres i czy eksport zleceń do Rejestru został "
        "zrobiony i zapisany, i uruchom ponownie."
    )


def test_period_order_with_empty_or_unknown_skuteczne_stops_with_register_row_numbers(tmp_path: Path) -> None:
    rows: list[RegisterRow] = [
        register_order(1, datetime(2026, 9, 7, 15, 0), successful="???"),  # poprzedni okres
        register_order(2, datetime(2026, 9, 8, 8, 0), successful=" Nie "),
        register_order(3, datetime(2026, 9, 9, 8, 0), successful=""),
        register_order(4, datetime(2026, 9, 10, 8, 0), successful="tak"),
        register_order(5, datetime(2026, 9, 11, 8, 0), successful="częściowo"),
        register_order(6, datetime(2026, 9, 12, 8, 0), successful="   "),
    ]
    fixture = make_preparation_fixture(tmp_path, rows)

    error = stop_message(fixture)

    assert error.message.code == "ZLE_SKUTECZNE"
    assert str(error) == (
        "Co się stało: Zlecenia okresu mają puste albo nieznane SKUTECZNE (dozwolone: tak, nie). "
        "Nie utworzono żadnego pliku.\n"
        f"Gdzie: plik {REGISTER_NAME}, arkusz ZLECENIA, wiersze 4, 6, 7\n"
        "Co zrobić: Wpisz tak albo nie w kolumnie SKUTECZNE we wskazanych wierszach Rejestru zleceń. "
        "Zapisz i zamknij Rejestr, i uruchom ponownie."
    )
    assert "częściowo" not in str(error)


def test_zlecenie_skuteczne_with_worker_outside_worker_config_stops_with_identifier(tmp_path: Path) -> None:
    rows: list[RegisterRow] = [
        register_order(2, datetime(2026, 9, 8, 8, 0), worker="nowy.wykonawca"),
        register_order(3, datetime(2026, 9, 9, 8, 0), worker=" Kamil.Frontczak "),
        register_order(4, datetime(2026, 9, 10, 8, 0), successful="TAK", worker="NOWY.wykonawca"),
        register_order(5, datetime(2026, 9, 11, 8, 0), successful="nie", worker="ktos.nieskuteczny"),
        register_order(6, datetime(2026, 9, 12, 8, 0), worker=""),
    ]
    fixture = make_preparation_fixture(tmp_path, rows)

    error = stop_message(fixture)

    assert error.message.code == "NIEZNANY_WYKONAWCA"
    assert str(error) == (
        "Co się stało: Zlecenia skuteczne mają wykonawców spoza konfiguracji wykonawców: "
        "nowy.wykonawca, (pusty). Nie utworzono żadnego pliku.\n"
        f"Gdzie: plik {REGISTER_NAME}, arkusz ZLECENIA, nowy.wykonawca: wiersze 2, 4; (pusty): wiersz 6\n"
        "Co zrobić: Dopisz identyfikator wykonawcy do konfiguracji wykonawców (worker_mapping.yaml), "
        "tej samej co w Przebiegu rozliczeń, albo popraw WYKONAWCA we wskazanych wierszach Rejestru zleceń. "
        "Zapisz i zamknij Rejestr, i uruchom ponownie."
    )
    assert "ktos.nieskuteczny" not in str(error)


def test_worker_outside_worker_config_in_unsuccessful_order_does_not_stop(tmp_path: Path) -> None:
    rows: list[RegisterRow] = [
        register_order(2, datetime(2026, 9, 8, 8, 0)),
        register_order(3, datetime(2026, 9, 9, 8, 0), successful="nie", worker="ktos.nieskuteczny"),
    ]
    fixture = make_preparation_fixture(tmp_path, rows)

    summary = run_preparation(fixture)

    assert (summary.period_order_count, summary.successful_order_count) == (2, 1)
    assert fixture.internal_settlement_path.is_file()
    assert fixture.collective_file_path.is_file()


def test_more_zlecenia_skuteczne_than_wzorzec_zero_rows_warns_and_creates_both_files(tmp_path: Path) -> None:
    successful_count = COLLECTIVE_TEMPLATE_ZERO_ROWS + 2
    rows: list[RegisterRow] = [
        register_order(number, datetime(2026, 9, 8, 8, number)) for number in range(1, successful_count + 1)
    ]
    rows.insert(3, register_order(99, datetime(2026, 9, 8, 9, 0), successful="nie"))
    fixture = make_preparation_fixture(tmp_path, rows)

    summary = run_preparation(fixture)

    assert [warning.text for warning in summary.warnings] == [
        "Co się stało: Zleceń skutecznych: 8, wierszy przygotowanych zerami we Wzorcu pliku zbiorczego: 6. "
        "Dolne wiersze Pliku zbiorczego nie mają zer w kolumnach ilości.\n"
        f"Gdzie: plik {COLLECTIVE_FILE_NAME}, wiersze 24–25\n"
        "Co zrobić: Uzupełnij ilości w tych wierszach ręcznie. Jeśli zdarza się to często, przekaż to "
        "osobie utrzymującej narzędzie, żeby dodała wiersze z zerami we Wzorcu pliku zbiorczego."
    ]
    assert summary.warnings[0].code == "MALO_WIERSZY_Z_ZERAMI"
    assert summary.successful_order_count == successful_count
    assert len(sheet_rows(fixture.internal_settlement_path, min_row=2, max_col=1)) == successful_count + 1
    created = cell_values(fixture.collective_file_path, min_row=18, max_row=26, min_col=1, max_col=14)
    assert [row[5] for row in created] == [f"ZL-SYN-{number:03d}" for number in range(1, 9)] + [None]
    assert [row[13] for row in created] == [0] * COLLECTIVE_TEMPLATE_ZERO_ROWS + [None] * 3


def test_zlecenia_skuteczne_filling_exactly_wzorzec_zero_rows_do_not_warn(tmp_path: Path) -> None:
    rows: list[RegisterRow] = [
        register_order(number, datetime(2026, 9, 8, 8, number))
        for number in range(1, COLLECTIVE_TEMPLATE_ZERO_ROWS + 1)
    ]
    fixture = make_preparation_fixture(tmp_path, rows)

    summary = run_preparation(fixture)

    assert summary.warnings == []

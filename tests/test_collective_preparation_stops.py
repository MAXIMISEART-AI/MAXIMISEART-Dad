"""Zatrzymania Przygotowania pliku zbiorczego przy problemach z Rejestrem zleceń i wzorcami."""

from __future__ import annotations

from datetime import datetime
import os
from pathlib import Path

from openpyxl import Workbook, load_workbook
import pytest

from rozliczenia.collective_preparation import PreparationError, PreparationSummary, prepare_collective_file
from rozliczenia.workbook_files import ExternalLinksError, WorkbookSaveError
import rozliczenia.workbook_files as workbook_files

from tests.collective_preparation_fixtures import (
    COLLECTIVE_FILE_NAME,
    INTERNAL_SETTLEMENT_NAME,
    PERIOD,
    REGISTER_HEADERS,
    PreparationFixture,
    RegisterRow,
    make_preparation_fixture,
    register_order,
    write_register,
)


def run_preparation(fixture: PreparationFixture, *, dry_run: bool = False) -> PreparationSummary:
    return prepare_collective_file(
        fixture.register_path,
        fixture.periods_directory,
        PERIOD,
        fixture.config_path,
        internal_template_path=fixture.internal_template_path,
        collective_template_path=fixture.collective_template_path,
        dry_run=dry_run,
    )


def input_snapshot(fixture: PreparationFixture) -> dict[Path, bytes]:
    paths = (fixture.register_path, fixture.internal_template_path, fixture.collective_template_path)
    return {path: path.read_bytes() for path in paths if path.exists()}


def stop_preparation(fixture: PreparationFixture, *, dry_run: bool = False) -> PreparationError:
    """Uruchamia proces, oczekuje zatrzymania i sprawdza, że nic nie powstało ani nie zmieniło się."""

    inputs_before = input_snapshot(fixture)
    periods_before = sorted(path.name for path in fixture.periods_directory.iterdir())

    with pytest.raises(PreparationError) as raised:
        run_preparation(fixture, dry_run=dry_run)

    assert sorted(path.name for path in fixture.periods_directory.iterdir()) == periods_before
    assert input_snapshot(fixture) == inputs_before
    assert "SYN-" not in str(raised.value)
    return raised.value


def test_missing_rejestr_zlecen_stops_without_files(tmp_path: Path) -> None:
    fixture = make_preparation_fixture(tmp_path)
    fixture.register_path.unlink()

    error = stop_preparation(fixture)

    assert error.message.code == "BRAK_REJESTRU"
    assert str(error) == (
        "Co się stało: Nie znaleziono Rejestru zleceń. Nie utworzono żadnego pliku.\n"
        f"Gdzie: plik ZLECENIA INTERMAX OD 08_11_2021.xlsx, folder {tmp_path.name}\n"
        "Co zrobić: Wybierz właściwy plik Rejestru zleceń i uruchom ponownie."
    )


def test_rejestr_open_in_excel_stops_and_leaves_lock_file(tmp_path: Path) -> None:
    fixture = make_preparation_fixture(tmp_path)
    lock_file = fixture.register_path.with_name(f"~${fixture.register_path.name}")
    lock_file.write_bytes(b"")

    error = stop_preparation(fixture)

    assert error.message.code == "REJESTR_OTWARTY"
    assert str(error) == (
        "Co się stało: Rejestr zleceń jest otwarty w Excelu. Nie utworzono żadnego pliku.\n"
        f"Gdzie: plik ZLECENIA INTERMAX OD 08_11_2021.xlsx, folder {tmp_path.name}\n"
        "Co zrobić: Zapisz i zamknij Rejestr zleceń w Excelu, potem uruchom ponownie. "
        "Jeśli Excel jest zamknięty, a komunikat wraca, usuń z tego samego folderu "
        "pozostawiony plik ~$ZLECENIA INTERMAX OD 08_11_2021.xlsx i uruchom ponownie."
    )
    assert lock_file.exists()


def test_rejestr_without_required_header_stops_with_header_name(tmp_path: Path) -> None:
    fixture = make_preparation_fixture(tmp_path)
    write_register(
        fixture.register_path,
        headers=tuple(header for header in REGISTER_HEADERS if header != "SKUTECZNE"),
    )

    error = stop_preparation(fixture)

    assert error.message.code == "BRAK_NAGLOWKA_REJESTRU"
    assert str(error) == (
        "Co się stało: W Rejestrze zleceń brakuje wymaganego nagłówka SKUTECZNE. "
        "Nie utworzono żadnego pliku.\n"
        "Gdzie: plik ZLECENIA INTERMAX OD 08_11_2021.xlsx, arkusz ZLECENIA, wiersz 1\n"
        "Co zrobić: Dopisz albo popraw nagłówek SKUTECZNE w pierwszym wierszu arkusza ze zleceniami, "
        "zapisz i zamknij Rejestr zleceń i uruchom ponownie."
    )


def test_rejestr_with_duplicated_required_header_stops_with_header_name(tmp_path: Path) -> None:
    fixture = make_preparation_fixture(tmp_path)
    write_register(fixture.register_path, headers=(*REGISTER_HEADERS, "WYKONAWCA "))

    error = stop_preparation(fixture)

    assert error.message.code == "POWTORZONY_NAGLOWEK_REJESTRU"
    assert str(error) == (
        "Co się stało: W Rejestrze zleceń nagłówek WYKONAWCA występuje więcej niż raz, "
        "więc nie wiadomo, z której kolumny brać dane. Nie utworzono żadnego pliku.\n"
        "Gdzie: plik ZLECENIA INTERMAX OD 08_11_2021.xlsx, arkusz ZLECENIA, wiersz 1\n"
        "Co zrobić: Zostaw nagłówek WYKONAWCA tylko w jednej kolumnie, "
        "zapisz i zamknij Rejestr zleceń i uruchom ponownie."
    )


def test_rejestr_without_sheet_with_required_headers_stops(tmp_path: Path) -> None:
    fixture = make_preparation_fixture(tmp_path)
    write_register(fixture.register_path, headers=("KLIENT", "TELEFON", "WYKONAWCA"))

    error = stop_preparation(fixture)

    assert error.message.code == "BRAK_ARKUSZA_ZLECEN"
    assert str(error) == (
        "Co się stało: W Rejestrze zleceń nie znaleziono arkusza ze zleceniami, czyli arkusza "
        "z wymaganymi nagłówkami w pierwszym wierszu. Nie utworzono żadnego pliku.\n"
        "Gdzie: plik ZLECENIA INTERMAX OD 08_11_2021.xlsx\n"
        "Co zrobić: Sprawdź, czy wybrano właściwy plik Rejestru zleceń. Pierwszy wiersz arkusza "
        "ze zleceniami musi zawierać nagłówki: DATA GODZ. POCZ., MIASTO, adres, UMOWA, URZĄDZENIA, "
        "CZYNNOŚCI, nr zlecenia, WYKONAWCA, NUMER UMOWY/ZLECENIA ORANGE, SKUTECZNE, "
        "CZYNNOŚCI ZREALIZOWANE."
    )


def add_register_sheet(
    register_path: Path,
    title: str,
    rows: list[RegisterRow],
    *,
    headers: tuple[str, ...] = REGISTER_HEADERS,
    hidden: bool = False,
    first: bool = False,
) -> None:
    """Dopisuje do syntetycznego Rejestru arkusz z nagłówkami w wierszu 1 i wierszami od 2."""

    workbook = load_workbook(register_path)
    sheet = workbook.create_sheet(title, 0 if first else None)
    for column, header in enumerate(headers, start=1):
        sheet.cell(1, column).value = header
    for row_number, row in enumerate(rows, start=2):
        for column, header in enumerate(headers, start=1):
            if row is not None and header in row:
                sheet.cell(row_number, column).value = row[header]
    if hidden:
        sheet.sheet_state = "hidden"
    workbook.save(register_path)
    workbook.close()


def test_decoy_sheets_do_not_hide_sheet_with_orders(tmp_path: Path) -> None:
    fixture = make_preparation_fixture(tmp_path)
    add_register_sheet(
        fixture.register_path,
        "komentarze",
        [{"UWAGI": "sprawdzić w poniedziałek", "WYKONAWCA": "adrian.maciejewski"}],
        headers=("DATA GODZ. POCZ.", "WYKONAWCA", "UWAGI"),
        first=True,
    )
    add_register_sheet(
        fixture.register_path,
        "słowniki",
        [{"MIASTO": "POZNAŃ", "UMOWA": "abonament", "SKUTECZNE": "tak"}],
        headers=("MIASTO", "UMOWA", "SKUTECZNE", "URZĄDZENIA"),
        hidden=True,
    )

    summary = run_preparation(fixture)

    assert (summary.period_order_count, summary.successful_order_count) == (4, 3)
    assert fixture.internal_settlement_path.is_file()
    assert fixture.collective_file_path.is_file()


def test_period_orders_in_more_than_one_sheet_stop_with_sheet_names(tmp_path: Path) -> None:
    fixture = make_preparation_fixture(tmp_path)
    add_register_sheet(fixture.register_path, "ZLECENIA 2", [register_order(7, datetime(2026, 9, 10, 9, 0))])

    error = stop_preparation(fixture)

    assert error.message.code == "ZLECENIA_W_WIELU_ARKUSZACH"
    assert str(error) == (
        "Co się stało: Zlecenia tego okresu są w więcej niż jednym arkuszu Rejestru zleceń, "
        "więc nie wiadomo, który arkusz jest właściwy. Nie utworzono żadnego pliku.\n"
        f"Gdzie: plik ZLECENIA INTERMAX OD 08_11_2021.xlsx, arkusze ZLECENIA, ZLECENIA 2, okres {PERIOD}\n"
        "Co zrobić: Zostaw zlecenia tego okresu tylko w jednym arkuszu, "
        "zapisz i zamknij Rejestr zleceń i uruchom ponownie."
    )


def test_sheet_with_orders_of_other_periods_does_not_block_period(tmp_path: Path) -> None:
    fixture = make_preparation_fixture(tmp_path)
    add_register_sheet(
        fixture.register_path,
        "archiwum 2025",
        [register_order(8, datetime(2025, 9, 9, 9, 0)), None, register_order(9, datetime(2025, 9, 10, 9, 0))],
        hidden=True,
        first=True,
    )

    summary = run_preparation(fixture)

    assert (summary.period_order_count, summary.successful_order_count) == (4, 3)


def test_damaged_rejestr_zlecen_stops_without_files(tmp_path: Path) -> None:
    fixture = make_preparation_fixture(tmp_path)
    fixture.register_path.write_bytes(b"to nie jest skoroszyt Excela")

    error = stop_preparation(fixture)

    assert error.message.code == "USZKODZONY_REJESTR"
    assert str(error) == (
        "Co się stało: Nie można odczytać Rejestru zleceń. Plik jest uszkodzony "
        "albo nie jest skoroszytem .xlsx. Nie utworzono żadnego pliku.\n"
        f"Gdzie: plik ZLECENIA INTERMAX OD 08_11_2021.xlsx, folder {tmp_path.name}\n"
        "Co zrobić: Sprawdź, czy Rejestr zleceń otwiera się w Excelu i jest zapisany jako .xlsx, "
        "zamknij go i uruchom ponownie. Jeśli błąd wraca, przekaż to osobie utrzymującej narzędzie."
    )


WZORCE = pytest.mark.parametrize(
    "template_name",
    ["Wzorzec rozliczenia wewnętrznego.xlsx", "Wzorzec pliku zbiorczego.xlsx"],
)


def template_path(fixture: PreparationFixture, template_name: str) -> Path:
    path = fixture.internal_template_path.with_name(template_name)
    assert path in (fixture.internal_template_path, fixture.collective_template_path)
    return path


@WZORCE
def test_missing_wzorzec_stops_without_files(tmp_path: Path, template_name: str) -> None:
    fixture = make_preparation_fixture(tmp_path)
    template_path(fixture, template_name).unlink()

    error = stop_preparation(fixture)

    assert error.message.code == "BRAK_WZORCA"
    assert str(error) == (
        "Co się stało: Nie znaleziono wzorca, z którego powstają pliki okresu. Nie utworzono żadnego pliku.\n"
        f"Gdzie: plik {template_name}, folder config\n"
        "Co zrobić: Przekaż ten komunikat osobie utrzymującej narzędzie."
    )


@WZORCE
def test_wzorzec_open_in_excel_stops_and_leaves_lock_file(tmp_path: Path, template_name: str) -> None:
    fixture = make_preparation_fixture(tmp_path)
    lock_file = template_path(fixture, template_name).with_name(f"~${template_name}")
    lock_file.write_bytes(b"")

    error = stop_preparation(fixture)

    assert error.message.code == "WZORZEC_OTWARTY"
    assert str(error) == (
        "Co się stało: Wzorzec jest otwarty w Excelu. Nie utworzono żadnego pliku.\n"
        f"Gdzie: plik {template_name}, folder config\n"
        "Co zrobić: Zamknij wzorzec w Excelu bez zapisywania zmian i uruchom ponownie. "
        "Jeśli Excel jest zamknięty, a komunikat wraca, usuń z tego samego folderu "
        f"pozostawiony plik ~${template_name} i uruchom ponownie."
    )
    assert lock_file.exists()


@WZORCE
def test_damaged_wzorzec_stops_before_reading_rejestr(tmp_path: Path, template_name: str) -> None:
    fixture = make_preparation_fixture(tmp_path)
    template_path(fixture, template_name).write_bytes(b"uszkodzony wzorzec")
    fixture.register_path.write_bytes(b"uszkodzony Rejestr")

    error = stop_preparation(fixture)

    assert error.message.code == "USZKODZONY_WZORZEC"
    assert str(error) == (
        "Co się stało: Nie można odczytać wzorca. Plik jest uszkodzony "
        "albo nie jest skoroszytem .xlsx. Nie utworzono żadnego pliku.\n"
        f"Gdzie: plik {template_name}, folder config\n"
        "Co zrobić: Przekaż ten komunikat osobie utrzymującej narzędzie."
    )


@pytest.mark.parametrize(
    ("template_name", "header_cell", "header", "sheet", "row"),
    [
        ("Wzorzec rozliczenia wewnętrznego.xlsx", "G1", "NUMER ZL.", "Arkusz1", 1),
        ("Wzorzec pliku zbiorczego.xlsx", "H17", "WYKONAWCA", "Sheet1", 17),
    ],
)
@pytest.mark.parametrize("dry_run", [False, True])
def test_wzorzec_without_expected_header_stops_before_reading_rejestr(
    tmp_path: Path, template_name: str, header_cell: str, header: str, sheet: str, row: int, dry_run: bool
) -> None:
    fixture = make_preparation_fixture(tmp_path)
    path = template_path(fixture, template_name)
    workbook = load_workbook(path, keep_links=True)
    workbook[sheet][header_cell].value = "inna kolumna"
    workbook.save(path)
    workbook.close()
    fixture.register_path.write_bytes(b"uszkodzony Rejestr")

    error = stop_preparation(fixture, dry_run=dry_run)

    assert error.message.code == "ZLY_WZORZEC"
    assert str(error) == (
        f"Co się stało: We wzorcu brakuje nagłówka {header}, więc nie wiadomo, gdzie wpisać zlecenia. "
        "Nie utworzono żadnego pliku.\n"
        f"Gdzie: plik {template_name}, arkusz {sheet}, wiersz {row}\n"
        "Co zrobić: Przekaż ten komunikat osobie utrzymującej narzędzie."
    )


def test_missing_folder_okresow_stops_without_creating_it(tmp_path: Path) -> None:
    fixture = make_preparation_fixture(tmp_path)
    fixture.periods_directory.rmdir()

    with pytest.raises(PreparationError) as raised:
        run_preparation(fixture)

    assert raised.value.message.code == "BRAK_FOLDERU_OKRESOW"
    assert str(raised.value) == (
        "Co się stało: Nie znaleziono folderu okresów. Nie utworzono żadnego pliku.\n"
        f"Gdzie: folder {tmp_path.name}\\INEA\n"
        "Co zrobić: Wybierz istniejący folder okresów, w którym są foldery poprzednich tygodni, "
        "i uruchom ponownie."
    )
    assert not fixture.periods_directory.exists()


@pytest.mark.parametrize(
    ("failure", "period_directory_exists"),
    [
        (OSError("wymuszony błąd dysku"), False),
        (ExternalLinksError("wymuszony błąd linków"), True),
        (WorkbookSaveError("wymuszony błąd zapisu"), True),
    ],
)
def test_failed_save_of_plik_zbiorczy_leaves_no_period_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, period_directory_exists: bool, failure: Exception
) -> None:
    fixture = make_preparation_fixture(tmp_path)
    if period_directory_exists:
        fixture.period_directory.mkdir()
    real_save = workbook_files.save_workbook
    saved: list[str] = []

    def save_first_then_fail(workbook: Workbook, target: Path, *, external_links_from: Path | None = None) -> None:
        if target.name == COLLECTIVE_FILE_NAME:
            raise failure
        saved.append(target.name)
        real_save(workbook, target, external_links_from=external_links_from)

    monkeypatch.setattr(workbook_files, "save_workbook", save_first_then_fail)

    error = stop_preparation(fixture)

    assert saved == [INTERNAL_SETTLEMENT_NAME]
    assert error.message.code == "BLAD_ZAPISU"
    assert "wymuszony" not in str(error)
    assert [path.name for path in fixture.periods_directory.iterdir()] == ([PERIOD] if period_directory_exists else [])
    if period_directory_exists:
        assert list(fixture.period_directory.iterdir()) == []


def test_failed_publication_of_plik_zbiorczy_removes_published_rozliczenie_wewnetrzne(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fixture = make_preparation_fixture(tmp_path)
    fixture.period_directory.mkdir()
    real_rename = os.rename

    def rename_fails_for_plik_zbiorczy(source: str | os.PathLike[str], target: str | os.PathLike[str]) -> None:
        if Path(target) == fixture.collective_file_path:
            raise OSError("wymuszony błąd publikacji")
        real_rename(source, target)

    monkeypatch.setattr(os, "rename", rename_fails_for_plik_zbiorczy)

    error = stop_preparation(fixture)

    assert error.message.code == "BLAD_ZAPISU"
    assert list(fixture.period_directory.iterdir()) == []

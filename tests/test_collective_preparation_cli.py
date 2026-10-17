from __future__ import annotations

from datetime import datetime
from io import StringIO
from pathlib import Path

from rozliczenia.preparation_cli import main

from tests.collective_preparation_fixtures import (
    COLLECTIVE_FILE_NAME,
    COLLECTIVE_TEMPLATE_ZERO_ROWS,
    INTERNAL_SETTLEMENT_NAME,
    PERIOD,
    PreparationFixture,
    RegisterRow,
    make_preparation_fixture,
    register_order,
)


def run_preparation_cli(fixture: PreparationFixture, *extra_args: str) -> tuple[int, str]:
    output = StringIO()
    exit_code = main(
        [
            "--register",
            str(fixture.register_path),
            "--periods-directory",
            str(fixture.periods_directory),
            "--period",
            PERIOD,
            "--config",
            str(fixture.config_path),
            "--internal-template",
            str(fixture.internal_template_path),
            "--collective-template",
            str(fixture.collective_template_path),
            *extra_args,
        ],
        output=output,
    )
    return exit_code, output.getvalue()


def test_cli_creates_both_period_files_and_prints_summary(tmp_path: Path) -> None:
    fixture = make_preparation_fixture(tmp_path)

    exit_code, output = run_preparation_cli(fixture)

    assert exit_code == 0
    assert output.splitlines() == [
        f"Przygotowanie pliku zbiorczego | okres: {PERIOD}",
        "Status końcowy: OK",
        "Zlecenia okresu: 4",
        "Zlecenia skuteczne: 3",
        "Pominięte puste wiersze: 3",
        f"Rozliczenie wewnętrzne: {INTERNAL_SETTLEMENT_NAME}",
        f"Plik zbiorczy: {COLLECTIVE_FILE_NAME}",
    ]
    assert fixture.internal_settlement_path.is_file()
    assert fixture.collective_file_path.is_file()


def test_cli_stop_shows_co_gdzie_co_zrobic_and_exits_1(tmp_path: Path) -> None:
    fixture = make_preparation_fixture(tmp_path)
    fixture.period_directory.mkdir()
    fixture.collective_file_path.write_bytes(b"reczne poprawki taty")

    exit_code, output = run_preparation_cli(fixture)

    assert exit_code == 1
    lines = output.splitlines()
    assert lines[:2] == [
        f"Przygotowanie pliku zbiorczego | okres: {PERIOD}",
        "Status końcowy: ZATRZYMANO",
    ]
    assert lines[2].startswith("Co się stało: Plik tego okresu już istnieje")
    assert lines[3] == f"Gdzie: folder INEA\\{PERIOD}, plik {COLLECTIVE_FILE_NAME}"
    assert lines[4].startswith("Co zrobić: ")
    assert not fixture.internal_settlement_path.exists()
    assert "SYN-" not in output


def test_cli_unexpected_error_hides_exception_text_and_exits_1(tmp_path: Path) -> None:
    fixture = make_preparation_fixture(tmp_path)
    fixture.register_path.write_bytes(b"to nie jest skoroszyt SYN-001")

    exit_code, output = run_preparation_cli(fixture)

    assert exit_code == 1
    assert "Status końcowy: BŁĄD" in output
    assert "Co zrobić: " in output
    assert "SYN-" not in output
    assert "Traceback" not in output
    assert list(fixture.periods_directory.iterdir()) == []


def test_cli_shows_zero_rows_warning_after_summary_and_exits_0(tmp_path: Path) -> None:
    rows: list[RegisterRow] = [
        register_order(number, datetime(2026, 9, 8, 8, number))
        for number in range(1, COLLECTIVE_TEMPLATE_ZERO_ROWS + 2)
    ]
    fixture = make_preparation_fixture(tmp_path, rows)

    exit_code, output = run_preparation_cli(fixture)

    assert exit_code == 0
    lines = output.splitlines()
    assert lines[1] == "Status końcowy: OK"
    assert lines[7:] == [
        "Ostrzeżenie:",
        "Co się stało: Zleceń skutecznych: 7, wierszy przygotowanych zerami we Wzorcu pliku zbiorczego: 6. "
        "Dolne wiersze Pliku zbiorczego nie mają zer w kolumnach ilości.",
        f"Gdzie: plik {COLLECTIVE_FILE_NAME}, wiersz 24",
        "Co zrobić: Uzupełnij ilości w tych wierszach ręcznie. Jeśli zdarza się to często, przekaż to "
        "osobie utrzymującej narzędzie, żeby dodała wiersze z zerami we Wzorcu pliku zbiorczego.",
    ]
    assert "SYN-" not in output

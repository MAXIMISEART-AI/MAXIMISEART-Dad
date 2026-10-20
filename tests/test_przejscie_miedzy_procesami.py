"""Plik zbiorczy z Przygotowania pliku zbiorczego jest wejściem Przebiegu rozliczeń bez ręcznych zmian."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from rozliczenia.engine import run_settlements

from tests.fixtures.preparation import PERIOD, make_preparation_fixture
from tests.fixtures.preparation import cell_values, collective_row, run_preparation
from tests.fixtures.settlement import write_template


def test_plik_zbiorczy_z_przygotowania_daje_rozliczenia_pracownikow_z_ich_zleceniami_skutecznymi(
    tmp_path: Path,
) -> None:
    fixture = make_preparation_fixture(tmp_path)
    worker_template = tmp_path / "Wzorzec rozliczenia pracownika.xlsx"
    write_template(worker_template)

    preparation = run_preparation(fixture)
    settlement = run_settlements(preparation.collective_file, fixture.config_path, worker_template_path=worker_template)

    assert settlement.issues == []
    assert [(result.worker_name, result.status, result.rows) for result in settlement.results] == [
        ("Adrian Testowy", "ZAPISANO", 1),
        ("Darek Fikcyjny", "ZAPISANO", 1),
        ("Kamil Syntetyczny", "ZAPISANO", 1),
    ]
    target_directory = fixture.period_directory / f"Rozliczenie pracowników {PERIOD}"
    expected_rows = {
        "Adrian Testowy": collective_row(2, datetime(2026, 9, 8, 0, 0), "tak", "adrian.testowy"),
        "Darek Fikcyjny": collective_row(6, datetime(2026, 9, 14, 18, 30), "TAK", "dariusz.fikcyjny2"),
        "Kamil Syntetyczny": collective_row(4, datetime(2026, 9, 12, 12, 0), " Tak ", "kamil.syntetyczny"),
    }
    assert sorted(path.name for path in target_directory.iterdir()) == sorted(
        f"Rozliczenie {PERIOD} - {name}.xlsx" for name in expected_rows
    )
    collective_file_rows = cell_values(preparation.collective_file, min_row=18, max_row=20, min_col=1, max_col=46)
    collective_file_row_of = {  # Wiersze danych A:AT Pliku zbiorczego, w kolejności Rejestru zleceń
        "Adrian Testowy": collective_file_rows[0],
        "Kamil Syntetyczny": collective_file_rows[1],
        "Darek Fikcyjny": collective_file_rows[2],
    }
    for name, expected_row in expected_rows.items():
        settlement_file = target_directory / f"Rozliczenie {PERIOD} - {name}.xlsx"
        assert cell_values(settlement_file, min_row=18, max_row=19, min_col=1, max_col=11) == [
            expected_row,
            (None,) * 11,
        ]
        # Przebieg rozliczeń kopiuje cały Wiersz danych A:AT po pozycji kolumn.
        assert cell_values(settlement_file, min_row=18, max_row=18, min_col=1, max_col=46) == [
            collective_file_row_of[name]
        ]

from __future__ import annotations

from pathlib import Path

import pytest
from openpyxl import Workbook, load_workbook

from rozliczenia.workbook_files import ExcelRow
import rozliczenia.workbook_files as workbook_files
from rozliczenia.template_settlement import TemplateWriteError, process_template

from tests.test_settlement_engine import PERIOD, active_worksheet, write_template

WORKER = "Adrian Maciejewski"


def make_template_fixture(tmp_path: Path) -> tuple[Path, Path]:
    """Wzorzec rozliczenia pracownika i ścieżka nowego Szablonu pracownika w pustym folderze."""

    template_path = tmp_path / "Wzorzec rozliczenia pracownika.xlsx"
    write_template(template_path)
    target_directory = tmp_path / "staging"
    target_directory.mkdir()
    return template_path, target_directory / f"Rozliczenie {PERIOD} - {WORKER}.xlsx"


def change_template(template_path: Path, cell: str, value: str) -> None:
    workbook = load_workbook(template_path)
    try:
        active_worksheet(workbook)[cell] = value
        workbook.save(template_path)
    finally:
        workbook.close()


def synthetic_rows() -> list[ExcelRow]:
    return [("syntetyczne miasto",) + (None,) * 45]


def test_przetworzenie_szablonu_pracownika_zglasza_bledny_naglowek(tmp_path: Path) -> None:
    template_path, target_path = make_template_fixture(tmp_path)
    change_template(template_path, "H17", "NIE WYKONAWCA")

    result = process_template(WORKER, template_path, target_path, [])

    assert result.status == "ZLY_SZABLON"
    assert [issue.code for issue in result.issues] == ["ZLY_SZABLON"]
    assert not target_path.exists()


def test_przetworzenie_szablonu_pracownika_przerywa_po_bledzie_zapisu(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    template_path, target_path = make_template_fixture(tmp_path)

    def fail_write(workbook: Workbook, target: Path, *, external_links_from: Path | None = None) -> None:
        raise workbook_files.WorkbookSaveError("synthetic write failure")

    monkeypatch.setattr(workbook_files, "save_workbook", fail_write)

    with pytest.raises(TemplateWriteError):
        process_template(WORKER, template_path, target_path, synthetic_rows())

    assert not target_path.exists()


def test_przetworzenie_szablonu_pracownika_nie_nadpisuje_danych(tmp_path: Path) -> None:
    template_path, target_path = make_template_fixture(tmp_path)
    change_template(template_path, "A18", "wczesniejsza wartosc")

    result = process_template(WORKER, template_path, target_path, synthetic_rows())

    assert result.status == "ZABLOKOWANY"
    assert [issue.code for issue in result.issues] == ["NADPISANIE_ZABLOKOWANE"]
    assert not target_path.exists()


def test_przetworzenie_pustego_szablonu_pracownika_zostawia_szablon_z_wzorca(tmp_path: Path) -> None:
    template_path, target_path = make_template_fixture(tmp_path)

    result = process_template(WORKER, template_path, target_path, [])

    assert (result.status, result.rows, result.issues) == ("PUSTY_SZABLON", 0, ())
    assert target_path.is_file()


def test_przetworzenie_szablonu_pracownika_zapisuje_wiersze(tmp_path: Path) -> None:
    template_path, target_path = make_template_fixture(tmp_path)

    result = process_template(WORKER, template_path, target_path, synthetic_rows())

    assert (result.status, result.rows, result.output_file) == ("ZAPISANO", 1, target_path)
    workbook = load_workbook(target_path)
    try:
        assert active_worksheet(workbook)["A18"].value == "syntetyczne miasto"
    finally:
        workbook.close()

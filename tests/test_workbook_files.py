from __future__ import annotations

from pathlib import Path

from rozliczenia.workbook_files import is_open_in_excel

from tests.test_settlement_engine import write_template


def test_skoroszyt_z_plikiem_blokady_excela_jest_otwarty(tmp_path: Path) -> None:
    workbook_path = tmp_path / "Wzorzec.xlsx"
    write_template(workbook_path)

    assert not is_open_in_excel(workbook_path)

    (tmp_path / "~$Wzorzec.xlsx").touch()

    assert is_open_in_excel(workbook_path)

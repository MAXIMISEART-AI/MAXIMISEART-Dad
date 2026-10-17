from __future__ import annotations

from pathlib import Path

from openpyxl import load_workbook
import pytest

from rozliczenia.workbook_files import ExternalLinksError, is_open_in_excel, save_workbook

from tests.test_settlement_engine import (
    active_worksheet,
    add_external_link_fixture,
    external_link_parts,
    write_template,
)


def make_linked_pattern(path: Path) -> Path:
    write_template(path)
    add_external_link_fixture(path)
    return path


def test_skoroszyt_z_plikiem_blokady_excela_jest_otwarty(tmp_path: Path) -> None:
    workbook_path = tmp_path / "Wzorzec.xlsx"
    write_template(workbook_path)

    assert not is_open_in_excel(workbook_path)

    (tmp_path / "~$Wzorzec.xlsx").touch()

    assert is_open_in_excel(workbook_path)


def test_zapis_skoroszytu_z_wzorca_zachowuje_kazdy_link_zewnetrzny(tmp_path: Path) -> None:
    pattern_path = make_linked_pattern(tmp_path / "Wzorzec.xlsx")
    pattern_before = pattern_path.read_bytes()
    output_directory = tmp_path / "okres"
    output_directory.mkdir()
    target_path = output_directory / "Plik zbiorczy.xlsx"
    workbook = load_workbook(pattern_path, keep_links=True)
    try:
        active_worksheet(workbook)["A18"] = "syntetyczne miasto"

        save_workbook(workbook, target_path, external_links_from=pattern_path)
    finally:
        workbook.close()

    assert external_link_parts(target_path) == external_link_parts(pattern_path)
    assert len(external_link_parts(target_path)) == 2
    saved = load_workbook(target_path)
    try:
        assert active_worksheet(saved)["A18"].value == "syntetyczne miasto"
        assert active_worksheet(saved)["AU18"].value == "=N18"
    finally:
        saved.close()
    assert sorted(path.name for path in output_directory.iterdir()) == ["Plik zbiorczy.xlsx"]
    assert pattern_path.read_bytes() == pattern_before


def test_nieczytelne_linki_zewnetrzne_przerywaja_zapis_bez_zmiany_skoroszytu(tmp_path: Path) -> None:
    target_path = make_linked_pattern(tmp_path / "Plik zbiorczy.xlsx")
    target_before = target_path.read_bytes()
    damaged_pattern = tmp_path / "Wzorzec.xlsx"
    damaged_pattern.write_bytes(b"to nie jest skoroszyt")
    workbook = load_workbook(target_path, keep_links=True)
    try:
        active_worksheet(workbook)["A18"] = "syntetyczne miasto"

        with pytest.raises(ExternalLinksError):
            save_workbook(workbook, target_path, external_links_from=damaged_pattern)
    finally:
        workbook.close()

    assert target_path.read_bytes() == target_before
    assert sorted(path.name for path in tmp_path.iterdir()) == ["Plik zbiorczy.xlsx", "Wzorzec.xlsx"]

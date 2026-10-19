"""Moduł skoroszytu przez jego interfejs: otwarcie z jedną klasyfikacją, układ arkusza i plik z Wzorca."""

from __future__ import annotations

import re
import zipfile
from collections.abc import Callable
from pathlib import Path

import pytest
from openpyxl import load_workbook
from openpyxl.styles import Font

from rozliczenia import workbook_files
from rozliczenia.workbook_files import (
    ExternalLinksError,
    Layout,
    Problem,
    WorkbookError,
    file_from_template,
    open_template,
    read_data_rows,
    read_workbook,
    save_workbook,
)

from tests.test_settlement_engine import (
    active_worksheet,
    add_external_link_fixture,
    cut_sheet_after_data_rows,
    external_link_parts,
    write_source,
    write_template,
)


def _rewrite_parts(path: Path, change: Callable[[str, bytes], bytes | None]) -> None:
    """Przepisuje części archiwum .xlsx; ``None`` usuwa część."""

    with zipfile.ZipFile(path) as source:
        members = [(info, source.read(info.filename)) for info in source.infolist()]
    with zipfile.ZipFile(path, "w") as target:
        for info, data in members:
            changed = change(info.filename, data)
            if changed is not None:
                target.writestr(info, changed)


def not_a_zip(path: Path) -> None:
    path.write_bytes(b"to nie jest skoroszyt")


def without_styles(path: Path) -> None:
    """Komórki zostają ze stylem, ale ``xl/styles.xml`` znika."""

    _rewrite_parts(path, lambda name, data: None if name == "xl/styles.xml" else data)


def without_sheet(path: Path) -> None:
    _rewrite_parts(
        path,
        lambda name, data: re.sub(rb"<sheets>.*?</sheets>", b"<sheets/>", data) if name == "xl/workbook.xml" else data,
    )


def styled_template(path: Path) -> Path:
    """Skoroszyt w układzie Pliku zbiorczego z komórką ze stylem w Wierszu danych."""

    write_template(path)
    workbook = load_workbook(path)
    try:
        sheet = active_worksheet(workbook)
        sheet["N18"].font = Font(bold=True)
        workbook.save(path)
    finally:
        workbook.close()
    return path


def _read_with_format(path: Path) -> None:
    with read_workbook(path) as workbook:
        for sheet in workbook.sheets():
            list(sheet.formatted_rows(min_row=1, columns=range(1, 15)))


def _check_template(path: Path) -> None:
    with open_template(path, Layout.COLLECTIVE):
        pass


def _file_from_template(path: Path) -> None:
    target = path.with_name("Plik z Wzorca.xlsx")
    try:
        with file_from_template(path, target, Layout.COLLECTIVE, recalculate=True):
            pass
    finally:
        assert not target.exists()


OPENINGS: dict[str, Callable[[Path], object]] = {
    "odczyt": read_data_rows,
    "odczyt-z-formatem": _read_with_format,
    "wzorzec": _check_template,
    "plik-z-wzorca": _file_from_template,
}


DAMAGES: dict[str, Callable[[Path], None]] = {
    "nie-zip": not_a_zip,
    "uciety-xml-arkusza": cut_sheet_after_data_rows,
    "bez-styles-xml": without_styles,
    "bez-arkusza": without_sheet,
}
# Odczyt samych wartości nie sięga po style, więc skoroszyt bez styles.xml daje się wtedy przeczytać.
UNREADABLE_CASES = [
    pytest.param(damage, opening, id=f"{damage}-{opening}")
    for damage in DAMAGES
    for opening in OPENINGS
    if (damage, opening) != ("bez-styles-xml", "odczyt")
]


@pytest.mark.parametrize(("damage", "opening"), UNREADABLE_CASES)
def test_uszkodzony_skoroszyt_jest_nieczytelny_przy_kazdym_otwarciu(tmp_path: Path, damage: str, opening: str) -> None:
    path = styled_template(tmp_path / "Skoroszyt.xlsx")
    DAMAGES[damage](path)

    with pytest.raises(WorkbookError) as raised:
        OPENINGS[opening](path)

    assert raised.value.problem is Problem.UNREADABLE
    assert raised.value.path == path


def test_skoroszyt_bez_stylow_daje_sie_przeczytac_bez_formatu(tmp_path: Path) -> None:
    path = tmp_path / "Rozliczenie - zbiorcze.xlsx"
    write_source(path, include_unmapped=False)
    without_styles(path)

    assert [row.number for row in read_data_rows(path)] == [18, 19, 20]


@pytest.mark.parametrize("opening", OPENINGS)
def test_brak_pliku_przy_kazdym_otwarciu(tmp_path: Path, opening: str) -> None:
    with pytest.raises(WorkbookError) as raised:
        OPENINGS[opening](tmp_path / "Brak.xlsx")

    assert raised.value.problem is Problem.MISSING


@pytest.mark.parametrize("opening", OPENINGS)
def test_plik_otwarty_w_excelu_przy_kazdym_otwarciu(tmp_path: Path, opening: str) -> None:
    path = styled_template(tmp_path / "Skoroszyt.xlsx")
    lock_file = tmp_path / "~$Skoroszyt.xlsx"
    lock_file.touch()

    with pytest.raises(WorkbookError) as raised:
        OPENINGS[opening](path)

    assert raised.value.problem is Problem.OPEN_IN_EXCEL
    assert lock_file.exists()


def test_dostepny_skoroszyt_przechodzi_sprawdzenie_dostepnosci(tmp_path: Path) -> None:
    path = styled_template(tmp_path / "Skoroszyt.xlsx")

    workbook_files.ensure_available(path)

    (tmp_path / "~$Skoroszyt.xlsx").touch()
    with pytest.raises(WorkbookError) as raised:
        workbook_files.ensure_available(path)
    assert raised.value.problem is Problem.OPEN_IN_EXCEL


def move_worker_header(path: Path, cell: str | None) -> None:
    workbook = load_workbook(path)
    try:
        sheet = active_worksheet(workbook)
        sheet["H17"] = None
        if cell is not None:
            sheet[cell] = " wykonawca "
        workbook.save(path)
    finally:
        workbook.close()


def _check_worker_header(path: Path) -> None:
    with open_template(path, Layout.COLLECTIVE) as sheet:
        sheet.check_worker_header()


HEADER_CHECKS: dict[str, Callable[[Path], object]] = {
    "odczyt-wierszy-danych": read_data_rows,
    "wzorzec": _check_worker_header,
}


@pytest.mark.parametrize("check", HEADER_CHECKS)
@pytest.mark.parametrize(("cell", "worker_column"), [("C17", "C"), (None, None)], ids=["WYKONAWCA-w-C", "bez-WYKONAWCA"])
def test_wykonawca_poza_h17_to_zly_uklad(tmp_path: Path, check: str, cell: str | None, worker_column: str | None) -> None:
    path = tmp_path / "Rozliczenie - zbiorcze.xlsx"
    write_source(path, include_unmapped=False)
    move_worker_header(path, cell)

    with pytest.raises(WorkbookError) as raised:
        HEADER_CHECKS[check](path)

    assert raised.value.problem is Problem.LAYOUT
    assert raised.value.worker_column == worker_column


def test_naglowek_wykonawca_nie_zalezy_od_wielkosci_liter_i_spacji(tmp_path: Path) -> None:
    path = tmp_path / "Rozliczenie - zbiorcze.xlsx"
    write_source(path, include_unmapped=False)
    move_worker_header(path, "H17")

    _check_worker_header(path)
    assert len(read_data_rows(path)) == 3


def test_wiersze_danych_pliku_zbiorczego_w_kolejnosci_z_wykonawca_i_wartosciami_a_at(tmp_path: Path) -> None:
    path = tmp_path / "Rozliczenie - zbiorcze.xlsx"
    write_source(path, include_unmapped=False)
    workbook = load_workbook(path)
    try:
        sheet = active_worksheet(workbook)
        sheet.insert_rows(19)  # pusty wiersz między Wierszami danych nie jest Wierszem danych
        sheet["L22"] = "poza A:K"  # wiersz bez wartości w A:K nie jest Wierszem danych
        sheet["AT18"] = "uwagi"
        sheet["AU18"] = "poza A:AT"
        workbook.save(path)
    finally:
        workbook.close()
    before = path.read_bytes()

    rows = read_data_rows(path)

    assert [(row.number, row.worker) for row in rows] == [
        (18, "adrian.maciejewski"),
        (20, "dariusz.nowak2"),
        (21, "adrian.maciejewski"),
    ]
    assert all(len(row.values) == 46 for row in rows)
    assert rows[0].values[:2] == ("POZNAŃ", "syntetyczny adres 1")
    assert rows[0].values[45] == "uwagi"
    assert path.read_bytes() == before


def linked_template(path: Path) -> Path:
    write_template(path)
    add_external_link_fixture(path)
    return path


def test_plik_z_wzorca_ma_wiersze_danych_formuly_formatowanie_i_kazdy_link_zewnetrzny(tmp_path: Path) -> None:
    template_path = linked_template(tmp_path / "Wzorzec.xlsx")
    template_before = template_path.read_bytes()
    output_directory = tmp_path / "okres"
    output_directory.mkdir()
    target_path = output_directory / "Rozliczenie - Wykonawca.xlsx"
    rows = [
        ("syntetyczne miasto 1",) + (None,) * 12 + (2,) + (None,) * 31 + ("uwagi 1",),
        ("syntetyczne miasto 2",) + (None,) * 45,
    ]

    with file_from_template(template_path, target_path, Layout.COLLECTIVE, recalculate=True) as sheet:
        sheet.write_data_rows(rows)
        assert not target_path.exists()

    assert external_link_parts(target_path) == external_link_parts(template_path)
    assert len(external_link_parts(target_path)) == 2
    saved = load_workbook(target_path)
    try:
        written = active_worksheet(saved)
        assert [
            next(written.iter_rows(min_row=row, max_row=row, max_col=46, values_only=True)) for row in (18, 19)
        ] == rows
        assert written["AU18"].value == "=N18"
        assert written["AU19"].value == "=N19"
        assert written["H17"].value == "WYKONAWCA"
        assert written["A17"].fill.fgColor.rgb == "0000AA55"
        assert saved["Rates"]["B1"].value == 17.5
        assert saved.calculation.fullCalcOnLoad is True
    finally:
        saved.close()
    assert sorted(path.name for path in output_directory.iterdir()) == [target_path.name]
    assert template_path.read_bytes() == template_before


def test_wyjatek_w_bloku_pliku_z_wzorca_nie_zostawia_pliku(tmp_path: Path) -> None:
    template_path = linked_template(tmp_path / "Wzorzec.xlsx")
    template_before = template_path.read_bytes()
    output_directory = tmp_path / "okres"
    output_directory.mkdir()

    with pytest.raises(RuntimeError, match="syntetyczny"):
        with file_from_template(
            template_path, output_directory / "Plik.xlsx", Layout.COLLECTIVE, recalculate=False
        ) as sheet:
            sheet.write_data_rows([("syntetyczne miasto",) + (None,) * 45])
            raise RuntimeError("syntetyczny błąd w bloku")

    assert list(output_directory.iterdir()) == []
    assert template_path.read_bytes() == template_before


def test_nieudany_zapis_pliku_z_wzorca_nie_zostawia_pliku(tmp_path: Path) -> None:
    template_path = linked_template(tmp_path / "Wzorzec.xlsx")
    missing_directory = tmp_path / "brak"

    with pytest.raises(workbook_files.WorkbookSaveError):
        with file_from_template(template_path, missing_directory / "Plik.xlsx", Layout.COLLECTIVE, recalculate=False):
            pass

    assert not missing_directory.exists()


def test_wzorzec_z_wartoscia_w_wierszu_danych_ma_dane_a_formula_nie(tmp_path: Path) -> None:
    template_path = styled_template(tmp_path / "Wzorzec.xlsx")
    with open_template(template_path, Layout.COLLECTIVE) as sheet:
        assert not sheet.has_input_data()

    workbook = load_workbook(template_path)
    try:
        active_worksheet(workbook)["K25"] = "wcześniejsza wartość"
        workbook.save(template_path)
    finally:
        workbook.close()
    with open_template(template_path, Layout.COLLECTIVE) as sheet:
        assert sheet.has_input_data()


def test_nieczytelne_linki_zewnetrzne_przerywaja_zapis_bez_zmiany_skoroszytu(tmp_path: Path) -> None:
    target_path = linked_template(tmp_path / "Plik zbiorczy.xlsx")
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

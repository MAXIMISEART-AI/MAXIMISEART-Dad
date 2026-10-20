"""Moduł skoroszytu przez jego interfejs: otwarcie z jedną klasyfikacją, układ arkusza i plik z Wzorca."""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from collections.abc import Callable
from datetime import date, datetime, time
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
from openpyxl import load_workbook
from openpyxl.cell.rich_text import CellRichText, TextBlock
from openpyxl.cell.text import InlineFont
from openpyxl.styles import Font
from openpyxl.styles.numbers import is_date_format

from rozliczenia import workbook_files
from rozliczenia.workbook_files import (
    ExcelRow,
    ExternalLinksError,
    Layout,
    Problem,
    WorkbookError,
    WorkbookSaveError,
    WorkerSettlementTemplate,
    file_from_template,
    open_template,
    read_data_rows,
    read_workbook,
    save_workbook,
)

from tests.fixtures.benchmark import WORKER_TEMPLATE, write_synthetic_templates, zip_part
from tests.fixtures.porownanie import compare_worker_settlements
from tests.fixtures.workbooks import active_worksheet, add_external_link_fixture, cut_sheet_after_data_rows, external_link_parts, without_sheet, without_styles
from tests.fixtures.settlement import write_source, write_template


def not_a_zip(path: Path) -> None:
    path.write_bytes(b"to nie jest skoroszyt")


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
        (18, "adrian.testowy"),
        (20, "dariusz.fikcyjny2"),
        (21, "adrian.testowy"),
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


def shared_formula_masters(path: Path) -> list[str]:
    """Wzory wspólnych formuł arkusza ``Sheet1`` (zakres, numer i treść) w kolejności z pliku."""

    return re.findall(r'<f t="shared" ref="[^"]+" si="\d+">[^<]*</f>', zip_part(path, "xl/worksheets/sheet1.xml"))


def calculation_flags(path: Path) -> dict[str, str | None]:
    calculation = ET.fromstring(zip_part(path, "xl/workbook.xml")).find(
        "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}calcPr"
    )
    assert calculation is not None
    return {name: calculation.get(name) for name in ("calcMode", "fullCalcOnLoad", "forceFullCalc")}


def test_rozliczenie_pracownika_z_wzorca_zachowuje_wspolne_formuly_calcchain_i_flagi_przeliczania(tmp_path: Path) -> None:
    template_path = write_synthetic_templates(tmp_path / "wzorce") / WORKER_TEMPLATE
    template_before = template_path.read_bytes()
    output_directory = tmp_path / "okres"
    output_directory.mkdir()
    target_path = output_directory / "Rozliczenie - Wykonawca.xlsx"
    rows: list[ExcelRow] = [
        ("syntetyczne miasto 1",) + (None,) * 12 + (2,) + (None,) * 31 + ("uwagi 1",),
        ("syntetyczne miasto 2",) + (None,) * 45,
    ]

    WorkerSettlementTemplate(template_path).create_settlement(target_path, rows)

    assert shared_formula_masters(target_path) == shared_formula_masters(template_path)
    assert len(shared_formula_masters(template_path)) > 4
    assert zip_part(target_path, "xl/calcChain.xml") == zip_part(template_path, "xl/calcChain.xml")
    assert calculation_flags(target_path) == {"calcMode": "auto", "fullCalcOnLoad": "1", "forceFullCalc": "1"}
    assert external_link_parts(target_path) == external_link_parts(template_path)
    saved = load_workbook(target_path)
    try:
        written = active_worksheet(saved)
        assert [
            next(written.iter_rows(min_row=row, max_row=row, max_col=46, values_only=True)) for row in (18, 19)
        ] == rows
        assert written["N20"].value == 0
        assert str(written["AU19"].value).startswith("=N19*")
        assert written["H17"].value == "WYKONAWCA"
    finally:
        saved.close()
    assert sorted(path.name for path in output_directory.iterdir()) == [target_path.name]
    assert template_path.read_bytes() == template_before


def _settlement_folders(tmp_path: Path, template_path: Path, rows: list[ExcelRow]) -> tuple[Path, Path]:
    """Rozliczenie pracownika z ``WorkerSettlementTemplate`` i plik z Wzorca zapisany przez openpyxl, każdy w swoim folderze."""

    created = tmp_path / "rozliczenie"
    expected = tmp_path / "przez-openpyxl"
    created.mkdir()
    expected.mkdir()
    name = "Rozliczenie - Wykonawca.xlsx"
    WorkerSettlementTemplate(template_path).create_settlement(created / name, rows)
    with file_from_template(template_path, expected / name, Layout.COLLECTIVE, recalculate=True) as sheet:
        sheet.write_data_rows(rows)
    return created, expected


def _row(**columns: Any) -> ExcelRow:
    values: list[Any] = [None] * 46
    for letter, value in columns.items():
        values[_column_index(letter) - 1] = value
    return tuple(values)


def _column_index(letter: str) -> int:
    index = 0
    for character in letter:
        index = index * 26 + ord(character) - 64
    return index


VALUE_ROWS: list[ExcelRow] = [
    _row(
        A='<b>Miasto & "Wieś"</b> \'1\' ]]>',
        B=" spacje na brzegach ",
        C="=N18*2",
        D="=",
        E="#N/A",
        F="",
        G=date(2026, 9, 8),
        H="adrian.testowy",
        I=12345678901234567,
        J=True,
        K=datetime(2026, 9, 8, 7, 30, 15),
        N=None,
        O=1.25,
        P=Decimal("2.5"),
        Q=time(13, 45),
        R=False,
        AT="zażółć gęślą jaźń\nnowa linia",
    ),
    _row(A="tylko miasto"),
    _row(A="wiersz poza Wzorcem", N=3),
]


@pytest.mark.parametrize("template", ["maly", "syntetyczny"])
def test_rozliczenie_pracownika_ma_wartosci_kazdego_typu_jak_plik_z_wzorca(tmp_path: Path, template: str) -> None:
    if template == "maly":
        template_path = linked_template(tmp_path / "Wzorzec.xlsx")
    else:
        template_path = write_synthetic_templates(tmp_path / "wzorce") / WORKER_TEMPLATE

    created, expected = _settlement_folders(tmp_path, template_path, VALUE_ROWS)

    assert set(compare_worker_settlements(expected, created).values()) == {0}
    saved = load_workbook(created / "Rozliczenie - Wykonawca.xlsx")
    try:
        written = active_worksheet(saved)
        assert written["A18"].value == '<b>Miasto & "Wieś"</b> \'1\' ]]>'
        assert written["B18"].value == " spacje na brzegach "
        assert written["C18"].value == "=N18*2"
        assert (written["D18"].value, written["E18"].value, written["F18"].value) == ("=", "#N/A", None)
        assert written["G18"].value == datetime(2026, 9, 8)
        assert is_date_format(written["G18"].number_format)
        assert written["K18"].value == datetime(2026, 9, 8, 7, 30, 15)
        assert is_date_format(written["K18"].number_format)
        assert written["Q18"].value == time(13, 45)
        assert (written["I18"].value, written["J18"].value, written["R18"].value) == (1.234567890123457e16, True, False)
        assert (written["O18"].value, written["P18"].value) == (1.25, 2.5)
        assert written["AT18"].value == "zażółć gęślą jaźń\nnowa linia"
        assert (written["N18"].value, written["N19"].value, written["N20"].value) == (None, None, 3)
        assert written["A20"].value == "wiersz poza Wzorcem"
    finally:
        saved.close()


def formula_in_data_row(path: Path) -> Path:
    write_template(path)
    workbook = load_workbook(path)
    try:
        active_worksheet(workbook)["K18"] = "=N18+1"
        workbook.save(path)
    finally:
        workbook.close()
    add_external_link_fixture(path)
    return path


RICH_TEXT_ROWS: list[ExcelRow] = [_row(A=CellRichText("zwykły ", TextBlock(InlineFont(b=True), "pogrubiony")), N=1)]


@pytest.mark.parametrize(
    ("make_template", "rows"),
    [(formula_in_data_row, VALUE_ROWS), (linked_template, RICH_TEXT_ROWS)],
    ids=["formula-w-wierszu-danych-wzorca", "tekst-sformatowany"],
)
def test_rozliczenie_pracownika_spoza_ksztaltu_excela_jest_jak_plik_z_wzorca(
    tmp_path: Path, make_template: Callable[[Path], Path], rows: list[ExcelRow]
) -> None:
    template_path = make_template(tmp_path / "Wzorzec.xlsx")

    created, expected = _settlement_folders(tmp_path, template_path, rows)

    assert set(compare_worker_settlements(expected, created).values()) == {0}


def test_znak_niedozwolony_w_xml_przerywa_zapis_rozliczenia_pracownika_bez_pliku(tmp_path: Path) -> None:
    template_path = linked_template(tmp_path / "Wzorzec.xlsx")
    output_directory = tmp_path / "okres"
    output_directory.mkdir()

    with pytest.raises(WorkbookSaveError):
        WorkerSettlementTemplate(template_path).create_settlement(
            output_directory / "Rozliczenie.xlsx", [_row(A="syntetyczny\x01znak")]
        )

    assert list(output_directory.iterdir()) == []


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

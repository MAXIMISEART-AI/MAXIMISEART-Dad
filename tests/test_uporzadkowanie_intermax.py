"""Uporządkowanie INTERMAX przez rdzeń Uruchomienia procesu: wynikowy INTERMAX z dysku, Kopie INTERMAX i Zatrzymania."""

from __future__ import annotations

import re
import zipfile
from collections.abc import Callable
from dataclasses import replace
from datetime import datetime
from io import BytesIO
from pathlib import Path

import pytest
from openpyxl import load_workbook

from rozliczenia.intermax_ordering import OrderingSummary
from rozliczenia.intermax_process import PROCESS, OrderingInputs
from rozliczenia.process_run import Finished, Outcome, Stop, run_process

from tests.fixtures.clock import ManualClock
from tests.fixtures.intermax import (
    APP_LAST,
    DATE,
    FIRST,
    LAST,
    NUMBER,
    ORDER_SHEET,
    WORKER,
    Intermax,
    Layout,
    Order,
    order_rows,
    parts,
)
from tests.fixtures.interlocutor import Tata

NOW = datetime(2026, 10, 25, 21, 5, 7)
COPY_NAME = "INTERMAX przed uporządkowaniem 2026-10-25 21-05-07.xlsx"
REGISTER_NAME = "ZLECENIA INTERMAX OD 08_11_2021.xlsx"


def _write(path: Path, content: bytes) -> None:
    path.write_bytes(content)


def _run(
    tmp_path: Path, *, now: datetime = NOW, store: Callable[[Path, bytes], None] = _write
) -> Outcome[OrderingSummary]:
    inputs = OrderingInputs(tmp_path / "OneDrive" / REGISTER_NAME, tmp_path / "Kopie INTERMAX", lambda: now, store)
    return run_process(
        PROCESS, inputs, Tata(), view=lambda _inputs, summary: summary, metrics_path=tmp_path / "m.jsonl", clock=ManualClock()
    )


def _register(tmp_path: Path, intermax: Intermax | None = None) -> tuple[Path, Layout]:
    folder = tmp_path / "OneDrive"
    folder.mkdir(exist_ok=True)
    path = folder / REGISTER_NAME
    return path, (intermax or Intermax()).write(path)


def _expected(order: Order) -> tuple[object, ...]:
    values = order.values()
    return tuple(values.get(column) for column in range(1, APP_LAST + 1))


def _stop(outcome: Outcome[OrderingSummary]) -> Stop:
    assert isinstance(outcome.ending, Stop), outcome.ending
    return outcome.ending


def test_dzien_staje_pod_zoltym_wierszem_w_segmentach_wykonawcow_alfabetycznie_i_po_godzinie(tmp_path: Path) -> None:
    path, layout = _register(tmp_path)
    anna_10, anna_10_later, anna_16 = layout.raw[1], layout.raw[4], layout.raw[2]
    bartek, jan_8, jan_14_shifted = layout.raw[5], layout.raw[3], layout.raw[0]

    outcome = _run(tmp_path)

    assert isinstance(outcome.ending, Finished) and outcome.ending.result == "OK"
    assert outcome.view is not None
    assert (outcome.view.day.isoformat(), outcome.view.order_count, outcome.view.worker_count) == ("2026-10-26", 6, 3)
    assert layout.yellow is not None
    assert order_rows(path, layout.yellow + 1, layout.yellow + 12) == [
        None,
        _expected(anna_10),
        _expected(anna_10_later),
        _expected(anna_16),
        None,
        _expected(bartek),
        None,
        _expected(jan_8),
        _expected(jan_14_shifted),
        None,
        None,
        None,
    ]


def test_bez_zoltego_wiersza_dzien_staje_10_pustych_wierszy_pod_ostatnim_uporzadkowanym_zleceniem(tmp_path: Path) -> None:
    path, layout = _register(tmp_path, Intermax(yellow=False, gap=1))

    _run(tmp_path)

    rows = order_rows(path, layout.last_ordered + 1, layout.last_ordered + 11)
    assert rows[:10] == [None] * 10
    assert rows[10] == _expected(layout.raw[1])
    sheet = load_workbook(path, read_only=True).worksheets[1]
    assert sheet.max_row == layout.last_ordered + 10 + 6 + 2, "<dimension> obejmuje dłuższy dzień"


def test_pierwszy_wiersz_na_miejscu_nie_jest_przesuwany(tmp_path: Path) -> None:
    path, layout = _register(tmp_path, Intermax(shifted=False))

    _run(tmp_path)

    assert layout.yellow is not None
    assert order_rows(path, layout.yellow + 9, layout.yellow + 9) == [_expected(layout.raw[0])]


def test_zlecenia_maja_wyglad_reszty_intermax_a_kolumny_za_uwagi_zostaja_jak_przyszly(tmp_path: Path) -> None:
    path, layout = _register(tmp_path)

    _run(tmp_path)

    assert layout.yellow is not None
    sheet = load_workbook(path).worksheets[1]
    for row in (layout.yellow + 2, layout.yellow + 9):
        for column in range(FIRST, LAST + 1):
            cell = sheet.cell(row, column)
            font = cell.font
            assert (font.name, font.sz, font.b, font.i, font.color.rgb) == (
                "Calibri",
                9 if column == WORKER else 8,
                False,
                False,
                "FF000000",
            ), cell.coordinate
            assert cell.fill.fill_type is None, cell.coordinate
            assert {side.style for side in (cell.border.left, cell.border.right, cell.border.top, cell.border.bottom)} == {
                "thin"
            }
            assert (cell.alignment.horizontal, cell.alignment.vertical) == ("left", "center")
        assert sheet.cell(row, DATE).number_format == "m/d/yy h:mm"
        for column in range(LAST + 1, APP_LAST + 1):
            cell = sheet.cell(row, column)
            assert (cell.font.name, cell.font.sz, cell.font.b, cell.fill.fill_type) == ("Roboto", 4, True, "solid")


def test_inne_czesci_pliku_i_wiersze_nad_dniem_zostaja_bajt_w_bajt_a_hiperlacza_ida_ze_zleceniem(tmp_path: Path) -> None:
    path, layout = _register(tmp_path)
    before = parts(path)

    _run(tmp_path)

    after = parts(path)
    sheet_part, styles_part = "xl/worksheets/sheet2.xml", "xl/styles.xml"
    assert list(after) == list(before)
    assert {name for name in before if before[name] != after[name]} <= {sheet_part, styles_part}
    assert layout.yellow is not None
    region = next(row for row in re.finditer(rb'<row r="(\d+)"', before[sheet_part]) if int(row.group(1)) > layout.yellow)
    without_dimension = re.compile(rb"<dimension [^>]*>")
    above = without_dimension.sub(b"", before[sheet_part][: region.start()])
    assert b"<sheetData>" in above and without_dimension.sub(b"", after[sheet_part]).startswith(above)
    sheet = load_workbook(path).worksheets[1]
    links = {
        cell.value: link.target
        for row in range(layout.yellow + 2, layout.yellow + 10)
        if (link := (cell := sheet.cell(row, NUMBER)).hyperlink) is not None
    }
    assert links == {f"ZL-{order.number}": order.link for order in layout.raw}


def test_kopia_intermax_ma_nazwe_z_zegara_procesu_i_bajty_sprzed_uporzadkowania(tmp_path: Path) -> None:
    path, _ = _register(tmp_path)
    original = path.read_bytes()

    _run(tmp_path)

    copy = tmp_path / "Kopie INTERMAX" / COPY_NAME
    assert copy.read_bytes() == original
    assert path.read_bytes() != original


def test_po_jedenastej_kopii_zostaje_10_najnowszych_a_inne_pliki_folderu_zostaja(tmp_path: Path) -> None:
    _register(tmp_path)
    copies = tmp_path / "Kopie INTERMAX"
    copies.mkdir()
    older = [copies / f"INTERMAX przed uporządkowaniem 2026-10-{day:02d} 07-00-00.xlsx" for day in range(10, 20)]
    for copy in older:
        copy.write_bytes(b"kopia")
    (copies / "notatka.txt").write_text("tata", encoding="utf-8")

    _run(tmp_path)

    assert sorted(path.name for path in copies.iterdir()) == sorted(
        [*(copy.name for copy in older[1:]), COPY_NAME, "notatka.txt"]
    )


def _changed_part(content: bytes) -> bytes:
    """Ten sam skoroszyt z jedną zmienioną częścią spoza uporządkowanego dnia."""

    out = BytesIO()
    with zipfile.ZipFile(BytesIO(content)) as source, zipfile.ZipFile(out, "w") as target:
        for info in source.infolist():
            data = source.read(info)
            target.writestr(info, data + b" " if info.filename == "docProps/app.xml" else data)
    return out.getvalue()


def test_niezgodnosc_w_sprawdzeniu_zapisu_to_zatrzymanie_do_maksa_bez_zmiany_intermax_i_kopii(tmp_path: Path) -> None:
    path, _ = _register(tmp_path)
    original = path.read_bytes()

    def store(target: Path, content: bytes) -> None:
        target.write_bytes(_changed_part(content))

    outcome = _run(tmp_path, store=store)

    stop = _stop(outcome)
    assert (stop.message.code, stop.stop_kind) == ("ZAPIS_INTERMAX_NIEZGODNY", "for_maks")
    assert path.read_bytes() == original
    assert [entry.name for entry in path.parent.iterdir()] == [REGISTER_NAME], "plik tymczasowy nie zostaje"
    assert not (tmp_path / "Kopie INTERMAX").exists()


def test_bez_surowych_zlecen_zatrzymanie_dla_taty_i_nic_nie_zapisano(tmp_path: Path) -> None:
    path, _ = _register(tmp_path, Intermax(raw=()))
    original = path.read_bytes()

    stop = _stop(_run(tmp_path))

    assert (stop.message.code, stop.stop_kind) == ("BRAK_SUROWYCH_ZLECEN", "for_tata")
    assert ORDER_SHEET in stop.message.where
    assert path.read_bytes() == original
    assert not (tmp_path / "Kopie INTERMAX").exists()


def test_intermax_otwarty_w_excelu_to_zatrzymanie_dla_taty_bez_zapisu(tmp_path: Path) -> None:
    path, _ = _register(tmp_path)
    original = path.read_bytes()
    lock = path.with_name(f"~${path.name}")
    lock.write_bytes(b"")

    stop = _stop(_run(tmp_path))

    assert (stop.message.code, stop.stop_kind) == ("INTERMAX_OTWARTY", "for_tata")
    assert path.read_bytes() == original
    assert not (tmp_path / "Kopie INTERMAX").exists()


def test_scalone_komorki_w_surowych_zleceniach_to_zatrzymanie_do_maksa_bez_zapisu(tmp_path: Path) -> None:
    path, layout = _register(tmp_path)
    workbook = load_workbook(path)
    workbook.worksheets[1].merge_cells(start_row=layout.first_raw + 1, start_column=4, end_row=layout.first_raw + 2, end_column=4)
    workbook.save(path)
    original = path.read_bytes()

    stop = _stop(_run(tmp_path))

    assert (stop.message.code, stop.stop_kind) == ("NIEOBSLUGIWANY_UKLAD_INTERMAX", "for_maks")
    assert path.read_bytes() == original


@pytest.mark.parametrize("now", [datetime(2026, 10, 25, 21, 5, 7), datetime(2026, 10, 27, 8, 0, 0)])
def test_uruchomienie_ma_okres_dzisiejszej_daty_z_zegara_procesu(tmp_path: Path, now: datetime) -> None:
    inputs = replace(OrderingInputs(tmp_path / REGISTER_NAME), now=lambda: now)

    assert inputs.period == {25: "20_26_10_2026", 27: "27_02_11_2026"}[now.day]
    assert inputs.dry_run is False

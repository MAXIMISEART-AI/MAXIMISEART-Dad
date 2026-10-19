from __future__ import annotations

from collections.abc import Callable, Mapping
from datetime import date, datetime, timedelta
from pathlib import Path
import time

from openpyxl import Workbook, load_workbook
from openpyxl.utils import get_column_letter
import pytest

from rozliczenia.domain import ProgressEvent, ProgressObserver, ProgressPhase, ProgressState
from rozliczenia.progress import PhaseState, ProgressProjection
from rozliczenia.collective_preparation import (
    PreparationSummary,
    prepare_collective_file,
)
from rozliczenia.message import Message, StopError
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
    write_collective_template,
    write_internal_template,
)
from tests.test_settlement_engine import active_worksheet, external_link_parts, projected


def run_preparation(
    fixture: PreparationFixture,
    period: str = PERIOD,
    *,
    dry_run: bool = False,
    observer: ProgressObserver | None = None,
    confirm_plan: Callable[[PreparationSummary], None] | None = None,
) -> PreparationSummary:
    return prepare_collective_file(
        fixture.register_path,
        fixture.periods_directory,
        period,
        fixture.config_path,
        internal_template_path=fixture.internal_template_path,
        collective_template_path=fixture.collective_template_path,
        dry_run=dry_run,
        observer=observer,
        confirm_plan=confirm_plan,
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
    assert summary.skipped_empty_rows == 5
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

    with pytest.raises(StopError) as raised:
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


@pytest.mark.parametrize(
    "token",
    [
        "8_14_09_2026",
        "09_15_09_2026",
        "08_15_09_2026",
        "okres",
        "../14_09_2026",
        # Na przełomie miesięcy i lat miesiąc i rok tokenu są z wtorku, nie z poniedziałku.
        "27_02_11_2026",
        "29_04_01_2027",
    ],
)
def test_invalid_period_token_stops_before_reading_rejestr(tmp_path: Path, token: str) -> None:
    fixture = make_preparation_fixture(tmp_path)

    with pytest.raises(StopError) as raised:
        run_preparation(fixture, token)

    assert raised.value.message.code == "ZLY_TOKEN_OKRESU"
    assert list(fixture.periods_directory.iterdir()) == []


@pytest.mark.parametrize(
    ("token", "tuesday"),
    [("27_02_10_2026", datetime(2026, 10, 27)), ("29_04_12_2026", datetime(2026, 12, 29))],
)
def test_period_crossing_month_or_year_takes_month_and_year_of_tuesday(
    tmp_path: Path, token: str, tuesday: datetime
) -> None:
    rows: list[RegisterRow] = [
        register_order(1, tuesday - timedelta(minutes=1)),
        register_order(2, tuesday + timedelta(hours=8)),
        register_order(3, tuesday + timedelta(days=7, minutes=-1)),
        register_order(4, tuesday + timedelta(days=7)),
    ]
    fixture = make_preparation_fixture(tmp_path, rows)

    summary = run_preparation(fixture, token)

    assert summary.period_order_count == 2
    assert list(summary.orders_per_day)[0] == tuesday.date()
    assert (fixture.periods_directory / token / f"Rozliczenie wew. {token}.xlsx").is_file()


EXPECTED_ORDERS_PER_DAY = {
    date(2026, 9, 8): 1,
    date(2026, 9, 9): 1,
    date(2026, 9, 10): 0,
    date(2026, 9, 11): 0,
    date(2026, 9, 12): 1,
    date(2026, 9, 13): 0,
    date(2026, 9, 14): 1,
}


def test_summary_reports_orders_per_day_for_every_day_of_the_period(tmp_path: Path) -> None:
    fixture = make_preparation_fixture(tmp_path)

    summary = run_preparation(fixture)

    assert summary.orders_per_day == EXPECTED_ORDERS_PER_DAY
    assert list(summary.orders_per_day) == sorted(EXPECTED_ORDERS_PER_DAY)


def test_dry_run_returns_plan_with_orders_per_day_and_writes_nothing(tmp_path: Path) -> None:
    fixture = make_preparation_fixture(tmp_path)
    inputs = (fixture.register_path, fixture.internal_template_path, fixture.collective_template_path)
    before = [path.read_bytes() for path in inputs]

    summary = run_preparation(fixture, dry_run=True)

    assert summary.period == PERIOD
    assert summary.period_order_count == 4
    assert summary.successful_order_count == 3
    assert summary.skipped_empty_rows == 5
    assert summary.orders_per_day == EXPECTED_ORDERS_PER_DAY
    assert summary.internal_settlement_file == fixture.internal_settlement_path
    assert summary.collective_file == fixture.collective_file_path
    assert list(fixture.periods_directory.iterdir()) == []
    assert [path.read_bytes() for path in inputs] == before


STAGES_IN_ORDER = [
    (ProgressPhase.CHECKING, ProgressState.START),
    (ProgressPhase.CHECKING, ProgressState.END),
    (ProgressPhase.READING, ProgressState.START),
    (ProgressPhase.READING, ProgressState.END),
    (ProgressPhase.READING, ProgressState.ISSUE_COUNT),
    (ProgressPhase.PLANNING, ProgressState.START),
    (ProgressPhase.PLANNING, ProgressState.END),
    (ProgressPhase.PLANNING, ProgressState.PLAN_READY),
    (ProgressPhase.SAVING, ProgressState.START),
    (ProgressPhase.SAVING, ProgressState.END),
]


@pytest.mark.parametrize("dry_run", [False, True])
def test_zdarzenia_przebiegu_pass_four_stages_in_order_without_worker_events(
    tmp_path: Path, dry_run: bool
) -> None:
    fixture = make_preparation_fixture(tmp_path, [register_order(1, datetime(2026, 9, 13, 23, 59))])
    recorded: list[ProgressEvent] = []
    projection = ProgressProjection("DRY-RUN" if dry_run else "RUN", PERIOD)

    def recording_observer(event: ProgressEvent) -> None:
        recorded.append(event)
        projection.update(event)

    summary = run_preparation(fixture, dry_run=dry_run, observer=recording_observer)

    assert [(event.phase, event.state) for event in recorded] == STAGES_IN_ORDER
    assert all(event.worker_name is None for event in recorded)
    assert set(projection.snapshot.phase_states.values()) == {PhaseState.COMPLETED}
    assert [warning.code for warning in summary.warnings] == ["NIEPELNY_OKRES"]
    assert projection.snapshot.issue_count == 1
    assert projection.snapshot.template_total == 0
    assert "SYN-" not in repr(recorded)


def test_progress_projection_accepts_przygotowanie_pliku_zbiorczego_interrupted_in_zapisywanie_with_its_time(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fixture = make_preparation_fixture(tmp_path)
    projection = ProgressProjection("RUN", PERIOD)
    save_s = 0.05

    def fail_save(workbook: Workbook, target: Path, *, external_links_from: Path | None = None) -> None:
        time.sleep(save_s)
        raise ExternalLinksError("wymuszony błąd")

    monkeypatch.setattr(workbook_files, "save_workbook", fail_save)

    with pytest.raises(StopError):
        run_preparation(fixture, observer=projected(projection))

    assert projection.snapshot.phase_states == {
        ProgressPhase.CHECKING: PhaseState.COMPLETED,
        ProgressPhase.READING: PhaseState.COMPLETED,
        ProgressPhase.PLANNING: PhaseState.COMPLETED,
        ProgressPhase.SAVING: PhaseState.FAILED,
    }
    assert projection.snapshot.phase_durations_ms[ProgressPhase.SAVING] >= save_s * 1000


def test_interrupted_przygotowanie_emits_failed_without_exception_text(tmp_path: Path) -> None:
    fixture = make_preparation_fixture(tmp_path)
    fixture.period_directory.mkdir()
    fixture.collective_file_path.write_bytes(b"reczne poprawki taty")
    recorded: list[ProgressEvent] = []

    with pytest.raises(StopError):
        run_preparation(fixture, observer=recorded.append)

    assert [(event.phase, event.state) for event in recorded] == [
        (ProgressPhase.CHECKING, ProgressState.START),
        (ProgressPhase.CHECKING, ProgressState.FAILED),
    ]
    assert "istnieje" not in repr(recorded)
    assert COLLECTIVE_FILE_NAME not in repr(recorded)


def test_failing_observer_is_detached_and_does_not_change_result_or_files(tmp_path: Path) -> None:
    fixture = make_preparation_fixture(tmp_path)
    calls = 0

    def failing_observer(event: ProgressEvent) -> None:
        nonlocal calls
        calls += 1
        raise RuntimeError("awaria terminala")

    summary = run_preparation(fixture, observer=failing_observer)

    assert calls == 1
    assert summary.period_order_count == 4
    assert summary.successful_order_count == 3
    assert summary.orders_per_day == EXPECTED_ORDERS_PER_DAY
    assert fixture.internal_settlement_path.is_file()
    assert fixture.collective_file_path.is_file()


def cell_formats(path: Path, coordinates: list[str]) -> dict[str, tuple[object, ...]]:
    """Wypełnienie, kolor czcionki, pogrubienie i kursywa wskazanych komórek."""

    workbook = load_workbook(path)
    try:
        sheet = active_worksheet(workbook)
        formats: dict[str, tuple[object, ...]] = {}
        for coordinate in coordinates:
            cell = sheet[coordinate]
            fill = cell.fill.fgColor.rgb if cell.fill.fill_type == "solid" else None
            # Kolor motywu (domyślny tekst) nie jest wyróżnieniem.
            color = cell.font.color.rgb if cell.font.color is not None and cell.font.color.type == "rgb" else None
            formats[coordinate] = (fill, color, bool(cell.font.b), bool(cell.font.i))
        return formats
    finally:
        workbook.close()


def test_highlights_from_rejestr_reach_both_files_and_plain_cells_get_none(tmp_path: Path) -> None:
    fixture = make_preparation_fixture(tmp_path)

    run_preparation(fixture)

    # Zlecenie 2: ADRES wyróżniony; zlecenie 4: WYKONAWCA kursywą; reszta bez wyróżnień.
    assert cell_formats(fixture.internal_settlement_path, ["C2", "H4", "B2", "C3", "H2"]) == {
        "C2": ("FFFFFF00", "FFC00000", True, False),
        "H4": (None, None, False, True),
        "B2": (None, None, False, False),
        "C3": (None, None, False, False),
        "H2": (None, None, False, False),
    }
    assert cell_formats(fixture.collective_file_path, ["B18", "H19", "A18", "B19", "H18"]) == {
        "B18": ("FFFFFF00", "FFC00000", True, False),
        "H19": (None, None, False, True),
        "A18": (None, None, False, False),
        "B19": (None, None, False, False),
        "H18": (None, None, False, False),
    }


def data_fonts(path: Path, *, min_row: int, max_row: int, max_col: int) -> set[tuple[object, object]]:
    workbook = load_workbook(path)
    try:
        sheet = active_worksheet(workbook)
        return {
            (cell.font.name, cell.font.sz)
            for row in sheet.iter_rows(min_row=min_row, max_row=max_row, max_col=max_col)
            for cell in row
        }
    finally:
        workbook.close()


def test_data_rows_take_font_face_and_size_from_wzorzec_not_rejestr(tmp_path: Path) -> None:
    fixture = make_preparation_fixture(tmp_path)

    run_preparation(fixture)

    # Rejestr: Arial 8; wzorce: Calibri 10.
    assert data_fonts(fixture.internal_settlement_path, min_row=2, max_row=5, max_col=11) == {("Calibri", 10)}
    assert data_fonts(fixture.collective_file_path, min_row=18, max_row=20, max_col=11) == {("Calibri", 10)}


def test_cells_without_own_style_take_wzorzec_row_font_before_column_font(tmp_path: Path) -> None:
    fixture = make_preparation_fixture(tmp_path)
    write_internal_template(fixture.internal_template_path, row_style=True)
    write_collective_template(fixture.collective_template_path, row_style=True)

    run_preparation(fixture)

    # Wiersze danych wzorców: styl wiersza Calibri 10; kolumny: Calibri 11; komórki bez własnego stylu.
    assert data_fonts(fixture.internal_settlement_path, min_row=2, max_row=5, max_col=11) == {("Calibri", 10)}
    assert data_fonts(fixture.collective_file_path, min_row=18, max_row=20, max_col=11) == {("Calibri", 10)}


def test_data_column_keeps_date_format_from_rejestr(tmp_path: Path) -> None:
    fixture = make_preparation_fixture(tmp_path)

    run_preparation(fixture)

    internal = load_workbook(fixture.internal_settlement_path)
    collective = load_workbook(fixture.collective_file_path)
    try:
        internal_dates = [active_worksheet(internal).cell(row, 1) for row in range(2, 6)]
        collective_dates = [active_worksheet(collective).cell(row, 7) for row in range(18, 21)]
        assert {
            (type(cell.value), cell.number_format) for cell in internal_dates + collective_dates
        } == {(datetime, "dd.mm.yyyy hh:mm")}
    finally:
        internal.close()
        collective.close()


def sheet_layout(path: Path, *, header_row: int, max_col: int) -> dict[str, object]:
    """Szerokości kolumn, wysokości wierszy, nagłówek z formatowaniem i blokada wierszy."""

    workbook = load_workbook(path)
    try:
        sheet = active_worksheet(workbook)
        return {
            "widths": [sheet.column_dimensions[get_column_letter(column)].width for column in range(1, max_col + 1)],
            "heights": [sheet.row_dimensions[row].height for row in range(1, header_row + 6)],
            "header": [
                (cell.value, cell.font.name, cell.font.sz, cell.font.b, cell.fill.fgColor.rgb)
                for cell in sheet[header_row][:max_col]
            ],
            "freeze_panes": sheet.freeze_panes,
        }
    finally:
        workbook.close()


@pytest.mark.parametrize("kind", ["internal", "collective"])
def test_column_widths_header_and_frozen_row_equal_wzorzec(tmp_path: Path, kind: str) -> None:
    fixture = make_preparation_fixture(tmp_path)

    run_preparation(fixture)

    if kind == "internal":
        template, created, header_row = fixture.internal_template_path, fixture.internal_settlement_path, 1
    else:
        template, created, header_row = fixture.collective_template_path, fixture.collective_file_path, 17
    expected = sheet_layout(template, header_row=header_row, max_col=47)
    assert expected["freeze_panes"] == f"A{header_row + 1}"
    assert sheet_layout(created, header_row=header_row, max_col=47) == expected


def test_plik_zbiorczy_columns_outside_a_to_k_keep_wzorzec_formatting(tmp_path: Path) -> None:
    fixture = make_preparation_fixture(tmp_path)

    run_preparation(fixture)

    def formats(path: Path) -> list[tuple[object, ...]]:
        workbook = load_workbook(path)
        try:
            sheet = active_worksheet(workbook)
            return [
                (cell.coordinate, cell.fill.fill_type, cell.fill.fgColor.rgb, cell.number_format, cell.font.name)
                for row in sheet.iter_rows(min_row=18, max_row=24, min_col=12, max_col=47)
                for cell in row
            ]
        finally:
            workbook.close()

    expected = formats(fixture.collective_template_path)
    assert ("N18", "solid", "FFCCE5FF", "0", "Calibri") in expected
    assert formats(fixture.collective_file_path) == expected


def autofilter_range(path: Path) -> str | None:
    workbook = load_workbook(path)
    try:
        ref: str | None = active_worksheet(workbook).auto_filter.ref
        return ref
    finally:
        workbook.close()


def test_autofilter_covers_header_and_last_order_row_in_both_files(tmp_path: Path) -> None:
    fixture = make_preparation_fixture(tmp_path)

    run_preparation(fixture)

    # Wzorce mają zakres B:C do wiersza +40, który ma zostać zignorowany.
    # Rozliczenie wewnętrzne: nagłówki A:M i 4 zlecenia okresu.
    assert autofilter_range(fixture.internal_settlement_path) == "A1:M5"
    # Plik zbiorczy: nagłówki wiersza 17 od A do AP i 3 Zlecenia skuteczne.
    assert autofilter_range(fixture.collective_file_path) == "A17:AP20"


def test_autofilter_covers_only_header_when_period_has_no_zlecenia_skuteczne(tmp_path: Path) -> None:
    rows: list[RegisterRow] = [register_order(1, datetime(2026, 9, 9, 10, 0), successful="nie")]
    fixture = make_preparation_fixture(tmp_path, rows)

    run_preparation(fixture)

    assert autofilter_range(fixture.internal_settlement_path) == "A1:M2"
    assert autofilter_range(fixture.collective_file_path) == "A17:AP17"


REGISTER_NAME = "ZLECENIA INTERMAX OD 08_11_2021.xlsx"


def stop_message(fixture: PreparationFixture) -> StopError:
    """Uruchamia Przygotowanie, oczekuje zatrzymania i sprawdza, że nic nie powstało."""

    with pytest.raises(StopError) as raised:
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
        register_order(number, datetime(2026, 9, 14, 8, number)) for number in range(1, successful_count + 1)
    ]
    rows.insert(3, register_order(99, datetime(2026, 9, 14, 9, 0), successful="nie"))
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
        register_order(number, datetime(2026, 9, 14, 8, number))
        for number in range(1, COLLECTIVE_TEMPLATE_ZERO_ROWS + 1)
    ]
    fixture = make_preparation_fixture(tmp_path, rows)

    summary = run_preparation(fixture)

    assert summary.warnings == []


def test_last_order_before_monday_warns_about_incomplete_period_with_orders_per_day(tmp_path: Path) -> None:
    rows: list[RegisterRow] = [
        register_order(1, datetime(2026, 9, 8, 8, 0)),
        None,
        register_order(2, datetime(2026, 9, 12, 23, 59), successful="nie"),
        register_order(3, datetime(2026, 9, 10, 9, 0)),
    ]
    fixture = make_preparation_fixture(tmp_path, rows)

    plan = run_preparation(fixture, dry_run=True)

    assert [warning.text for warning in plan.warnings] == [
        "Co się stało: Ostatnie zlecenie okresu jest z soboty 12.09.2026, a okres kończy się w poniedziałek "
        "14.09.2026. Rejestr zleceń może nie mieć jeszcze wszystkich zleceń tego okresu.\n"
        f"Gdzie: plik {REGISTER_NAME}, arkusz ZLECENIA, okres {PERIOD}\n"
        "Co zrobić: Sprawdź liczby zleceń na dzień. Jeśli brakuje zleceń, przerwij, uzupełnij eksport "
        "w Rejestrze zleceń, zapisz go i uruchom ponownie. Jeśli okres jest pełny, kontynuuj."
    ]
    assert plan.warnings[0].code == "NIEPELNY_OKRES"
    assert plan.orders_per_day == {
        date(2026, 9, 8): 1,
        date(2026, 9, 9): 0,
        date(2026, 9, 10): 1,
        date(2026, 9, 11): 0,
        date(2026, 9, 12): 1,
        date(2026, 9, 13): 0,
        date(2026, 9, 14): 0,
    }
    assert list(fixture.periods_directory.iterdir()) == []


def test_incomplete_period_warning_does_not_block_creating_both_files(tmp_path: Path) -> None:
    fixture = make_preparation_fixture(tmp_path, [register_order(1, datetime(2026, 9, 13, 23, 59))])

    summary = run_preparation(fixture)

    assert [warning.code for warning in summary.warnings] == ["NIEPELNY_OKRES"]
    assert fixture.internal_settlement_path.is_file()
    assert fixture.collective_file_path.is_file()


def test_order_on_monday_anywhere_in_rejestr_means_full_period(tmp_path: Path) -> None:
    rows: list[RegisterRow] = [
        register_order(1, datetime(2026, 9, 14, 0, 0)),
        register_order(2, datetime(2026, 9, 9, 8, 0)),
    ]
    fixture = make_preparation_fixture(tmp_path, rows)

    plan = run_preparation(fixture, dry_run=True)

    assert plan.warnings == []


def test_skipped_empty_rows_are_all_empty_rows_from_first_to_last_period_order(tmp_path: Path) -> None:
    rows: list[RegisterRow] = [
        None,
        register_order(1, datetime(2026, 9, 7, 15, 0)),  # poprzedni okres
        None,
        register_order(2, datetime(2026, 9, 8, 8, 0)),
        None,
        register_order(3, datetime(2026, 9, 15, 8, 0)),  # następny okres, między zleceniami okresu
        None,
        None,
        register_order(4, datetime(2026, 9, 14, 8, 0)),  # spóźnione zlecenie okresu
        None,
    ]
    fixture = make_preparation_fixture(tmp_path, rows)

    summary = run_preparation(fixture, dry_run=True)

    assert summary.period_order_count == 2
    assert summary.skipped_empty_rows == 3


def test_confirm_plan_gets_plan_after_planowanie_and_before_zapisywanie(tmp_path: Path) -> None:
    fixture = make_preparation_fixture(tmp_path)
    recorded: list[ProgressEvent] = []
    seen: list[tuple[int, int, list[tuple[ProgressPhase, ProgressState]], bool]] = []

    def confirm_plan(plan: PreparationSummary) -> None:
        stages = [(event.phase, event.state) for event in recorded]
        seen.append((plan.period_order_count, plan.successful_order_count, stages, fixture.period_directory.exists()))

    summary = run_preparation(fixture, observer=recorded.append, confirm_plan=confirm_plan)

    assert seen == [(4, 3, STAGES_IN_ORDER[:8], False)]
    assert [(event.phase, event.state) for event in recorded] == STAGES_IN_ORDER
    assert summary.period_order_count == 4
    assert fixture.collective_file_path.is_file()


def test_stage_times_seen_by_confirm_plan_do_not_change_while_zapisywanie_is_measured(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fixture = make_preparation_fixture(tmp_path)
    save_s = 0.05
    real_save_workbook = workbook_files.save_workbook
    seen: list[tuple[Mapping[ProgressPhase, int], dict[ProgressPhase, int]]] = []

    def slow_save(workbook: Workbook, target: Path, *, external_links_from: Path | None = None) -> None:
        time.sleep(save_s)
        real_save_workbook(workbook, target, external_links_from=external_links_from)

    def confirm_plan(plan: PreparationSummary) -> None:
        seen.append((plan.phase_durations_ms, dict(plan.phase_durations_ms)))

    monkeypatch.setattr(workbook_files, "save_workbook", slow_save)

    summary = run_preparation(fixture, confirm_plan=confirm_plan)

    [(seen_durations, read_in_confirm_plan)] = seen
    assert set(read_in_confirm_plan) == {ProgressPhase.CHECKING, ProgressPhase.READING, ProgressPhase.PLANNING}
    assert dict(seen_durations) == read_in_confirm_plan
    assert summary.phase_durations_ms[ProgressPhase.SAVING] >= save_s * 1000
    assert dict(summary.phase_durations_ms) == {
        **read_in_confirm_plan,
        ProgressPhase.SAVING: summary.phase_durations_ms[ProgressPhase.SAVING],
    }
    with pytest.raises(TypeError):
        summary.phase_durations_ms[ProgressPhase.SAVING] = 0  # type: ignore[index]


def test_stop_from_confirm_plan_creates_no_file_and_no_folder_okresu(tmp_path: Path) -> None:
    fixture = make_preparation_fixture(tmp_path)
    recorded: list[ProgressEvent] = []
    refusal = StopError(
        Message(code="ODMOWA", what="Odmowa w teście.", where="test", action="Nic.")
    )

    def refuse(plan: PreparationSummary) -> None:
        raise refusal

    with pytest.raises(StopError) as raised:
        run_preparation(fixture, observer=recorded.append, confirm_plan=refuse)

    assert raised.value is refusal
    assert [(event.phase, event.state) for event in recorded] == STAGES_IN_ORDER[:8]
    assert list(fixture.periods_directory.iterdir()) == []


def test_dry_run_does_not_call_confirm_plan(tmp_path: Path) -> None:
    fixture = make_preparation_fixture(tmp_path)
    calls: list[PreparationSummary] = []

    run_preparation(fixture, dry_run=True, confirm_plan=calls.append)

    assert calls == []


def test_time_spent_in_confirm_plan_is_not_counted_in_przygotowanie_time(tmp_path: Path) -> None:
    fixture = make_preparation_fixture(tmp_path)
    recorded: list[ProgressEvent] = []
    pause_s = 1.5

    summary = run_preparation(
        fixture, observer=recorded.append, confirm_plan=lambda plan: time.sleep(pause_s)
    )

    assert sum(summary.phase_durations_ms.values()) < pause_s * 1000
    assert max(event.elapsed_ms or 0 for event in recorded) < pause_s * 1000

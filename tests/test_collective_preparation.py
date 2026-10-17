from __future__ import annotations

from datetime import date, datetime
from pathlib import Path

from openpyxl import Workbook, load_workbook
import pytest

from rozliczenia.domain import ProgressEvent, ProgressObserver, ProgressPhase, ProgressState
from rozliczenia.progress import PhaseState, ProgressProjection
from rozliczenia.collective_preparation import PreparationError, PreparationSummary, prepare_collective_file
from rozliczenia.workbook_files import ExternalLinksError
import rozliczenia.workbook_files as workbook_files

from tests.collective_preparation_fixtures import (
    COLLECTIVE_FILE_NAME,
    INTERNAL_SETTLEMENT_NAME,
    INTERNAL_TEMPLATE_HEADERS,
    PERIOD,
    PreparationFixture,
    RegisterRow,
    make_preparation_fixture,
    register_order,
)
from tests.test_settlement_engine import active_worksheet, external_link_parts


def run_preparation(
    fixture: PreparationFixture,
    period: str = PERIOD,
    *,
    dry_run: bool = False,
    observer: ProgressObserver | None = None,
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
    assert summary.skipped_empty_rows == 3
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

    with pytest.raises(PreparationError) as raised:
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


def test_failed_save_of_second_file_publishes_neither_file_nor_folder_okresu(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fixture = make_preparation_fixture(tmp_path)
    real_save = workbook_files.save_workbook
    saved: list[str] = []

    def save_first_then_fail(workbook: Workbook, target: Path, *, external_links_from: Path | None = None) -> None:
        if saved:
            raise ExternalLinksError("wymuszony błąd")
        saved.append(target.name)
        real_save(workbook, target, external_links_from=external_links_from)

    monkeypatch.setattr(workbook_files, "save_workbook", save_first_then_fail)

    with pytest.raises(PreparationError) as raised:
        run_preparation(fixture)

    assert saved == [INTERNAL_SETTLEMENT_NAME]
    assert raised.value.message.code == "BLAD_ZAPISU"
    assert "wymuszony" not in str(raised.value)
    assert list(fixture.periods_directory.iterdir()) == []


@pytest.mark.parametrize("token", ["8_14_09_2026", "09_15_09_2026", "08_15_09_2026", "okres"])
def test_invalid_period_token_stops_before_reading_rejestr(tmp_path: Path, token: str) -> None:
    fixture = make_preparation_fixture(tmp_path)

    with pytest.raises(PreparationError) as raised:
        run_preparation(fixture, token)

    assert raised.value.message.code == "ZLY_TOKEN_OKRESU"
    assert list(fixture.periods_directory.iterdir()) == []


@pytest.mark.parametrize("token", ["29_05_09_2026", "29_05_10_2026"])
def test_period_crossing_months_accepts_month_of_tuesday_or_monday(tmp_path: Path, token: str) -> None:
    rows: list[RegisterRow] = [
        register_order(1, datetime(2026, 9, 28, 23, 59)),
        register_order(2, datetime(2026, 9, 29, 8, 0)),
        register_order(3, datetime(2026, 10, 5, 23, 59)),
        register_order(4, datetime(2026, 10, 6, 0, 0)),
    ]
    fixture = make_preparation_fixture(tmp_path, rows)

    summary = run_preparation(fixture, token)

    assert summary.period_order_count == 2
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
    assert summary.skipped_empty_rows == 3
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
    fixture = make_preparation_fixture(tmp_path)
    recorded: list[ProgressEvent] = []
    projection = ProgressProjection("DRY-RUN" if dry_run else "RUN", PERIOD)

    def recording_observer(event: ProgressEvent) -> None:
        recorded.append(event)
        projection.update(event)

    run_preparation(fixture, dry_run=dry_run, observer=recording_observer)

    assert [(event.phase, event.state) for event in recorded] == STAGES_IN_ORDER
    assert all(event.worker_name is None for event in recorded)
    assert set(projection.snapshot.phase_states.values()) == {PhaseState.COMPLETED}
    assert "SYN-" not in repr(recorded)


def test_interrupted_przygotowanie_emits_failed_without_exception_text(tmp_path: Path) -> None:
    fixture = make_preparation_fixture(tmp_path)
    fixture.period_directory.mkdir()
    fixture.collective_file_path.write_bytes(b"reczne poprawki taty")
    recorded: list[ProgressEvent] = []

    with pytest.raises(PreparationError):
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

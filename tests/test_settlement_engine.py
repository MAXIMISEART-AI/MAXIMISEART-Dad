from __future__ import annotations

from pathlib import Path
import time
from collections.abc import Callable, Iterable

from openpyxl import load_workbook
from openpyxl.worksheet.worksheet import Worksheet
import pytest

from rozliczenia.domain import (
    PhaseEnded,
    PhaseFailed,
    PhaseStarted,
    ProgressEvent,
    ProgressPhase,
    WorkerEnded,
    WorkerFailed,
    WorkerResult,
    WorkerStarted,
)
from rozliczenia.engine import run_settlements
from rozliczenia.message import StopError
from rozliczenia.progress import PhaseState, ProgressProjection
import rozliczenia.template_settlement as template_settlement
from rozliczenia.workbook_files import ExcelRow
from tests.fixtures.workbooks import active_worksheet, column_widths, cut_sheet_after_data_rows, without_sheet
from tests.fixtures.settlement import (
    NOT_A_PERIOD,
    PERIOD,
    SOURCE_NAME,
    WORKER_TEMPLATE_COLUMN_WIDTHS,
    make_fixture,
    projected,
    write_source,
)


UNREADABLE_SOURCE_MESSAGE = (
    f"Nie można odczytać Pliku zbiorczego {SOURCE_NAME}. "
    "Sprawdź, czy plik otwiera się w Excelu i nie jest uszkodzony."
)


def overwrite_with_non_workbook(path: Path) -> None:
    path.write_bytes(b"uszkodzony")


def terminal_text(error: StopError) -> str:
    """Tekst, który terminal pokazuje po „Nie wykonano: ” dla tego zatrzymania."""

    return "\n".join(error.message.terminal_lines)


def make_complete_run_fixture(tmp_path: Path) -> tuple[Path, Path, Path, Path]:
    source_path, target_directory, config_path = make_fixture(tmp_path)
    return source_path, target_directory, config_path, tmp_path / "Wzorzec rozliczenia pracownika.xlsx"


def expected_source_row(address: str, order_number: str, worker_id: str, quantity: int) -> tuple[object, ...]:
    return (
        "POZNAŃ",
        address,
        None,
        None,
        None,
        order_number,
        None,
        worker_id,
        None,
        None,
        None,
        None,
        None,
        quantity,
    ) + (None,) * 32


def worksheet_input_row(sheet: Worksheet, row_number: int) -> tuple[object, ...]:
    return next(sheet.iter_rows(min_row=row_number, max_row=row_number, max_col=46, values_only=True))


def test_przygotowanie_skoroszytow_pracownikow_publikuje_folder_rozliczen_pracownikow(
    tmp_path: Path,
) -> None:
    source_path, target_directory, config_path, worker_template_path = make_complete_run_fixture(tmp_path)
    worker_template_before = worker_template_path.read_bytes()

    summary = run_settlements(source_path, config_path, worker_template_path=worker_template_path)

    expected_files = {
        f"Rozliczenie {PERIOD} - {name}.xlsx"
        for name in ("Adrian Testowy", "Darek Fikcyjny", "Kamil Syntetyczny")
    }
    assert {path.name for path in target_directory.glob("*.xlsx")} == expected_files
    assert summary.written_count == 2
    assert summary.empty_count == 1
    assert summary.issues == []
    assert all(result.output_file.parent == target_directory for result in summary.results)
    assert worker_template_path.read_bytes() == worker_template_before

    adrian_workbook = load_workbook(
        target_directory / f"Rozliczenie {PERIOD} - Adrian Testowy.xlsx",
        data_only=False,
    )
    try:
        adrian = active_worksheet(adrian_workbook)
        assert adrian_workbook.sheetnames == ["Sheet1", "Rates"]
        assert worksheet_input_row(adrian, 18) == expected_source_row(
            "syntetyczny adres 1", "#1", "adrian.testowy", 1
        )
        assert worksheet_input_row(adrian, 19) == expected_source_row(
            "syntetyczny adres 3", "#3", "adrian.testowy", 3
        )
    finally:
        adrian_workbook.close()

    darek_workbook = load_workbook(
        target_directory / f"Rozliczenie {PERIOD} - Darek Fikcyjny.xlsx",
        data_only=False,
    )
    try:
        darek = active_worksheet(darek_workbook)
        assert worksheet_input_row(darek, 18) == expected_source_row(
            "syntetyczny adres 2", "#2", "dariusz.fikcyjny2", 2
        )
    finally:
        darek_workbook.close()

    empty_workbook = load_workbook(
        target_directory / f"Rozliczenie {PERIOD} - Kamil Syntetyczny.xlsx",
        data_only=False,
    )
    try:
        empty = active_worksheet(empty_workbook)
        assert worksheet_input_row(empty, 18) == (None,) * 13 + (0,) + (None,) * 32
    finally:
        empty_workbook.close()


def test_kazde_rozliczenie_pracownika_takze_puste_ma_szerokosci_kolumn_wzorca_rozliczenia_pracownika(
    tmp_path: Path,
) -> None:
    source_path, target_directory, config_path, worker_template_path = make_complete_run_fixture(tmp_path)

    summary = run_settlements(source_path, config_path, worker_template_path=worker_template_path)

    assert summary.empty_count == 1
    expected = [WORKER_TEMPLATE_COLUMN_WIDTHS.get(column) for column in range(1, 48)]
    published = sorted(target_directory.glob("*.xlsx"))
    assert len(published) == 3
    for path in published:
        workbook = load_workbook(path)
        try:
            assert column_widths(active_worksheet(workbook), 47) == expected, path.name
        finally:
            workbook.close()


def test_wykonawca_bez_mapowania_wstrzymuje_publikacje_folderu_rozliczen_pracownikow(
    tmp_path: Path,
) -> None:
    source_path, target_directory, config_path = make_fixture(tmp_path)
    write_source(source_path, include_unmapped=True)

    with pytest.raises(StopError) as raised:
        run_settlements(source_path, config_path, worker_template_path=tmp_path / "Wzorzec rozliczenia pracownika.xlsx")

    assert "WYKONAWCA bez mapowania" in terminal_text(raised.value)
    assert not target_directory.exists()
    assert not list(target_directory.parent.glob(f".{target_directory.name}.staging-*"))


def test_dry_run_does_not_write(tmp_path: Path) -> None:
    source_path, target_directory, config_path = make_fixture(tmp_path)

    summary = run_settlements(
        source_path,
        config_path,
        dry_run=True,
        worker_template_path=tmp_path / "Wzorzec rozliczenia pracownika.xlsx",
    )

    assert summary.planned_count == 2
    assert summary.empty_count == 1
    assert not target_directory.exists()


@pytest.mark.parametrize(
    "damage",
    [overwrite_with_non_workbook, cut_sheet_after_data_rows, without_sheet],
    ids=["nie-skoroszyt", "urwany-arkusz", "bez-arkusza"],
)
def test_nieczytelny_plik_zbiorczy_zatrzymuje_przebieg_rozliczen_bezpiecznym_komunikatem(
    tmp_path: Path,
    damage: Callable[[Path], None],
) -> None:
    source_path, target_directory, config_path = make_fixture(tmp_path)
    damage(source_path)

    with pytest.raises(StopError) as stop:
        run_settlements(source_path, config_path, worker_template_path=tmp_path / "Wzorzec rozliczenia pracownika.xlsx")

    assert terminal_text(stop.value) == UNREADABLE_SOURCE_MESSAGE
    assert not target_directory.exists()
    assert not list(target_directory.parent.glob(f".{target_directory.name}.staging-*"))


def test_plik_zbiorczy_bez_wykonawca_w_h17_zatrzymuje_przebieg_rozliczen(tmp_path: Path) -> None:
    source_path, target_directory, config_path = make_fixture(tmp_path)
    workbook = load_workbook(source_path)
    try:
        sheet = active_worksheet(workbook)
        sheet["H17"], sheet["C17"] = None, "WYKONAWCA"
        workbook.save(source_path)
    finally:
        workbook.close()

    with pytest.raises(StopError) as stop:
        run_settlements(source_path, config_path, worker_template_path=tmp_path / "Wzorzec rozliczenia pracownika.xlsx")

    assert stop.value.message.code == "ZLY_PLIK_ZBIORCZY"
    assert terminal_text(stop.value) == "W wierszu 17 nie znaleziono nagłówka WYKONAWCA w kolumnie H."
    assert not target_directory.exists()


def test_istniejacy_folder_rozliczen_pracownikow_nie_jest_nadpisywany(tmp_path: Path) -> None:
    source_path, target_directory, config_path = make_fixture(tmp_path)
    target_directory.mkdir()
    sentinel = target_directory / "existing.txt"
    sentinel.write_text("zachowaj", encoding="utf-8")

    with pytest.raises(StopError) as raised:
        run_settlements(source_path, config_path, worker_template_path=tmp_path / "Wzorzec rozliczenia pracownika.xlsx")

    assert "Folder docelowy już istnieje" in terminal_text(raised.value)
    assert sentinel.read_text(encoding="utf-8") == "zachowaj"


def lock_in_excel(path: Path) -> None:
    path.with_name(f"~${path.name}").touch()


def set_cell(cell: str, value: str) -> Callable[[Path], None]:
    def change(path: Path) -> None:
        workbook = load_workbook(path)
        try:
            active_worksheet(workbook)[cell] = value
            workbook.save(path)
        finally:
            workbook.close()

    return change


@pytest.mark.parametrize("dry_run", [False, True], ids=["RUN", "DRY-RUN"])
@pytest.mark.parametrize(
    ("damage", "detail"),
    [
        (lock_in_excel, "Wzorzec rozliczenia pracownika jest otwarty lub zablokowany."),
        (overwrite_with_non_workbook, "Nie można odczytać Wzorca rozliczenia pracownika."),
        (set_cell("H17", "NIE WYKONAWCA"), "Wzorzec rozliczenia pracownika nie ma nagłówka WYKONAWCA w H:17."),
        (
            set_cell("A18", "SENSITIVE-SYNTHETIC"),
            "Wzorzec rozliczenia pracownika zawiera dane i nie może być użyty jako wzór.",
        ),
    ],
    ids=["otwarty-w-excelu", "nie-skoroszyt", "bez-wykonawca-w-h17", "z-danymi"],
)
def test_wzorzec_rozliczenia_pracownika_ktorego_nie_mozna_uzyc_zatrzymuje_sprawdzanie(
    tmp_path: Path, damage: Callable[[Path], None], detail: str, dry_run: bool
) -> None:
    source_path, target_directory, config_path = make_fixture(tmp_path)
    worker_template_path = tmp_path / "Wzorzec rozliczenia pracownika.xlsx"
    damage(worker_template_path)

    with pytest.raises(StopError) as raised:
        run_settlements(source_path, config_path, dry_run=dry_run, worker_template_path=worker_template_path)

    assert raised.value.message.code == "ZLY_WZORZEC_PRACOWNIKA"
    assert terminal_text(raised.value) == detail
    assert "SENSITIVE-SYNTHETIC" not in raised.value.message.text
    assert not target_directory.exists()


def test_niepoprawna_konfiguracja_wykonawcow_zatrzymuje_sprawdzanie(tmp_path: Path) -> None:
    source_path, target_directory, config_path = make_fixture(tmp_path)
    config_path.write_text("workers: [", encoding="utf-8")

    with pytest.raises(StopError) as raised:
        run_settlements(source_path, config_path, worker_template_path=tmp_path / "Wzorzec rozliczenia pracownika.xlsx")

    assert raised.value.message.code == "ZLA_KONFIGURACJA_WYKONAWCOW"
    assert not target_directory.exists()


def test_wzorzec_rozliczenia_pracownika_otwarty_w_zapisywaniu_wstrzymuje_publikacje(tmp_path: Path) -> None:
    source_path, target_directory, config_path, worker_template_path = make_complete_run_fixture(tmp_path)
    lock_file = worker_template_path.with_name(f"~${worker_template_path.name}")

    def lock_in_saving(event: ProgressEvent) -> None:
        if isinstance(event, WorkerStarted):
            lock_file.touch()

    with pytest.raises(StopError) as raised:
        run_settlements(source_path, config_path, worker_template_path=worker_template_path, observer=lock_in_saving)

    assert raised.value.message.code == "BLAD_KOPII_WZORCA"
    assert not target_directory.exists()
    assert not list(target_directory.parent.glob(f".{target_directory.name}.staging-*"))


def test_folder_rozliczen_pracownikow_utworzony_w_trakcie_zapisywania_nie_jest_nadpisywany(tmp_path: Path) -> None:
    source_path, target_directory, config_path, worker_template_path = make_complete_run_fixture(tmp_path)
    sentinel = target_directory / "existing.txt"

    def create_folder_in_saving(event: ProgressEvent) -> None:
        if isinstance(event, WorkerStarted) and not target_directory.exists():
            target_directory.mkdir()
            sentinel.write_text("zachowaj", encoding="utf-8")

    with pytest.raises(StopError) as raised:
        run_settlements(
            source_path, config_path, worker_template_path=worker_template_path, observer=create_folder_in_saving
        )

    assert raised.value.message.code == "FOLDER_ROZLICZEN_ISTNIEJE"
    assert [path.name for path in target_directory.iterdir()] == [sentinel.name]
    assert sentinel.read_text(encoding="utf-8") == "zachowaj"
    assert not list(target_directory.parent.glob(f".{target_directory.name}.staging-*"))


def test_brak_wzorca_rozliczenia_pracownika_podpowiada_zmiane_nazwy_starego_pliku(
    tmp_path: Path,
) -> None:
    source_path, target_directory, config_path = make_fixture(tmp_path)
    worker_template_path = tmp_path / "Wzorzec rozliczenia pracownika.xlsx"
    worker_template_path.rename(tmp_path / "placeholder.xlsx")

    with pytest.raises(StopError) as raised:
        run_settlements(source_path, config_path, worker_template_path=worker_template_path)

    assert terminal_text(raised.value) == (
        "Nie znaleziono Wzorca rozliczenia pracownika: Wzorzec rozliczenia pracownika.xlsx. "
        "Zmień nazwę pliku placeholder.xlsx w tym samym folderze na „Wzorzec rozliczenia pracownika.xlsx”."
    )
    assert not target_directory.exists()


@pytest.mark.parametrize(
    ("source", "detail"),
    [
        (f"{PERIOD}/Rozliczenie wew. {PERIOD}.xlsx", "Plik Rozliczenie wew. jest poza zakresem tego procesu."),
        (f"INEA/{SOURCE_NAME}", f"Folder pliku musi nazywać się tak samo jak okres: {PERIOD}."),
    ],
    ids=["rozliczenie_wewnetrzne", "folder_nazwany_inaczej_niz_okres"],
)
def test_rozliczenie_wewnetrzne_albo_plik_zbiorczy_poza_folderem_okresu_zatrzymuje_przebieg_rozliczen(
    tmp_path: Path, source: str, detail: str
) -> None:
    source_path = tmp_path / source
    source_path.parent.mkdir()
    source_path.touch()

    with pytest.raises(StopError) as raised:
        run_settlements(source_path, tmp_path / "missing.yaml")

    assert raised.value.message.code == "ZLY_PLIK_ZBIORCZY"
    assert terminal_text(raised.value) == detail


def test_plik_zbiorczy_z_tokenem_ktory_nie_jest_okresem_zatrzymuje_przebieg_rozliczen(tmp_path: Path) -> None:
    source_path, target_directory, config_path = make_fixture(tmp_path, period=NOT_A_PERIOD)

    with pytest.raises(StopError) as raised:
        run_settlements(source_path, config_path, worker_template_path=tmp_path / "Wzorzec rozliczenia pracownika.xlsx")

    assert raised.value.message.code == "ZLY_PLIK_ZBIORCZY"
    assert not target_directory.exists()
    assert [path.name for path in source_path.parent.iterdir()] == [source_path.name]


def test_recording_observer_receives_safe_zdarzenia_przebiegu_and_can_be_disabled(tmp_path: Path) -> None:
    source_path, _, config_path = make_fixture(tmp_path)
    recorded: list[ProgressEvent] = []
    calls = 0

    def recording_observer(event: ProgressEvent) -> None:
        nonlocal calls
        calls += 1
        recorded.append(event)
        raise RuntimeError("observer output failed")

    summary = run_settlements(
        source_path,
        config_path,
        worker_template_path=tmp_path / "Wzorzec rozliczenia pracownika.xlsx",
        observer=recording_observer,
    )

    assert summary.written_count == 2
    assert summary.issues == []
    assert calls == 1
    assert len(recorded) == 1
    assert isinstance(recorded[0], PhaseStarted)
    assert "syntetyczny" not in repr(recorded[0])


def test_failed_przetworzenie_szablonu_pracownika_emits_failure_without_false_completion(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source_path, target_directory, config_path = make_fixture(tmp_path)
    original_process_template = template_settlement.process_template
    calls = 0
    recorded: list[ProgressEvent] = []

    def fail_on_second_save(
        worker_name: str,
        template_path: Path,
        path: Path,
        rows: Iterable[ExcelRow],
    ) -> WorkerResult:
        nonlocal calls
        calls += 1
        if calls == 2:
            raise template_settlement.TemplateWriteError("synthetic failure")
        return original_process_template(worker_name, template_path, path, rows)

    monkeypatch.setattr(template_settlement, "process_template", fail_on_second_save)

    with pytest.raises(StopError) as raised:
        run_settlements(
            source_path,
            config_path,
            worker_template_path=tmp_path / "Wzorzec rozliczenia pracownika.xlsx",
            observer=recorded.append,
        )

    assert "folder wynikowy nie został opublikowany" in terminal_text(raised.value)
    assert not target_directory.exists()
    assert not list(target_directory.parent.glob(f".{target_directory.name}.staging-*"))

    failed = [event for event in recorded if isinstance(event, (PhaseFailed, WorkerFailed))]
    assert len(failed) == 1
    assert isinstance(failed[0], WorkerFailed)
    assert failed[0].worker_name == "Darek Fikcyjny"
    assert failed[0].template_index == 2
    assert all("syntetyczny" not in repr(event) and "#1" not in repr(event) for event in failed)
    assert not any(
        isinstance(event, WorkerEnded) and event.worker_name == "Darek Fikcyjny" for event in recorded
    )
    assert not any(isinstance(event, PhaseEnded) and event.phase is ProgressPhase.SAVING for event in recorded)

    monkeypatch.setattr(template_settlement, "process_template", original_process_template)
    summary = run_settlements(source_path, config_path, worker_template_path=tmp_path / "Wzorzec rozliczenia pracownika.xlsx")
    assert summary.written_count == 2
    assert target_directory.is_dir()


def test_failed_faza_przebiegu_rozliczen_is_interrupted_without_exception_text(tmp_path: Path) -> None:
    source_path = tmp_path / "08_14_09_2026" / "Rozliczenie 08_14_09_2026 - zbiorcze.xlsx"
    recorded: list[ProgressEvent] = []

    with pytest.raises(StopError) as raised:
        run_settlements(source_path, tmp_path / "missing.yaml", observer=recorded.append)

    assert "Nie znaleziono pliku" in terminal_text(raised.value)
    assert [type(event) for event in recorded] == [PhaseStarted, PhaseFailed]
    assert recorded[-1].phase is ProgressPhase.CHECKING
    assert "Nie znaleziono pliku" not in repr(recorded[-1])


@pytest.mark.parametrize(
    ("dry_run", "include_unmapped", "issue_count"),
    [(False, False, 0), (True, True, 1)],
    ids=["zapis", "dry-run-z-problemem"],
)
def test_progress_projection_accepts_whole_przebieg_rozliczen(
    tmp_path: Path, dry_run: bool, include_unmapped: bool, issue_count: int
) -> None:
    source_path, _, config_path = make_fixture(tmp_path)
    write_source(source_path, include_unmapped=include_unmapped)
    projection = ProgressProjection("DRY-RUN" if dry_run else "RUN", PERIOD)

    summary = run_settlements(
        source_path,
        config_path,
        dry_run=dry_run,
        worker_template_path=tmp_path / "Wzorzec rozliczenia pracownika.xlsx",
        observer=projected(projection),
    )

    snapshot = projection.snapshot
    assert set(snapshot.phase_states.values()) == {PhaseState.COMPLETED}
    assert snapshot.template_total == 3
    assert snapshot.templates_completed == 3
    assert snapshot.issue_count == issue_count
    assert set(summary.phase_durations_ms) == set(ProgressPhase)
    with pytest.raises(TypeError):
        summary.phase_durations_ms[ProgressPhase.SAVING] = 0  # type: ignore[index]


def test_progress_projection_accepts_przebieg_rozliczen_interrupted_in_zapisywanie_with_its_time(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source_path, _, config_path = make_fixture(tmp_path)
    projection = ProgressProjection("RUN", PERIOD)
    save_s = 0.05

    def fail_save(worker_name: str, template_path: Path, path: Path, rows: Iterable[ExcelRow]) -> WorkerResult:
        time.sleep(save_s)
        raise template_settlement.TemplateWriteError("synthetic failure")

    monkeypatch.setattr(template_settlement, "process_template", fail_save)

    with pytest.raises(StopError):
        run_settlements(
            source_path,
            config_path,
            worker_template_path=tmp_path / "Wzorzec rozliczenia pracownika.xlsx",
            observer=projected(projection),
        )

    snapshot = projection.snapshot
    assert snapshot.phase_states == {
        ProgressPhase.CHECKING: PhaseState.COMPLETED,
        ProgressPhase.READING: PhaseState.COMPLETED,
        ProgressPhase.PLANNING: PhaseState.COMPLETED,
        ProgressPhase.SAVING: PhaseState.FAILED,
    }
    assert snapshot.template_total == 3
    assert snapshot.current_worker == "Adrian Testowy"
    assert snapshot.phase_durations_ms[ProgressPhase.SAVING] >= save_s * 1000

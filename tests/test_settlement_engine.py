from __future__ import annotations

from pathlib import Path
import os
import tempfile
import time
import xml.etree.ElementTree as ET
import zipfile
from collections.abc import Callable, Iterable

from openpyxl import Workbook, load_workbook
from openpyxl.styles import PatternFill
from openpyxl.worksheet.worksheet import Worksheet
import pytest
import yaml

from rozliczenia.collective_file import ExcelRow
from rozliczenia.domain import ProgressEvent, ProgressObserver, ProgressPhase, ProgressState, WorkerResult
from rozliczenia.engine import run_settlements
from rozliczenia.message import StopError
from rozliczenia.progress import PhaseState, ProgressProjection
import rozliczenia.template_settlement as template_settlement


PERIOD = "08_14_09_2026"
SOURCE_NAME = f"Rozliczenie {PERIOD} - zbiorcze.xlsx"
UNREADABLE_SOURCE_MESSAGE = (
    f"Nie można odczytać Pliku zbiorczego {SOURCE_NAME}. "
    "Sprawdź, czy plik otwiera się w Excelu i nie jest uszkodzony."
)


def active_worksheet(workbook: Workbook) -> Worksheet:
    sheet = workbook.active
    assert isinstance(sheet, Worksheet)
    return sheet


def write_mapping(path: Path) -> Path:
    path.write_text(
        yaml.safe_dump(
            {
                "schema_version": 1,
                "workers": {
                    "adrian.maciejewski": "Adrian Maciejewski",
                    "dariusz.nowak2": "Darek Nowak",
                    "kamil.frontczak": "Kamil Frontczak",
                },
            },
            allow_unicode=True,
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    return path


def write_template(path: Path) -> None:
    workbook = Workbook()
    sheet = active_worksheet(workbook)
    sheet.title = "Sheet1"
    sheet.cell(17, 8).value = "WYKONAWCA"
    sheet["A17"].fill = PatternFill(fill_type="solid", fgColor="00AA55")
    sheet.cell(18, 47).value = "=N18"
    sheet.cell(19, 47).value = "=N19"
    sheet.cell(18, 14).value = 0
    sheet.cell(19, 14).value = 0
    rates = workbook.create_sheet("Rates")
    rates["A1"] = "synthetic rate"
    rates["B1"] = 17.5
    workbook.save(path)


def add_external_link_fixture(path: Path) -> None:
    """Dodaje minimalny, prawidłowy link zewnętrzny do syntetycznego XLSX."""

    ns_main = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
    ns_rel = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
    ns_pkg_rel = "http://schemas.openxmlformats.org/package/2006/relationships"
    ns_content = "http://schemas.openxmlformats.org/package/2006/content-types"
    ET.register_namespace("", ns_main)
    ET.register_namespace("r", ns_rel)
    ET.register_namespace("", ns_pkg_rel)

    descriptor = {
        "xl/externalLinks/externalLink1.xml": (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            f'<externalLink xmlns="{ns_main}" xmlns:r="{ns_rel}">'
            '<externalBook><sheetNames><sheetName val="Słownik"/></sheetNames>'
            '<definedNames/><sheetDataSet><sheetData sheetId="0"/></sheetDataSet>'
            "</externalBook></externalLink>"
        ).encode("utf-8"),
        "xl/externalLinks/_rels/externalLink1.xml.rels": (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            f'<Relationships xmlns="{ns_pkg_rel}">'
            '<Relationship Id="rId2" Type="http://schemas.microsoft.com/office/2019/04/relationships/externalLinkLongPath" '
            'Target="https://example.invalid/workbook.xlsm" TargetMode="External"/>'
            '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/externalLinkPath" '
            'Target="file:///C:/workbook.xlsm" TargetMode="External"/>'
            "</Relationships>"
        ).encode("utf-8"),
    }
    file_descriptor, temp_name = tempfile.mkstemp(suffix=".xlsx", dir=path.parent)
    os.close(file_descriptor)
    temporary_path = Path(temp_name)
    try:
        with zipfile.ZipFile(path) as source, zipfile.ZipFile(temporary_path, "w") as target:
            for info in source.infolist():
                data = source.read(info.filename)
                if info.filename == "xl/workbook.xml":
                    root = ET.fromstring(data)
                    references = ET.SubElement(root, f"{{{ns_main}}}externalReferences")
                    ET.SubElement(references, f"{{{ns_main}}}externalReference", {f"{{{ns_rel}}}id": "rIdSynExternal1"})
                    data = ET.tostring(root, encoding="utf-8", xml_declaration=True)
                elif info.filename == "xl/_rels/workbook.xml.rels":
                    root = ET.fromstring(data)
                    ET.SubElement(
                        root,
                        f"{{{ns_pkg_rel}}}Relationship",
                        {
                            "Id": "rIdSynExternal1",
                            "Type": "http://schemas.openxmlformats.org/officeDocument/2006/relationships/externalLink",
                            "Target": "externalLinks/externalLink1.xml",
                        },
                    )
                    data = ET.tostring(root, encoding="utf-8", xml_declaration=True)
                elif info.filename == "[Content_Types].xml":
                    root = ET.fromstring(data)
                    ET.SubElement(
                        root,
                        f"{{{ns_content}}}Override",
                        {
                            "PartName": "/xl/externalLinks/externalLink1.xml",
                            "ContentType": "application/vnd.openxmlformats-officedocument.spreadsheetml.externalLink+xml",
                        },
                    )
                    data = ET.tostring(root, encoding="utf-8", xml_declaration=True)
                target.writestr(info, data)
            for name, data in descriptor.items():
                target.writestr(name, data)
        os.replace(temporary_path, path)
    finally:
        temporary_path.unlink(missing_ok=True)


def external_link_parts(path: Path) -> dict[str, bytes]:
    with zipfile.ZipFile(path) as archive:
        return {
            info.filename: archive.read(info.filename)
            for info in archive.infolist()
            if info.filename.startswith("xl/externalLinks/")
        }


def write_source(path: Path, *, include_unmapped: bool = True) -> None:
    workbook = Workbook()
    sheet = active_worksheet(workbook)
    sheet.title = "Sheet1"
    sheet.cell(17, 8).value = "WYKONAWCA"
    rows = [
        ("POZNAŃ", "syntetyczny adres 1", "adrian.maciejewski", "#1"),
        ("POZNAŃ", "syntetyczny adres 2", "dariusz.nowak2", "#2"),
        ("POZNAŃ", "syntetyczny adres 3", "adrian.maciejewski", "#3"),
    ]
    if include_unmapped:
        rows.append(("POZNAŃ", "syntetyczny adres 4", "andrzej.kulawski2", "#4"))
    for row_number, (city, address, worker, order_number) in enumerate(rows, start=18):
        sheet.cell(row_number, 1).value = city
        sheet.cell(row_number, 2).value = address
        sheet.cell(row_number, 6).value = order_number
        sheet.cell(row_number, 8).value = worker
        sheet.cell(row_number, 14).value = row_number - 17
    workbook.save(path)


def overwrite_with_non_workbook(path: Path) -> None:
    path.write_bytes(b"uszkodzony")


def cut_sheet_after_data_rows(path: Path, sheet_part: str = "xl/worksheets/sheet1.xml") -> None:
    """Skoroszyt się otwiera, ale XML arkusza ``sheet_part`` urywa się za jego ostatnim wierszem.

    Początek arkusza, np. WYKONAWCA w H17, daje się odczytać; błąd wychodzi dopiero przy dalszym czytaniu.
    """

    with zipfile.ZipFile(path) as source:
        members = [(info, source.read(info.filename)) for info in source.infolist()]
    with zipfile.ZipFile(path, "w") as target:
        for info, data in members:
            if info.filename == sheet_part:
                data = data[: data.rindex(b"</sheetData>")]
            target.writestr(info, data)


def terminal_text(error: StopError) -> str:
    """Tekst, który terminal pokazuje po „Nie wykonano: ” dla tego zatrzymania."""

    return "\n".join(error.message.terminal_lines)


def make_fixture(tmp_path: Path) -> tuple[Path, Path, Path]:
    period_directory = tmp_path / PERIOD
    period_directory.mkdir(parents=True)
    target_directory = period_directory / f"Rozliczenie pracowników {PERIOD}"
    source_path = period_directory / SOURCE_NAME
    write_source(source_path, include_unmapped=False)
    config_path = write_mapping(tmp_path / "worker_mapping.yaml")
    write_template(tmp_path / "Wzorzec rozliczenia pracownika.xlsx")
    return source_path, target_directory, config_path


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
        for name in ("Adrian Maciejewski", "Darek Nowak", "Kamil Frontczak")
    }
    assert {path.name for path in target_directory.glob("*.xlsx")} == expected_files
    assert summary.written_count == 2
    assert summary.empty_count == 1
    assert summary.issues == []
    assert all(result.output_file.parent == target_directory for result in summary.results)
    assert worker_template_path.read_bytes() == worker_template_before

    adrian_workbook = load_workbook(
        target_directory / f"Rozliczenie {PERIOD} - Adrian Maciejewski.xlsx",
        data_only=False,
    )
    try:
        adrian = active_worksheet(adrian_workbook)
        assert adrian_workbook.sheetnames == ["Sheet1", "Rates"]
        assert worksheet_input_row(adrian, 18) == expected_source_row(
            "syntetyczny adres 1", "#1", "adrian.maciejewski", 1
        )
        assert worksheet_input_row(adrian, 19) == expected_source_row(
            "syntetyczny adres 3", "#3", "adrian.maciejewski", 3
        )
        assert adrian["AU18"].value == "=N18"
        assert adrian["AU19"].value == "=N19"
        assert adrian["A17"].fill.fill_type == "solid"
        assert adrian["A17"].fill.fgColor.rgb == "0000AA55"
        assert adrian_workbook["Rates"]["B1"].value == 17.5
    finally:
        adrian_workbook.close()

    darek_workbook = load_workbook(
        target_directory / f"Rozliczenie {PERIOD} - Darek Nowak.xlsx",
        data_only=False,
    )
    try:
        darek = active_worksheet(darek_workbook)
        assert worksheet_input_row(darek, 18) == expected_source_row(
            "syntetyczny adres 2", "#2", "dariusz.nowak2", 2
        )
        assert darek["AU18"].value == "=N18"
    finally:
        darek_workbook.close()

    empty_workbook = load_workbook(
        target_directory / f"Rozliczenie {PERIOD} - Kamil Frontczak.xlsx",
        data_only=False,
    )
    try:
        empty = active_worksheet(empty_workbook)
        assert worksheet_input_row(empty, 18) == (None,) * 13 + (0,) + (None,) * 32
        assert empty["AU18"].value == "=N18"
        assert empty["A17"].fill.fgColor.rgb == "0000AA55"
    finally:
        empty_workbook.close()


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
    [overwrite_with_non_workbook, cut_sheet_after_data_rows],
    ids=["nie-skoroszyt", "urwany-arkusz"],
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


def test_istniejacy_folder_rozliczen_pracownikow_nie_jest_nadpisywany(tmp_path: Path) -> None:
    source_path, target_directory, config_path = make_fixture(tmp_path)
    target_directory.mkdir()
    sentinel = target_directory / "existing.txt"
    sentinel.write_text("zachowaj", encoding="utf-8")

    with pytest.raises(StopError) as raised:
        run_settlements(source_path, config_path, worker_template_path=tmp_path / "Wzorzec rozliczenia pracownika.xlsx")

    assert "Folder docelowy już istnieje" in terminal_text(raised.value)
    assert sentinel.read_text(encoding="utf-8") == "zachowaj"


def test_external_link_relationships_survive_target_write(tmp_path: Path) -> None:
    source_path, target_directory, config_path = make_fixture(tmp_path)
    worker_template_path = tmp_path / "Wzorzec rozliczenia pracownika.xlsx"
    add_external_link_fixture(worker_template_path)
    before = external_link_parts(worker_template_path)

    run_settlements(source_path, config_path, worker_template_path=worker_template_path)

    target_path = target_directory / f"Rozliczenie {PERIOD} - Adrian Maciejewski.xlsx"
    assert external_link_parts(target_path) == before
    assert external_link_parts(worker_template_path) == before


def test_blokada_wzorca_rozliczenia_pracownika_wstrzymuje_publikacje_folderu_rozliczen_pracownikow(
    tmp_path: Path,
) -> None:
    source_path, target_directory, config_path = make_fixture(tmp_path)
    worker_template_path = tmp_path / "Wzorzec rozliczenia pracownika.xlsx"
    worker_template_path.with_name(f"~${worker_template_path.name}").touch()

    with pytest.raises(StopError) as raised:
        run_settlements(source_path, config_path, worker_template_path=worker_template_path)

    assert "Wzorzec rozliczenia pracownika jest otwarty lub zablokowany" in terminal_text(raised.value)
    assert not target_directory.exists()


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


def test_internal_settlement_file_is_rejected(tmp_path: Path) -> None:
    internal_path = tmp_path / PERIOD / f"Rozliczenie wew. {PERIOD}.xlsx"
    internal_path.parent.mkdir()
    internal_path.touch()

    try:
        run_settlements(internal_path, tmp_path / "missing.yaml")
    except StopError as exc:
        assert "wew." in terminal_text(exc)
    else:
        raise AssertionError("Plik Rozliczenie wew. powinien zostać odrzucony")


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
    assert isinstance(recorded[0], ProgressEvent)
    assert recorded[0].state is ProgressState.START
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
        path: Path,
        rows: Iterable[ExcelRow],
    ) -> WorkerResult:
        nonlocal calls
        calls += 1
        if calls == 2:
            raise template_settlement.TemplateWriteError("synthetic failure")
        return original_process_template(worker_name, path, rows)

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

    failed = [event for event in recorded if event.state is ProgressState.FAILED]
    assert len(failed) == 1
    assert failed[0].phase is ProgressPhase.SAVING
    assert failed[0].worker_name == "Darek Nowak"
    assert failed[0].template_index == 2
    assert failed[0].worker_elapsed_ms is not None
    assert all("syntetyczny" not in repr(event) and "#1" not in repr(event) for event in failed)
    assert not any(
        event.state is ProgressState.WORKER_END and event.worker_name == "Darek Nowak" for event in recorded
    )
    assert not any(event.state is ProgressState.END and event.phase is ProgressPhase.SAVING for event in recorded)

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
    assert [event.state for event in recorded] == [ProgressState.START, ProgressState.FAILED]
    assert recorded[-1].phase is ProgressPhase.CHECKING
    assert "Nie znaleziono pliku" not in repr(recorded[-1])


def projected(projection: ProgressProjection) -> ProgressObserver:
    def observer(event: ProgressEvent) -> None:
        projection.update(event)

    return observer


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

    def fail_save(worker_name: str, path: Path, rows: Iterable[ExcelRow]) -> WorkerResult:
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
    assert snapshot.current_worker == "Adrian Maciejewski"
    assert snapshot.phase_durations_ms[ProgressPhase.SAVING] >= save_s * 1000

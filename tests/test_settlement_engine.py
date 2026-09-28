from __future__ import annotations

from pathlib import Path
import os
import tempfile
import xml.etree.ElementTree as ET
import zipfile

from openpyxl import Workbook, load_workbook
import pytest
import yaml

from rozliczenia.domain import ProgressEvent, ProgressPhase, ProgressState
from rozliczenia.engine import SettlementError, run_settlements
import rozliczenia.template_settlement as template_settlement


PERIOD = "08_14_09_2026"
SOURCE_NAME = f"Rozliczenie {PERIOD} - zbiorcze.xlsx"


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
    sheet = workbook.active
    sheet.title = "Sheet1"
    sheet.cell(17, 8).value = "WYKONAWCA"
    sheet.cell(18, 47).value = "=N18"
    sheet.cell(19, 47).value = "=N19"
    sheet.cell(18, 14).value = 0
    sheet.cell(19, 14).value = 0
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
                    ET.SubElement(references, f"{{{ns_main}}}externalReference", {f"{{{ns_rel}}}id": "rId2"})
                    data = ET.tostring(root, encoding="utf-8", xml_declaration=True)
                elif info.filename == "xl/_rels/workbook.xml.rels":
                    root = ET.fromstring(data)
                    ET.SubElement(
                        root,
                        f"{{{ns_pkg_rel}}}Relationship",
                        {
                            "Id": "rId2",
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


def write_source(path: Path) -> None:
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "Sheet1"
    sheet.cell(17, 8).value = "WYKONAWCA"
    rows = [
        ("POZNAŃ", "syntetyczny adres 1", "adrian.maciejewski", "#1"),
        ("POZNAŃ", "syntetyczny adres 2", "dariusz.nowak2", "#2"),
        ("POZNAŃ", "syntetyczny adres 3", "adrian.maciejewski", "#3"),
        ("POZNAŃ", "syntetyczny adres 4", "andrzej.kulawski2", "#4"),
    ]
    for row_number, (city, address, worker, order_number) in enumerate(rows, start=18):
        sheet.cell(row_number, 1).value = city
        sheet.cell(row_number, 2).value = address
        sheet.cell(row_number, 6).value = order_number
        sheet.cell(row_number, 8).value = worker
        sheet.cell(row_number, 14).value = row_number - 17
    workbook.save(path)


def make_fixture(tmp_path: Path) -> tuple[Path, Path, Path]:
    period_directory = tmp_path / PERIOD
    target_directory = period_directory / f"Rozliczenie pracowników {PERIOD}"
    target_directory.mkdir(parents=True)
    source_path = period_directory / SOURCE_NAME
    write_source(source_path)
    write_template(target_directory / f"Rozliczenie {PERIOD} - Adrian Maciejewski.xlsx")
    write_template(target_directory / f"Rozliczenie {PERIOD} - Darek Nowak.xlsx")
    write_template(target_directory / f"Rozliczenie {PERIOD} - Kamil Frontczak.xlsx")
    write_template(target_directory / f"Rozliczenie {PERIOD} -.xlsx")
    return source_path, target_directory, write_mapping(tmp_path / "worker_mapping.yaml")


def test_groups_rows_by_worker_and_preserves_template_formulas(tmp_path: Path) -> None:
    source_path, target_directory, config_path = make_fixture(tmp_path)

    summary = run_settlements(source_path, config_path)

    assert summary.written_count == 2
    assert summary.empty_count == 1
    assert summary.total_rows == 3
    assert any(issue.code == "BRAK_MAPOWANIA" for issue in summary.issues)

    adrian = load_workbook(
        target_directory / f"Rozliczenie {PERIOD} - Adrian Maciejewski.xlsx",
        data_only=False,
    ).active
    assert adrian["A18"].value == "POZNAŃ"
    assert adrian["F18"].value == "#1"
    assert adrian["A19"].value == "POZNAŃ"
    assert adrian["F19"].value == "#3"
    assert adrian["AU18"].value == "=N18"
    assert adrian["AU19"].value == "=N19"

    empty_template = load_workbook(
        target_directory / f"Rozliczenie {PERIOD} - Kamil Frontczak.xlsx",
        data_only=False,
    ).active
    assert empty_template["A18"].value is None
    assert empty_template["AU18"].value == "=N18"


def test_dry_run_does_not_write(tmp_path: Path) -> None:
    source_path, target_directory, config_path = make_fixture(tmp_path)
    target_path = target_directory / f"Rozliczenie {PERIOD} - Adrian Maciejewski.xlsx"

    summary = run_settlements(source_path, config_path, dry_run=True)

    assert summary.planned_count == 2
    assert load_workbook(target_path, data_only=False).active["A18"].value is None


def test_existing_input_data_is_never_overwritten(tmp_path: Path) -> None:
    source_path, target_directory, config_path = make_fixture(tmp_path)
    target_path = target_directory / f"Rozliczenie {PERIOD} - Adrian Maciejewski.xlsx"
    workbook = load_workbook(target_path)
    workbook.active["A18"] = "wcześniejsza ręczna wartość"
    workbook.save(target_path)

    summary = run_settlements(source_path, config_path)

    assert any(issue.code == "NADPISANIE_ZABLOKOWANE" for issue in summary.issues)
    assert load_workbook(target_path, data_only=False).active["A18"].value == "wcześniejsza ręczna wartość"


def test_external_link_relationships_survive_target_write(tmp_path: Path) -> None:
    source_path, target_directory, config_path = make_fixture(tmp_path)
    target_path = target_directory / f"Rozliczenie {PERIOD} - Adrian Maciejewski.xlsx"
    add_external_link_fixture(target_path)
    before = external_link_parts(target_path)

    run_settlements(source_path, config_path)

    assert external_link_parts(target_path) == before


def test_locked_target_is_reported_without_stopping_other_files(tmp_path: Path) -> None:
    source_path, target_directory, config_path = make_fixture(tmp_path)
    locked_target = target_directory / f"Rozliczenie {PERIOD} - Darek Nowak.xlsx"
    lock_file = target_directory / f"~${locked_target.name}"
    lock_file.touch()

    summary = run_settlements(source_path, config_path)

    assert any(issue.code == "PLIK_ZABLOKOWANY" for issue in summary.issues)
    assert any(result.status == "ZAPISANO" for result in summary.results)


def test_internal_settlement_file_is_rejected(tmp_path: Path) -> None:
    internal_path = tmp_path / PERIOD / f"Rozliczenie wew. {PERIOD}.xlsx"
    internal_path.parent.mkdir()
    internal_path.touch()

    try:
        run_settlements(internal_path, tmp_path / "missing.yaml")
    except SettlementError as exc:
        assert "wew." in str(exc)
    else:
        raise AssertionError("Plik Rozliczenie wew. powinien zostać odrzucony")


def test_recording_observer_receives_safe_zdarzenia_przebiegu_and_can_be_disabled(tmp_path: Path) -> None:
    source_path, _, config_path = make_fixture(tmp_path)
    recorded = []
    calls = 0

    def recording_observer(event) -> None:
        nonlocal calls
        calls += 1
        recorded.append(event)
        raise RuntimeError("observer output failed")

    summary = run_settlements(source_path, config_path, observer=recording_observer)

    assert summary.written_count == 2
    assert calls == 1
    assert len(recorded) == 1
    assert isinstance(recorded[0], ProgressEvent)
    assert recorded[0].state is ProgressState.START
    assert "syntetyczny" not in repr(recorded[0])


def test_failed_przetworzenie_szablonu_pracownika_emits_failure_without_false_completion(
    tmp_path: Path, monkeypatch
) -> None:
    source_path, _, config_path = make_fixture(tmp_path)
    original_process_template = template_settlement.process_template
    calls = 0
    recorded = []

    def fail_on_second_save(worker_name: str, path: Path, rows, *, dry_run: bool = False):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise template_settlement.TemplateWriteError("synthetic failure")
        return original_process_template(worker_name, path, rows, dry_run=dry_run)

    monkeypatch.setattr(template_settlement, "process_template", fail_on_second_save)

    with pytest.raises(template_settlement.TemplateWriteError):
        run_settlements(source_path, config_path, observer=recorded.append)

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


def test_failed_faza_przebiegu_rozliczen_is_interrupted_without_exception_text(tmp_path: Path) -> None:
    source_path = tmp_path / "08_14_09_2026" / "Rozliczenie 08_14_09_2026 - zbiorcze.xlsx"
    recorded = []

    with pytest.raises(SettlementError, match="Nie znaleziono pliku"):
        run_settlements(source_path, tmp_path / "missing.yaml", observer=recorded.append)

    assert [event.state for event in recorded] == [ProgressState.START, ProgressState.FAILED]
    assert recorded[-1].phase is ProgressPhase.CHECKING
    assert "Nie znaleziono pliku" not in repr(recorded[-1])

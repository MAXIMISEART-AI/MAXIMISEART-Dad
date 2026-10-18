from __future__ import annotations

from dataclasses import replace
from io import StringIO
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import types
import zipfile
from collections.abc import Iterable
from typing import Any, TextIO, cast

from openpyxl import load_workbook
import pytest

from rozliczenia.cli import main
from rozliczenia.collective_file import ExcelRow
from rozliczenia.domain import Issue, SettlementSummary, WorkerResult
import rozliczenia.engine as settlement_engine
import rozliczenia.process_run as process_run
import rozliczenia.template_settlement as template_settlement
from rozliczenia.telemetry import MetricsStore

from tests.test_settlement_engine import (
    PERIOD,
    UNREADABLE_SOURCE_MESSAGE,
    active_worksheet,
    make_fixture,
    write_source,
)


def run_cli(
    source_path: Path,
    config_path: Path,
    metrics_path: Path,
    *extra_args: str,
) -> tuple[int, str]:
    output = StringIO()
    exit_code = main(
        [
            "--source",
            str(source_path),
            "--config",
            str(config_path),
            "--worker-template",
            str(config_path.parent / "Wzorzec rozliczenia pracownika.xlsx"),
            "--metrics",
            str(metrics_path),
            *extra_args,
        ],
        output=output,
    )
    return exit_code, output.getvalue()


def make_preview_fixture(tmp_path: Path) -> tuple[Path, Path, Path]:
    source_path, target_directory, config_path = make_fixture(tmp_path)
    write_source(source_path, include_unmapped=True)
    return source_path, target_directory, config_path


def assert_fixture_workbooks(target_directory: Path, *, dry_run: bool) -> None:
    if dry_run:
        assert not target_directory.exists()
        return

    expected_filenames = {
        f"Rozliczenie {PERIOD} - {worker_name}.xlsx"
        for worker_name in ("Adrian Maciejewski", "Darek Nowak", "Kamil Frontczak")
    }
    assert {path.name for path in target_directory.glob("*.xlsx")} == expected_filenames
    for worker_name in ("Adrian Maciejewski", "Darek Nowak"):
        workbook = load_workbook(target_directory / f"Rozliczenie {PERIOD} - {worker_name}.xlsx")
        try:
            sheet = active_worksheet(workbook)
            assert sheet["A18"].value == "POZNAŃ"
            assert sheet["AU18"].value == "=N18"
        finally:
            workbook.close()

    workbook = load_workbook(target_directory / f"Rozliczenie {PERIOD} - Kamil Frontczak.xlsx")
    try:
        sheet = active_worksheet(workbook)
        assert sheet["A18"].value is None
        assert sheet["AU18"].value == "=N18"
    finally:
        workbook.close()


def assert_completed_metrics(
    metrics_path: Path,
    *,
    dry_run: bool,
    issues: int = 0,
) -> dict[str, Any]:
    record = json.loads(metrics_path.read_text(encoding="utf-8"))
    assert record["schema_version"] == 1
    assert record["mode"] == ("DRY-RUN" if dry_run else "RUN")
    assert record["completed"] is True
    assert record["counters"] == {
        "templates_total": 3,
        "templates_completed": 3,
        "rows": 3,
        "written": 0 if dry_run else 2,
        "empty": 1,
        "planned": 2 if dry_run else 0,
        "skipped": 0,
        "issues": issues,
    }
    return cast(dict[str, Any], record)


def test_plain_cli_reports_progress_and_writes_safe_metrics(tmp_path: Path) -> None:
    source_path, _, config_path = make_fixture(tmp_path)
    metrics_path = tmp_path / "metrics.jsonl"

    exit_code, output = run_cli(source_path, config_path, metrics_path)

    assert exit_code == 0
    assert "RUN" in output
    assert output.index("Sprawdzanie") < output.index("Odczyt danych")
    assert output.index("Odczyt danych") < output.index("Planowanie")
    assert output.index("Planowanie") < output.index("Zapisywanie")
    assert "Postęp szablonów: 1/3" in output
    assert "Postęp szablonów: 2/3" in output
    assert "Postęp szablonów: 3/3 (100%)" in output
    assert "WYKONAWCA: Adrian Maciejewski" in output
    assert "Ostatnie operacje" in output
    assert "Wiersze danych: 3" in output
    assert "Liczniki:" in output
    assert "Zapisane szablony: 2" in output
    assert "Puste szablony: 1" in output
    assert "Pominięte szablony: 0" in output
    assert "Status końcowy: OK" in output
    assert "\x1b" not in output

    record = json.loads(metrics_path.read_text(encoding="utf-8"))
    assert record["schema_version"] == 1
    assert record["mode"] == "RUN"
    assert record["completed"] is True
    assert record["result"] == "OK"
    assert record["total_duration_ms"] >= 0
    assert set(record["phase_durations_ms"]) == {
        "Sprawdzanie",
        "Odczyt danych",
        "Planowanie",
        "Zapisywanie",
    }
    assert record["counters"]["templates_total"] == 3
    assert record["counters"]["templates_completed"] == 3
    metrics_text = metrics_path.read_text(encoding="utf-8")
    assert metrics_text.count("\n") == 1
    assert "syntetyczny adres" not in metrics_text
    assert "#1" not in metrics_text
    assert str(source_path) not in metrics_text


def test_metrics_store_rejects_record_with_full_path(tmp_path: Path) -> None:
    source_path, _, config_path = make_fixture(tmp_path)
    metrics_path = tmp_path / "metrics.jsonl"
    run_cli(source_path, config_path, metrics_path)

    record = json.loads(metrics_path.read_text(encoding="utf-8"))
    record["source_path"] = str(source_path)

    with pytest.raises(ValueError):
        MetricsStore(metrics_path).append(record)

    assert metrics_path.read_text(encoding="utf-8").count("\n") == 1


def test_metrics_store_repairs_torn_final_line(tmp_path: Path) -> None:
    source_path, _, config_path = make_fixture(tmp_path)
    metrics_path = tmp_path / "metrics.jsonl"
    run_cli(source_path, config_path, metrics_path)
    record = json.loads(metrics_path.read_text(encoding="utf-8"))

    with metrics_path.open("ab") as stream:
        stream.write(b'{"schema_version":1\n')
    MetricsStore(metrics_path).append(record)

    assert len(MetricsStore(metrics_path).read()) == 2
    assert metrics_path.read_bytes().endswith(b"\n")

    with metrics_path.open("ab") as stream:
        stream.write(b"\xff\n")
    MetricsStore(metrics_path).append(record)

    assert len(MetricsStore(metrics_path).read()) == 3


@pytest.mark.parametrize(
    ("dry_run", "mode"),
    [(False, "RUN"), (True, "DRY-RUN")],
)
def test_cli_runs_without_rich(tmp_path: Path, dry_run: bool, mode: str) -> None:
    fixture = make_preview_fixture(tmp_path) if dry_run else make_fixture(tmp_path)
    source_path, target_directory, config_path = fixture
    metrics_path = tmp_path / "metrics.jsonl"
    environment = os.environ.copy()
    environment["PYTHONPATH"] = str(Path(__file__).parents[1] / "src")
    arguments = [
        "--source",
        str(source_path),
        "--config",
        str(config_path),
        "--worker-template",
        str(config_path.parent / "Wzorzec rozliczenia pracownika.xlsx"),
        "--metrics",
        str(metrics_path),
    ]
    if dry_run:
        arguments.append("--dry-run")
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "import sys; sys.modules['rich'] = None; from rozliczenia.cli import main; raise SystemExit(main())",
            *arguments,
        ],
        capture_output=True,
        text=True,
        env=environment,
    )

    assert result.returncode == (2 if dry_run else 0), result.stderr
    assert "Etap: Sprawdzanie" in result.stdout
    assert "Postęp szablonów: 3/3 (100%)" in result.stdout
    assert "WYKONAWCA: Adrian Maciejewski" in result.stdout
    assert f"Status końcowy: {'Wymaga sprawdzenia' if dry_run else 'OK'}" in result.stdout

    assert_fixture_workbooks(target_directory, dry_run=dry_run)
    assert_completed_metrics(metrics_path, dry_run=dry_run, issues=1 if dry_run else 0)
    metrics_text = metrics_path.read_text(encoding="utf-8")
    assert "syntetyczny adres" not in metrics_text
    assert "#1" not in metrics_text
    assert str(source_path) not in metrics_text


@pytest.mark.parametrize(
    ("dry_run", "mode"),
    [(False, "RUN"), (True, "DRY-RUN")],
)
def test_interactive_rich_cli_uses_shared_progress_for_synthetic_workbooks(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    dry_run: bool,
    mode: str,
) -> None:
    pytest.importorskip("rich")
    from rich.console import Console as RichConsole

    class TtyOutput(StringIO):
        def isatty(self) -> bool:
            return True

    class FakeConsole:
        color_system = "standard"

        def __init__(self, *, file: TextIO) -> None:
            self.renderer = RichConsole(file=file, color_system=None)

        def print(self, renderable: Any) -> None:
            self.renderer.print(renderable)

    class FakeLive:
        def __init__(self, renderable: Any, *, console: FakeConsole, **_kwargs: Any) -> None:
            self.console = console
            self.renderable = renderable
            self.refreshes = 0

        def start(self, *, refresh: bool) -> None:
            pass

        def update(self, renderable: Any, *, refresh: bool) -> None:
            self.refreshes += 1
            self.console.print(renderable)

        def stop(self) -> None:
            pass

    fixture = make_preview_fixture(tmp_path) if dry_run else make_fixture(tmp_path)
    source_path, target_directory, config_path = fixture
    metrics_path = tmp_path / "metrics.jsonl"
    output = TtyOutput()
    live_instances: list[FakeLive] = []

    def make_live(renderable: Any, *, console: FakeConsole, **kwargs: Any) -> FakeLive:
        live = FakeLive(renderable, console=console, **kwargs)
        live_instances.append(live)
        return live

    monkeypatch.setattr(process_run, "Console", FakeConsole)
    monkeypatch.setattr(process_run, "Live", make_live)
    arguments = [
        "--source",
        str(source_path),
        "--config",
        str(config_path),
        "--worker-template",
        str(config_path.parent / "Wzorzec rozliczenia pracownika.xlsx"),
        "--metrics",
        str(metrics_path),
    ]
    if dry_run:
        arguments.append("--dry-run")

    exit_code = main(arguments, output=output)

    assert exit_code == (2 if dry_run else 0)
    assert live_instances and live_instances[0].refreshes > 0
    rendered = output.getvalue()
    assert mode in rendered
    assert "Postęp szablonów: 3/3 (100%)" in rendered
    assert "Bieżący WYKONAWCA: Adrian Maciejewski" in rendered
    if dry_run:
        assert "PLAN" in rendered
    else:
        assert "ZAPISANO" in rendered
    assert "syntetyczny adres" not in rendered
    assert "#1" not in rendered

    assert_fixture_workbooks(target_directory, dry_run=dry_run)
    assert_completed_metrics(metrics_path, dry_run=dry_run, issues=1 if dry_run else 0)


def test_cli_existing_folder_rozliczen_pracownikow_is_preserved(tmp_path: Path) -> None:
    source_path, target_directory, config_path = make_fixture(tmp_path)
    target_directory.mkdir(parents=True)
    sentinel = target_directory / "existing.txt"
    sentinel.write_text("zachowaj", encoding="utf-8")

    exit_code, output = run_cli(source_path, config_path, tmp_path / "metrics.jsonl")

    assert exit_code == 1
    assert "Folder docelowy już istnieje" in output
    assert "Status semantyczny: BŁĄD" in output
    assert sentinel.read_text(encoding="utf-8") == "zachowaj"


def test_cli_nieczytelny_plik_zbiorczy_pokazuje_bezpieczny_komunikat(tmp_path: Path) -> None:
    source_path, target_directory, config_path = make_fixture(tmp_path)
    source_path.write_bytes(b"uszkodzony")

    exit_code, output = run_cli(source_path, config_path, tmp_path / "metrics.jsonl")

    assert exit_code == 1
    assert "Status semantyczny: BŁĄD" in output
    assert f"Nie wykonano: {UNREADABLE_SOURCE_MESSAGE}" in output
    assert "File is not a zip file" not in output
    assert not target_directory.exists()


def test_cli_wykonawca_bez_mapowania_nie_publikuje_folderu(tmp_path: Path) -> None:
    source_path, target_directory, config_path = make_preview_fixture(tmp_path)

    exit_code, output = run_cli(source_path, config_path, tmp_path / "metrics.jsonl")

    assert exit_code == 1
    assert "WYKONAWCA bez mapowania" in output
    assert "andrzej.kulawski2" not in output
    assert "syntetyczny adres" not in output
    assert not target_directory.exists()
    assert not list(target_directory.parent.glob(f".{target_directory.name}.staging-*"))
    record = json.loads((tmp_path / "metrics.jsonl").read_text(encoding="utf-8"))
    assert record["completed"] is False
    assert record["result"] == "BLAD_KRYTYCZNY"


def test_cli_dry_run_shows_complete_plan_without_creating_output(tmp_path: Path) -> None:
    source_path, target_directory, config_path = make_preview_fixture(tmp_path)
    worker_template_path = tmp_path / "Wzorzec rozliczenia pracownika.xlsx"
    source_before = source_path.read_bytes()
    worker_template_before = worker_template_path.read_bytes()

    exit_code, output = run_cli(source_path, config_path, tmp_path / "metrics.jsonl", "--dry-run")

    assert exit_code == 2
    assert "DRY-RUN" in output
    assert f"Okres rozliczeniowy: {PERIOD}" in output
    assert f"Folder rozliczeń pracowników: {target_directory}" in output
    assert "Plan plików:" in output
    assert f"Rozliczenie {PERIOD} - Adrian Maciejewski.xlsx | Wiersze do uzupełnienia: 2" in output
    assert f"Rozliczenie {PERIOD} - Darek Nowak.xlsx | Wiersze do uzupełnienia: 1" in output
    assert (
        f"Rozliczenie {PERIOD} - Kamil Frontczak.xlsx | "
        "Wiersze do uzupełnienia: 0 | Pusty skoroszyt"
    ) in output
    assert "Nieznany identyfikator WYKONAWCA" in output
    assert "andrzej.kulawski2" not in output
    assert "syntetyczny adres" not in output
    assert "#1" not in output
    assert "Planowane szablony: 2" in output
    assert "Nic nie zapisano" in output
    assert not target_directory.exists()
    assert source_path.read_bytes() == source_before
    assert worker_template_path.read_bytes() == worker_template_before
    assert_completed_metrics(tmp_path / "metrics.jsonl", dry_run=True, issues=1)


@pytest.mark.parametrize(
    ("problem", "expected_message"),
    [
        ("missing-worker-template", "Nie znaleziono Wzorca rozliczenia pracownika"),
        ("corrupt-worker-template", "Nie można odczytać Wzorca rozliczenia pracownika"),
        ("locked-worker-template", "Wzorzec rozliczenia pracownika jest otwarty lub zablokowany"),
        ("wrong-worker-template-header", "Wzorzec rozliczenia pracownika nie ma nagłówka WYKONAWCA"),
        ("worker-template-has-data", "Wzorzec rozliczenia pracownika zawiera dane"),
        ("invalid-config", "Niepoprawny YAML konfiguracji"),
        ("unsupported-config-version", "Nieobsługiwana wersja konfiguracji"),
        ("unsafe-worker-name", "nieprawidłową dla nazwy pliku"),
        ("long-worker-name", "zbyt długą dla nazwy pliku"),
    ],
)
def test_cli_dry_run_rejects_invalid_inputs_before_creating_output(
    tmp_path: Path,
    problem: str,
    expected_message: str,
) -> None:
    source_path, target_directory, config_path = make_preview_fixture(tmp_path)
    worker_template_path = tmp_path / "Wzorzec rozliczenia pracownika.xlsx"
    if problem == "missing-worker-template":
        worker_template_path.unlink()
    elif problem == "corrupt-worker-template":
        worker_template_path.write_bytes(b"not an Excel workbook")
    elif problem == "locked-worker-template":
        worker_template_path.with_name(f"~${worker_template_path.name}").touch()
    elif problem == "wrong-worker-template-header":
        workbook = load_workbook(worker_template_path)
        active_worksheet(workbook)["H17"] = "NIE WYKONAWCA"
        workbook.save(worker_template_path)
        workbook.close()
    elif problem == "worker-template-has-data":
        workbook = load_workbook(worker_template_path)
        active_worksheet(workbook)["A18"] = "SENSITIVE-SYNTHETIC"
        workbook.save(worker_template_path)
        workbook.close()
    elif problem == "invalid-config":
        config_path.write_text("workers: [", encoding="utf-8")
    elif problem == "unsupported-config-version":
        config_path.write_text(
            "schema_version: 2\nworkers:\n  synthetic.worker: Worker\n",
            encoding="utf-8",
        )
    elif problem == "unsafe-worker-name":
        config_path.write_text(
            "schema_version: 1\nworkers:\n  synthetic.worker: ../outside\n",
            encoding="utf-8",
        )
    elif problem == "long-worker-name":
        config_path.write_text(
            f"schema_version: 1\nworkers:\n  synthetic.worker: {'X' * 223}\n",
            encoding="utf-8",
        )

    exit_code, output = run_cli(source_path, config_path, tmp_path / "metrics.jsonl", "--dry-run")

    assert exit_code == 1
    assert expected_message in output
    assert "synthetic.worker" not in output
    assert "synthetic address" not in output
    assert "SENSITIVE-SYNTHETIC" not in output
    assert not target_directory.exists()


def test_cli_dry_run_rejects_existing_folder_rozliczen_pracownikow(tmp_path: Path) -> None:
    source_path, target_directory, config_path = make_preview_fixture(tmp_path)
    target_directory.mkdir(parents=True)
    sentinel = target_directory / "existing.txt"
    sentinel.write_text("zachowaj", encoding="utf-8")

    exit_code, output = run_cli(source_path, config_path, tmp_path / "metrics.jsonl", "--dry-run")

    assert exit_code == 1
    assert "Folder docelowy już istnieje" in output
    assert sentinel.read_text(encoding="utf-8") == "zachowaj"


def test_critical_failure_is_recorded_as_incomplete_run(tmp_path: Path) -> None:
    period_directory = tmp_path / PERIOD
    period_directory.mkdir()
    source_path = period_directory / f"Rozliczenie {PERIOD} - zbiorcze.xlsx"
    metrics_path = tmp_path / "metrics.jsonl"

    exit_code, output = run_cli(source_path, tmp_path / "missing.yaml", metrics_path)

    assert exit_code == 1
    assert "Nie wykonano" in output
    assert "Status semantyczny: BŁĄD" in output
    record = json.loads(metrics_path.read_text(encoding="utf-8"))
    assert record["completed"] is False
    assert record["result"] == "BLAD_KRYTYCZNY"


UNEXPECTED_FAILURE_LINE = (
    "Nie wykonano: Wystąpił nieoczekiwany błąd; folder rozliczeń pracowników nie został opublikowany. "
    "Uruchom ponownie; jeśli błąd wraca, przekaż to osobie utrzymującej narzędzie."
)


def install_source_dialog(monkeypatch: pytest.MonkeyPatch, *, selected: str, answer_after_s: float = 0) -> list[str]:
    """Zastępuje okno wyboru Pliku zbiorczego (tkinter); zwraca tytuły pokazanych okien."""

    shown: list[str] = []

    class FakeRoot:
        def withdraw(self) -> None:
            pass

        def destroy(self) -> None:
            pass

    def askopenfilename(*, title: str, **_kwargs: object) -> str:
        shown.append(title)
        time.sleep(answer_after_s)
        return selected

    filedialog = types.ModuleType("tkinter.filedialog")
    setattr(filedialog, "askopenfilename", askopenfilename)
    tk_module = types.ModuleType("tkinter")
    setattr(tk_module, "Tk", FakeRoot)
    setattr(tk_module, "filedialog", filedialog)
    monkeypatch.setitem(sys.modules, "tkinter", tk_module)
    monkeypatch.setitem(sys.modules, "tkinter.filedialog", filedialog)
    return shown


def append_completed_records(metrics_path: Path, mode: str, count: int = 5) -> None:
    for sample in range(count):
        MetricsStore(metrics_path).append(
            {
                "schema_version": 1,
                "started_at": f"2026-09-28T00:00:0{sample}+00:00",
                "mode": mode,
                "period": PERIOD,
                "completed": True,
                "result": "OK",
                "total_duration_ms": 1000,
                "phase_durations_ms": {"Sprawdzanie": 1, "Odczyt danych": 1, "Planowanie": 1, "Zapisywanie": 1},
                "counters": {
                    "templates_total": 1,
                    "templates_completed": 1,
                    "rows": 1,
                    "written": 1,
                    "empty": 0,
                    "planned": 0,
                    "skipped": 0,
                    "issues": 0,
                },
            }
        )


def test_cancelled_plik_zbiorczy_selection_stops_with_statistics_and_without_dialog_time(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    metrics_path = tmp_path / "metrics.jsonl"
    append_completed_records(metrics_path, "RUN")
    shown = install_source_dialog(monkeypatch, selected="", answer_after_s=1.0)

    output = StringIO()
    exit_code = main(["--metrics", str(metrics_path)], output=output)

    assert exit_code == 1
    assert shown == ["Wybierz plik zbiorczy rozliczenia"]
    lines = output.getvalue().splitlines()
    assert lines[0] == "Rozliczenia | okres: nieznany | tryb: RUN"
    status = lines.index("Status semantyczny: BŁĄD")
    assert lines[status + 1] == "Nie wykonano: Nie wybrano pliku zbiorczego."
    assert lines[status + 2].startswith("Czas uruchomienia: ")
    assert int(lines[status + 2].removeprefix("Czas uruchomienia: ").removesuffix(" ms")) < 1000
    assert lines[status + 3] == "Statystyki RUN | próbek: 5"
    record = MetricsStore(metrics_path).read()[-1]
    assert (record["period"], record["completed"], record["result"]) == ("nieznany", False, "BLAD_KRYTYCZNY")
    assert record["total_duration_ms"] < 1000


def test_cancelled_plik_zbiorczy_selection_warns_when_metrics_are_not_saved(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    metrics_parent = tmp_path / "not-a-directory"
    metrics_parent.write_text("nie katalog", encoding="utf-8")
    install_source_dialog(monkeypatch, selected="")

    output = StringIO()
    exit_code = main(["--metrics", str(metrics_parent / "metrics.jsonl")], output=output)

    assert exit_code == 1
    assert output.getvalue().splitlines()[-1] == (
        "Ostrzeżenie: Nie zapisano metryk; proces rozliczeń zakończył się niezależnie."
    )


def test_broken_wzorzec_rozliczenia_pracownika_shows_safe_message_instead_of_parser_text(tmp_path: Path) -> None:
    source_path, target_directory, config_path = make_fixture(tmp_path)
    worker_template_path = config_path.parent / "Wzorzec rozliczenia pracownika.xlsx"
    with zipfile.ZipFile(source_path) as source:
        entries = [(entry.filename, source.read(entry)) for entry in source.infolist()]
    with zipfile.ZipFile(worker_template_path, "w") as broken:
        for name, data in entries:
            broken.writestr(name, b"<x" if name.startswith("xl/worksheets/") else data)

    exit_code, output = run_cli(source_path, config_path, tmp_path / "metrics.jsonl")

    assert exit_code == 1
    lines = output.splitlines()
    status = lines.index("Status semantyczny: BŁĄD")
    assert lines[status + 1] == UNEXPECTED_FAILURE_LINE
    assert lines[status + 2].startswith("Czas uruchomienia: ")
    assert "unclosed token" not in output
    assert "Traceback" not in output
    assert not target_directory.exists()


def test_summary_failure_after_rozliczenia_pracownikow_were_written_says_they_exist(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source_path, target_directory, config_path = make_fixture(tmp_path)
    metrics_path = tmp_path / "metrics.jsonl"
    run_settlements = settlement_engine.run_settlements

    def run_with_unprintable_summary(*args: Any, **kwargs: Any) -> SettlementSummary:
        summary = run_settlements(*args, **kwargs)
        return replace(summary, issues=[cast(Issue, "SYN-001")])

    monkeypatch.setattr(settlement_engine, "run_settlements", run_with_unprintable_summary)

    exit_code, output = run_cli(source_path, config_path, metrics_path)

    assert exit_code == 1
    lines = output.splitlines()
    status = lines.index("Status semantyczny: BŁĄD")
    assert lines[status + 1] == (
        "Rozliczenia pracowników powstały, ale nie udało się pokazać podsumowania. "
        "Sprawdź Folder okresu i przekaż ten komunikat osobie utrzymującej narzędzie."
    )
    assert lines[status + 2].startswith("Czas uruchomienia: ")
    assert "SYN-" not in output
    assert "Traceback" not in output
    assert target_directory.is_dir()
    record = json.loads(metrics_path.read_text(encoding="utf-8"))
    assert (record["completed"], record["result"]) == (False, "BLAD_KRYTYCZNY")


def test_critical_write_failure_shows_interrupted_szablon_pracownika_and_records_incomplete_run(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source_path, target_directory, config_path = make_fixture(tmp_path)
    metrics_path = tmp_path / "metrics.jsonl"
    original_process_template = template_settlement.process_template
    save_calls = 0

    def fail_on_second_save(
        worker_name: str,
        path: Path,
        rows: Iterable[ExcelRow],
    ) -> WorkerResult:
        nonlocal save_calls
        save_calls += 1
        if save_calls == 2:
            raise template_settlement.TemplateWriteError("synthetic write failure")
        return original_process_template(worker_name, path, rows)

    monkeypatch.setattr(template_settlement, "process_template", fail_on_second_save)

    exit_code, output = run_cli(source_path, config_path, metrics_path)

    assert exit_code == 1
    assert not target_directory.exists()
    assert not list(target_directory.parent.glob(f".{target_directory.name}.staging-*"))
    assert "folder wynikowy nie został opublikowany" in output
    assert "Postęp szablonów: 1/3 (33%)" in output
    assert (
        "Etap przerwany: Zapisywanie | WYKONAWCA: Darek Nowak | "
        "Szablon pracownika: 2/3"
    ) in output
    record = json.loads(metrics_path.read_text(encoding="utf-8"))
    assert record["completed"] is False
    assert record["result"] == "BLAD_KRYTYCZNY"
    assert set(record["counters"].values()) == {0}

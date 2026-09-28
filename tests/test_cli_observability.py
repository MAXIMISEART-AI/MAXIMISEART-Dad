from __future__ import annotations

from io import StringIO
import json
import os
from pathlib import Path
import subprocess
import sys
from collections.abc import Iterable
from typing import Any, TextIO, cast

from openpyxl import load_workbook
import pytest

import rozliczenia.cli as cli
from rozliczenia.cli import main
from rozliczenia.domain import ProgressEventFactory, ProgressObserver, ProgressPhase, SettlementSummary, WorkerResult
import rozliczenia.engine as settlement_engine
from rozliczenia.progress import ProgressNotice, ProgressSnapshot
from rozliczenia.rich_progress import RichProgressAdapter
from rozliczenia.template_settlement import ExcelRow
import rozliczenia.template_settlement as template_settlement
from rozliczenia.progress import PhaseState, ProgressNoticeKind
from rozliczenia.telemetry import MetricsStore

from tests.test_settlement_engine import PERIOD, active_worksheet, make_fixture


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
            "--metrics",
            str(metrics_path),
            *extra_args,
        ],
        output=output,
    )
    return exit_code, output.getvalue()


def assert_fixture_workbooks(target_directory: Path, *, dry_run: bool) -> None:
    expected_input = None if dry_run else "POZNAŃ"
    for worker_name in ("Adrian Maciejewski", "Darek Nowak"):
        workbook = load_workbook(target_directory / f"Rozliczenie {PERIOD} - {worker_name}.xlsx")
        try:
            sheet = active_worksheet(workbook)
            assert sheet["A18"].value == expected_input
            assert sheet["AU18"].value == "=N18"
        finally:
            workbook.close()

    for filename in (
        f"Rozliczenie {PERIOD} - Kamil Frontczak.xlsx",
        f"Rozliczenie {PERIOD} -.xlsx",
    ):
        workbook = load_workbook(target_directory / filename)
        try:
            sheet = active_worksheet(workbook)
            assert sheet["A18"].value is None
            assert sheet["AU18"].value == "=N18"
        finally:
            workbook.close()


def assert_completed_metrics(metrics_path: Path, *, dry_run: bool) -> dict[str, Any]:
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
        "issues": 1,
    }
    return cast(dict[str, Any], record)


def test_interactive_dashboard_does_not_refresh_without_an_event(monkeypatch: pytest.MonkeyPatch) -> None:
    pytest.importorskip("rich")

    class TtyOutput(StringIO):
        def isatty(self) -> bool:
            return True

    class FakeConsole:
        color_system = "standard"

        def __init__(self, *, file: TextIO) -> None:
            self.file = file

    live_instances = []

    class FakeLive:
        def __init__(self, renderable: Any, **kwargs: Any) -> None:
            live_instances.append(kwargs)

        def start(self, *, refresh: bool) -> None:
            pass

    monkeypatch.setattr(cli, "Console", FakeConsole)
    monkeypatch.setattr(cli, "Live", FakeLive)

    dashboard = cli.Dashboard(TtyOutput(), "RUN", PERIOD)
    dashboard.start()

    assert live_instances[0].get("auto_refresh", True) is False


def test_interactive_dashboard_renders_the_accepted_snapshot_and_notice(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pytest.importorskip("rich")

    class TtyOutput(StringIO):
        def isatty(self) -> bool:
            return True

    class FakeConsole:
        color_system = "standard"

        def __init__(self, *, file: TextIO) -> None:
            self.file = file

    class FakeLive:
        def __init__(self, renderable: Any, **_kwargs: Any) -> None:
            self.initial_renderable = renderable
            self.updates: list[tuple[Any, bool]] = []

        def start(self, *, refresh: bool) -> None:
            pass

        def update(self, renderable: Any, *, refresh: bool) -> None:
            self.updates.append((renderable, refresh))

        def stop(self) -> None:
            pass

    renders: list[tuple[ProgressSnapshot, ProgressNotice | None, Any]] = []
    original_render = RichProgressAdapter.render

    def record_render(
        adapter: RichProgressAdapter,
        snapshot: ProgressSnapshot,
        notice: ProgressNotice | None = None,
    ) -> Any:
        renderable = original_render(adapter, snapshot, notice)
        renders.append((snapshot, notice, renderable))
        return renderable

    monkeypatch.setattr(cli, "Console", FakeConsole)
    monkeypatch.setattr(cli, "Live", FakeLive)
    monkeypatch.setattr(RichProgressAdapter, "render", record_render)

    dashboard = cli.Dashboard(TtyOutput(), "RUN", PERIOD)
    dashboard.start()
    dashboard(ProgressEventFactory.phase_started(ProgressPhase.CHECKING))

    assert renders[0][1] is None
    assert renders[0][0].phase_states[ProgressPhase.CHECKING] is PhaseState.PENDING
    snapshot, notice, renderable = renders[1]
    assert snapshot.phase_states[ProgressPhase.CHECKING] is PhaseState.RUNNING
    assert notice is not None
    assert notice.kind is ProgressNoticeKind.PHASE_STARTED
    assert dashboard.live is not None
    assert dashboard.live.updates == [(renderable, True)]


def test_interactive_rich_render_failure_falls_back_without_interrupting_settlements(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    pytest.importorskip("rich")

    class TtyOutput(StringIO):
        def isatty(self) -> bool:
            return True

    class FakeConsole:
        color_system = "standard"

        def __init__(self, *, file: TextIO) -> None:
            self.file = file

        def print(self, value: str) -> None:
            self.file.write(f"{value}\n")

    class FakeLive:
        def __init__(self, _renderable: Any, **_kwargs: Any) -> None:
            pass

        def start(self, *, refresh: bool) -> None:
            pass

        def update(self, _renderable: Any, *, refresh: bool) -> None:
            pass

        def stop(self) -> None:
            pass

    source_path, _, config_path = make_fixture(tmp_path)
    metrics_path = tmp_path / "metrics.jsonl"
    output = TtyOutput()
    render_calls = 0
    original_render = RichProgressAdapter.render

    def fail_on_first_refresh(
        adapter: RichProgressAdapter,
        snapshot: ProgressSnapshot,
        notice: ProgressNotice | None = None,
    ) -> Any:
        nonlocal render_calls
        render_calls += 1
        if render_calls == 2:
            raise RuntimeError("synthetic Rich rendering failure")
        return original_render(adapter, snapshot, notice)

    monkeypatch.setattr(cli, "Console", FakeConsole)
    monkeypatch.setattr(cli, "Live", FakeLive)
    monkeypatch.setattr(RichProgressAdapter, "render", fail_on_first_refresh)

    exit_code = main(
        [
            "--source",
            str(source_path),
            "--config",
            str(config_path),
            "--metrics",
            str(metrics_path),
        ],
        output=output,
    )

    assert exit_code == 2
    assert render_calls >= 2
    assert "Etap: Sprawdzanie" in output.getvalue()
    assert "Postęp szablonów: 3/3 (100%)" in output.getvalue()
    record = json.loads(metrics_path.read_text(encoding="utf-8"))
    assert record["completed"] is True
    assert record["counters"]["templates_completed"] == 3


def test_plain_cli_reports_progress_and_writes_safe_metrics(tmp_path: Path) -> None:
    source_path, _, config_path = make_fixture(tmp_path)
    metrics_path = tmp_path / "metrics.jsonl"

    exit_code, output = run_cli(source_path, config_path, metrics_path)

    assert exit_code == 2
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
    assert "Wymaga sprawdzenia" in output
    assert "\x1b" not in output

    record = json.loads(metrics_path.read_text(encoding="utf-8"))
    assert record["schema_version"] == 1
    assert record["mode"] == "RUN"
    assert record["completed"] is True
    assert record["result"] == "WYMAGA_SPRAWDZENIA"
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


@pytest.mark.parametrize("fail_at_write", [1, 4])
def test_plain_output_failure_detaches_observer_and_completes_przebieg_rozliczen(
    tmp_path: Path, fail_at_write: int
) -> None:
    class FailingOutput(StringIO):
        writes = 0

        def write(self, value: str) -> int:
            self.writes += 1
            if self.writes >= fail_at_write:
                raise OSError("synthetic output failure")
            return super().write(value)

    source_path, _, config_path = make_fixture(tmp_path)
    metrics_path = tmp_path / "metrics.jsonl"
    output = FailingOutput()

    exit_code = main(
        [
            "--source",
            str(source_path),
            "--config",
            str(config_path),
            "--metrics",
            str(metrics_path),
        ],
        output=output,
    )

    assert exit_code == 2
    record = json.loads(metrics_path.read_text(encoding="utf-8"))
    assert record["completed"] is True
    assert record["counters"]["templates_completed"] == 3
    assert record["counters"]["written"] == 2
    assert record["result"] == "WYMAGA_SPRAWDZENIA"
    assert output.writes == fail_at_write


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
    source_path, target_directory, config_path = make_fixture(tmp_path)
    metrics_path = tmp_path / "metrics.jsonl"
    environment = os.environ.copy()
    environment["PYTHONPATH"] = str(Path(__file__).parents[1] / "src")
    arguments = [
        "--source",
        str(source_path),
        "--config",
        str(config_path),
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

    assert result.returncode == 2, result.stderr
    assert "Etap: Sprawdzanie" in result.stdout
    assert "Postęp szablonów: 3/3 (100%)" in result.stdout
    assert "WYKONAWCA: Adrian Maciejewski" in result.stdout
    assert "Status końcowy: Wymaga sprawdzenia" in result.stdout

    assert_fixture_workbooks(target_directory, dry_run=dry_run)
    assert_completed_metrics(metrics_path, dry_run=dry_run)
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

    source_path, target_directory, config_path = make_fixture(tmp_path)
    metrics_path = tmp_path / "metrics.jsonl"
    output = TtyOutput()
    live_instances: list[FakeLive] = []

    def make_live(renderable: Any, *, console: FakeConsole, **kwargs: Any) -> FakeLive:
        live = FakeLive(renderable, console=console, **kwargs)
        live_instances.append(live)
        return live

    monkeypatch.setattr(cli, "Console", FakeConsole)
    monkeypatch.setattr(cli, "Live", make_live)
    arguments = [
        "--source",
        str(source_path),
        "--config",
        str(config_path),
        "--metrics",
        str(metrics_path),
    ]
    if dry_run:
        arguments.append("--dry-run")

    exit_code = main(arguments, output=output)

    assert exit_code == 2
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
    assert_completed_metrics(metrics_path, dry_run=dry_run)


def test_cli_can_run_the_settlement_engine_without_an_observer(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source_path, target_directory, config_path = make_fixture(tmp_path)
    metrics_path = tmp_path / "metrics.jsonl"
    observers: list[ProgressObserver | None] = []
    original_run_settlements = settlement_engine.run_settlements

    def record_observer(
        source: Path,
        config: Path,
        *,
        dry_run: bool = False,
        observer: ProgressObserver | None = None,
    ) -> SettlementSummary:
        observers.append(observer)
        return original_run_settlements(source, config, dry_run=dry_run, observer=observer)

    monkeypatch.setattr(cli, "run_settlements", record_observer)

    exit_code, output = run_cli(source_path, config_path, metrics_path, "--no-observer")

    assert exit_code == 2
    assert observers == [None]
    assert "Status końcowy: Wymaga sprawdzenia" in output
    assert "Postęp szablonów:" not in output
    assert_fixture_workbooks(target_directory, dry_run=False)
    record = assert_completed_metrics(metrics_path, dry_run=False)
    assert set(record["phase_durations_ms"]) == {
        "Sprawdzanie",
        "Odczyt danych",
        "Planowanie",
        "Zapisywanie",
    }
    assert record["phase_durations_ms"]["Zapisywanie"] > 0


def test_plain_cli_completes_progress_for_locked_and_skipped_szablon_pracownika(tmp_path: Path) -> None:
    source_path, target_directory, config_path = make_fixture(tmp_path)
    locked_path = target_directory / f"Rozliczenie {PERIOD} - Darek Nowak.xlsx"
    (target_directory / f"~${locked_path.name}").touch()

    invalid_path = target_directory / f"Rozliczenie {PERIOD} - Kamil Frontczak.xlsx"
    workbook = load_workbook(invalid_path)
    try:
        active_worksheet(workbook)["H17"] = "NIE WYKONAWCA"
        workbook.save(invalid_path)
    finally:
        workbook.close()

    exit_code, output = run_cli(source_path, config_path, tmp_path / "metrics.jsonl")

    assert exit_code == 2
    assert "Postęp szablonów: 3/3 (100%)" in output
    assert "Ostatnia operacja: Darek Nowak | ZABLOKOWANY" in output
    assert "Ostatnia operacja: Kamil Frontczak | ZLY_SZABLON" in output
    assert "status: OSTRZEŻENIE" in output
    assert "status: BŁĄD" in output
    assert "Pominięte szablony: 2" in output


def test_plain_cli_shows_dry_run_and_does_not_write_szablon_pracownika(tmp_path: Path) -> None:
    source_path, target_directory, config_path = make_fixture(tmp_path)
    metrics_path = tmp_path / "metrics.jsonl"

    exit_code, output = run_cli(source_path, config_path, metrics_path, "--dry-run")

    assert exit_code == 2
    assert "DRY-RUN" in output
    assert "Nic nie zapisano" in output
    assert "Planowane szablony: 2" in output
    assert (target_directory / f"Rozliczenie {PERIOD} - Adrian Maciejewski.xlsx").exists()
    assert "A18" not in output

    record = json.loads(metrics_path.read_text(encoding="utf-8"))
    assert record["mode"] == "DRY-RUN"
    assert record["counters"]["written"] == 0
    assert record["counters"]["planned"] == 2


def test_statistics_are_available_after_five_comparable_runs(tmp_path: Path) -> None:
    source_path, _, config_path = make_fixture(tmp_path)
    metrics_path = tmp_path / "metrics.jsonl"

    for _ in range(5):
        run_cli(source_path, config_path, metrics_path, "--dry-run")

    _, output = run_cli(source_path, config_path, metrics_path, "--dry-run")

    assert "Statystyki DRY-RUN" in output
    assert "P50" in output
    assert "P95" in output
    assert "próbek: 6" in output

    _, run_output = run_cli(source_path, config_path, metrics_path)
    assert "Statystyki RUN" not in run_output


def test_statistics_panel_reports_values_for_both_modes_and_all_phases(tmp_path: Path) -> None:
    source_path, _, config_path = make_fixture(tmp_path)
    metrics_path = tmp_path / "metrics.jsonl"
    phase_durations = {
        "Sprawdzanie": 1000,
        "Odczyt danych": 2000,
        "Planowanie": 3000,
        "Zapisywanie": 4000,
    }

    for mode, total_duration_ms in (("RUN", 100_000), ("DRY-RUN", 200_000)):
        for sample in range(5):
            MetricsStore(metrics_path).append(
                {
                    "schema_version": 1,
                    "started_at": f"2026-09-28T00:00:0{sample}+00:00",
                    "mode": mode,
                    "period": "08_14_09_2026",
                    "completed": True,
                    "result": "OK",
                    "total_duration_ms": total_duration_ms,
                    "phase_durations_ms": phase_durations,
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

    _, output = run_cli(source_path, config_path, metrics_path, "--dry-run")

    assert "Statystyki RUN | próbek: 5" in output
    assert "Statystyki DRY-RUN | próbek: 6" in output
    assert "całe uruchomienie | P50: 100000 ms | P95: 100000 ms" in output
    assert "całe uruchomienie | P50: 200000 ms | P95: 200000 ms" in output
    assert "Sprawdzanie | P50: 1000 ms | P95: 1000 ms" in output
    assert "Odczyt danych | P50: 2000 ms | P95: 2000 ms" in output
    assert "Planowanie | P50: 3000 ms | P95: 3000 ms" in output
    assert "Zapisywanie | P50: 4000 ms | P95: 4000 ms" in output


def test_malformed_history_does_not_change_process_result(tmp_path: Path) -> None:
    source_path, _, config_path = make_fixture(tmp_path)
    metrics_path = tmp_path / "metrics.jsonl"

    for _ in range(5):
        run_cli(source_path, config_path, metrics_path, "--dry-run")
    with metrics_path.open("a", encoding="utf-8") as stream:
        stream.write(
            '{"schema_version":1,"mode":"DRY-RUN","completed":true,'
            '"total_duration_ms":"not-a-duration"}\n'
        )
        stream.write(
            '{"schema_version":1,"mode":[],"completed":true,'
            '"total_duration_ms":1}\n'
        )

    exit_code, output = run_cli(source_path, config_path, metrics_path, "--dry-run")

    assert exit_code == 2
    assert "Wymaga sprawdzenia" in output
    assert "Statystyki DRY-RUN" in output


def test_metrics_failure_is_only_an_observability_warning(tmp_path: Path) -> None:
    source_path, _, config_path = make_fixture(tmp_path)
    metrics_parent = tmp_path / "not-a-directory"
    metrics_parent.write_text("nie katalog", encoding="utf-8")

    exit_code, output = run_cli(source_path, config_path, metrics_parent / "metrics.jsonl")

    assert exit_code == 2
    assert "Nie zapisano metryk" in output
    assert "Wymaga sprawdzenia" in output


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


def test_cancelled_source_selection_shows_critical_dashboard_status(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    metrics_path = tmp_path / "metrics.jsonl"

    def cancel_selection() -> Path:
        raise settlement_engine.SettlementError("Nie wybrano pliku zbiorczego.")

    monkeypatch.setattr("rozliczenia.cli.choose_source_file", cancel_selection)

    output = StringIO()
    exit_code = main(["--metrics", str(metrics_path)], output=output)

    assert exit_code == 1
    assert "Rozliczenia | okres: nieznany | tryb: RUN" in output.getvalue()
    assert "Status semantyczny: BŁĄD" in output.getvalue()
    assert "Czas uruchomienia:" in output.getvalue()
    record = json.loads(metrics_path.read_text(encoding="utf-8"))
    assert record["completed"] is False
    assert record["result"] == "BLAD_KRYTYCZNY"


def test_critical_write_failure_preserves_partial_counters(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source_path, _, config_path = make_fixture(tmp_path)
    metrics_path = tmp_path / "metrics.jsonl"
    original_process_template = template_settlement.process_template
    save_calls = 0

    def fail_on_second_save(
        worker_name: str,
        path: Path,
        rows: Iterable[ExcelRow],
        *,
        dry_run: bool = False,
    ) -> WorkerResult:
        nonlocal save_calls
        save_calls += 1
        if save_calls == 2:
            raise template_settlement.TemplateWriteError("synthetic write failure")
        return original_process_template(worker_name, path, rows, dry_run=dry_run)

    monkeypatch.setattr(template_settlement, "process_template", fail_on_second_save)

    exit_code, output = run_cli(source_path, config_path, metrics_path)

    assert exit_code == 1
    assert "Postęp szablonów: 1/3 (33%)" in output
    assert (
        "Etap przerwany: Zapisywanie | WYKONAWCA: Darek Nowak | "
        "Szablon pracownika: 2/3"
    ) in output
    record = json.loads(metrics_path.read_text(encoding="utf-8"))
    assert record["completed"] is False
    assert record["result"] == "BLAD_KRYTYCZNY"
    assert record["counters"] == {
        "templates_total": 3,
        "templates_completed": 1,
        "rows": 2,
        "written": 1,
        "empty": 0,
        "planned": 0,
        "skipped": 0,
        "issues": 2,
    }

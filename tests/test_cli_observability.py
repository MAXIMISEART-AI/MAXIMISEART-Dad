from __future__ import annotations

from io import StringIO
import json
import os
from pathlib import Path
import subprocess
import sys

from openpyxl import load_workbook
import pytest

from rozliczenia.cli import main
from rozliczenia.telemetry import MetricsStore

from tests.test_settlement_engine import PERIOD, make_fixture


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


def test_metrics_store_rejects_record_with_full_path(tmp_path: Path) -> None:
    source_path, _, config_path = make_fixture(tmp_path)
    metrics_path = tmp_path / "metrics.jsonl"
    run_cli(source_path, config_path, metrics_path)

    record = json.loads(metrics_path.read_text(encoding="utf-8"))
    record["source_path"] = str(source_path)

    with pytest.raises(ValueError):
        MetricsStore(metrics_path).append(record)

    assert metrics_path.read_text(encoding="utf-8").count("\n") == 1


def test_cli_runs_without_rich(tmp_path: Path) -> None:
    source_path, _, config_path = make_fixture(tmp_path)
    metrics_path = tmp_path / "metrics.jsonl"
    environment = os.environ.copy()
    environment["PYTHONPATH"] = str(Path(__file__).parents[1] / "src")
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "import sys; sys.modules['rich'] = None; from rozliczenia.cli import main; raise SystemExit(main())",
            "--source",
            str(source_path),
            "--config",
            str(config_path),
            "--metrics",
            str(metrics_path),
            "--dry-run",
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


def test_plain_cli_completes_progress_for_locked_and_skipped_templates(tmp_path: Path) -> None:
    source_path, target_directory, config_path = make_fixture(tmp_path)
    locked_path = target_directory / f"Rozliczenie {PERIOD} - Darek Nowak.xlsx"
    (target_directory / f"~${locked_path.name}").touch()

    invalid_path = target_directory / f"Rozliczenie {PERIOD} - Kamil Frontczak.xlsx"
    workbook = load_workbook(invalid_path)
    try:
        workbook.active["H17"] = "NIE WYKONAWCA"
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


def test_plain_cli_shows_dry_run_and_does_not_write_worker_templates(tmp_path: Path) -> None:
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

from __future__ import annotations

from io import StringIO
import json
import os
from pathlib import Path
import subprocess
import sys
from typing import Any, TextIO

import pytest

import rozliczenia.cli as cli
from rozliczenia.preparation_cli import default_metrics_path, main
from rozliczenia.telemetry import MetricsStore

from tests.collective_preparation_fixtures import (
    COLLECTIVE_FILE_NAME,
    INTERNAL_SETTLEMENT_NAME,
    PERIOD,
    PreparationFixture,
    make_preparation_fixture,
)

PREPARATION_COUNTERS = {"period_orders", "successful_orders", "skipped_empty_rows", "warnings"}
ORDERS_PER_DAY_LINES = [
    "Zlecenia na dzień:",
    "- wt 08.09.2026: 1",
    "- śr 09.09.2026: 1",
    "- czw 10.09.2026: 0",
    "- pt 11.09.2026: 0",
    "- sob 12.09.2026: 1",
    "- niedz 13.09.2026: 0",
    "- pon 14.09.2026: 1",
]


def metrics_path_for(fixture: PreparationFixture) -> Path:
    return fixture.register_path.parent / "przygotowanie-metrics.jsonl"


def preparation_arguments(fixture: PreparationFixture, *extra_args: str) -> list[str]:
    return [
        "--register",
        str(fixture.register_path),
        "--periods-directory",
        str(fixture.periods_directory),
        "--period",
        PERIOD,
        "--config",
        str(fixture.config_path),
        "--internal-template",
        str(fixture.internal_template_path),
        "--collective-template",
        str(fixture.collective_template_path),
        "--metrics",
        str(metrics_path_for(fixture)),
        *extra_args,
    ]


def run_preparation_cli(fixture: PreparationFixture, *extra_args: str) -> tuple[int, str]:
    output = StringIO()
    exit_code = main(preparation_arguments(fixture, *extra_args), output=output)
    return exit_code, output.getvalue()


def metric_records(fixture: PreparationFixture) -> list[dict[str, Any]]:
    text = metrics_path_for(fixture).read_text(encoding="utf-8")
    return [json.loads(line) for line in text.splitlines()]


def summary_lines(output: str) -> list[str]:
    lines = output.splitlines()
    return lines[lines.index("Status końcowy: OK") :]


def test_cli_creates_both_period_files_and_prints_summary_with_orders_per_day(tmp_path: Path) -> None:
    fixture = make_preparation_fixture(tmp_path)

    exit_code, output = run_preparation_cli(fixture)

    assert exit_code == 0
    lines = summary_lines(output)
    assert lines[0] == "Status końcowy: OK"
    assert lines[1].startswith("Czas uruchomienia: ")
    assert lines[2:] == [
        f"Okres: {PERIOD}",
        "Zlecenia okresu: 4",
        "Zlecenia skuteczne: 3",
        "Pominięte puste wiersze: 3",
        *ORDERS_PER_DAY_LINES,
        "Ostrzeżenia: 0",
        f"Rozliczenie wewnętrzne: {INTERNAL_SETTLEMENT_NAME}",
        f"Plik zbiorczy: {COLLECTIVE_FILE_NAME}",
    ]
    assert fixture.internal_settlement_path.is_file()
    assert fixture.collective_file_path.is_file()
    assert "SYN-" not in output


def test_cli_dashboard_shows_four_stages_in_order_without_szablony_pracownika(tmp_path: Path) -> None:
    fixture = make_preparation_fixture(tmp_path)

    _, output = run_preparation_cli(fixture)

    lines = output.splitlines()
    assert lines[:6] == [
        f"Przygotowanie pliku zbiorczego | okres: {PERIOD} | tryb: RUN",
        "Status: uruchomiono",
        "Etap: Sprawdzanie",
        "Etap: Odczyt danych",
        "Etap: Planowanie",
        "Etap: Zapisywanie",
    ]
    assert "Szablon" not in output
    assert "WYKONAWCA" not in output
    assert "\x1b" not in output


def test_cli_dry_run_shows_plan_with_orders_per_day_and_creates_nothing(tmp_path: Path) -> None:
    fixture = make_preparation_fixture(tmp_path)

    exit_code, output = run_preparation_cli(fixture, "--dry-run")

    assert exit_code == 0
    assert output.splitlines()[0] == f"Przygotowanie pliku zbiorczego | okres: {PERIOD} | tryb: DRY-RUN"
    lines = summary_lines(output)
    assert lines[2:] == [
        f"Okres: {PERIOD}",
        "Zlecenia okresu: 4",
        "Zlecenia skuteczne: 3",
        "Pominięte puste wiersze: 3",
        *ORDERS_PER_DAY_LINES,
        "Ostrzeżenia: 0",
        f"Rozliczenie wewnętrzne: {INTERNAL_SETTLEMENT_NAME}",
        f"Plik zbiorczy: {COLLECTIVE_FILE_NAME}",
        "DRY-RUN: Nic nie zapisano",
    ]
    assert list(fixture.periods_directory.iterdir()) == []
    [record] = metric_records(fixture)
    assert record["mode"] == "DRY-RUN"
    assert record["completed"] is True


def test_cli_stop_shows_co_gdzie_co_zrobic_and_exits_1(tmp_path: Path) -> None:
    fixture = make_preparation_fixture(tmp_path)
    fixture.period_directory.mkdir()
    fixture.collective_file_path.write_bytes(b"reczne poprawki taty")

    exit_code, output = run_preparation_cli(fixture)

    assert exit_code == 1
    lines = output.splitlines()
    stop = lines.index("Status końcowy: ZATRZYMANO")
    assert lines[stop - 1] == "Etap przerwany: Sprawdzanie"
    assert lines[stop + 1].startswith("Co się stało: Plik tego okresu już istnieje")
    assert lines[stop + 2] == f"Gdzie: folder INEA\\{PERIOD}, plik {COLLECTIVE_FILE_NAME}"
    assert lines[stop + 3].startswith("Co zrobić: ")
    assert not fixture.internal_settlement_path.exists()
    assert "SYN-" not in output
    [record] = metric_records(fixture)
    assert record["completed"] is False
    assert record["result"] == "BLAD_KRYTYCZNY"
    assert record["counters"] == dict.fromkeys(PREPARATION_COUNTERS, 0)


def test_cli_unexpected_error_hides_exception_text_and_exits_1(tmp_path: Path) -> None:
    fixture = make_preparation_fixture(tmp_path)
    fixture.register_path.write_bytes(b"to nie jest skoroszyt SYN-001")

    exit_code, output = run_preparation_cli(fixture)

    assert exit_code == 1
    assert "Etap przerwany: Odczyt danych" in output
    assert "Status końcowy: BŁĄD" in output
    assert "Co zrobić: " in output
    assert "SYN-" not in output
    assert "Traceback" not in output
    assert list(fixture.periods_directory.iterdir()) == []


@pytest.mark.parametrize(("extra_args", "mode"), [((), "RUN"), (("--dry-run",), "DRY-RUN")])
def test_cli_writes_safe_metrics_with_preparation_counters(
    tmp_path: Path, extra_args: tuple[str, ...], mode: str
) -> None:
    fixture = make_preparation_fixture(tmp_path)

    run_preparation_cli(fixture, *extra_args)

    [record] = metric_records(fixture)
    assert record["schema_version"] == 1
    assert record["mode"] == mode
    assert record["period"] == PERIOD
    assert record["completed"] is True
    assert record["result"] == "OK"
    assert set(record["phase_durations_ms"]) == {"Sprawdzanie", "Odczyt danych", "Planowanie", "Zapisywanie"}
    assert record["counters"] == {
        "period_orders": 4,
        "successful_orders": 3,
        "skipped_empty_rows": 3,
        "warnings": 0,
    }
    metrics_text = metrics_path_for(fixture).read_text(encoding="utf-8")
    assert "SYN-" not in metrics_text
    assert str(tmp_path) not in metrics_text
    assert MetricsStore(metrics_path_for(fixture)).read() == []


def test_przygotowanie_has_own_metrics_history_next_to_przebieg_rozliczen() -> None:
    assert default_metrics_path().parent == cli.default_metrics_path().parent
    assert default_metrics_path().name == ".przygotowanie-pliku-zbiorczego-metrics.jsonl"


def test_invalid_period_is_recorded_as_unknown_period(tmp_path: Path) -> None:
    fixture = make_preparation_fixture(tmp_path)
    arguments = preparation_arguments(fixture)
    arguments[arguments.index(PERIOD)] = "zly okres"

    exit_code = main(arguments, output=StringIO())

    assert exit_code == 1
    [record] = metric_records(fixture)
    assert record["period"] == "nieznany"
    assert record["result"] == "BLAD_KRYTYCZNY"


def test_statistics_appear_after_five_comparable_przygotowania(tmp_path: Path) -> None:
    fixture = make_preparation_fixture(tmp_path)

    for _ in range(4):
        _, output = run_preparation_cli(fixture, "--dry-run")
    assert "Statystyki" not in output

    _, output = run_preparation_cli(fixture, "--dry-run")

    assert "Statystyki DRY-RUN | próbek: 5" in output
    assert "całe uruchomienie | P50: " in output
    assert "Zapisywanie | P50: " in output
    assert "Statystyki RUN" not in output


def test_terminal_output_failure_does_not_change_result_files_or_exit_code(tmp_path: Path) -> None:
    class FailingOutput(StringIO):
        def write(self, value: str) -> int:
            raise OSError("synthetic output failure")

    fixture = make_preparation_fixture(tmp_path)

    exit_code = main(preparation_arguments(fixture), output=FailingOutput())

    assert exit_code == 0
    assert fixture.internal_settlement_path.is_file()
    assert fixture.collective_file_path.is_file()
    [record] = metric_records(fixture)
    assert record["result"] == "OK"
    assert record["counters"]["period_orders"] == 4


@pytest.mark.parametrize(("extra_args", "mode"), [((), "RUN"), (("--dry-run",), "DRY-RUN")])
def test_cli_runs_without_rich_with_the_same_information(
    tmp_path: Path, extra_args: tuple[str, ...], mode: str
) -> None:
    fixture = make_preparation_fixture(tmp_path)
    environment = os.environ.copy()
    environment["PYTHONPATH"] = str(Path(__file__).parents[1] / "src")

    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "import sys; sys.modules['rich'] = None; "
            "from rozliczenia.preparation_cli import main; raise SystemExit(main())",
            *preparation_arguments(fixture, *extra_args),
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        env={**environment, "PYTHONUTF8": "1"},
    )

    assert result.returncode == 0, result.stderr
    assert f"Przygotowanie pliku zbiorczego | okres: {PERIOD} | tryb: {mode}" in result.stdout
    assert "Etap: Zapisywanie" in result.stdout
    assert "Status końcowy: OK" in result.stdout
    assert "\n".join(ORDERS_PER_DAY_LINES) in result.stdout
    assert f"Plik zbiorczy: {COLLECTIVE_FILE_NAME}" in result.stdout
    assert fixture.collective_file_path.exists() is (mode == "RUN")
    [record] = metric_records(fixture)
    assert record["mode"] == mode


def test_interactive_rich_dashboard_uses_shared_projection_without_szablony_pracownika(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    pytest.importorskip("rich")
    from rich.console import Console as RichConsole

    class TtyOutput(StringIO):
        def isatty(self) -> bool:
            return True

    class FakeConsole:
        color_system = "standard"

        def __init__(self, *, file: TextIO) -> None:
            self.renderer = RichConsole(file=file, color_system=None, width=120)

        def print(self, renderable: Any) -> None:
            self.renderer.print(renderable)

    class FakeLive:
        def __init__(self, renderable: Any, *, console: FakeConsole, **_kwargs: Any) -> None:
            self.console = console

        def start(self, *, refresh: bool) -> None:
            pass

        def update(self, renderable: Any, *, refresh: bool) -> None:
            self.console.print(renderable)

        def stop(self) -> None:
            pass

    monkeypatch.setattr(cli, "Console", FakeConsole)
    monkeypatch.setattr(cli, "Live", FakeLive)
    fixture = make_preparation_fixture(tmp_path)
    output = TtyOutput()

    exit_code = main(preparation_arguments(fixture), output=output)

    assert exit_code == 0
    rendered = output.getvalue()
    assert f"Przygotowanie pliku zbiorczego | {PERIOD} | RUN" in rendered
    assert "Zapisywanie" in rendered
    assert "Szablon" not in rendered
    assert "WYKONAWCA" not in rendered
    assert "\n".join(ORDERS_PER_DAY_LINES) in rendered
    assert "SYN-" not in rendered

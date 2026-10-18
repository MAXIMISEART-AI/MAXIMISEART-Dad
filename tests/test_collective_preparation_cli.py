from __future__ import annotations

from datetime import date, datetime, timedelta
from io import StringIO
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import types
from typing import Any, NoReturn, TextIO

import pytest

from rozliczenia import collective_preparation, preparation_register
import rozliczenia.cli as cli
import rozliczenia.process_run as process_run
from rozliczenia.plain_progress import PlainProgressAdapter
from rozliczenia.preparation_cli import default_metrics_path, main
from rozliczenia.telemetry import MetricsStore

from tests.collective_preparation_fixtures import (
    COLLECTIVE_FILE_NAME,
    COLLECTIVE_TEMPLATE_ZERO_ROWS,
    INTERNAL_SETTLEMENT_NAME,
    PERIOD,
    PreparationFixture,
    RegisterRow,
    make_preparation_fixture,
    register_order,
)

DETACHED_OBSERVER_NOTICE = "Podgląd postępu przestał się aktualizować; wynik nie zależy od tego."
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
        "Pominięte puste wiersze: 5",
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
        "Pominięte puste wiersze: 5",
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


def test_summary_failure_after_period_files_were_written_says_they_exist(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fixture = make_preparation_fixture(tmp_path)
    prepare = collective_preparation.prepare_collective_file

    def prepare_with_unprintable_summary(*args: Any, **kwargs: Any) -> Any:
        summary = prepare(*args, **kwargs)
        summary.orders_per_day = {"SYN-001": 1}  # type: ignore[dict-item]  # podsumowanie, którego nie da się pokazać
        return summary

    monkeypatch.setattr(collective_preparation, "prepare_collective_file", prepare_with_unprintable_summary)

    exit_code, output = run_preparation_cli(fixture)

    assert exit_code == 1
    lines = output.splitlines()
    status = lines.index("Status końcowy: BŁĄD")
    assert lines[status + 1 : status + 4] == [
        "Co się stało: Pliki okresu powstały, ale nie udało się pokazać podsumowania.",
        "Gdzie: Przygotowanie pliku zbiorczego",
        "Co zrobić: Sprawdź Folder okresu i przekaż ten komunikat osobie utrzymującej narzędzie.",
    ]
    assert lines[status + 4].startswith("Czas uruchomienia: ")
    assert "Nie utworzono żadnego pliku" not in output
    assert "SYN-" not in output
    assert "Traceback" not in output
    assert fixture.internal_settlement_path.is_file()
    assert fixture.collective_file_path.is_file()
    [record] = metric_records(fixture)
    assert (record["completed"], record["result"]) == (False, "BLAD_KRYTYCZNY")
    assert record["counters"] == dict.fromkeys(PREPARATION_COUNTERS, 0)


def test_cli_unexpected_error_hides_exception_text_and_exits_1(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fixture = make_preparation_fixture(tmp_path)

    def fail_unexpectedly(*args: object, **kwargs: object) -> NoReturn:
        raise RuntimeError("nieprzewidziany błąd przy SYN-001")

    # Uszkodzony Rejestr jest już typowanym zatrzymaniem, więc błąd nieprzewidziany jest wstrzyknięty w Odczyt danych.
    monkeypatch.setattr(preparation_register, "read_register", fail_unexpectedly)

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
        "skipped_empty_rows": 5,
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


@pytest.mark.parametrize("observer_fails", [False, True], ids=["bez-awarii", "awaria-obserwatora"])
@pytest.mark.parametrize(
    ("interrupted", "expected_exit_code", "expected_result"),
    [(False, 0, "OK"), (True, 1, "BLAD_KRYTYCZNY")],
    ids=["sukces", "przerwanie"],
)
def test_detached_observer_is_reported_by_one_line_at_the_end_of_przygotowanie_pliku_zbiorczego(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    observer_fails: bool,
    interrupted: bool,
    expected_exit_code: int,
    expected_result: str,
) -> None:
    def fail_progress_update(*_args: object) -> NoReturn:
        raise RuntimeError("synthetic adapter failure")

    if observer_fails:
        monkeypatch.setattr(PlainProgressAdapter, "update", fail_progress_update)
    fixture = make_preparation_fixture(tmp_path)
    if interrupted:
        fixture.period_directory.mkdir()
        fixture.collective_file_path.write_bytes(b"reczne poprawki taty")

    exit_code, output = run_preparation_cli(fixture)

    assert exit_code == expected_exit_code
    [record] = metric_records(fixture)
    assert record["result"] == expected_result
    assert fixture.internal_settlement_path.is_file() is not interrupted
    if observer_fails:
        assert output.splitlines()[-1] == DETACHED_OBSERVER_NOTICE
        assert output.count(DETACHED_OBSERVER_NOTICE) == 1
        assert "synthetic adapter failure" not in output
        assert "SYN-" not in output
    else:
        assert DETACHED_OBSERVER_NOTICE not in output


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


class TtyOutput(StringIO):
    def isatty(self) -> bool:
        return True


def install_fake_rich(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """Rich renderuje do zwykłego tekstu; zwraca dziennik startów i zatrzymań widoku na żywo."""

    pytest.importorskip("rich")
    from rich.console import Console as RichConsole

    live_log: list[str] = []

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
            live_log.append("start")

        def update(self, renderable: Any, *, refresh: bool) -> None:
            self.console.print(renderable)

        def stop(self) -> None:
            live_log.append("stop")

    monkeypatch.setattr(process_run, "Console", FakeConsole)
    monkeypatch.setattr(process_run, "Live", FakeLive)
    return live_log


def test_interactive_rich_dashboard_uses_shared_projection_without_szablony_pracownika(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    install_fake_rich(monkeypatch)
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


def test_rich_dashboard_pauses_for_incomplete_period_question_and_resumes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    live_log = install_fake_rich(monkeypatch)
    fixture = incomplete_period_fixture(tmp_path)
    output = TtyOutput()

    exit_code = main(preparation_arguments(fixture), output=output, input_stream=StringIO("t\n"))

    assert exit_code == 0
    assert live_log == ["start", "stop", "start", "stop"]
    rendered = output.getvalue()
    after_question = rendered[rendered.index("Kontynuować mimo niepełnego okresu?") :]
    assert "Zapisywanie" in after_question
    assert "Etap: Zapisywanie" not in rendered.splitlines()  # bez przejścia na widok liniowy
    assert fixture.collective_file_path.is_file()


def test_cli_shows_zero_rows_warning_in_summary_and_exits_0(tmp_path: Path) -> None:
    rows: list[RegisterRow] = [
        register_order(number, datetime(2026, 9, 14, 8, number))
        for number in range(1, COLLECTIVE_TEMPLATE_ZERO_ROWS + 2)
    ]
    fixture = make_preparation_fixture(tmp_path, rows)

    exit_code, output = run_preparation_cli(fixture)

    assert exit_code == 0
    lines = summary_lines(output)
    warnings = lines.index("Ostrzeżenia: 1")
    assert lines[warnings + 1 : warnings + 4] == [
        "- Co się stało: Zleceń skutecznych: 7, wierszy przygotowanych zerami we Wzorcu pliku zbiorczego: 6. "
        "Dolne wiersze Pliku zbiorczego nie mają zer w kolumnach ilości.",
        f"  Gdzie: plik {COLLECTIVE_FILE_NAME}, wiersz 24",
        "  Co zrobić: Uzupełnij ilości w tych wierszach ręcznie. Jeśli zdarza się to często, przekaż to "
        "osobie utrzymującej narzędzie, żeby dodała wiersze z zerami we Wzorcu pliku zbiorczego.",
    ]
    assert lines[warnings + 4] == f"Rozliczenie wewnętrzne: {INTERNAL_SETTLEMENT_NAME}"
    assert fixture.collective_file_path.is_file()
    [record] = metric_records(fixture)
    assert record["result"] == "OK"
    assert record["counters"]["warnings"] == 1
    assert "SYN-" not in output


def without_option(arguments: list[str], option: str) -> list[str]:
    index = arguments.index(option)
    return arguments[:index] + arguments[index + 2 :]


def run_cli_asking_for_period(
    fixture: PreparationFixture, answers: str, *extra_args: str, today: date = date(2026, 9, 16)
) -> tuple[int, str]:
    output = StringIO()
    arguments = without_option(preparation_arguments(fixture, *extra_args), "--period")
    exit_code = main(arguments, output=output, input_stream=StringIO(answers), today=today)
    return exit_code, output.getvalue()


@pytest.mark.parametrize("today", [date(2026, 9, 15) + timedelta(days=offset) for offset in range(7)])
def test_enter_confirms_proposed_last_full_period_on_every_weekday(tmp_path: Path, today: date) -> None:
    fixture = make_preparation_fixture(tmp_path)

    exit_code, output = run_cli_asking_for_period(fixture, "\n", today=today)

    assert exit_code == 0
    assert "Proponowany okres: 08_14_09_2026 (wtorek 08.09.2026 – poniedziałek 14.09.2026)" in output
    assert f"Przygotowanie pliku zbiorczego | okres: {PERIOD} | tryb: RUN" in output
    assert fixture.internal_settlement_path.is_file()
    assert fixture.collective_file_path.is_file()


def _proposals_around_boundary(
    before: str, crossing: str, after: str, crossing_monday: date
) -> list[tuple[date, str, date]]:
    """Propozycja w każdym dniu od poniedziałku kończącego okres na przełomie do wtorku tydzień później."""

    week = timedelta(days=7)
    return [
        (crossing_monday, before, crossing_monday - week),  # poniedziałek: okres na przełomie trwa
        *[(crossing_monday + timedelta(days=offset), crossing, crossing_monday) for offset in range(1, 8)],
        (crossing_monday + week + timedelta(days=1), after, crossing_monday + week),
    ]


@pytest.mark.parametrize(
    ("today", "proposed", "monday"),
    [
        # Na przełomie miesięcy i lat token ma miesiąc i rok wtorku.
        *_proposals_around_boundary("20_26_10_2026", "27_02_10_2026", "03_09_11_2026", date(2026, 11, 2)),
        *_proposals_around_boundary("22_28_12_2026", "29_04_12_2026", "05_11_01_2027", date(2027, 1, 4)),
    ],
)
def test_proposed_period_at_month_and_year_boundary_names_folder_okresu(
    tmp_path: Path, today: date, proposed: str, monday: date
) -> None:
    fixture = make_preparation_fixture(tmp_path, [register_order(1, datetime(monday.year, monday.month, monday.day, 12))])

    exit_code, output = run_cli_asking_for_period(fixture, "\n", today=today)

    assert exit_code == 0, output
    assert f"Proponowany okres: {proposed} " in output
    assert (fixture.periods_directory / proposed / f"Rozliczenie {proposed} - zbiorcze.xlsx").is_file()


def test_typed_period_replaces_proposed_one(tmp_path: Path) -> None:
    fixture = make_preparation_fixture(tmp_path)

    exit_code, output = run_cli_asking_for_period(fixture, " 01_07_09_2026 \n")

    assert exit_code == 0
    assert "Przygotowanie pliku zbiorczego | okres: 01_07_09_2026 | tryb: RUN" in output
    assert (fixture.periods_directory / "01_07_09_2026" / "Rozliczenie 01_07_09_2026 - zbiorcze.xlsx").is_file()
    assert not fixture.period_directory.exists()


def test_invalid_typed_period_is_rejected_with_message_and_asked_again(tmp_path: Path) -> None:
    fixture = make_preparation_fixture(tmp_path)

    exit_code, output = run_cli_asking_for_period(fixture, "15_21_09_2025\n27_02_11_2026\n\n")

    assert exit_code == 0
    assert output.count("Co się stało: Okres nie ma postaci dd_dd_mm_rrrr od wtorku do poniedziałku.") == 2
    assert "Gdzie: okres '15_21_09_2025'" in output
    assert "Gdzie: okres '27_02_11_2026'" in output
    assert "Na przełomie miesięcy miesiąc i rok są z wtorku, np. 27_02_10_2026" in output
    assert sorted(path.name for path in fixture.periods_directory.iterdir()) == [PERIOD]
    assert fixture.collective_file_path.is_file()


def test_rejected_period_without_another_answer_stops_without_writing(tmp_path: Path) -> None:
    fixture = make_preparation_fixture(tmp_path)

    exit_code, output = run_cli_asking_for_period(fixture, "okres\n")

    assert exit_code == 1
    lines = output.splitlines()
    stop = lines.index("Status końcowy: ZATRZYMANO")
    assert lines[stop + 1] == "Co się stało: Nie potwierdzono okresu ani nie wpisano innego. Nie utworzono żadnego pliku."
    assert "Przygotowanie pliku zbiorczego | okres: nieznany | tryb: RUN" in output
    assert list(fixture.periods_directory.iterdir()) == []
    [record] = metric_records(fixture)
    assert (record["period"], record["completed"], record["result"]) == ("nieznany", False, "BLAD_KRYTYCZNY")


def install_dialogs(monkeypatch: pytest.MonkeyPatch, *, file: str, directory: str) -> list[str]:
    """Zastępuje okna wyboru tkinter; zwraca tytuły pokazanych okien."""

    shown: list[str] = []

    class FakeRoot:
        def withdraw(self) -> None:
            pass

        def destroy(self) -> None:
            pass

    def askopenfilename(*, title: str, **_kwargs: object) -> str:
        shown.append(title)
        return file

    def askdirectory(*, title: str, **_kwargs: object) -> str:
        shown.append(title)
        return directory

    filedialog = types.ModuleType("tkinter.filedialog")
    setattr(filedialog, "askopenfilename", askopenfilename)
    setattr(filedialog, "askdirectory", askdirectory)
    tk_module = types.ModuleType("tkinter")
    setattr(tk_module, "Tk", FakeRoot)
    setattr(tk_module, "filedialog", filedialog)
    monkeypatch.setitem(sys.modules, "tkinter", tk_module)
    monkeypatch.setitem(sys.modules, "tkinter.filedialog", filedialog)
    return shown


def arguments_without_paths(fixture: PreparationFixture) -> list[str]:
    return without_option(without_option(preparation_arguments(fixture), "--register"), "--periods-directory")


def test_rejestr_and_folder_okresow_are_chosen_in_dialogs_one_after_another(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fixture = make_preparation_fixture(tmp_path)
    shown = install_dialogs(monkeypatch, file=str(fixture.register_path), directory=str(fixture.periods_directory))

    exit_code = main(arguments_without_paths(fixture), output=StringIO())

    assert exit_code == 0
    assert shown == ["Wybierz plik Rejestru zleceń", "Wybierz folder okresów (np. INEA)"]
    assert fixture.internal_settlement_path.is_file()
    assert fixture.collective_file_path.is_file()


@pytest.mark.parametrize(
    ("cancelled", "expected_what"),
    [
        ("file", "Nie wybrano pliku Rejestru zleceń. Nie utworzono żadnego pliku."),
        ("directory", "Nie wybrano folderu okresów. Nie utworzono żadnego pliku."),
    ],
)
def test_cancelled_dialog_stops_with_message_and_writes_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, cancelled: str, expected_what: str
) -> None:
    fixture = make_preparation_fixture(tmp_path)
    install_dialogs(
        monkeypatch,
        file="" if cancelled == "file" else str(fixture.register_path),
        directory="" if cancelled == "directory" else str(fixture.periods_directory),
    )
    output = StringIO()

    exit_code = main(arguments_without_paths(fixture), output=output)

    assert exit_code == 1
    lines = output.getvalue().splitlines()
    stop = lines.index("Status końcowy: ZATRZYMANO")
    assert lines[stop + 1] == f"Co się stało: {expected_what}"
    assert lines[stop + 3].startswith("Co zrobić: Uruchom ponownie")
    assert list(fixture.periods_directory.iterdir()) == []
    [record] = metric_records(fixture)
    assert (record["completed"], record["result"]) == (False, "BLAD_KRYTYCZNY")


def incomplete_period_fixture(tmp_path: Path) -> PreparationFixture:
    """Okres 08_14_09_2026, w którym ostatnie zlecenie jest z soboty."""

    rows: list[RegisterRow] = [
        register_order(1, datetime(2026, 9, 8, 8, 0)),
        None,
        register_order(2, datetime(2026, 9, 9, 10, 0), successful="nie"),
        register_order(3, datetime(2026, 9, 12, 12, 0)),
    ]
    return make_preparation_fixture(tmp_path, rows)


INCOMPLETE_ORDERS_PER_DAY_LINES = [
    "Zlecenia na dzień:",
    "- wt 08.09.2026: 1",
    "- śr 09.09.2026: 1",
    "- czw 10.09.2026: 0",
    "- pt 11.09.2026: 0",
    "- sob 12.09.2026: 1",
    "- niedz 13.09.2026: 0",
    "- pon 14.09.2026: 0",
]


def run_cli_answering(fixture: PreparationFixture, answers: str, *extra_args: str) -> tuple[int, str]:
    output = StringIO()
    exit_code = main(preparation_arguments(fixture, *extra_args), output=output, input_stream=StringIO(answers))
    return exit_code, output.getvalue()


def test_incomplete_period_shows_orders_per_day_and_refusal_writes_nothing(tmp_path: Path) -> None:
    fixture = incomplete_period_fixture(tmp_path)

    exit_code, output = run_cli_answering(fixture, "n\n")

    assert exit_code == 1
    lines = output.splitlines()
    warning = lines.index("Ostrzeżenie: niepełny okres")
    assert lines[warning + 1].startswith("Co się stało: Ostatnie zlecenie okresu jest z soboty 12.09.2026")
    assert lines[warning + 4 : warning + 12] == INCOMPLETE_ORDERS_PER_DAY_LINES
    assert lines[warning + 12].startswith("Kontynuować mimo niepełnego okresu?")
    stop = lines.index("Status końcowy: ZATRZYMANO")
    assert lines[stop + 1] == (
        "Co się stało: Przerwano z powodu niepełnego okresu, zgodnie z odpowiedzią. Nie utworzono żadnego pliku."
    )
    assert lines[stop + 2] == f"Gdzie: okres {PERIOD}"
    assert list(fixture.periods_directory.iterdir()) == []
    assert "SYN-" not in output
    [record] = metric_records(fixture)
    assert (record["period"], record["completed"], record["result"]) == (PERIOD, False, "BLAD_KRYTYCZNY")


@pytest.mark.parametrize("answers", ["\n", "", "nie\n", "x\n"])
def test_anything_but_yes_to_incomplete_period_is_refusal(tmp_path: Path, answers: str) -> None:
    fixture = incomplete_period_fixture(tmp_path)

    exit_code, _ = run_cli_answering(fixture, answers)

    assert exit_code == 1
    assert list(fixture.periods_directory.iterdir()) == []


@pytest.mark.parametrize("answer", ["t", " TAK "])
def test_yes_to_incomplete_period_creates_both_files_and_exits_0(tmp_path: Path, answer: str) -> None:
    fixture = incomplete_period_fixture(tmp_path)

    exit_code, output = run_cli_answering(fixture, f"{answer}\n")

    assert exit_code == 0
    assert fixture.internal_settlement_path.is_file()
    assert fixture.collective_file_path.is_file()
    lines = summary_lines(output)
    assert "Ostrzeżenia: 1" in lines
    assert lines[lines.index("Ostrzeżenia: 1") + 1].startswith("- Co się stało: Ostatnie zlecenie okresu")
    [record] = metric_records(fixture)
    assert (record["result"], record["counters"]["warnings"]) == ("OK", 1)


def test_dry_run_of_incomplete_period_does_not_ask_and_shows_warning_in_plan(tmp_path: Path) -> None:
    fixture = incomplete_period_fixture(tmp_path)

    exit_code, output = run_cli_answering(fixture, "", "--dry-run")

    assert exit_code == 0
    assert "Kontynuować" not in output
    lines = summary_lines(output)
    assert lines[lines.index("Ostrzeżenia: 1") + 1].startswith("- Co się stało: Ostatnie zlecenie okresu")
    assert "DRY-RUN: Nic nie zapisano" in lines
    assert list(fixture.periods_directory.iterdir()) == []


def test_stop_found_before_question_is_shown_once_on_dashboard(tmp_path: Path) -> None:
    fixture = incomplete_period_fixture(tmp_path)
    fixture.period_directory.mkdir()
    fixture.internal_settlement_path.write_bytes(b"reczne poprawki taty")

    exit_code, output = run_cli_answering(fixture, "")

    assert exit_code == 1
    assert "Kontynuować" not in output
    assert output.count("Co się stało: Plik tego okresu już istnieje") == 1
    assert "Etap przerwany: Sprawdzanie" in output


def test_incomplete_period_question_follows_planowanie_on_one_dashboard(tmp_path: Path) -> None:
    fixture = incomplete_period_fixture(tmp_path)

    exit_code, output = run_cli_answering(fixture, "t\n")

    assert exit_code == 0
    lines = output.splitlines()
    question = next(index for index, line in enumerate(lines) if line.startswith("Kontynuować"))
    assert lines[: lines.index("Ostrzeżenie: niepełny okres")] == [
        f"Przygotowanie pliku zbiorczego | okres: {PERIOD} | tryb: RUN",
        "Status: uruchomiono",
        "Etap: Sprawdzanie",
        "Etap: Odczyt danych",
        "Etap: Planowanie",
    ]
    assert lines[question + 1] == "Etap: Zapisywanie"
    assert output.count("Przygotowanie pliku zbiorczego | okres:") == 1


def test_refused_incomplete_period_ends_after_planowanie_without_zapisywanie(tmp_path: Path) -> None:
    fixture = incomplete_period_fixture(tmp_path)

    exit_code, output = run_cli_answering(fixture, "n\n")

    assert exit_code == 1
    assert "Etap: Planowanie" in output
    assert "Zapisywanie" not in output
    [record] = metric_records(fixture)
    assert record["phase_durations_ms"]["Zapisywanie"] == 0


class SlowAnswer(StringIO):
    """Tata odpowiada po chwili namysłu."""

    def readline(self, size: int | None = -1, /) -> str:  # type: ignore[override]  # typeshed: _IOBase -> bytes
        time.sleep(1.5)
        return super().readline()


def test_time_waiting_for_answer_is_not_counted_in_metrics(tmp_path: Path) -> None:
    fixture = incomplete_period_fixture(tmp_path)
    output = StringIO()

    exit_code = main(preparation_arguments(fixture), output=output, input_stream=SlowAnswer("t\n"))

    assert exit_code == 0
    [record] = metric_records(fixture)
    assert record["total_duration_ms"] < 1500
    # Każdy etap i czas uruchomienia są zaokrąglane do ms osobno: margines 1 ms na etap.
    phase_durations = record["phase_durations_ms"].values()
    assert sum(phase_durations) <= record["total_duration_ms"] + len(phase_durations)
    reported = next(line for line in output.getvalue().splitlines() if line.startswith("Czas uruchomienia: "))
    assert int(reported.removeprefix("Czas uruchomienia: ").removesuffix(" ms")) < 1500

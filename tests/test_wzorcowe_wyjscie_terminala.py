"""Wzorcowe wyjście terminala obu procesów: każde zakończenie porównane z plikiem w repo.

Każdy scenariusz uruchamia CLI Przebiegu rozliczeń (``rozliczenia.cli``) albo
Przygotowania pliku zbiorczego (``rozliczenia.preparation_cli``) na
syntetycznych danych i porównuje pełne wyjście terminala z plikiem
``tests/golden/terminal/<scenariusz>.txt``. Przed porównaniem test zamienia
wartości niedeterministyczne na stałe: folder tymczasowy testu na ``<TMP>``
(z ``/`` jako separatorem do końca linii) i każdą liczbę milisekund na
``<N> ms``.

Zmiana tekstu terminala jest świadomą zmianą pliku wzorcowego w tym samym
commicie. Pliki odświeża się poleceniem::

    UPDATE_GOLDEN=1 .venv/bin/python -m pytest tests/test_wzorcowe_wyjscie_terminala.py

(w PowerShell: ``$env:UPDATE_GOLDEN=1; py -3 -m pytest tests/test_wzorcowe_wyjscie_terminala.py``),
a potem przegląda ``git diff tests/golden/terminal`` przed commitem. Bez tej
zmiennej brak pliku wzorcowego albo każda różnica to błąd testu.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass, replace
from datetime import date
from io import StringIO
import os
from pathlib import Path
import re
from typing import Any, NoReturn, cast

import pytest

from rozliczenia import collective_file, collective_preparation, preparation_register
from rozliczenia import cli as settlement_cli
from rozliczenia import preparation_cli
from rozliczenia.domain import Issue, SettlementSummary, WorkerResult
import rozliczenia.engine as settlement_engine
import rozliczenia.template_settlement as template_settlement
from rozliczenia.workbook_files import ExcelRow, WorkerSettlementTemplate

from tests.fixtures.preparation import incomplete_period_fixture, make_preparation_fixture
from tests.fixtures.settlement import append_completed_records, make_fixture, make_preview_fixture
from tests.fixtures.terminal import (
    install_source_dialog,
    preparation_arguments,
    run_cli,
    run_cli_answering,
    run_cli_asking_for_period,
    run_preparation_cli,
)

GOLDEN_DIRECTORY = Path(__file__).resolve().parent / "golden" / "terminal"
MILLISECONDS = re.compile(r"\d+ ms\b")

Scenario = Callable[[Path, pytest.MonkeyPatch], tuple[int, str]]


@dataclass(frozen=True)
class Ending:
    """Jedno zakończenie procesu w terminalu: scenariusz i oczekiwany kod wyjścia."""

    run: Scenario
    exit_code: int


def normalized(output: str, tmp_path: Path) -> str:
    """Wyjście bez wartości zależnych od maszyny i czasu."""

    lines: list[str] = []
    roots = sorted({str(tmp_path), str(tmp_path.resolve())}, key=len, reverse=True)
    for line in output.splitlines():
        for root in roots:
            if root in line:
                head, tail = line.split(root, 1)
                line = f"{head}<TMP>{tail.replace(os.sep, '/')}"
                break
        lines.append(MILLISECONDS.sub("<N> ms", line))
    return "\n".join(lines) + "\n"


# Przebieg rozliczeń


def _settlement(*extra_args: str, fixture: Callable[[Path], tuple[Path, Path, Path]] = make_fixture) -> Scenario:
    def scenario(tmp_path: Path, _monkeypatch: pytest.MonkeyPatch) -> tuple[int, str]:
        source_path, _, config_path = fixture(tmp_path)
        return run_cli(source_path, config_path, tmp_path / "metrics.jsonl", *extra_args)

    return scenario


def _settlement_ok_with_statistics(tmp_path: Path, _monkeypatch: pytest.MonkeyPatch) -> tuple[int, str]:
    source_path, _, config_path = make_fixture(tmp_path)
    metrics_path = tmp_path / "metrics.jsonl"
    append_completed_records(metrics_path, "RUN")
    return run_cli(source_path, config_path, metrics_path)


def _settlement_folder_exists(tmp_path: Path, _monkeypatch: pytest.MonkeyPatch) -> tuple[int, str]:
    source_path, target_directory, config_path = make_fixture(tmp_path)
    target_directory.mkdir()
    return run_cli(source_path, config_path, tmp_path / "metrics.jsonl")


def _settlement_unreadable_collective_file(tmp_path: Path, _monkeypatch: pytest.MonkeyPatch) -> tuple[int, str]:
    source_path, _, config_path = make_fixture(tmp_path)
    source_path.write_bytes(b"uszkodzony")
    return run_cli(source_path, config_path, tmp_path / "metrics.jsonl")


def _settlement_missing_worker_template(tmp_path: Path, _monkeypatch: pytest.MonkeyPatch) -> tuple[int, str]:
    source_path, _, config_path = make_fixture(tmp_path)
    (tmp_path / "Wzorzec rozliczenia pracownika.xlsx").rename(tmp_path / "placeholder.xlsx")
    return run_cli(source_path, config_path, tmp_path / "metrics.jsonl")


def _settlement_collective_file_not_selected(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[int, str]:
    install_source_dialog(monkeypatch, selected="")
    output = StringIO()
    exit_code = settlement_cli.main(["--metrics", str(tmp_path / "metrics.jsonl")], output=output)
    return exit_code, output.getvalue()


def _settlement_worker_file_failed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[int, str]:
    original = template_settlement.process_template
    calls = 0

    def fail_on_second_template(
        worker_name: str, template: WorkerSettlementTemplate, path: Path, rows: Iterable[ExcelRow]
    ) -> WorkerResult:
        nonlocal calls
        calls += 1
        if calls == 2:
            raise RuntimeError("nieprzewidziany błąd przy SYN-001")
        return original(worker_name, template, path, rows)

    monkeypatch.setattr(template_settlement, "process_template", fail_on_second_template)
    return _settlement()(tmp_path, monkeypatch)


def _settlement_unexpected_failure(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[int, str]:
    def fail_unexpectedly(*args: object, **kwargs: object) -> NoReturn:
        raise RuntimeError("nieprzewidziany błąd przy SYN-001")

    # Nieczytelny Plik zbiorczy jest typowanym zatrzymaniem, więc błąd nieprzewidziany jest wstrzyknięty w Odczyt danych.
    monkeypatch.setattr(collective_file, "read_data_rows", fail_unexpectedly)
    return _settlement()(tmp_path, monkeypatch)


def _settlement_unprintable_summary(*extra_args: str) -> Scenario:
    def scenario(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[int, str]:
        run_settlements = settlement_engine.run_settlements

        def run_with_unprintable_summary(*args: Any, **kwargs: Any) -> SettlementSummary:
            return replace(run_settlements(*args, **kwargs), issues=[cast(Issue, "SYN-001")])

        monkeypatch.setattr(settlement_engine, "run_settlements", run_with_unprintable_summary)
        return _settlement(*extra_args)(tmp_path, monkeypatch)

    return scenario


def _settlement_metrics_not_saved(tmp_path: Path, _monkeypatch: pytest.MonkeyPatch) -> tuple[int, str]:
    source_path, _, config_path = make_fixture(tmp_path)
    not_a_directory = tmp_path / "nie-katalog"
    not_a_directory.write_text("nie katalog", encoding="utf-8")
    return run_cli(source_path, config_path, not_a_directory / "metrics.jsonl")


# Przygotowanie pliku zbiorczego


def _preparation(*extra_args: str) -> Scenario:
    def scenario(tmp_path: Path, _monkeypatch: pytest.MonkeyPatch) -> tuple[int, str]:
        return run_preparation_cli(make_preparation_fixture(tmp_path), *extra_args)

    return scenario


def _preparation_period_file_exists(tmp_path: Path, _monkeypatch: pytest.MonkeyPatch) -> tuple[int, str]:
    fixture = make_preparation_fixture(tmp_path)
    fixture.period_directory.mkdir()
    fixture.collective_file_path.write_bytes(b"reczne poprawki taty")
    return run_preparation_cli(fixture)


def _preparation_period_not_entered(tmp_path: Path, _monkeypatch: pytest.MonkeyPatch) -> tuple[int, str]:
    return run_cli_asking_for_period(make_preparation_fixture(tmp_path), "okres\n", today=date(2026, 9, 16))


def _preparation_unexpected_failure(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[int, str]:
    def fail_unexpectedly(*args: object, **kwargs: object) -> NoReturn:
        raise RuntimeError("nieprzewidziany błąd przy SYN-001")

    monkeypatch.setattr(preparation_register, "read_register", fail_unexpectedly)
    return _preparation()(tmp_path, monkeypatch)


def _preparation_unprintable_summary(*extra_args: str) -> Scenario:
    def scenario(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[int, str]:
        prepare = collective_preparation.prepare_collective_file

        def prepare_with_unprintable_summary(*args: Any, **kwargs: Any) -> Any:
            summary = prepare(*args, **kwargs)
            summary.orders_per_day = {"SYN-001": 1}  # type: ignore[dict-item]  # podsumowanie, którego nie da się pokazać
            return summary

        monkeypatch.setattr(collective_preparation, "prepare_collective_file", prepare_with_unprintable_summary)
        return _preparation(*extra_args)(tmp_path, monkeypatch)

    return scenario


def _preparation_incomplete_period(answers: str) -> Scenario:
    def scenario(tmp_path: Path, _monkeypatch: pytest.MonkeyPatch) -> tuple[int, str]:
        return run_cli_answering(incomplete_period_fixture(tmp_path), answers)

    return scenario


def _preparation_metrics_not_saved(tmp_path: Path, _monkeypatch: pytest.MonkeyPatch) -> tuple[int, str]:
    fixture = make_preparation_fixture(tmp_path)
    not_a_directory = tmp_path / "nie-katalog"
    not_a_directory.write_text("nie katalog", encoding="utf-8")
    arguments = preparation_arguments(fixture)
    arguments[arguments.index("--metrics") + 1] = str(not_a_directory / "metrics.jsonl")
    output = StringIO()
    exit_code = preparation_cli.main(arguments, output=output)
    return exit_code, output.getvalue()


ENDINGS: dict[str, Ending] = {
    "przebieg-ok-ze-statystykami": Ending(_settlement_ok_with_statistics, 0),
    "przebieg-wymaga-sprawdzenia-dry-run": Ending(_settlement("--dry-run", fixture=make_preview_fixture), 2),
    "przebieg-zatrzymanie-folder-istnieje": Ending(_settlement_folder_exists, 1),
    "przebieg-zatrzymanie-nieczytelny-plik-zbiorczy": Ending(_settlement_unreadable_collective_file, 1),
    "przebieg-zatrzymanie-brak-wzorca": Ending(_settlement_missing_worker_template, 1),
    "przebieg-zatrzymanie-wykonawca-bez-mapowania": Ending(_settlement(fixture=make_preview_fixture), 1),
    "przebieg-zatrzymanie-nie-wybrano-pliku": Ending(_settlement_collective_file_not_selected, 1),
    "przebieg-zatrzymanie-blad-szablonu-pracownika": Ending(_settlement_worker_file_failed, 1),
    "przebieg-nieoczekiwany-blad": Ending(_settlement_unexpected_failure, 1),
    "przebieg-blad-po-silniku-podsumowanie-run": Ending(_settlement_unprintable_summary(), 1),
    "przebieg-blad-po-silniku-plan-dry-run": Ending(_settlement_unprintable_summary("--dry-run"), 1),
    "przebieg-nieudany-zapis-metryk": Ending(_settlement_metrics_not_saved, 0),
    "przygotowanie-ok": Ending(_preparation(), 0),
    "przygotowanie-ok-dry-run": Ending(_preparation("--dry-run"), 0),
    "przygotowanie-zatrzymanie-plik-okresu-istnieje": Ending(_preparation_period_file_exists, 1),
    "przygotowanie-zatrzymanie-nie-potwierdzono-okresu": Ending(_preparation_period_not_entered, 1),
    "przygotowanie-nieoczekiwany-blad": Ending(_preparation_unexpected_failure, 1),
    "przygotowanie-blad-po-silniku-podsumowanie-run": Ending(_preparation_unprintable_summary(), 1),
    "przygotowanie-blad-po-silniku-plan-dry-run": Ending(_preparation_unprintable_summary("--dry-run"), 1),
    "przygotowanie-niepelny-okres-zgoda": Ending(_preparation_incomplete_period("t\n"), 0),
    "przygotowanie-niepelny-okres-odmowa": Ending(_preparation_incomplete_period("n\n"), 1),
    "przygotowanie-nieudany-zapis-metryk": Ending(_preparation_metrics_not_saved, 0),
}


@pytest.mark.parametrize("name", ENDINGS)
def test_wyjscie_terminala_zgadza_sie_z_plikiem_wzorcowym(
    name: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    ending = ENDINGS[name]
    exit_code, output = ending.run(tmp_path, monkeypatch)
    actual = normalized(output, tmp_path)
    golden = GOLDEN_DIRECTORY / f"{name}.txt"

    if os.environ.get("UPDATE_GOLDEN") == "1":
        golden.parent.mkdir(parents=True, exist_ok=True)
        golden.write_text(actual, encoding="utf-8", newline="\n")

    assert exit_code == ending.exit_code
    assert golden.is_file(), f"Brak pliku wzorcowego {golden.name}; utwórz go przez UPDATE_GOLDEN=1."
    assert actual == golden.read_text(encoding="utf-8")


def test_kazdy_plik_wzorcowy_ma_scenariusz() -> None:
    assert sorted(path.stem for path in GOLDEN_DIRECTORY.glob("*.txt")) == sorted(ENDINGS)

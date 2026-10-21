"""Przebieg rozliczeń i Przygotowanie pliku zbiorczego przez rdzeń Uruchomienia procesu (``run_process``)."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
import json
from pathlib import Path
from typing import Any

import pytest

from rozliczenia import preparation_process, settlement_process
from rozliczenia.preparation_process import PreparationInputs
from rozliczenia.process_run import Outcome, Process, ProcessInputs, Stop, run_process
from rozliczenia.settlement_process import SettlementInputs
from rozliczenia.telemetry import MetricsStore

from tests.fixtures.fake_process import fail
from tests.fixtures.interlocutor import Tata
from tests.fixtures.preparation import make_preparation_fixture
from tests.fixtures.settlement import NOT_A_PERIOD, PERIOD, make_fixture

PHASES = {"Sprawdzanie", "Odczyt danych", "Planowanie", "Zapisywanie"}


@dataclass(frozen=True)
class ProcessCase:
    process: Process[Any, Any]
    inputs: Callable[[bool], ProcessInputs]
    period_files: tuple[Path, ...]
    client_data_markers: tuple[str, ...]


def settlement(tmp_path: Path, *, period: str = PERIOD) -> ProcessCase:
    source, target_directory, config = make_fixture(tmp_path, period=period)
    worker_template = config.parent / "Wzorzec rozliczenia pracownika.xlsx"
    return ProcessCase(
        process=settlement_process.PROCESS,
        inputs=lambda dry_run: SettlementInputs(source, dry_run, config, worker_template),
        period_files=(target_directory,),
        client_data_markers=("syntetyczny adres", "#1"),
    )


def preparation(tmp_path: Path, *, period: str = PERIOD) -> ProcessCase:
    fixture = make_preparation_fixture(tmp_path)
    return ProcessCase(
        process=preparation_process.PROCESS,
        inputs=lambda dry_run: PreparationInputs(
            fixture.register_path,
            fixture.periods_directory,
            period,
            dry_run,
            fixture.config_path,
            fixture.internal_template_path,
            fixture.collective_template_path,
        ),
        period_files=(fixture.internal_settlement_path, fixture.collective_file_path),
        client_data_markers=("SYN-",),
    )


CASES = {"przebieg-rozliczen": settlement, "przygotowanie-pliku-zbiorczego": preparation}


def summary_view(_inputs: ProcessInputs, summary: object) -> object:
    return summary


def run(
    case: ProcessCase,
    metrics_path: Path,
    *,
    dry_run: bool = False,
    view: Callable[[Any, Any], object] = summary_view,
) -> Outcome[object]:
    return run_process(case.process, case.inputs(dry_run), Tata(), view=view, metrics_path=metrics_path)


@pytest.mark.parametrize("dry_run", [False, True], ids=["RUN", "DRY-RUN"])
@pytest.mark.parametrize("name", CASES)
def test_podsumowanie_ktorego_nie_da_sie_pokazac_konczy_zatrzymaniem_a_pliki_okresu_sa_tylko_po_uruchom(
    tmp_path: Path, name: str, dry_run: bool
) -> None:
    case = CASES[name](tmp_path)

    outcome = run(case, tmp_path / "metrics.jsonl", dry_run=dry_run, view=fail)

    not_shown = case.process.plan_not_shown if dry_run else case.process.summary_not_shown
    assert outcome.ending == Stop("after_engine", not_shown)
    assert [path.exists() for path in case.period_files] == [not dry_run] * len(case.period_files)


SETTLEMENT_COUNTERS = {
    "templates_total": 3,
    "templates_completed": 3,
    "rows": 3,
    "written": 2,
    "empty": 1,
    "planned": 0,
    "skipped": 0,
    "issues": 0,
}
PREPARATION_COUNTERS = {"period_orders": 4, "successful_orders": 3, "skipped_empty_rows": 5, "warnings": 0}


@pytest.mark.parametrize(
    ("name", "dry_run", "counters"),
    [
        ("przebieg-rozliczen", False, SETTLEMENT_COUNTERS),
        ("przebieg-rozliczen", True, SETTLEMENT_COUNTERS | {"written": 0, "planned": 2}),
        ("przygotowanie-pliku-zbiorczego", False, PREPARATION_COUNTERS),
        ("przygotowanie-pliku-zbiorczego", True, PREPARATION_COUNTERS),
    ],
    ids=["przebieg-RUN", "przebieg-DRY-RUN", "przygotowanie-RUN", "przygotowanie-DRY-RUN"],
)
def test_rekord_metryk_ma_liczniki_procesu_bez_sciezek_i_danych_klientow(
    tmp_path: Path, name: str, dry_run: bool, counters: dict[str, int]
) -> None:
    case = CASES[name](tmp_path)
    metrics_path = tmp_path / "metrics.jsonl"

    outcome = run(case, metrics_path, dry_run=dry_run)

    assert (outcome.result, outcome.metrics_saved) == ("OK", True)
    metrics_text = metrics_path.read_text(encoding="utf-8")
    [line] = metrics_text.splitlines()
    record = json.loads(line)
    assert (record["mode"], record["period"], record["completed"], record["result"]) == (
        "DRY-RUN" if dry_run else "RUN",
        PERIOD,
        True,
        "OK",
    )
    assert record["counters"] == counters
    assert set(record["phase_durations_ms"]) == PHASES
    assert str(tmp_path) not in metrics_text
    assert [marker for marker in case.client_data_markers if marker in metrics_text] == []
    assert MetricsStore(metrics_path, case.process.counter_names).read() == [record]


@pytest.mark.parametrize(
    ("name", "period", "code"),
    [
        ("przebieg-rozliczen", NOT_A_PERIOD, "ZLY_PLIK_ZBIORCZY"),
        ("przygotowanie-pliku-zbiorczego", "zly okres", "ZLY_TOKEN_OKRESU"),
    ],
)
def test_okres_ktorego_nie_da_sie_ustalic_trafia_do_metryk_jako_nieznany(
    tmp_path: Path, name: str, period: str, code: str
) -> None:
    case = CASES[name](tmp_path, period=period)

    outcome = run(case, tmp_path / "metrics.jsonl")

    assert isinstance(outcome.ending, Stop)
    assert (outcome.ending.kind, outcome.ending.message.code) == ("stop", code)
    [record] = MetricsStore(tmp_path / "metrics.jsonl", case.process.counter_names).read()
    assert (record["period"], record["completed"], record["result"]) == ("nieznany", False, "BLAD_KRYTYCZNY")
    assert record["counters"] == dict.fromkeys(case.process.counter_names, 0)

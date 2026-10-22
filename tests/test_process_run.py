"""Rdzeń Uruchomienia procesu (``run_process``) na sztucznym procesie w pamięci, z rozmówcą testowym.

Sztuczny proces jest trzecim adapterem seamu ``Process``, obok Przebiegu
rozliczeń i Przygotowania pliku zbiorczego.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
import time
from typing import NoReturn

import pytest

from rozliczenia.decision import Conversation
from rozliczenia.domain import ProgressObserver
from rozliczenia.phase_runner import PhaseRunner
from rozliczenia.process_run import Finished, Outcome, Process, Stop, run_process

from tests.fixtures.fake_process import (
    ENDINGS,
    METRICS_WARNING,
    PERIOD,
    Durations,
    Inputs,
    asking_between_planning_and_saving,
    fail,
    fake_process,
    records,
    stop_error,
)
from tests.fixtures.interlocutor import Tata


def durations_view(_inputs: Inputs, durations: Durations) -> Durations:
    return durations


def run_core(
    process: Process[Inputs, Durations],
    metrics_path: Path,
    *,
    dry_run: bool = False,
    tata: Tata | None = None,
    view: Callable[[Inputs, Durations], Durations] = durations_view,
) -> Outcome[Durations]:
    return run_process(process, Inputs(dry_run=dry_run), tata or Tata(), view=view, metrics_path=metrics_path)


@pytest.mark.parametrize("dry_run", [False, True], ids=["RUN", "DRY-RUN"])
def test_core_closes_every_ending_with_a_message(tmp_path: Path, dry_run: bool) -> None:
    own = stop_error("Brak pliku.")

    def stop_in_engine(_inputs: Inputs, _observer: ProgressObserver, _conversation: Conversation) -> NoReturn:
        raise own

    endings: dict[str, tuple[Process[Inputs, Durations], Callable[[Inputs, Durations], Durations]]] = {
        "stop": (fake_process(execute=stop_in_engine), durations_view),
        "unexpected": (fake_process(execute=fail), durations_view),
        "after_engine": (fake_process(finished=fail), durations_view),
        "view": (fake_process(), fail),
    }

    seen = {
        name: run_core(process, tmp_path / "metrics.jsonl", dry_run=dry_run, view=view)
        for name, (process, view) in endings.items()
    }

    not_shown = ENDINGS["plan_not_shown" if dry_run else "summary_not_shown"]
    assert {
        name: (outcome.ending.kind, outcome.ending.message, outcome.view)
        for name, outcome in seen.items()
        if isinstance(outcome.ending, Stop)
    } == {
        "stop": ("stop", own.message, None),
        "unexpected": ("unexpected", ENDINGS["unexpected_failure"], None),
        "after_engine": ("after_engine", not_shown, None),
        "view": ("after_engine", not_shown, None),
    }
    assert [
        (record["result"], record["completed"], record["counters"]) for record in records(tmp_path / "metrics.jsonl")
    ] == [("BLAD_KRYTYCZNY", False, {"items": 0})] * 4


def test_zatrzymanie_zapisuje_rekord_z_okresem_zerowymi_licznikami_i_czasami_etapow_ktore_sie_wykonaly(
    tmp_path: Path,
) -> None:
    checking_ms = 50

    def stop_in_reading(_inputs: Inputs, observer: ProgressObserver, _conversation: Conversation) -> NoReturn:
        phases = PhaseRunner(observer)
        phases.check(lambda: time.sleep(checking_ms / 1000))

        def read() -> NoReturn:
            raise stop_error("Brak pliku.")

        phases.read(read)
        raise AssertionError("Odczyt danych miał zatrzymać proces.")

    outcome = run_core(fake_process(execute=stop_in_reading), tmp_path / "metrics.jsonl")

    assert isinstance(outcome.ending, Stop)
    assert outcome.ending.kind == "stop"
    [record] = records(tmp_path / "metrics.jsonl")
    assert (record["period"], record["completed"], record["result"], record["counters"]) == (
        PERIOD,
        False,
        "BLAD_KRYTYCZNY",
        {"items": 0},
    )
    durations = record["phase_durations_ms"]
    assert durations["Sprawdzanie"] >= checking_ms
    assert (durations["Planowanie"], durations["Zapisywanie"]) == (0, 0)


def test_nieudany_zapis_metryk_to_tylko_ostrzezenie_bez_zmiany_wyniku_procesu(tmp_path: Path) -> None:
    not_a_directory = tmp_path / "nie-katalog"
    not_a_directory.write_text("nie katalog", encoding="utf-8")

    saved = run_core(fake_process(), tmp_path / "metrics.jsonl")
    unsaved = run_core(fake_process(), not_a_directory / "metrics.jsonl")

    assert (saved.metrics_saved, saved.notices) == (True, ())
    assert (unsaved.metrics_saved, unsaved.notices) == (False, (METRICS_WARNING,))
    assert isinstance(unsaved.ending, Finished)
    assert (unsaved.result, unsaved.ending.counters) == ("OK", {"items": 1})
    assert unsaved.view == unsaved.ending.phase_durations_ms


@pytest.mark.parametrize("interrupted_at", ["w-silniku", "przy-decyzji-taty"])
def test_przerwanie_przechodzi_przez_rdzen(tmp_path: Path, interrupted_at: str) -> None:
    def interrupt() -> NoReturn:
        raise KeyboardInterrupt

    def interrupted(_inputs: Inputs, _observer: ProgressObserver, _conversation: Conversation) -> NoReturn:
        interrupt()

    if interrupted_at == "w-silniku":
        process, tata = fake_process(execute=interrupted), Tata()
    else:
        process, tata = fake_process(execute=asking_between_planning_and_saving), Tata(before_answer=interrupt)

    with pytest.raises(KeyboardInterrupt):
        run_core(process, tmp_path / "metrics.jsonl", tata=tata)


def test_czas_decyzji_taty_nie_liczy_sie_do_czasu_uruchomienia(tmp_path: Path) -> None:
    pause_s = 1.0
    tata = Tata(before_answer=lambda: time.sleep(pause_s))

    outcome = run_core(fake_process(execute=asking_between_planning_and_saving), tmp_path / "metrics.jsonl", tata=tata)

    assert outcome.result == "OK"
    assert len(tata.decisions) == 1
    assert outcome.total_duration_ms < pause_s * 1000
    [record] = records(tmp_path / "metrics.jsonl")
    assert record["total_duration_ms"] == outcome.total_duration_ms

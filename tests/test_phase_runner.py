from __future__ import annotations

import time

import pytest

from rozliczenia.domain import ProgressEvent, ProgressEventFactory, ProgressPhase, ProgressState
from rozliczenia.phase_runner import PhaseRunner


def test_etap_zglasza_start_i_koniec_oraz_mierzy_czas() -> None:
    events: list[ProgressEvent] = []
    runner = PhaseRunner(events.append)

    result = runner.run(ProgressPhase.CHECKING, lambda: "sprawdzono")

    assert result == "sprawdzono"
    assert [(event.phase, event.state) for event in events] == [
        (ProgressPhase.CHECKING, ProgressState.START),
        (ProgressPhase.CHECKING, ProgressState.END),
    ]
    assert events[-1].phase_elapsed_ms == runner.phase_durations_ms[ProgressPhase.CHECKING]


def test_przerwany_etap_zglasza_failed_raz_i_przekazuje_wyjatek() -> None:
    events: list[ProgressEvent] = []
    runner = PhaseRunner(events.append)

    def fail() -> None:
        raise RuntimeError("syntetyczny błąd")

    with pytest.raises(RuntimeError):
        runner.run(ProgressPhase.READING, fail)

    def fail_after_reporting() -> None:
        runner.notify(
            ProgressEventFactory.worker_failed(
                "Wykonawca",
                template_index=1,
                template_total=1,
                elapsed_ms=runner.elapsed_ms(),
                phase_elapsed_ms=0,
            )
        )
        raise RuntimeError("syntetyczny błąd")

    with pytest.raises(RuntimeError):
        runner.run(ProgressPhase.SAVING, fail_after_reporting)

    assert [(event.phase, event.state, event.worker_name) for event in events] == [
        (ProgressPhase.READING, ProgressState.START, None),
        (ProgressPhase.READING, ProgressState.FAILED, None),
        (ProgressPhase.SAVING, ProgressState.START, None),
        (ProgressPhase.SAVING, ProgressState.FAILED, "Wykonawca"),
    ]
    assert set(runner.phase_durations_ms) == {ProgressPhase.READING, ProgressPhase.SAVING}


def test_uszkodzony_obserwator_jest_odlaczany_bez_wplywu_na_etap() -> None:
    calls: list[ProgressEvent] = []

    def broken_observer(event: ProgressEvent) -> None:
        calls.append(event)
        raise RuntimeError("syntetyczna awaria obserwatora")

    runner = PhaseRunner(broken_observer)

    assert runner.run(ProgressPhase.PLANNING, lambda: 3) == 3
    assert runner.run(ProgressPhase.SAVING, lambda: 4, template_total=2) == 4
    assert [(event.phase, event.state) for event in calls] == [
        (ProgressPhase.PLANNING, ProgressState.START),
    ]
    assert set(runner.phase_durations_ms) == {ProgressPhase.PLANNING, ProgressPhase.SAVING}


def test_etap_dziala_bez_obserwatora() -> None:
    runner = PhaseRunner(None)

    assert runner.run(ProgressPhase.CHECKING, lambda: "ok") == "ok"
    assert ProgressPhase.CHECKING in runner.phase_durations_ms


def test_czas_wstrzymania_miedzy_etapami_nie_wlicza_sie_do_czasu_uruchomienia() -> None:
    events: list[ProgressEvent] = []
    runner = PhaseRunner(events.append)
    runner.run(ProgressPhase.PLANNING, lambda: None)

    with runner.paused():
        time.sleep(0.3)
    runner.run(ProgressPhase.SAVING, lambda: None)

    assert runner.elapsed_ms() < 300
    assert max(event.elapsed_ms or 0 for event in events) < 300

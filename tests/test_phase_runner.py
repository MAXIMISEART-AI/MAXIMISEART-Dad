"""Sekwencer etapów: tylko zachowanie, którego poprawne procesy nie mogą wywołać.

Pełne przebiegi z prawdziwą projekcją postępu jako obserwatorem są w testach
Przebiegu rozliczeń i Przygotowania pliku zbiorczego.
"""

from __future__ import annotations

from collections.abc import Callable

import pytest

from rozliczenia.domain import PhaseFailed, PlanReady, ProgressEvent, ProgressProtocolError
from rozliczenia.phase_runner import PhaseRunner


def fail() -> None:
    raise RuntimeError("syntetyczny błąd")


def run_whole(runner: PhaseRunner) -> None:
    runner.check(lambda: None)
    runner.read(lambda: None)
    runner.plan(lambda: None)
    runner.save(lambda: None)


def run_check(runner: PhaseRunner) -> None:
    runner.check(lambda: None)


def fail_check(runner: PhaseRunner) -> None:
    with pytest.raises(RuntimeError):
        runner.check(fail)


@pytest.mark.parametrize(
    ("before", "stage"),
    [
        (lambda runner: None, "read"),
        (run_check, "check"),
        (run_whole, "save"),
        (run_whole, "check"),
        (fail_check, "read"),
        (fail_check, "check"),
    ],
    ids=[
        "przed-sprawdzaniem",
        "ponowiony",
        "po-zapisywaniu",
        "od-nowa-po-zapisywaniu",
        "po-failed",
        "ponowiony-po-failed",
    ],
)
def test_etap_poza_kolejnoscia_jest_bledem_kodu_przed_uruchomieniem_operacji(
    before: Callable[[PhaseRunner], None], stage: str
) -> None:
    runner = PhaseRunner(None)
    before(runner)
    calls: list[str] = []

    with pytest.raises(ProgressProtocolError):
        getattr(runner, stage)(lambda: calls.append(stage))

    assert calls == []


def test_etap_uruchomiony_w_trakcie_poprzedniego_jest_bledem_kodu() -> None:
    runner = PhaseRunner(None)
    calls: list[str] = []

    with pytest.raises(ProgressProtocolError):
        runner.check(lambda: runner.read(lambda: calls.append("odczyt")))

    assert calls == []


def test_pominieta_liczba_problemow_w_planowaniu_przenosi_wartosc_z_odczytu_danych() -> None:
    events: list[ProgressEvent] = []
    runner = PhaseRunner(events.append)

    runner.check(lambda: None)
    runner.read(lambda: ["problem", "problem"], issue_count=len)
    runner.plan(lambda: ["Adrian Testowy", "Darek Fikcyjny", "Kamil Syntetyczny"], templates=lambda names: names)

    plan_ready = [event for event in events if isinstance(event, PlanReady)]
    assert [(event.issue_count, event.template_total) for event in plan_ready] == [(2, 3)]


def test_wstrzymanie_zegara_w_trakcie_etapu_jest_bledem_kodu() -> None:
    runner = PhaseRunner(None)

    def pause_inside_stage() -> None:
        with runner.paused():
            pass

    with pytest.raises(ProgressProtocolError):
        runner.check(pause_inside_stage)


def run_until_plan(runner: PhaseRunner) -> None:
    runner.check(lambda: None)
    runner.read(lambda: None)
    runner.plan(lambda: None, templates=lambda result: ["Adrian Testowy", "Darek Fikcyjny"])


def settled_outside_saving(runner: PhaseRunner) -> None:
    runner.each_template(lambda worker_name: pytest.fail("Szablon pracownika poza Zapisywaniem."))


@pytest.mark.parametrize("stage", ["check", "read", "plan"])
def test_przetworzenie_szablonow_pracownika_w_innym_etapie_niz_zapisywanie_jest_bledem_kodu(stage: str) -> None:
    runner = PhaseRunner(None)
    if stage != "check":
        runner.check(lambda: None)
    if stage == "plan":
        runner.read(lambda: None)

    with pytest.raises(ProgressProtocolError):
        getattr(runner, stage)(lambda: settled_outside_saving(runner))


def test_przetworzenie_szablonow_pracownika_poza_trwajacym_zapisywaniem_jest_bledem_kodu() -> None:
    runner = PhaseRunner(None)
    run_until_plan(runner)

    with pytest.raises(ProgressProtocolError):
        settled_outside_saving(runner)


@pytest.mark.parametrize(
    ("read_issue_count", "plan_issue_count", "next_stage"),
    [(2, 1, "save"), (-1, None, "plan")],
    ids=["malejaca-liczba-problemow", "ujemna-liczba-problemow"],
)
def test_niepoprawna_liczba_konczy_etap_przerwaniem_i_bledem_kodu(
    read_issue_count: int, plan_issue_count: int | None, next_stage: str
) -> None:
    runner = PhaseRunner(None)
    runner.check(lambda: None)

    with pytest.raises(ProgressProtocolError):
        runner.read(lambda: None, issue_count=lambda result: read_issue_count)
        runner.plan(lambda: None, issue_count=None if plan_issue_count is None else lambda result: plan_issue_count)

    calls: list[str] = []
    with pytest.raises(ProgressProtocolError):
        getattr(runner, next_stage)(lambda: calls.append(next_stage))
    assert calls == []


def test_zapisywanie_bez_szablonow_pracownika_z_planu_jest_bledem_kodu() -> None:
    events: list[ProgressEvent] = []
    runner = PhaseRunner(events.append)
    run_until_plan(runner)

    with pytest.raises(ProgressProtocolError):
        runner.save(lambda: None)

    assert isinstance(events[-1], PhaseFailed)

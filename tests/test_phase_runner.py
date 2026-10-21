"""Sekwencer etapów: tylko zachowanie, którego poprawne procesy nie mogą wywołać.

Pełne przebiegi z prawdziwą projekcją postępu jako obserwatorem są w testach
Przebiegu rozliczeń i Przygotowania pliku zbiorczego.
"""

from __future__ import annotations

from collections.abc import Callable

import pytest

from rozliczenia.domain import (
    IssueCountReady,
    PhaseFailed,
    PlanReady,
    ProgressEvent,
    ProgressProtocolError,
    WorkerEnded,
    WorkerEvent,
    WorkerFailed,
    WorkerStarted,
)
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
    runner.plan(lambda: 3, template_total=lambda total: total)

    plan_ready = [event for event in events if isinstance(event, PlanReady)]
    assert [(event.issue_count, event.template_total) for event in plan_ready] == [(2, 3)]


def test_wstrzymanie_zegara_w_trakcie_etapu_jest_bledem_kodu() -> None:
    runner = PhaseRunner(None)

    def pause_inside_stage() -> None:
        with runner.paused():
            pass

    with pytest.raises(ProgressProtocolError):
        runner.check(pause_inside_stage)


def worker_started(runner: PhaseRunner, index: int = 1, name: str = "Wykonawca") -> WorkerStarted:
    return WorkerStarted(name, template_index=index, template_total=2, elapsed_ms=runner.elapsed_ms())


def worker_ended(runner: PhaseRunner, index: int = 1, name: str = "Wykonawca") -> WorkerEnded:
    return WorkerEnded(
        name,
        template_index=index,
        template_total=2,
        status="ZAPISANO",
        rows=1,
        elapsed_ms=runner.elapsed_ms(),
        issue_count=0,
    )


def worker_failed(runner: PhaseRunner, index: int = 1, name: str = "Wykonawca") -> WorkerFailed:
    return WorkerFailed(
        name, template_index=index, template_total=2, elapsed_ms=runner.elapsed_ms(), phase_elapsed_ms=0
    )


def run_until_plan(runner: PhaseRunner) -> None:
    runner.check(lambda: None)
    runner.read(lambda: None)
    runner.plan(lambda: None, template_total=lambda result: 2)


def test_zdarzenie_przebiegu_etapu_zgloszone_przez_proces_zamiast_sekwencera_jest_bledem_kodu() -> None:
    runner = PhaseRunner(None)
    run_until_plan(runner)

    def notify_phase_event() -> None:
        runner.notify(IssueCountReady(elapsed_ms=runner.elapsed_ms(), issue_count=1))  # type: ignore[arg-type]

    with pytest.raises(ProgressProtocolError):
        runner.save(notify_phase_event)


@pytest.mark.parametrize("stage", ["check", "read", "plan"])
def test_zdarzenie_przetworzenia_szablonu_pracownika_w_innym_etapie_niz_zapisywanie_jest_bledem_kodu(stage: str) -> None:
    runner = PhaseRunner(None)
    if stage != "check":
        runner.check(lambda: None)
    if stage == "plan":
        runner.read(lambda: None)

    with pytest.raises(ProgressProtocolError):
        getattr(runner, stage)(lambda: runner.notify(worker_started(runner)))


def test_zdarzenie_przetworzenia_szablonu_pracownika_poza_trwajacym_zapisywaniem_jest_bledem_kodu() -> None:
    runner = PhaseRunner(None)
    run_until_plan(runner)

    with pytest.raises(ProgressProtocolError):
        runner.notify(worker_started(runner))


@pytest.mark.parametrize(
    ("read_issue_count", "plan_issue_count", "template_total", "next_stage"),
    [(2, 1, 0, "save"), (-1, None, 0, "plan"), (0, None, -1, "save")],
    ids=["malejaca-liczba-problemow", "ujemna-liczba-problemow", "ujemna-liczba-szablonow"],
)
def test_niepoprawna_liczba_konczy_etap_przerwaniem_i_bledem_kodu(
    read_issue_count: int, plan_issue_count: int | None, template_total: int, next_stage: str
) -> None:
    runner = PhaseRunner(None)
    runner.check(lambda: None)

    with pytest.raises(ProgressProtocolError):
        runner.read(lambda: None, issue_count=lambda result: read_issue_count)
        runner.plan(
            lambda: None,
            template_total=lambda result: template_total,
            issue_count=None if plan_issue_count is None else lambda result: plan_issue_count,
        )

    calls: list[str] = []
    with pytest.raises(ProgressProtocolError):
        getattr(runner, next_stage)(lambda: calls.append(next_stage))
    assert calls == []


@pytest.mark.parametrize(
    "notify",
    [
        lambda runner: [worker_started(runner, index=2)],
        lambda runner: [worker_started(runner), worker_started(runner, index=2)],
        lambda runner: [worker_ended(runner)],
        lambda runner: [worker_started(runner), worker_ended(runner, name="Inny Wykonawca")],
        lambda runner: [worker_started(runner), worker_failed(runner, index=2)],
        lambda runner: [
            WorkerStarted("Wykonawca", template_index=1, template_total=3, elapsed_ms=runner.elapsed_ms())
        ],
    ],
    ids=[
        "pominiety-szablon",
        "drugi-przed-zakonczeniem-pierwszego",
        "zakonczenie-bez-rozpoczecia",
        "zakonczenie-innego-wykonawcy",
        "przerwanie-innego-szablonu",
        "inna-liczba-szablonow-niz-plan",
    ],
)
def test_zdarzenia_szablonow_pracownika_poza_kolejnoscia_sa_bledem_kodu(
    notify: Callable[[PhaseRunner], list[WorkerEvent]],
) -> None:
    runner = PhaseRunner(None)
    run_until_plan(runner)

    def save() -> None:
        for event in notify(runner):
            runner.notify(event)

    with pytest.raises(ProgressProtocolError):
        runner.save(save)


def test_zapisywanie_konczy_sie_dopiero_po_wszystkich_szablonach_pracownika_z_planu() -> None:
    events: list[ProgressEvent] = []
    runner = PhaseRunner(events.append)
    run_until_plan(runner)

    def save_one_of_two() -> None:
        runner.notify(worker_started(runner))
        runner.notify(worker_ended(runner))

    with pytest.raises(ProgressProtocolError):
        runner.save(save_one_of_two)

    assert isinstance(events[-1], PhaseFailed)

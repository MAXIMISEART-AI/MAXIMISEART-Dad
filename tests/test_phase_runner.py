"""Sekwencer etapów: tylko zachowanie, którego poprawne procesy nie mogą wywołać.

Pełne przebiegi z prawdziwą projekcją postępu jako obserwatorem są w testach
Przebiegu rozliczeń i Przygotowania pliku zbiorczego.
"""

from __future__ import annotations

import time

import pytest

from rozliczenia.domain import ProgressEvent, ProgressProtocolError, ProgressState
from rozliczenia.phase_runner import PhaseRunner


def test_etap_poza_kolejnoscia_jest_bledem_kodu_przed_uruchomieniem_operacji() -> None:
    runner = PhaseRunner(None)
    calls: list[str] = []

    with pytest.raises(ProgressProtocolError):
        runner.read(lambda: calls.append("odczyt"))

    assert calls == []


def test_pominieta_liczba_problemow_w_planowaniu_przenosi_wartosc_z_odczytu_danych() -> None:
    events: list[ProgressEvent] = []
    runner = PhaseRunner(events.append)

    runner.check(lambda: None)
    runner.read(lambda: ["problem", "problem"], issue_count=len)
    runner.plan(lambda: 3, template_total=lambda total: total)

    plan_ready = [event for event in events if event.state is ProgressState.PLAN_READY]
    assert [(event.issue_count, event.template_total) for event in plan_ready] == [(2, 3)]


def test_czas_wstrzymania_miedzy_planowaniem_a_zapisywaniem_nie_wlicza_sie_do_czasu_uruchomienia() -> None:
    runner = PhaseRunner(None)
    runner.check(lambda: None)
    runner.read(lambda: None)
    runner.plan(lambda: None)

    with runner.paused():
        time.sleep(0.3)
    runner.save(lambda: None)

    assert runner.elapsed_ms() < 300

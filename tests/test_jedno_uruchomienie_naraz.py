"""Jedno Uruchomienie procesu naraz i brak zamknięcia Centrum rozliczeń w trakcie pracy, w każdym przeplocie w zakresie.

Kolejność kroków dwóch kart, Decyzji taty, wątku Uruchomienia i zamknięcia serwera
jest poza zasięgiem testów przez API, więc sprawdza ją wyczerpująco skrypt skilla
``verify-jedno-uruchomienie-naraz`` na prawdziwych ``RunHost`` i ``Shutdown``.
Zakres, znane ustalenia i postępowanie przy porażce opisuje
``.agents/skills/verify-jedno-uruchomienie-naraz/SKILL.md``.
"""

from __future__ import annotations

import importlib.util
import sys
import threading
import time
from pathlib import Path
from types import ModuleType

import pytest

EXPLORER = (
    Path(__file__).resolve().parents[1]
    / ".agents"
    / "skills"
    / "verify-jedno-uruchomienie-naraz"
    / "scripts"
    / "explore_runs.py"
)


def _load_explorer() -> ModuleType:
    spec = importlib.util.spec_from_file_location("explore_runs", EXPLORER)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_centrum_prowadzi_jedno_uruchomienie_naraz_i_nie_zamyka_sie_w_trakcie_w_kazdym_przeplocie() -> None:
    explorer = _load_explorer()

    outcome = explorer.summarize([explorer.explore(scope) for scope in explorer.SCOPES.values()])

    assert outcome.exit_code == 0, "\n".join(outcome.lines)


def test_sprawdzenie_przeplotow_prowadzi_watki_modelu_bez_watkow_systemu(monkeypatch: pytest.MonkeyPatch) -> None:
    """Czas sprawdzenia nie zależy od tego, jak zajęte są procesory runnera (#565).

    Wątek systemu na każdy wątek modelu oddawał sterowanie przez jądro przy każdym kroku, a na runnerze CI zajętym
    innymi workerami xdist sprawdzenie dochodziło do limitu 120 s pytest.
    """

    explorer = _load_explorer()
    started: list[str] = []
    start = threading.Thread.start
    checking = {threading.current_thread()}

    def counted(thread: threading.Thread) -> None:
        # Wątki tła zostawione przez wcześniejsze testy w tym workerze startują swoje wątki same; liczy się tylko to,
        # co uruchomiło sprawdzenie, także z wątku, który samo uruchomiło.
        if threading.current_thread() in checking:
            checking.add(thread)
            started.append(thread.name)
        start(thread)

    monkeypatch.setattr(threading.Thread, "start", counted)

    report = explorer.explore(explorer.SCOPES["zamknij-w-trakcie"])

    assert report.runs_ended and report.clean_closes
    # Jeden wątek systemu na całe sprawdzenie: biegną na nim wątki modelu, a wywołujący patrzy z zewnątrz, czy robią kroki.
    assert len(started) == 1, started


def test_watek_modelu_czekajacy_poza_modelem_konczy_sprawdzenie_luka_modelu_z_nazwa_i_krokiem(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Prawdziwa blokada poza modelem zatrzymuje jedyny wątek systemu sprawdzenia (#651).

    Bez straży sprawdzenie wisiało do limitu 120 s pytest, z tym samym objawem co flaky test z #565. Krótkie czekania,
    razem dłuższe niż limit, nie są zawieszeniem: limit liczy się od ostatniego kroku, nie od startu sprawdzenia.
    """

    explorer = _load_explorer()
    monkeypatch.setattr(explorer, "STALL_SECONDS", 1.0)
    held = threading.Lock()
    held.acquire()
    start = explorer.runs.RunHost.start
    calls: list[object] = []

    def waiting(host: object, prepared: object) -> object:
        calls.append(prepared)
        if len(calls) <= 6:
            time.sleep(0.25)
            return start(host, prepared)
        with held:
            return start(host, prepared)

    monkeypatch.setattr(explorer.runs.RunHost, "start", waiting)

    report = explorer.explore(explorer.SCOPES["zamknij-w-trakcie"])

    [gap] = report.gaps
    assert gap.startswith("karta Uruchom 1: po kroku „żądanie POST /api/runs dociera do serwera” wątek modelu")
    assert "(with held:)" in gap
    assert explorer.summarize([report]).lines[-1].startswith("URUCHOMIENIA: LUKA MODELU")
    # Kolejne testy tego workera używają Centrum z prawdziwym threading.
    assert explorer.runs.threading is threading
    # Wątek, który doczekał się po porzuceniu, kończy się na następnym kroku i nie zmienia już raportu.
    schedules = report.schedules
    checker = next(thread for thread in threading.enumerate() if thread.name == "sprawdzenie przeplotów")
    held.release()
    checker.join(timeout=30)
    assert not checker.is_alive()
    assert report.schedules == schedules


def test_nieoczekiwany_blad_kodu_pod_sprawdzeniem_przerywa_sprawdzenie(monkeypatch: pytest.MonkeyPatch) -> None:
    explorer = _load_explorer()

    def broken(host: object, prepared: object) -> object:
        raise LookupError("start zepsuty w teście")

    monkeypatch.setattr(explorer.runs.RunHost, "start", broken)

    with pytest.raises(LookupError, match="start zepsuty w teście"):
        explorer.explore(explorer.SCOPES["zamknij-w-trakcie"])

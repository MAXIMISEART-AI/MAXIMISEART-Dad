"""Publikacja plików okresu w Przygotowaniu pliku zbiorczego we wszystkich harmonogramach w zakresie.

Przerwanie procesu, błąd systemu plików, drugie Uruchomienie procesu i działanie
taty między krokami publikacji są poza zasięgiem testów przez
``prepare_collective_file()``, więc sprawdza je wyczerpująco skrypt skilla
``verify-publikacja-plikow-okresu`` na prawdziwym ``preparation_files.py``.
Zakres, znane ustalenia i postępowanie przy porażce opisuje
``.agents/skills/verify-publikacja-plikow-okresu/SKILL.md``.
"""

from __future__ import annotations

import importlib.util
import sys
import threading
from pathlib import Path
from types import ModuleType

import pytest

EXPLORER = (
    Path(__file__).resolve().parents[1]
    / ".agents"
    / "skills"
    / "verify-publikacja-plikow-okresu"
    / "scripts"
    / "explore_publication.py"
)


def _load_explorer() -> ModuleType:
    spec = importlib.util.spec_from_file_location("explore_publication", EXPLORER)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@pytest.mark.dlugi
def test_publikacja_plikow_okresu_zachowuje_nienadpisywanie_i_razem_albo_zaden_w_kazdym_harmonogramie() -> None:
    explorer = _load_explorer()

    assert explorer.probe_interception() == []
    outcome = explorer.summarize([explorer.explore(scope) for scope in explorer.SCOPES.values()])

    assert outcome.exit_code == 0, "\n".join(outcome.lines)


def test_sprawdzenie_publikacji_prowadzi_uruchomienia_bez_watkow_systemu(monkeypatch: pytest.MonkeyPatch) -> None:
    """Czas sprawdzenia nie zależy od tego, jak zajęte są procesory runnera.

    Wątek systemu na każde Uruchomienie procesu w każdym harmonogramie oddawał sterowanie przez jądro przy każdym
    kroku, a na runnerze Windows z Pythonem 3.11 zajętym innymi workerami xdist sprawdzenie dochodziło do limitu
    120 s pytest i worker ginął (`main` od 6f94edb8).
    """

    explorer = _load_explorer()
    started: list[str] = []
    start = threading.Thread.start
    checking = threading.current_thread()

    def counted(thread: threading.Thread) -> None:
        # Wątki tła zostawione przez wcześniejsze testy w tym workerze startują swoje wątki same; liczy się tylko to,
        # co uruchomiło sprawdzenie.
        if threading.current_thread() is checking:
            started.append(thread.name)
        start(thread)

    monkeypatch.setattr(threading.Thread, "start", counted)

    report = explorer.explore(explorer.SCOPES["jedno-uruchomienie"])

    assert report.undisturbed_successes
    assert started == []

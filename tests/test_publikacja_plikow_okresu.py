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
def test_publikacja_plikow_okresu_zachowuje_nienadpisywanie_i_razem_albo_zaden_w_kazdym_harmonogramie(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    explorer = _load_explorer()
    write_period_files = explorer.preparation_files.write_period_files
    writing = 0
    interleaved = False

    def counted(*args: object) -> object:
        nonlocal writing, interleaved
        interleaved |= writing > 0
        writing += 1
        try:
            return write_period_files(*args)
        finally:
            writing -= 1

    monkeypatch.setattr(explorer.preparation_files, "write_period_files", counted)

    assert explorer.probe_interception() == []
    outcome = explorer.summarize([explorer.explore(scope) for scope in explorer.SCOPES.values()])

    assert outcome.exit_code == 0, "\n".join(outcome.lines)
    # Drugie Uruchomienie procesu musi wejść między kroki pierwszego, inaczej zakres dwóch Uruchomień sprawdza tylko
    # jedno po drugim i OK niczego nie mówi o wyścigu.
    assert interleaved, "w żadnym harmonogramie drugie Uruchomienie procesu nie ruszyło przed końcem pierwszego"


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


class _LimitCzasu(BaseException):
    """Jak `Failed: Timeout` pytest-timeout: wyjątek spoza `Exception`, który sygnał rzuca w kodzie publikacji."""


@pytest.mark.parametrize("zatrzymanie", range(1, 21))
def test_limit_czasu_w_kodzie_publikacji_konczy_sprawdzenie_tym_limitem(
    monkeypatch: pytest.MonkeyPatch, zatrzymanie: int
) -> None:
    """Limit pytest, który przychodzi w Uruchomieniu procesu, kończy sprawdzenie, a nie jedno Uruchomienie.

    Na Linuksie i macOS pytest-timeout rzuca `Failed: Timeout` w bieżącej ramce, a ta należy często do kodu
    publikacji w greenlecie Uruchomienia. Połknięty jako Zatrzymanie albo przerwany jak harmonogram w znanym stanie,
    zmieniał drzewo harmonogramów: sprawdzenie kończyło się `IndexError`, fałszywym naruszeniem albo przechodziło,
    a pętla bez końca w kodzie publikacji nie kończyła się wcale. Limit przychodzi tu w chwili N-tego Zatrzymania
    w `ensure_period_files_absent`, bo sprzątanie po nim trafia też w stany sprawdzone wcześniej.
    """

    explorer = _load_explorer()
    ensure_absent = explorer.preparation_files.ensure_period_files_absent
    stops = 0

    def ensure_absent_until_limit(files: object) -> None:
        nonlocal stops
        try:
            ensure_absent(files)
        except Exception:
            stops += 1
            if stops == zatrzymanie:
                raise _LimitCzasu from None
            raise

    monkeypatch.setattr(explorer.preparation_files, "ensure_period_files_absent", ensure_absent_until_limit)

    with pytest.raises(_LimitCzasu):
        explorer.explore(explorer.SCOPES["dwa-uruchomienia"])

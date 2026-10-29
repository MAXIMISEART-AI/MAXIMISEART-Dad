"""Jedno Uruchomienie procesu naraz i brak zamknięcia Centrum rozliczeń w trakcie pracy, w każdym przeplocie w zakresie.

Kolejność kroków dwóch kart, Decyzji taty, wątku Uruchomienia i zamknięcia serwera
jest poza zasięgiem testów przez API, więc sprawdza ją wyczerpująco skrypt skilla
``verify-jedno-uruchomienie-naraz`` na prawdziwych ``RunHost`` i ``Shutdown``.
Zakres, znane ustalenia i postępowanie przy porażce opisuje
``.agents/skills/verify-jedno-uruchomienie-naraz/SKILL.md``.

Sprawdzenie prawdziwego kodu biegnie we własnym procesie, jak w CI. Wątek modelu, który czeka na prawdziwą blokadę
spoza modelu, staje na zawsze i trzyma swoje blokady do końca procesu: w workerze pytest zatrzymywał każdy następny
test Centrum, który brał tę blokadę (#651). W procesie testu biegną tylko sprawdzenia, które same zwalniają to, na
co czeka wątek modelu, albo kończą się błędem przed czekaniem.
"""

from __future__ import annotations

import importlib.util
import re
import subprocess
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
# Poniżej limitu 120 s pytest, żeby sprawdzenie, które się nie kończy, padło z tym, co zdążyło wypisać.
OWN_PROCESS_LIMIT_S = 100

# Skrypt, który na końcu wypisuje nazwy wątków systemu uruchomionych w trakcie sprawdzenia.
COUNTED = """
import sys
import threading

sys.path.insert(0, sys.argv[1])
import explore_runs

started = []
start = threading.Thread.start


def counted(thread):
    started.append(thread.name)
    start(thread)


threading.Thread.start = counted
code = explore_runs.main(sys.argv[2:])
print("wątki systemu:", ", ".join(started))
raise SystemExit(code)
"""

# Skrypt, w którym wątek modelu czeka na zawsze na prawdziwy Event w miejscu z parametru testu.
WAITS_FOR_GOOD = """
import sys
from dataclasses import replace
from threading import Event

sys.path.insert(0, sys.argv[1])
import explore_runs

never = Event()
explore_runs.STALL_SECONDS = 1.0
{waits}
raise SystemExit(explore_runs.main(["--scope", "zamknij-w-trakcie"]))
"""


def _load_explorer() -> ModuleType:
    spec = importlib.util.spec_from_file_location("explore_runs", EXPLORER)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _in_own_process(*arguments: str) -> tuple[int | None, list[str]]:
    """Kod wyjścia Pythona z ``arguments`` we własnym procesie (``None``, gdy nie skończył się w limicie) i jego linie.

    ``-u`` wypisuje każdą linię od razu, więc proces zabity po limicie oddaje wszystko, co zdążył wypisać.
    """

    try:
        done = subprocess.run(
            [sys.executable, "-X", "utf8", "-u", *arguments],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            timeout=OWN_PROCESS_LIMIT_S,
            check=False,
        )
    except subprocess.TimeoutExpired as hung:
        return None, (hung.stdout or b"").decode("utf-8", "replace").splitlines()
    return done.returncode, done.stdout.decode("utf-8", "replace").splitlines()


def test_centrum_prowadzi_jedno_uruchomienie_naraz_i_nie_zamyka_sie_w_trakcie_w_kazdym_przeplocie() -> None:
    code, lines = _in_own_process(str(EXPLORER))

    assert code == 0 and lines[-1].startswith("URUCHOMIENIA OK"), "\n".join(lines)


def test_sprawdzenie_przeplotow_prowadzi_watki_modelu_bez_watkow_systemu() -> None:
    """Czas sprawdzenia nie zależy od tego, jak zajęte są procesory runnera (#565).

    Wątek systemu na każdy wątek modelu oddawał sterowanie przez jądro przy każdym kroku, a na runnerze CI zajętym
    innymi workerami xdist sprawdzenie dochodziło do limitu 120 s pytest.
    """

    code, lines = _in_own_process("-c", COUNTED, str(EXPLORER.parent), "--scope", "zamknij-w-trakcie")

    # Jeden wątek systemu na całe sprawdzenie: biegną na nim wątki modelu, a wywołujący patrzy z zewnątrz, czy robią kroki.
    assert (code, lines[-2:]) == (0, ["URUCHOMIENIA OK", "wątki systemu: sprawdzenie przeplotów"]), "\n".join(lines)


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


@pytest.mark.parametrize(
    ("waits", "stalled", "last"),
    [
        pytest.param(
            "explore_runs.PREPARED = replace(\n"
            "    explore_runs.PREPARED, process=replace(explore_runs.PREPARED.process, metrics_path=never.wait)\n"
            ")",
            "wątek modelu przez 1 s nie doszedł do pierwszego kroku",
            "karta Uruchom 1: odpowiedź 200: running",
            id="przed_pierwszym_krokiem",
        ),
        pytest.param(
            "explore_runs.runs.RunHost.remember = lambda *_: never.wait()",
            "po kroku „silnik kończy i dopisuje rekord metryk” wątek modelu przez 1 s nie doszedł do kolejnego",
            "wątek Uruchomienie 1: silnik kończy i dopisuje rekord metryk [",
            id="po_dwoch_krokach",
        ),
    ],
)
def test_watek_modelu_czekajacy_na_zawsze_konczy_proces_sprawdzenia_luka_z_miejscem_czekania_i_harmonogramem(
    waits: str, stalled: str, last: str
) -> None:
    """Porzucony wątek sprawdzenia czeka do końca procesu, więc proces kończy się po LUCE sam, z LUKĄ w wyjściu (#651).

    Wątek modelu czeka w bibliotece (``Event.wait``), więc LUKA podaje też linię sprawdzanego pliku, z której tam
    doszedł, a harmonogram pod nią kończy się na tym, co zdarzyło się przed czekaniem.
    """

    code, lines = _in_own_process("-c", WAITS_FOR_GOOD.format(waits=waits), str(EXPLORER.parent))

    output = "\n".join(lines)
    assert code == 2 and lines[-1].startswith("URUCHOMIENIA: LUKA MODELU (1)"), output
    [gap] = [line for line in lines if line.startswith("  LUKA MODELU: ")]
    assert re.fullmatch(
        rf"  LUKA MODELU: wątek Uruchomienie 1: {re.escape(stalled)} i stoi w threading\.py:\d+ .+, "
        r"dokąd doszedł z runs\.py:\d+ work, czyli czeka na coś spoza modelu .+",
        gap,
    ), gap
    schedule = lines[lines.index(gap) + 1 : lines.index("", lines.index(gap))]
    assert schedule and schedule[-1].split(". ", 1)[1].startswith(last), output


def test_nieoczekiwany_blad_kodu_pod_sprawdzeniem_przerywa_sprawdzenie(monkeypatch: pytest.MonkeyPatch) -> None:
    explorer = _load_explorer()

    def broken(host: object, prepared: object) -> object:
        raise LookupError("start zepsuty w teście")

    monkeypatch.setattr(explorer.runs.RunHost, "start", broken)

    with pytest.raises(LookupError, match="start zepsuty w teście"):
        explorer.explore(explorer.SCOPES["zamknij-w-trakcie"])

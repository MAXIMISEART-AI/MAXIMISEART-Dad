"""Zegar Centrum u taty (``SYSTEM_CLOCK``) i wątki w tle, na które zamknięcie Centrum nie czeka.

Testy Centrum podstawiają ``ManualClock``, więc prawdziwy budzik i wątek sprawdzenia klucza sprawdza tylko ten plik.
"""

from __future__ import annotations

import os
import subprocess
import sys
import threading
from pathlib import Path

from rozliczenia.centrum.clock import SYSTEM_CLOCK
from rozliczenia.centrum.keyed_box import KeyedBox

ROOT = Path(__file__).resolve().parents[1]

# Budzik za godzinę i sprawdzenie klucza w Skrzynce, która nie odpowiada; potem koniec programu. Moduł ``KeyedBox``
# z importu tego pliku: mutacje zmiany (``tools/ci/mutacje_zmiany.py``) wybierają testy pliku po grafie importów.
EXIT_WITH_BACKGROUND_THREADS = f"""
import threading

from rozliczenia.centrum.clock import SYSTEM_CLOCK
from {KeyedBox.__module__} import KeyedBox


class SilentBox:
    def labelled_issues(self, label, *, include_closed, key):
        threading.Event().wait()


SYSTEM_CLOCK.after(3600, print)
KeyedBox(SilentBox(), lambda: "github_pat_SYNTETYCZNY", clock=SYSTEM_CLOCK).check_in_background()
"""


def test_budzik_zegara_systemu_budzi_w_innym_watku() -> None:
    woken = threading.Event()
    threads: list[threading.Thread] = []

    def wake() -> None:
        threads.append(threading.current_thread())
        woken.set()

    SYSTEM_CLOCK.after(0, wake)

    assert woken.wait(10), "budzik nie zadzwonił"
    assert threads != [threading.current_thread()]


def test_zamkniecie_centrum_nie_czeka_na_budzik_ani_na_skrzynke_bez_odpowiedzi() -> None:
    environment = {**os.environ, "PYTHONPATH": str(ROOT / "src")}

    finished = subprocess.run(
        [sys.executable, "-c", EXIT_WITH_BACKGROUND_THREADS], env=environment, timeout=30, check=False
    )

    assert finished.returncode == 0

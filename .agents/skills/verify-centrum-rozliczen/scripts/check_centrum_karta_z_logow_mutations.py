"""Show that the drive of verify-centrum-rozliczen fails on broken variants of its `karta-z-logow` feature.

Each mutation runs the feature on its own copy of the checkout (``tools/mutacje.py``) and must make it fail.
A mutation whose anchor text is no longer in its file is reported as NIEAKTUALNA: update it to the new code.
"""

from __future__ import annotations

import argparse
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[4] / "tools"))
sys.path.insert(0, str(Path(__file__).resolve().parents[4] / ".agents/skills/verify-centrum-rozliczen/scripts"))

from cele_mutacji_centrum import APP, KARTA, RUN_CARDS
from mutacje import Edit, Mutation, check_all

MUTATIONS = (
    Mutation(
        "po starcie Centrum bez ostatniego Uruchomienia",
        (
            Edit(
                APP,
                "        previous=cards.last(),\n",
                "        previous=None,\n",
            ),
        ),
        KARTA,
        "karta Uruchomienia ginie z zamknięciem Centrum",
    ),
    Mutation(
        "Urwane Uruchomienie bez karty",
        (Edit(RUN_CARDS, "            return self._interrupted(started)\n", "            return None\n"),),
        KARTA,
        "po starcie Centrum tata nie wie, że Uruchomienie urwało się w trakcie",
    ),
)


if __name__ == "__main__":
    argparse.ArgumentParser(description=__doc__).parse_args()
    raise SystemExit(check_all(MUTATIONS))

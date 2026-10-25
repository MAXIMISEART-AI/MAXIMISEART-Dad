"""Show that the drive of verify-centrum-rozliczen fails on broken variants of its `zgloszenie` feature.

Each mutation runs the feature on its own copy of the checkout (``tools/mutacje.py``) and must make it fail.
A mutation whose anchor text is no longer in its file is reported as NIEAKTUALNA: update it to the new code.
"""

from __future__ import annotations

import argparse
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[4] / "tools"))
sys.path.insert(0, str(Path(__file__).resolve().parents[4] / ".agents/skills/verify-centrum-rozliczen/scripts"))

from cele_mutacji_centrum import KEYED_BOX, OUTBOX, ZGLOSZENIE
from mutacje import Edit, Mutation, check_all

MUTATIONS = (
    Mutation(
        "odmowa Skrzynki nie odrzuca klucza",
        (
            Edit(
                KEYED_BOX,
                "            self._verdict = _Verdict(digest, isinstance(outcome, Refused), asked_at)\n",
                "            self._verdict = _Verdict(digest, False, asked_at)\n",
            ),
        ),
        ZGLOSZENIE,
        "Konfiguracja mówi „Zgłoszenia: gotowe” o kluczu, którego Skrzynka odmawia",
    ),
    Mutation(
        "kolejka nie ponawia wysyłki po porażce",
        (
            Edit(
                OUTBOX,
                "                    if self._stopped_on is not None and not self._retry_armed:\n",
                "                    if False:\n",
            ),
        ),
        ZGLOSZENIE,
        "Zgłoszenie bez sieci nie wysyła się samo po powrocie sieci",
    ),
)


if __name__ == "__main__":
    argparse.ArgumentParser(description=__doc__).parse_args()
    raise SystemExit(check_all(MUTATIONS))

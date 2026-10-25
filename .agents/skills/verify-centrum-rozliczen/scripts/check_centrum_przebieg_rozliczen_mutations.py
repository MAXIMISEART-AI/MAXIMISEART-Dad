"""Show that the drive of verify-centrum-rozliczen fails on broken variants of its `przebieg-rozliczen` feature.

Each mutation runs the feature on its own copy of the checkout (``tools/mutacje.py``) and must make it fail.
A mutation whose anchor text is no longer in its file is reported as NIEAKTUALNA: update it to the new code.
"""

from __future__ import annotations

import argparse
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[4] / "tools"))
sys.path.insert(0, str(Path(__file__).resolve().parents[4] / ".agents/skills/verify-centrum-rozliczen/scripts"))

from cele_mutacji_centrum import PRZEBIEG, RUN_VIEW
from mutacje import Edit, Mutation, check_all

MUTATIONS = (
    Mutation(
        "po Przebiegu rozliczeń akcją główną jest Plik zbiorczy",
        (Edit(RUN_VIEW, '    result_action="open_worker_settlements_folder",\n', '    result_action="open_collective_file",\n'),),
        PRZEBIEG,
        "po zapisie Rozliczeń pracowników karta proponuje otwarcie Pliku zbiorczego zamiast ich folderu",
    ),
    Mutation(
        "pusty szablon nie jest oznaczony",
        (Edit(RUN_VIEW, '                empty=result.status == "PUSTY_SZABLON",\n', "                empty=False,\n"),),
        PRZEBIEG,
        "Rozliczenie pracownika bez zleceń wygląda jak zapisane, bez oznaczenia „pusty”",
    ),
)


if __name__ == "__main__":
    argparse.ArgumentParser(description=__doc__).parse_args()
    raise SystemExit(check_all(MUTATIONS))

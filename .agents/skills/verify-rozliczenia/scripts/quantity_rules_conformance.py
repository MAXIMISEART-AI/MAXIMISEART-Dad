"""Run the Reguły ilości conformance test: every line of Dad's instruction through Przygotowanie pliku zbiorczego.

``check_quantity_rules_mutations.py`` breaks one rule at a time and expects this check to fail. The test is
imported, not named by path, so the mutation runner sees the test and its fixtures among the files this check
reads. Ends with ``ILOŚCI USŁUG OK`` or ``ILOŚCI USŁUG FAIL``.
"""

from __future__ import annotations

import argparse
from pathlib import Path
import sys

import pytest

REPO_ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(REPO_ROOT))

from tests import test_ilosci_uslug as conformance  # noqa: E402

TEST = conformance.test_plik_zbiorczy_ma_ilosci_uslug_z_kazdej_linii_instrukcji_taty


def main() -> int:
    argparse.ArgumentParser(description=__doc__).parse_args()
    code = pytest.main(["-q", "-p", "no:cacheprovider", "--rootdir", str(REPO_ROOT), f"{conformance.__file__}::{TEST.__name__}"])
    print("ILOŚCI USŁUG OK" if code == pytest.ExitCode.OK else f"ILOŚCI USŁUG FAIL | pytest {int(code)}")
    return int(code)


if __name__ == "__main__":
    raise SystemExit(main())

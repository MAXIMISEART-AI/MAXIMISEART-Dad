"""Rozliczenie pracownika z kopii Wzorca (ADR 0008) jest takie, jak zapisane przez openpyxl, dla generowanych Wierszy danych.

Test właściciel zapisu w ``test_workbook_files.py`` sprawdza wybrane wartości. Granice
kawałków kompresji, nietypowe teksty i liczby oraz kilka Rozliczeń pracowników z jednego
wczytanego Wzorca sprawdza skrypt skilla ``verify-kopia-wzorca`` na prawdziwym
``template_copy.py``. Reguły, zakres, znane ustalenia i postępowanie przy porażce opisuje
``.agents/skills/verify-kopia-wzorca/SKILL.md``.
"""

from __future__ import annotations

import importlib.util
import sys
import warnings
from pathlib import Path
from types import ModuleType

import pytest

CHECKER = (
    Path(__file__).resolve().parents[1] / ".agents" / "skills" / "verify-kopia-wzorca" / "scripts" / "check_template_copy.py"
)


def _load_checker() -> ModuleType:
    spec = importlib.util.spec_from_file_location("check_template_copy", CHECKER)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


# 60 przykładów na każdy z dwóch Wzorców: ~30 s na Macu M4 Max, kilka razy dłużej na runnerze Windows.
@pytest.mark.timeout(600)
def test_rozliczenie_pracownika_z_kopii_wzorca_jest_jak_zapisane_przez_openpyxl_dla_generowanych_wierszy_danych() -> None:
    checker = _load_checker()

    with warnings.catch_warnings():
        warnings.filterwarnings("ignore", category=UserWarning, module="openpyxl")
        outcome = checker.run_check()

    assert outcome.exit_code == 0, "\n".join(outcome.lines)

"""Rozliczenie pracownika z kopii Wzorca (ADR 0008) jest takie, jak zapisane przez openpyxl, dla generowanych Wierszy danych.

Test właściciel zapisu w ``test_workbook_files.py`` sprawdza wybrane wartości i Wyróżnienia.
Granice kawałków kompresji, nietypowe teksty i liczby, generowane Wyróżnienia oraz kilka
Rozliczeń pracowników z jednego wczytanego Wzorca sprawdza skrypt skilla ``verify-kopia-wzorca``
na prawdziwym ``template_copy.py``. Reguły, zakres i postępowanie przy porażce opisuje
``.agents/skills/verify-kopia-wzorca/SKILL.md``.
"""

from __future__ import annotations

import importlib.util
import re
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


# 60 przykładów na każdy z dwóch Wzorców: ~65 s na Macu M4 Max, kilka razy dłużej na runnerze Windows.
@pytest.mark.timeout(600)
def test_rozliczenie_pracownika_z_kopii_wzorca_jest_jak_zapisane_przez_openpyxl_dla_generowanych_wierszy_danych() -> None:
    checker = _load_checker()

    with warnings.catch_warnings():
        warnings.filterwarnings("ignore", category=UserWarning, module="openpyxl")
        # Hypothesis warns about the size of a shrunk counterexample's repr; the checker prints its own story.
        warnings.filterwarnings("ignore", message="Generating overly large repr")
        outcome = checker.run_check()

    assert outcome.exit_code == 0, "\n".join(outcome.lines)


def test_kopia_wzorca_sprawdza_te_same_przyklady_niezaleznie_od_modulow_wczytanych_obok(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    checker = _load_checker()
    checked: list[str] = []

    def record(run: object, case: object) -> None:
        checked.append(re.sub(r" object at 0x[0-9a-f]+", "", repr(case.workers)))  # type: ignore[attr-defined]

    monkeypatch.setattr(checker.Run, "check", record)
    checker.run_check(shrink=False)
    alone, checked[:] = list(checked), []

    # Pełny pytest wczytuje moduły, których test uruchomiony sam nie wczytuje (#288).
    source = tmp_path / "modul_obok.py"
    source.write_text('LITERALY = ("kopia", "Wzorca", "#288", 4096, -7777, 12.5, b"bajty")\n', encoding="utf-8")
    spec = importlib.util.spec_from_file_location("modul_obok", source)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    monkeypatch.setitem(sys.modules, spec.name, module)
    checker.run_check(shrink=False)

    assert len(alone) > 2 * checker.DEFAULT_EXAMPLES
    assert checked == alone

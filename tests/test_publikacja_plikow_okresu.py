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
from pathlib import Path
from types import ModuleType

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


def test_publikacja_plikow_okresu_zachowuje_nienadpisywanie_i_razem_albo_zaden_w_kazdym_harmonogramie() -> None:
    explorer = _load_explorer()

    assert explorer.probe_interception() == []
    outcome = explorer.summarize([explorer.explore(scope) for scope in explorer.SCOPES.values()])

    assert outcome.exit_code == 0, "\n".join(outcome.lines)

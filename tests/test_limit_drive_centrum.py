"""Drive Centrum rozliczeń w ``verify-centrum-rozliczen`` uznaje się za zawieszony dopiero po limicie, który rośnie z
liczbą przejeżdżanych funkcji, więc nowa funkcja nie wypycha ``--feature all`` poza stały limit kroku."""

from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / ".agents" / "skills" / "verify-centrum-rozliczen" / "scripts"


@pytest.fixture
def runner(monkeypatch: pytest.MonkeyPatch) -> ModuleType:
    monkeypatch.syspath_prepend(str(SCRIPTS))
    spec = importlib.util.spec_from_file_location("run_centrum_verification", SCRIPTS / "run_centrum_verification.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_drive_wszystkich_funkcji_ma_limit_rosnacy_z_liczba_funkcji_a_jedna_funkcja_staly(runner: ModuleType) -> None:
    every = runner.driven("all", {})

    # all trwał w CI 280–305 s, a padał na stałych 300 s (runy 40309201075, 40322305317): limit daje mu co najmniej
    # dwa razy tyle i rośnie z każdą funkcją.
    assert runner.drive_timeout_s(every) == runner.DRIVE_SECONDS_PER_FEATURE * len(every) >= 2 * 305
    assert runner.drive_timeout_s((every[0],)) == runner.STEP_TIMEOUT_SECONDS
    assert runner.drive_timeout_s(("wydajnosc",)) == runner.PERFORMANCE_TIMEOUT_SECONDS

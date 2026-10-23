"""``tools/czesci_pytest.py`` dzieli pliki testów na części CI bez zgubionego i bez powtórzonego pliku."""

from __future__ import annotations

import importlib.util
from pathlib import Path
import shutil
import subprocess
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
TOOL = ROOT / "tools" / "czesci_pytest.py"


def _part(root: Path, text: str) -> list[str]:
    tool = root / "tools" / TOOL.name
    done = subprocess.run([sys.executable, str(tool), text], capture_output=True, text=True, encoding="utf-8", check=True)
    return done.stdout.split()


@pytest.mark.parametrize("count", [1, 2, 3])
def test_kazdy_plik_testow_jest_w_dokladnie_jednej_czesci(tmp_path: Path, count: int) -> None:
    tests = ["tests/test_a.py", "tests/b_test.py", "tests/podfolder/test_c.py", "tests/podfolder/d_test.py"]
    for name in [*tests, "tests/fixtures/pomocnik.py", "tests/conftest.py"]:
        (tmp_path / name).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / name).write_text("", encoding="utf-8")
    (tmp_path / "tools").mkdir()
    shutil.copy(TOOL, tmp_path / "tools" / TOOL.name)

    files = [name for number in range(1, count + 1) for name in _part(tmp_path, f"{number}/{count}")]

    assert sorted(files) == sorted(tests)


def test_czesci_repozytorium_obejmuja_kazdy_plik_testow() -> None:
    files = [name for number in (1, 2) for name in _part(ROOT, f"{number}/2")]

    assert len(files) == len(set(files))
    assert set(files) == {path.relative_to(ROOT).as_posix() for path in (ROOT / "tests").rglob("test_*.py")}


def test_czesc_zaczyna_sie_od_najdluzszego_pliku_a_plik_spoza_tabeli_wazy_mediane() -> None:
    spec = importlib.util.spec_from_file_location("czesci_pytest", TOOL)
    assert spec is not None and spec.loader is not None
    tool = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(tool)

    chosen = tool.parts(["a", "b", "c", "d", "nowy"], {"a": 10.0, "b": 1.0, "c": 6.0, "d": 4.0}, 2)

    assert chosen == [["a", "d"], ["c", "nowy", "b"]]


@pytest.mark.parametrize("part", ["0/2", "3/2", "2"])
def test_czesc_spoza_zakresu_jest_bledem_wywolania(part: str) -> None:
    done = subprocess.run([sys.executable, str(TOOL), part], capture_output=True, text=True, encoding="utf-8", check=False)

    assert (done.returncode, done.stdout) == (2, "")

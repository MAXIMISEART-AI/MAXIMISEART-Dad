"""Skrypty skilli ``verify-*`` mają jeden kontrakt wywołania: katalog runu, warianty i dowolny bieżący katalog."""

from __future__ import annotations

from pathlib import Path
import subprocess
import sys

import pytest

REPO = Path(__file__).resolve().parents[1]
SKILLS = REPO / ".agents" / "skills"
CLEANUPS = (
    SKILLS / "verify-rozliczenia" / "scripts" / "cleanup.py",
    SKILLS / "verify-centrum-rozliczen" / "scripts" / "centrum_cleanup.py",
)


def _script(script: Path, *arguments: str, cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(script), *arguments],
        cwd=cwd,
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        timeout=120,
    )


@pytest.mark.parametrize("cleanup", CLEANUPS, ids=lambda path: path.name)
def test_sprzatanie_nie_usuwa_katalogu_ktorego_nie_utworzyla_fixture(tmp_path: Path, cleanup: Path) -> None:
    foreign = tmp_path / "dane-kogos"
    foreign.mkdir()
    (foreign / "wazne.txt").write_text("zostaje\n", encoding="utf-8")

    done = _script(cleanup, "--root", str(foreign), cwd=tmp_path)

    assert done.returncode == 1, done.stdout + done.stderr
    assert (foreign / "wazne.txt").read_text(encoding="utf-8") == "zostaje\n"


def test_fixture_nie_pisze_do_niepustego_katalogu(tmp_path: Path) -> None:
    occupied = tmp_path / "zajety"
    occupied.mkdir()
    (occupied / "wazne.txt").write_text("zostaje\n", encoding="utf-8")

    done = _script(SKILLS / "verify-rozliczenia" / "scripts" / "create_fixture.py", "--root", str(occupied), cwd=tmp_path)

    assert done.returncode == 1, done.stdout + done.stderr
    assert sorted(path.name for path in occupied.iterdir()) == ["wazne.txt"]

"""Sprawdzenie modelu Aktualizacji narzędzia nie przechodzi w CI, gdy pokryty kod rozjechał się z modelem.

Model opisuje kod z commitu synchronizacji w ``SKILL.md`` skilla ``verify-aktualizacja-narzedzia``. CI klonuje
płytko, więc skrypt dopobiera historię, a rozjazd albo brak commitu kończy się w CI porażką, zanim ruszy TLC.
"""

from __future__ import annotations

import importlib.util
import os
from pathlib import Path
import shutil
import subprocess
import sys
from types import ModuleType

from tests.fixtures.git_repo import commit, git

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / ".agents" / "skills" / "verify-aktualizacja-narzedzia" / "scripts" / "sprawdz_aktualizacje.py"
COVERED = "src/rozliczenia/centrum/tool_update.py"
DRIFT = "AKTUALIZACJA: ROZJAZD MODELU Z KODEM"


def _skill_md(sync: str) -> str:
    return f"Covered files: `{COVERED}`.\n\nSync commit: `{sync}` (main).\n"


def _repo(root: Path) -> str:
    """Repozytorium z pokrytym plikiem i skryptem skilla; zwraca commit synchronizacji."""

    (root / COVERED).parent.mkdir(parents=True)
    (root / COVERED).write_text("X = 1\n", encoding="utf-8")
    scripts = root / ".agents" / "skills" / "verify-aktualizacja-narzedzia" / "scripts"
    scripts.mkdir(parents=True)
    shutil.copy(SCRIPT, scripts / SCRIPT.name)
    git(root, "init", "--quiet")
    return commit(root, "synchronizacja")


def _load() -> ModuleType:
    spec = importlib.util.spec_from_file_location("sprawdz_aktualizacje", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _check_in_ci(root: Path, sync: str) -> subprocess.CompletedProcess[str]:
    skill = root / ".agents" / "skills" / "verify-aktualizacja-narzedzia"
    (skill / "SKILL.md").write_text(_skill_md(sync), encoding="utf-8")
    return subprocess.run(
        [sys.executable, str(skill / "scripts" / SCRIPT.name)],
        cwd=root,
        env={**os.environ, "GITHUB_ACTIONS": "true"},
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=60,
        check=False,
    )


def test_w_ci_pokryty_kod_zmieniony_od_synchronizacji_konczy_sprawdzenie_porazka(tmp_path: Path) -> None:
    sync = _repo(tmp_path)
    (tmp_path / COVERED).write_text("X = 2\n", encoding="utf-8")
    commit(tmp_path, "zmiana pokrytego kodu")

    done = _check_in_ci(tmp_path, sync[:8])

    assert done.returncode == 1, done.stdout + done.stderr
    assert done.stdout.splitlines()[-1] == DRIFT
    assert f"pokryty kod zmienił się od {sync[:8]}: {COVERED}" in done.stdout


def test_w_ci_brak_commitu_synchronizacji_konczy_sprawdzenie_porazka(tmp_path: Path) -> None:
    _repo(tmp_path)

    done = _check_in_ci(tmp_path, "0" * 40)

    assert done.returncode == 1, done.stdout + done.stderr
    assert done.stdout.splitlines()[-1] == DRIFT
    assert f"commitu synchronizacji {'0' * 40} nie ma w tej historii" in done.stdout


def test_plytki_klon_dopobiera_historie_do_commitu_synchronizacji(tmp_path: Path) -> None:
    origin = tmp_path / "origin"
    origin.mkdir()
    sync = _repo(origin)
    (origin / COVERED).write_text("X = 2\n", encoding="utf-8")
    commit(origin, "zmiana pokrytego kodu")
    (origin / "inny.txt").write_text("inny\n", encoding="utf-8")
    commit(origin, "zmiana obok")
    clone = tmp_path / "klon"
    git(tmp_path, "clone", "--quiet", "--depth", "1", origin.as_uri(), str(clone))

    found = _load()._drift(clone, _skill_md(sync[:8]))

    assert found == f"pokryty kod zmienił się od {sync[:8]}: {COVERED}. Sprawdź, czy model dalej go opisuje."
    assert git(clone, "rev-parse", "--is-shallow-repository") == "false"


def test_pokryty_kod_bez_zmian_od_synchronizacji_nie_jest_rozjazdem(tmp_path: Path) -> None:
    sync = _repo(tmp_path)
    (tmp_path / "inny.txt").write_text("inny\n", encoding="utf-8")
    commit(tmp_path, "zmiana obok")

    assert _load()._drift(tmp_path, _skill_md(sync[:8])) is None

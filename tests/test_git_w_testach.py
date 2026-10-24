from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess

import pytest

from tests.fixtures.git_config import CONFIG
from tests.fixtures.tool_clone import git

MISSING_FIXTURE = (
    "git w teście czyta konfigurację komputera, więc wynik zależy od maszyny: tests/conftest.py musi mieć sesyjną "
    "fixture git_bez_konfiguracji_komputera z hermetic_git (tests/fixtures/git_config.py)"
)

def _maintenance_after_commit(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, *config: str) -> list[list[str]]:
    repo, trace = tmp_path / "repo", tmp_path / "trace2.json"
    repo.mkdir()
    git(repo, "init", "--quiet")
    monkeypatch.setenv("GIT_TRACE2_EVENT", str(trace))
    git(repo, *config, "commit", "--quiet", "--allow-empty", "--message", "x")
    events = [json.loads(line) for line in trace.read_text(encoding="utf-8").splitlines()]
    return [event["argv"] for event in events if event["event"] == "child_start" and "maintenance" in event["argv"]]


def test_commit_w_tescie_nie_uruchamia_konserwacji_repozytorium(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    assert _maintenance_after_commit(tmp_path, monkeypatch) == []


def test_slad_gita_pokazuje_konserwacje_wlaczona_jawnie(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    started = _maintenance_after_commit(tmp_path, monkeypatch, "-c", "maintenance.auto=true", "-c", "maintenance.autoDetach=false")

    assert [argv[1:3] for argv in started] == [["maintenance", "run"]]


def test_git_w_tescie_czyta_tylko_konfiguracje_testow(tmp_path: Path) -> None:
    git(tmp_path, "init", "--quiet")
    listed = git(tmp_path, "config", "--list", "--show-scope").splitlines()

    outside_repository = [line for line in listed if not line.startswith("local\t")]

    assert outside_repository == [f"global\t{key.lower()}={value}" for key, value in CONFIG.items()], MISSING_FIXTURE


def test_klon_pustego_origin_po_pushu_main_ma_pliki_na_kazdym_komputerze(tmp_path: Path) -> None:
    origin, work, other = tmp_path / "origin.git", tmp_path / "praca", tmp_path / "inny-klon"
    git(tmp_path, "init", "--quiet", "--bare", str(origin))
    git(tmp_path, "init", "--quiet", str(work))
    (work / "kod.py").write_text("WERSJA = 1\n", encoding="utf-8")
    git(work, "add", "kod.py")
    git(work, "commit", "--quiet", "--message", "pierwsza wersja")
    git(work, "push", "--quiet", str(origin), "HEAD:main")

    git(tmp_path, "clone", "--quiet", str(origin), str(other))

    assert (other / "kod.py").read_text(encoding="utf-8") == "WERSJA = 1\n", MISSING_FIXTURE


def test_git_ze_srodowiskiem_bez_konfiguracji_testow_wywraca_test(tmp_path: Path) -> None:
    with pytest.raises(AssertionError, match="GIT_CONFIG_NOSYSTEM nie jest 1.*Napraw: zbuduj env z os.environ"):
        subprocess.run(["git", "--version"], env={"PATH": os.environ["PATH"]}, capture_output=True, check=False)
    with pytest.raises(AssertionError, match="GIT_CONFIG_GLOBAL='/dev/null' to nie konfiguracja testów"):
        subprocess.run(["git", "--version"], env=os.environ | {"GIT_CONFIG_GLOBAL": "/dev/null"}, check=False)

    assert subprocess.run(["git", "--version"], env=os.environ | {"LC_ALL": "C"}, capture_output=True, check=False).returncode == 0

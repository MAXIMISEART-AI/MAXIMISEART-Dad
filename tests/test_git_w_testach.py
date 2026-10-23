from __future__ import annotations

import json
from pathlib import Path

import pytest

from tests.fixtures.tool_clone import git

pytestmark = pytest.mark.usefixtures("git_bez_konserwacji_w_tle")


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

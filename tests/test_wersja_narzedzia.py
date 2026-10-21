"""Dzień, od którego narzędzie jest na swoim commicie, odczytany z reflogu prawdziwego klonu Gita."""

from __future__ import annotations

from datetime import date
import os
from pathlib import Path
import subprocess

import pytest

from rozliczenia.centrum.version import commit_since, tool_commit

# Kwadrans po północy czasu polskiego to jeszcze poprzedni dzień w UTC: liczy się dzień na komputerze taty.
SWITCHED = "2026-10-13T00:15:00+02:00"
OTHER = "9a8b7c6d5e4f3a2b1c0d9e8f7a6b5c4d3e2f1a0b"


def _git(directory: Path, *arguments: str, when: str = SWITCHED) -> None:
    subprocess.run(
        ["git", "-c", "user.name=Maks", "-c", "user.email=maks@example.invalid", *arguments],
        cwd=directory,
        env=os.environ | {"GIT_COMMITTER_DATE": when},
        check=True,
        capture_output=True,
    )


def _clone(root: Path) -> str:
    root.mkdir()
    _git(root, "init", "--quiet")
    _git(root, "commit", "--quiet", "--allow-empty", "--message", "narzędzie")
    commit = tool_commit(root)
    assert commit is not None
    return commit


def test_klon_jest_na_commicie_od_dnia_ostatniego_przejscia(tmp_path: Path) -> None:
    clone = tmp_path / "narzedzie"
    commit = _clone(clone)

    assert commit_since(commit, clone) == date(2026, 10, 13)


def test_katalog_roboczy_worktree_ma_wlasny_dzien(tmp_path: Path) -> None:
    clone = tmp_path / "klon"
    commit = _clone(clone)
    _git(clone, "worktree", "add", "--quiet", "--detach", str(tmp_path / "drugi"), when="2026-10-20T09:00:00+02:00")

    assert commit_since(commit, tmp_path / "drugi") == date(2026, 10, 20)


def test_ostatni_wpis_reflogu_prowadzacy_do_innego_commitu_nie_daje_dnia(tmp_path: Path) -> None:
    clone = tmp_path / "narzedzie"
    commit = _clone(clone)

    assert commit_since(OTHER, clone) is None
    assert commit_since(commit, clone) is not None


@pytest.mark.parametrize("reflog", [None, ""], ids=["bez-reflogu", "pusty-reflog"])
def test_klon_bez_wpisow_reflogu_nie_ma_dnia(tmp_path: Path, reflog: str | None) -> None:
    clone = tmp_path / "narzedzie"
    commit = _clone(clone)
    head_log = clone / ".git" / "logs" / "HEAD"
    if reflog is None:
        head_log.unlink()
    else:
        head_log.write_text(reflog, encoding="utf-8")

    assert commit_since(commit, clone) is None


def test_narzedzie_poza_klonem_gita_nie_ma_dnia(tmp_path: Path) -> None:
    assert commit_since(OTHER, tmp_path) is None

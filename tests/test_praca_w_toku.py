"""``tools/praca_w_toku.py`` pokazuje sesji pracę w toku z innych worktree tego samego repozytorium."""

from __future__ import annotations

from pathlib import Path
import subprocess
import sys

import pytest

TOOL = Path(__file__).resolve().parents[1] / "tools" / "praca_w_toku.py"


def _git(cwd: Path, *args: str) -> None:
    subprocess.run(
        ["git", "-c", "user.name=Sesja", "-c", "user.email=sesja@example.invalid", "-c", "commit.gpgsign=false", *args],
        cwd=cwd,
        capture_output=True,
        check=True,
    )


def _commit(cwd: Path, path: str, content: str, message: str) -> None:
    (cwd / path).write_text(content, encoding="utf-8")
    _git(cwd, "add", path)
    _git(cwd, "commit", "-m", message)


def _report(cwd: Path, *args: str) -> str:
    completed = subprocess.run(
        [sys.executable, str(TOOL), "--lokalnie", *args],
        cwd=cwd,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=True,
    )
    return completed.stdout


@pytest.fixture
def checkouts(tmp_path: Path) -> dict[str, Path]:
    """Repo z originem i trzema worktree: inna sesja z pracą, sesja bez pracy i bieżący checkout."""

    origin, main = tmp_path / "origin.git", tmp_path / "main"
    _git(tmp_path, "init", "--bare", "-b", "main", str(origin))
    _git(tmp_path, "clone", str(origin), str(main))
    _commit(main, "wspolny.py", "a = 1\n", "start")
    _commit(main, "inny.py", "b = 1\n", "drugi plik")
    _git(main, "push", "-u", "origin", "main")

    other, idle, current = tmp_path / "inna-sesja", tmp_path / "bez-pracy", tmp_path / "biezacy"
    _git(main, "worktree", "add", "-b", "fix/opiekun", str(other))
    _commit(other, "wspolny.py", "a = 2\n", "fix(centrum): opiekun nie cofa bez startu (#7)")
    (other / "szkic.py").write_text("c = 1\n", encoding="utf-8")
    _git(main, "worktree", "add", "-b", "t3/bez-pracy", str(idle))
    _git(main, "worktree", "add", "-b", "feat/moje", str(current))
    _commit(current, "wspolny.py", "a = 3\n", "feat: moje")
    (current / "szkic.py").write_text("c = 2\n", encoding="utf-8")
    (current / "inny.py").write_text("b = 2\n", encoding="utf-8")
    return {"other": other, "current": current}


def test_raport_wymienia_inna_prace_w_toku_i_pliki_zmieniane_tez_tutaj(checkouts: dict[str, Path]) -> None:
    sandbox = checkouts["other"].parent / "piaskownica"
    _git(checkouts["other"], "worktree", "add", "--detach", str(sandbox), "fix/opiekun")
    (sandbox / "szkic.py").write_text("c = 3\n", encoding="utf-8")

    report = _report(checkouts["current"])
    work, _, overlaps = report.partition("NAKŁADANIA")

    assert "fix/opiekun" in work
    assert str(checkouts["other"].resolve()) in work
    assert "t3/bez-pracy" not in report
    assert "piaskownica" not in report  # odłączona kopia commitów gałęzi fix/opiekun
    overlap = next(line for line in overlaps.splitlines() if "fix/opiekun" in line)
    assert "wspolny.py" in overlap  # zacommitowany tam, niewypchnięty, i tutaj
    assert "szkic.py" in overlap  # niezacommitowany po obu stronach
    assert "inny.py" not in overlap


def test_issue_znajduje_galaz_ktorej_commit_odwoluje_sie_do_zgloszenia(checkouts: dict[str, Path]) -> None:
    assert "fix/opiekun" in _report(checkouts["current"], "--issue", "7")
    assert "fix/opiekun" not in _report(checkouts["current"], "--issue", "8")


def test_galaz_zbudowana_na_innej_naklada_sie_tylko_wlasnymi_commitami(checkouts: dict[str, Path]) -> None:
    stacked = checkouts["other"].parent / "na-opiekunie"
    _git(checkouts["other"], "worktree", "add", "-b", "fix/na-opiekunie", str(stacked), "fix/opiekun")
    _commit(stacked, "inny.py", "b = 3\n", "fix: na opiekunie")

    overlaps = _report(stacked, "--nakladania")

    lines = overlaps.splitlines()
    assert not [line for line in lines if line.startswith("- fix/opiekun")]
    assert "inny.py" in next(line for line in lines if line.startswith("- feat/moje"))

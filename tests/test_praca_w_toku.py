"""``tools/praca_w_toku.py`` pokazuje sesji pracę w toku z innych worktree tego samego repozytorium."""

from __future__ import annotations

import os
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


def _report(cwd: Path, *args: str, gh_answer: str | None = None) -> str:
    """Raport bez GitHuba albo z ``gh``, który na każde wywołanie odpowiada ``gh_answer``."""

    env, mode = dict(os.environ), ["--lokalnie"]
    if gh_answer is not None:
        fake = cwd.parent / "gh-na-niby"
        fake.mkdir(exist_ok=True)
        (fake / "odpowiedz.json").write_text(gh_answer, encoding="utf-8")
        if os.name == "nt":
            (fake / "gh.cmd").write_text(f'@type "{fake / "odpowiedz.json"}"\n', encoding="utf-8")
        else:
            (fake / "gh").write_text(f"#!/bin/sh\ncat '{fake / 'odpowiedz.json'}'\n", encoding="utf-8")
            (fake / "gh").chmod(0o755)
        env["PATH"], mode = f"{fake}{os.pathsep}{env['PATH']}", []
    completed = subprocess.run(
        [sys.executable, str(TOOL), *mode, *args],
        cwd=cwd,
        env=env,
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

    report = _report(checkouts["current"])
    work, _, overlaps = report.partition("NAKŁADANIA")

    assert "fix/opiekun" in work
    assert str(checkouts["other"].resolve()) in work
    assert "t3/bez-pracy" not in report
    assert "piaskownica" not in report  # czysta odłączona kopia commitów gałęzi fix/opiekun
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


def test_przeniesienie_naklada_sie_stara_sciezka(checkouts: dict[str, Path]) -> None:
    moving = checkouts["other"].parent / "przenosze"
    _git(checkouts["other"], "worktree", "add", "-b", "feat/przenosze", str(moving), "main")
    _git(moving, "mv", "wspolny.py", "przeniesiony.py")
    _git(moving, "commit", "-m", "refactor: przenoszę wspolny.py")
    _git(moving, "mv", "inny.py", "inny2.py")

    github_only = '[{"number": 9, "headRefName": "fix/zdalna", "title": "", "body": "", "files": [{"path": "wspolny.py"}]}]'

    lines = _report(moving, "--nakladania", gh_answer=github_only).splitlines()

    assert "wspolny.py" in next(line for line in lines if line.startswith("- fix/opiekun"))
    assert "- fix/zdalna (PR #9): wspolny.py" in lines
    mine = next(line for line in lines if line.startswith("- feat/moje"))
    assert "wspolny.py" in mine  # przeniesiony w commicie tutaj, zmieniony w commicie tam
    assert "inny.py" in mine  # przeniesiony tutaj bez commita, zmieniony tam bez commita


def test_odlaczony_head_liczy_sie_tylko_z_wlasnym_commitem_innym_niz_merge(checkouts: dict[str, Path]) -> None:
    merge, owner = checkouts["other"].parent / "scalenie", checkouts["other"].parent / "wlasciciel"
    _git(checkouts["other"], "worktree", "add", "--detach", str(merge), "main")
    _git(merge, "merge", "--no-ff", "--no-edit", "fix/opiekun")
    _git(checkouts["other"], "worktree", "add", "--detach", str(owner), "main")
    _commit(owner, "wspolny.py", "a = 4\n", "fix: poprawka właściciela PR")

    report = _report(checkouts["current"])

    assert str(merge.resolve()) not in report
    assert f"odłączony HEAD {owner.resolve()}: wspolny.py" in report


def test_zly_ksztalt_odpowiedzi_gh_to_raport_bez_githuba(checkouts: dict[str, Path]) -> None:
    report = _report(checkouts["current"], "--issue", "7", gh_answer="[{}]")

    assert "GITHUB POMINIĘTY" in report
    assert "fix/opiekun" in report  # praca lokalna nadal w raporcie


def test_zly_ksztalt_tresci_zgloszenia_to_raport_bez_githuba(checkouts: dict[str, Path]) -> None:
    report = _report(checkouts["current"], "--issue", "7", gh_answer="[]")

    assert report.count("GITHUB POMINIĘTY") == 1
    assert "fix/opiekun" in report  # praca lokalna nadal w raporcie


def test_odlaczony_head_z_samym_merge_liczy_sie_z_niezacommitowanymi_plikami(checkouts: dict[str, Path]) -> None:
    owner = checkouts["other"].parent / "wlasciciel-po-scaleniu"
    _git(checkouts["other"], "worktree", "add", "--detach", str(owner), "main")
    _git(owner, "merge", "--no-ff", "--no-edit", "fix/opiekun")
    (owner / "inny.py").write_text("b = 4\n", encoding="utf-8")

    lines = _report(checkouts["current"], "--nakladania").splitlines()

    # inny.py niezacommitowany po obu stronach, wspolny.py z commita fix/opiekun, który niesie merge
    assert f"- odłączony HEAD {owner.resolve()}: inny.py, wspolny.py" in lines

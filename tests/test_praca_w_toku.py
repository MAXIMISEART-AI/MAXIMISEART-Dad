"""``tools/praca_w_toku.py`` pokazuje sesji pracę w toku z innych worktree tego samego repozytorium."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
import itertools
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

import pytest

from tests.fixtures.git_repo import commit, git

TOOL = Path(__file__).resolve().parents[1] / "tools" / "praca_w_toku.py"


@pytest.fixture(autouse=True)
def git_bez_konfiguracji_komputera_testow(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", os.devnull)
    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")


def _git(cwd: Path, *args: str) -> None:
    subprocess.run(
        ["git", "-c", "user.name=Sesja", "-c", "user.email=sesja@example.invalid", *args],
        cwd=cwd,
        capture_output=True,
        check=True,
    )


def _commit(cwd: Path, path: str, content: str, message: str) -> None:
    (cwd / path).write_text(content, encoding="utf-8")
    _git(cwd, "add", path)
    _git(cwd, "commit", "-m", message)


def _fake_gh(directory: Path, answer: str, code: int = 0) -> str:
    """``PATH`` z ``gh``, który na każde wywołanie wypisuje ``answer`` i kończy się kodem ``code``."""

    fake = directory / "gh-na-niby"
    fake.mkdir(exist_ok=True)
    (fake / "odpowiedz.json").write_text(answer, encoding="utf-8")
    if os.name == "nt":
        (fake / "gh.cmd").write_text(f'@type "{fake / "odpowiedz.json"}"\n@exit /b {code}\n', encoding="utf-8")
    else:
        (fake / "gh").write_text(f"#!/bin/sh\ncat '{fake / 'odpowiedz.json'}'\nexit {code}\n", encoding="utf-8")
        (fake / "gh").chmod(0o755)
    return f"{fake}{os.pathsep}{os.environ['PATH']}"


def _report(cwd: Path, *args: str, path: str | None = None) -> str:
    """Raport bez GitHuba albo z ``gh`` szukanym w ``path``."""

    completed = subprocess.run(
        [sys.executable, str(TOOL), *(["--lokalnie"] if path is None else []), *args],
        cwd=cwd,
        env=dict(os.environ) if path is None else {**os.environ, "PATH": path},
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

    lines = _report(moving, "--nakladania", path=_fake_gh(moving.parent, github_only)).splitlines()

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
    report = _report(checkouts["current"], "--issue", "7", path=_fake_gh(checkouts["current"].parent, "[{}]"))

    assert "GITHUB POMINIĘTY" in report
    assert "fix/opiekun" in report  # praca lokalna nadal w raporcie


def test_zly_ksztalt_tresci_zgloszenia_to_raport_bez_githuba(checkouts: dict[str, Path]) -> None:
    report = _report(checkouts["current"], "--issue", "7", path=_fake_gh(checkouts["current"].parent, "[]"))

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


@dataclass(frozen=True)
class _Commit:
    name: str
    files: frozenset[str]
    merge: bool = False
    on_remote: bool = False


@dataclass(frozen=True)
class _Checkout:
    """Linia pracy w świecie testu: commity spoza ``main`` i niezacommitowane pliki, jak je zbudowano."""

    branch: str | None
    path: Path | None
    commits: frozenset[_Commit]
    dirty: frozenset[str] = frozenset()
    pr: int | None = None
    pr_files: frozenset[str] = frozenset()

    def changed(self, other: _Checkout) -> frozenset[str]:
        """Pliki zmieniane we własnych commitach (bez wspólnych z ``other``) albo niezacommitowane."""

        return frozenset().union(*(commit.files for commit in self.commits - other.commits)) | self.dirty


_REMOTE = _Commit("zdalna", frozenset({"zdalny.py"}), on_remote=True)
_MERGE = _Commit("merge", frozenset(), merge=True)
_UNFETCHED = _Commit("niepobrana", frozenset({"pr-plik.py"}))
_GITHUB_ONLY = (
    _Checkout("zdalna", None, frozenset({_REMOTE}), pr=9, pr_files=_REMOTE.files),
    _Checkout("niepobrana", None, frozenset({_UNFETCHED}), pr=10, pr_files=_UNFETCHED.files),
)
_PULL_REQUESTS = {
    "inny-g-wlasny-czysty": (8, {"wspolny.py", "tylko-w-pr.py"}),
    "ja": (7, {"wspolny.py"}),
    **{side.branch or "": (side.pr, side.pr_files) for side in _GITHUB_ONLY},
}


def _expected_report(me: _Checkout, world: list[_Checkout], github: bool) -> list[str]:
    """Raport ze specyfikacji w docstringu narzędzia, wyliczony z modelu świata, nie z Gita."""

    on_branches = {commit for side in world if side.branch is not None for commit in side.commits}

    def in_progress(side: _Checkout) -> bool:
        if side.dirty or (side.branch is not None and side.commits):
            return True
        own = [c for c in side.commits if not (c.merge or c.on_remote or c in on_branches)]
        return side.branch is None and bool(own)

    others = [side for side in world if side is not me and in_progress(side)] + (list(_GITHUB_ONLY) if github else [])
    lines = ["GITHUB POMINIĘTY | --lokalnie"] if not github else []
    lines.append(f"PRACA W TOKU | inne: {len(others)} | odniesienie: {me.path} ({me.branch or 'odłączony HEAD'})")
    overlaps = []
    for side in others:
        parts = [side.branch or "odłączony HEAD"]
        parts += [f"PR #{side.pr}"] if github and side.pr is not None else []
        files = frozenset().union(*(commit.files for commit in side.commits)) | side.dirty
        if side in _GITHUB_ONLY:
            parts += ["tylko na GitHubie", f"niezacommitowane 0, pliki {len(side.pr_files)}"]
        else:
            ahead, unpushed = len(side.commits), len([c for c in side.commits if not c.on_remote])
            files |= side.pr_files if github else frozenset()
            parts += [str(side.path) if side.path else "bez worktree"]
            parts += [f"przed origin/main {ahead}, niewypchnięte {unpushed}, niezacommitowane {len(side.dirty)}, pliki {len(files)}"]
            parts += ["praca"] if any(not c.merge for c in side.commits) else []
        lines.append("- " + " | ".join(parts))
        shared = me.changed(side) & side.changed(me)
        if shared:
            name = side.branch or f"odłączony HEAD {side.path}"
            pr = f" (PR #{side.pr})" if github and side.pr is not None else ""
            overlaps.append(f"- {name}{pr}: {', '.join(sorted(shared))}")
    lines += ["NAKŁADANIA | pliki zmieniane tu i w innej pracy w toku", *overlaps] if overlaps else ["NAKŁADANIA | brak"]
    return sorted(lines)


def _world(tmp_path: Path) -> list[_Checkout]:
    """Worktree w każdej kombinacji: HEAD dołączony albo odłączony × commity × niezacommitowane pliki, plus rebase i bisect."""

    origin, main = tmp_path / "origin.git", tmp_path / "main"
    git(tmp_path, "init", "--quiet", "--bare", "--initial-branch", "main", str(origin))
    git(tmp_path, "clone", "--quiet", str(origin), str(main))
    for name in ("wspolny.py", "szkic.py", "przenoszony.py", "zdalny.py", "rebasowany.py"):
        (main / name).write_text("x = 0\n", encoding="utf-8")
    commit(main, "start")
    git(main, "push", "--quiet", "--set-upstream", "origin", "main")
    git(main, "switch", "--quiet", "--create", "zdalna")
    (main / "zdalny.py").write_text("x = 1\n", encoding="utf-8")
    commit(main, "praca")
    git(main, "push", "--quiet", "origin", "zdalna")
    git(main, "switch", "--quiet", "--create", "zdalna-druga", "main")
    (main / "zdalny.py").write_text("x = 2\n", encoding="utf-8")
    commit(main, "praca")
    git(main, "push", "--quiet", "origin", "zdalna-druga")
    git(main, "switch", "--quiet", "main")
    git(main, "branch", "--quiet", "--delete", "--force", "zdalna", "zdalna-druga")

    def worktree(name: str, attached: bool, start: str = "main") -> Path:
        path = tmp_path / name
        git(main, "worktree", "add", "--quiet", *(["-b", name] if attached else ["--detach"]), str(path), start)
        return path.resolve()

    def write(path: Path, files: frozenset[str]) -> None:
        for name in files:
            (path / name).write_text(f"x = '{path.name}'\n", encoding="utf-8")

    world = []
    for attached, commits, dirty in itertools.product(
        (True, False), ("brak", "wlasny", "przeniesienie", "merge", "na-remote"), ("czysty", "zmiana", "przeniesienie")
    ):
        name = f"inny-{'g' if attached else 'o'}-{commits}-{dirty}"
        path = worktree(name, attached, "origin/zdalna" if commits == "na-remote" else "main")
        made: frozenset[_Commit] = frozenset()
        moved = "przenoszony.py"
        if commits == "wlasny":
            own = _Commit(name, frozenset({"wspolny.py"}))
            write(path, own.files)
            commit(path, "praca")
            made = frozenset({own})
        elif commits == "przeniesienie":
            moved = f"{name}.py"
            git(path, "mv", "przenoszony.py", moved)
            commit(path, "praca")
            made = frozenset({_Commit(name, frozenset({"przenoszony.py", moved}))})
        elif commits == "merge":
            git(path, "merge", "--quiet", "--no-ff", "--no-edit", "origin/zdalna")
            made = frozenset({_REMOTE, _MERGE})
        elif commits == "na-remote":
            made = frozenset({_REMOTE})
        changed: frozenset[str] = frozenset()
        if dirty == "zmiana":
            changed = frozenset({"szkic.py"})
            write(path, changed)
        elif dirty == "przeniesienie":
            changed = frozenset({moved, f"{name}-brudny.py"})
            (path / moved).rename(path / f"{name}-brudny.py")
        pr, pr_files = _PULL_REQUESTS.get(name, (None, set()))
        world.append(_Checkout(name if attached else None, path, made, changed, pr, frozenset(pr_files)))

    pushed = worktree("tylko-na-remote", False, "origin/zdalna-druga")
    world.append(_Checkout(None, pushed, frozenset({_Commit("zdalna-druga", frozenset({"zdalny.py"}), on_remote=True)})))

    sandbox = worktree("piaskownica", False, "inny-g-wlasny-czysty")
    world.append(_Checkout(None, sandbox, next(side for side in world if side.branch == "inny-g-wlasny-czysty").commits))

    without = worktree("bez-worktree", True)
    write(without, frozenset({"wspolny.py"}))
    commit(without, "praca")
    git(main, "worktree", "remove", str(without))
    world.append(_Checkout("bez-worktree", None, frozenset({_Commit("bez-worktree", frozenset({"wspolny.py"}))})))

    deleted = worktree("usuniety", True)
    write(deleted, frozenset({"wspolny.py"}))
    commit(deleted, "praca")
    shutil.rmtree(deleted)
    world.append(_Checkout("usuniety", None, frozenset({_Commit("usuniety", frozenset({"wspolny.py"}))})))

    rebasing, rebasing_detached = worktree("rebasuje", True), worktree("rebasuje-odlaczony", False)
    rebased = _Commit("rebasuje", frozenset({"wspolny.py", "rebasowany.py"}))
    for path in (rebasing, rebasing_detached):
        write(path, rebased.files)
        commit(path, "praca")
    world.append(_Checkout("rebasuje", rebasing, frozenset({rebased}), rebased.files))
    # Odłączony HEAD w trakcie rebase stoi na nowym main, a jego commit zna już tylko reflog.
    world.append(_Checkout(None, rebasing_detached, frozenset(), rebased.files))

    bisecting = worktree("szuka", True)
    searched = []
    for number in ("jeden", "dwa", "trzy"):
        write(bisecting, frozenset({f"szuka-{number}.py"}))
        commit(bisecting, "praca")
        searched.append(_Commit(f"szuka-{number}", frozenset({f"szuka-{number}.py"})))
    git(bisecting, "bisect", "start", "szuka", "origin/main")
    world.append(_Checkout("szuka", bisecting, frozenset(searched)))

    mine_dirty = frozenset({"szkic.py", "przenoszony.py", "nowy plik ł.py"})
    for name, attached in (("ja", True), ("ja-odlaczony", False)):
        path = worktree(name, attached)
        mine = _Commit(name, frozenset({"wspolny.py", "zdalny.py"}))
        write(path, mine.files)
        commit(path, "praca")
        write(path, mine_dirty)
        pr, pr_files = _PULL_REQUESTS.get(name, (None, set()))
        world.append(_Checkout(name if attached else None, path, frozenset({mine}), mine_dirty, pr, frozenset(pr_files)))

    stacked = worktree("ja-na-zdalnej", True, "origin/zdalna")
    write(stacked, frozenset({"wspolny.py"}))
    commit(stacked, "praca")
    write(stacked, frozenset({"szkic.py"}))
    stacked_commits = frozenset({_REMOTE, _Commit("ja-na-zdalnej", frozenset({"wspolny.py"}))})
    world.append(_Checkout("ja-na-zdalnej", stacked, stacked_commits, frozenset({"szkic.py"})))

    (main / "rebasowany.py").write_text("x = 'main'\n", encoding="utf-8")
    commit(main, "nowy main")
    git(main, "push", "--quiet", "origin", "main")
    for path in (rebasing, rebasing_detached):
        with pytest.raises(subprocess.CalledProcessError):
            git(path, "rebase", "origin/main")  # konflikt w rebasowany.py zatrzymuje rebase
    return world


def test_raport_zgodny_ze_specyfikacja_w_kazdym_stanie_repozytorium(tmp_path: Path) -> None:
    world = _world(tmp_path)
    answer = json.dumps(
        [
            {"number": pr, "headRefName": branch, "title": "", "body": "", "files": [{"path": p} for p in sorted(files)]}
            for branch, (pr, files) in _PULL_REQUESTS.items()
        ]
    )
    github = _fake_gh(tmp_path, answer)
    by_name = {side.path.name: (side, side.path) for side in world if side.path is not None}
    runs = {"ja": github, "ja-odlaczony": None, "ja-na-zdalnej": github, "rebasuje": None, "szuka": None}

    with ThreadPoolExecutor() as pool:
        reports = dict(zip(runs, pool.map(lambda run: _report(by_name[run[0]][1], path=run[1]), runs.items())))

    mismatches = []
    for name, report in reports.items():
        expected = _expected_report(by_name[name][0], world, github=runs[name] is not None)
        actual = sorted(report.splitlines())
        mismatches += [f"{name}: brak {line}" for line in expected if line not in actual]
        mismatches += [f"{name}: nadmiar {line}" for line in actual if line not in expected]

    assert not mismatches, "\n".join(mismatches)

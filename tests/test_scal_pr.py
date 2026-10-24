"""``tools/scal_pr.py``: agent scala PR tylko przy zielonym CI na HEAD, werdykcie PASS dla HEAD i scaleniu z bieżącą
bazą, które przechodzi ruff i mypy.

Testy biegną na prawdziwym Gicie z repozytorium bare jako ``origin`` (z ``refs/pull/N/head`` jak na GitHubie)
i na prawdziwym ``tools/ci_lokalnie.py --tylko ruff,mypy`` na małym kodzie. Atrapa ``gh`` podaje stan PR
i zapisuje wywołania ``gh pr merge`` zamiast scalać.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

import pytest

from tests.fixtures.git_repo import commit, git, repository

pytestmark = pytest.mark.skipif(sys.platform == "win32", reason="Atrapa gh to skrypt sh.")

TOOLS = Path(__file__).resolve().parents[1] / "tools"
SUM = "def suma(a: int, b: int) -> int:\n    return a + b\n"
SUM_OF_THREE = "def suma(a: int, b: int, c: int) -> int:\n    return a + b + c\n"
PYPROJECT = '[tool.ruff]\ninclude = ["kod/**/*.py"]\n\n[tool.mypy]\nstrict = true\nfiles = ["kod"]\n'
CLEANUP = 'import pathlib\n\npathlib.Path("posprzatane").write_text("tak")\nprint("SPRZĄTANIE OK | 0 usuniętych")\n'
FAKE_GH = """\
import json, os, pathlib, subprocess, sys

here = pathlib.Path(sys.argv[0]).parent
arguments = sys.argv[1:]
pulls = json.loads((here / "pulls.json").read_text())


def git(*command):
    identity = {f"GIT_{role}_{key}": value for role in ("AUTHOR", "COMMITTER") for key, value in (("NAME", "gh"), ("EMAIL", "gh@example.com"))}
    done = subprocess.run(["git", "-c", "commit.gpgsign=false", *command], cwd=here.parent / "origin.git", env={**os.environ, **identity}, capture_output=True, text=True, check=True)
    return done.stdout.strip()


if arguments[:2] == ["pr", "view"]:
    pull = pulls[arguments[2]]
    print(json.dumps({field: pull[field] for field in arguments[arguments.index("--json") + 1].split(",")}))
elif arguments[:2] == ["pr", "merge"]:
    pull = pulls[arguments[2]]
    if arguments[arguments.index("--match-head-commit") + 1] != pull["headRefOid"]:
        sys.exit("HEAD PR zmienił się")
    base = git("rev-parse", "refs/heads/main")
    tree = git("merge-tree", "--write-tree", base, pull["headRefOid"])
    merge = git("commit-tree", tree, "-p", base, "-p", pull["headRefOid"], "-m", "Merge")
    git("update-ref", "refs/heads/main", merge)
    pull.update(state="MERGED", mergeCommit={"oid": merge})
    (here / "pulls.json").write_text(json.dumps(pulls))
    with (here / "merges.jsonl").open("a") as log:
        log.write(json.dumps(arguments) + "\\n")
else:
    sys.exit(f"atrapa gh nie zna: {arguments}")
"""


def _check_run(status: str, conclusion: str | None, *, workflow: str = "CI") -> dict[str, str | None]:
    return {"__typename": "CheckRun", "name": "Required CI status", "status": status, "conclusion": conclusion, "workflowName": workflow}


GREEN = [
    {"__typename": "CheckRun", "name": "Ruff", "status": "COMPLETED", "conclusion": "SUCCESS", "workflowName": "CI"},
    _check_run("COMPLETED", "SUCCESS"),
]
COMMIT_STATUS = {"__typename": "StatusContext", "context": "Required CI status", "state": "SUCCESS"}
NOT_ACTIONS = "CI: brak „Required CI status” z GitHub Actions na HEAD"
NO_PASS = "werdykt: brak komentarza ani recenzji „WERDYKT: PASS {short}”"
OBJECTION = "werdykt: sprzeciw dla {short} bez nowszego „WERDYKT: PASS {short}”"
UNREADABLE = "werdykt: nieczytelny dla {short} bez nowszego „WERDYKT: PASS {short}”"


class FakeGitHub:
    def __init__(self, tmp_path: Path, files: dict[str, str]) -> None:
        origin = tmp_path / "origin.git"
        git(tmp_path, "init", "--quiet", "--bare", "--initial-branch=main", str(origin))
        self.origin = origin
        self.checkout = repository(
            tmp_path / "checkout",
            {".gitignore": ".mypy_cache/\n.ruff_cache/\n__pycache__/\nposprzatane\n", "pyproject.toml": PYPROJECT, **files},
        )
        for tool in ("scal_pr.py", "scalenia_pr.py"):
            shutil.copy2(TOOLS / tool, self.checkout / "tools" / tool)
        git(self.checkout, "checkout", "--quiet", "-b", "main")
        self.start = commit(self.checkout, "start")
        git(self.checkout, "remote", "add", "origin", str(origin))
        git(self.checkout, "push", "--quiet", "origin", "main")
        self.bin = tmp_path / "bin"
        self.bin.mkdir()
        (self.bin / "gh.py").write_text(FAKE_GH, encoding="utf-8")
        gh = self.bin / "gh"
        gh.write_text(f'#!/bin/sh\nexec "{sys.executable}" "{self.bin / "gh.py"}" "$@"\n', encoding="utf-8")
        gh.chmod(0o755)
        self.pulls: dict[str, dict[str, object]] = {}
        self.written = 0

    def open_pull(self, number: int, files: dict[str, str], *, parent: str = "") -> str:
        """HEAD nowego PR z zielonym CI i bez werdyktu: commit ``files`` na ``parent`` (domyślnie commit ``start``)."""

        head = self.commit_on(parent or self.start, files, f"PR {number}")
        git(self.checkout, "push", "--quiet", "origin", f"{head}:refs/pull/{number}/head")
        self.pulls[str(number)] = {
            "number": number,
            "title": f"PR {number}",
            "state": "OPEN",
            "isDraft": False,
            "isCrossRepository": False,
            "baseRefName": "main",
            "headRefOid": head,
            "statusCheckRollup": GREEN,
            "comments": [],
            "reviews": [],
            "mergeCommit": None,
        }
        self._save()
        return head

    def commit_on(self, parent: str, files: dict[str, str], subject: str) -> str:
        git(self.checkout, "checkout", "--quiet", "--detach", parent)
        for name, text in files.items():
            (self.checkout / name).parent.mkdir(parents=True, exist_ok=True)
            (self.checkout / name).write_text(text, encoding="utf-8")
        made = commit(self.checkout, subject)
        git(self.checkout, "checkout", "--quiet", "main")
        return made

    def update(self, number: int, **fields: object) -> None:
        self.pulls[str(number)].update(fields)
        self._save()

    def comment(self, number: int, body: str, association: str = "OWNER") -> None:
        self._write(number, "comments", {"body": body, "authorAssociation": association, "createdAt": self._now()})

    def review(self, number: int, body: str, association: str = "OWNER", *, state: str = "COMMENTED") -> None:
        self._write(number, "reviews", {"body": body, "authorAssociation": association, "state": state, "submittedAt": self._now()})

    def _now(self) -> str:
        self.written += 1
        return f"2026-10-24T03:{self.written // 60:02d}:{self.written % 60:02d}Z"

    def _write(self, number: int, kind: str, verdict: dict[str, str]) -> None:
        verdicts = self.pulls[str(number)][kind]
        assert isinstance(verdicts, list)
        verdicts.append({**verdict, "author": {"login": "recenzent"}})
        self._save()

    def push_main(self, files: dict[str, str]) -> str:
        for name, text in files.items():
            (self.checkout / name).write_text(text, encoding="utf-8")
        head = commit(self.checkout, "main idzie dalej")
        git(self.checkout, "push", "--quiet", "origin", "main")
        return head

    def run(self, *arguments: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, str(self.checkout / "tools" / "scal_pr.py"), *arguments],
            cwd=self.checkout,
            env={**os.environ, "PATH": f"{self.bin}{os.pathsep}{os.environ['PATH']}"},
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=300,
            check=False,
        )

    def merges(self) -> list[list[str]]:
        log = self.bin / "merges.jsonl"
        return [json.loads(line) for line in log.read_text(encoding="utf-8").splitlines()] if log.exists() else []

    def _save(self) -> None:
        (self.bin / "pulls.json").write_text(json.dumps(self.pulls), encoding="utf-8")


def _last_line(answered: subprocess.CompletedProcess[str]) -> str:
    return answered.stdout.rstrip().rpartition("\n")[2]


def test_gotowy_pr_jest_scalany_z_jego_head_a_po_merge_biegnie_sprzatanie(tmp_path: Path) -> None:
    github = FakeGitHub(tmp_path, {"kod/__init__.py": SUM, "tools/sprzatanie.py": CLEANUP})
    head = github.open_pull(1, {"kod/inne.py": "INNE: int = 1\n"})
    main = github.push_main({"kod/nazwa.py": 'NAZWA = "z main"\n'})
    github.comment(1, f"WERDYKT: FAIL {head}\n- krytyczne: brak testu")
    github.comment(1, f"Poprawione w {head[:7]}.")
    github.comment(1, f"WERDYKT: PASS {head[:9]}\n- drobne: nazwa")

    checked = github.run("1", "--bez-merge")
    merged = github.run("1")

    assert checked.returncode == 0, checked.stdout + checked.stderr
    assert _last_line(checked).startswith(f"SCAL OK | #1 {head[:7]} | gotowy do merge'a z main {main[:7]}")
    merge_commit = git(github.origin, "rev-parse", "refs/heads/main")
    assert merged.returncode == 0, merged.stdout + merged.stderr
    assert _last_line(merged) == (
        f"SCAL OK | #1 {head[:7]} | scalony do main jako {merge_commit[:7]} (baza {main[:7]}) | sprzątanie: SPRZĄTANIE OK | 0 usuniętych"
    )
    assert git(github.origin, "rev-list", "--parents", "-n", "1", merge_commit).split()[1:] == [main, head]
    assert github.merges() == [["pr", "merge", "1", "--merge", "--match-head-commit", head]]
    assert (github.checkout / "posprzatane").exists()


@pytest.mark.parametrize(
    ("ci", "comments", "reason"),
    [
        (
            [_check_run("COMPLETED", "FAILURE")],
            [("WERDYKT: PASS {head}", "OWNER")],
            "CI: „Required CI status” FAILURE",
        ),
        (
            [_check_run("IN_PROGRESS", None)],
            [("WERDYKT: PASS {head}", "OWNER")],
            "CI: „Required CI status” IN_PROGRESS",
        ),
        (
            [_check_run("COMPLETED", "FAILURE"), _check_run("COMPLETED", "SUCCESS")],
            [("WERDYKT: PASS {head}", "OWNER")],
            "CI: „Required CI status” FAILURE",
        ),
        (GREEN[:1], [("WERDYKT: PASS {head}", "OWNER")], NOT_ACTIONS),
        ([COMMIT_STATUS], [("WERDYKT: PASS {head}", "OWNER")], NOT_ACTIONS),
        ([_check_run("COMPLETED", "SUCCESS", workflow="")], [("WERDYKT: PASS {head}", "OWNER")], NOT_ACTIONS),
        (GREEN, [], NO_PASS),
        (GREEN, [("WERDYKT: PASS {old}", "OWNER")], NO_PASS),
        (GREEN, [("WERDYKT: PASS {head}", "NONE")], NO_PASS),
        (GREEN, [("WERDYKT: PASS {head}", "CONTRIBUTOR")], NO_PASS),
        (GREEN, [("WERDYKT: PASS {head}", "CONTRIBUTOR", "COMMENTED")], NO_PASS),
        (GREEN, [("WERDYKT: PASS {head}", "OWNER", "PENDING")], NO_PASS),
        (GREEN, [("Recenzja: WERDYKT: PASS {head}", "OWNER")], NO_PASS),
        (GREEN, [("WERDYKT: PASS {head} — bez uwag", "OWNER")], UNREADABLE),
        (GREEN, [("WERDYKT: PASS {head6}", "OWNER")], UNREADABLE),
        (GREEN, [("\ufeffWERDYKT: PASS {head}", "OWNER")], UNREADABLE),
        (GREEN, [("## Werdykt niezależny: PASS", "OWNER")], UNREADABLE),
        (GREEN, [("WERDYKT: PASS {head}", "OWNER"), ("**Werdykt: PASS** dla {head}", "MEMBER")], UNREADABLE),
        (GREEN, [("WERDYKT: PASS {head}", "OWNER"), ("WERDYKT: FAIL {head}", "MEMBER")], OBJECTION),
        ([_check_run("COMPLETED", "FAILURE")], [], f"CI: „Required CI status” FAILURE; {NO_PASS}"),
    ],
    ids=[
        "ci-czerwone",
        "ci-trwa",
        "ci-czerwone-w-jednym-z-dwoch-przebiegow",
        "ci-bez-wymaganego-checku",
        "ci-tylko-status-commitu",
        "ci-check-spoza-github-actions",
        "bez-werdyktu",
        "pass-dla-starszego-commitu",
        "pass-konta-bez-prawa-zapisu",
        "pass-kontrybutora",
        "pass-w-recenzji-kontrybutora",
        "pass-w-nieopublikowanej-recenzji",
        "pass-nie-w-pierwszej-linii",
        "pass-z-dopiskiem-w-pierwszej-linii",
        "pass-z-6-znakami-sha",
        "pass-z-bom",
        "pass-w-naglowku",
        "pass-w-markdownie-po-pass",
        "fail-po-pass",
        "wszystkie-przyczyny-naraz",
    ],
)
def test_bez_zielonego_ci_albo_werdyktu_pass_dla_head_pr_nie_jest_scalany(
    tmp_path: Path, ci: list[dict[str, str | None]], comments: list[tuple[str, ...]], reason: str
) -> None:
    github = FakeGitHub(tmp_path, {"kod/__init__.py": SUM})
    old = github.open_pull(1, {"kod/inne.py": "INNE: int = 1\n"})
    head = github.commit_on(old, {"kod/inne.py": "INNE: int = 2\n"}, "PR 1 po poprawce")
    git(github.checkout, "push", "--quiet", "--force", "origin", f"{head}:refs/pull/1/head")
    github.update(1, headRefOid=head, statusCheckRollup=ci)
    for body, association, *state in comments:
        text = body.format(head=head, old=old, head6=head[:6])
        github.review(1, text, association, state=state[0]) if state else github.comment(1, text, association)

    answered = github.run("1")

    assert answered.returncode == 1, answered.stdout + answered.stderr
    assert _last_line(answered) == f"SCAL ODMOWA | #1 {head[:7]} | {reason.format(short=head[:7])}"
    assert github.merges() == []


@pytest.mark.parametrize(
    ("kind", "objection"),
    [
        ("comment", "WERDYKT: FAIL {head} — brak testu"),
        ("comment", "WERDYKT: FAIL {head}."),
        ("comment", "**WERDYKT: FAIL {head}**"),
        ("comment", "WERDYKT: FAIL"),
        ("comment", "Werdykt: FAIL {head}"),
        ("comment", "WERDYKT:  FAIL {head}"),
        ("comment", "WERDYKT: FAIL {head}"),
        ("comment", "Recenzja V338r2: fail dla {head}"),
        ("comment", "Werdyktu jeszcze nie ma, czekam na CI"),
        ("comment", "## Weryfikacja niezależna: FAIL"),
        ("comment", "Weryfikacja niezależna: FAIL @ {head8}"),
        ("comment", "_Weryfikacja {head8}: do poprawy_"),
        ("comment", "VERDICT: FAIL {head}"),
        ("comment", "Verdict for {head}: changes requested"),
        ("comment", "❌ WERDYKT: FAIL {head}"),
        ("comment", "V338r2 WERDYKT: FAIL {head}"),
        ("comment", "## V338r2\n\nWERDYKT: FAIL {head}"),
        ("comment", "\n\nWERDYKT: FAIL {head}"),
        ("comment", "| WERDYKT | FAIL {head} |"),
        ("comment", "> WERDYKT: FAIL {head}"),
        ("comment", "> Werdykt dla {head}: do poprawy"),
        ("comment", "﻿WERDYKT: FAIL {head}"),
        ("comment", "​WERDYKT: FAIL {head}"),
        ("comment", "WERDYKT 20261024: FAIL"),
        ("comment", "WERDYKT: FAIL, run 18234567890"),
        ("comment", "Werdykt: FAIL, deadbeef w teście"),
        ("comment", "WERDYKT: FAIL {upper}"),
        ("comment", "WERDYKT: FAIL {head}0"),
        ("comment", "Werdykt: FAIL {head7} (poprzednio {old7})"),
        ("comment", "V338r4: FAILED {head7}"),
        ("comment", "Weryfikacja: FAILURE"),
        ("comment", "## V338r4\n\n**FAIL** {head7}: brak testu"),
        ("comment", "## V338r4 niezależny przegląd\n\nWynik: FAIL {head7}"),
        ("comment", "## V338r3\n\nWerdykt V338r3: FAIL {head7}"),
        ("comment", "Przegląd niezależny V338r4 dla PR: FAIL {head7}"),
        ("comment", "❌ NIE PASS {head7}"),
        ("comment", "## V338r4\n\nNie pass: brak testu"),
        ("comment", "Ocena: ＦＡＩＬ {head7}"),
        ("comment", "Werdykt: PASS {head7}, ale nie pass dla Windows"),
        ("COMMENTED", "WERDYKT: FAIL {head}"),
        ("COMMENTED", "Weryfikacja niezależna: FAIL"),
        ("CHANGES_REQUESTED", "Popraw nazwę funkcji."),
        ("CHANGES_REQUESTED", ""),
    ],
    ids=[
        "dopisek",
        "kropka",
        "markdown",
        "bez-sha",
        "male-litery-werdyktu",
        "dwie-spacje",
        "twarda-spacja",
        "male-litery-fail",
        "werdykt-bez-fail",
        "naglowek-weryfikacji-jak-na-305",
        "weryfikacja-z-sha-jak-na-229",
        "weryfikacja-bez-fail",
        "po-angielsku",
        "po-angielsku-bez-fail",
        "emoji",
        "prefiks-recenzenta",
        "naglowek-nad-werdyktem",
        "puste-linie-przed-werdyktem",
        "tabela",
        "cytat",
        "cytat-bez-fail",
        "bom",
        "zerowa-szerokosc",
        "data-to-nie-sha",
        "numer-runu-to-nie-sha",
        "slowo-hex-i-galaz-to-nie-sha",
        "sha-head-wielkimi",
        "sha-head-ze-znakiem-za-nim",
        "head-i-starszy-commit",
        "failed",
        "failure",
        "fail-w-markdownie-pod-naglowkiem",
        "wynik-pod-naglowkiem",
        "werdykt-pod-naglowkiem-z-fail-jako-trzecim-slowem",
        "fail-jako-szoste-slowo",
        "nie-pass",
        "nie-pass-pod-naglowkiem",
        "fail-pelnej-szerokosci",
        "pass-i-nie-pass",
        "recenzja",
        "recenzja-weryfikacji",
        "prosba-o-zmiany",
        "prosba-o-zmiany-bez-tresci",
    ],
)
def test_sprzeciw_zaufanego_konta_dla_head_po_pass_blokuje_merge(tmp_path: Path, kind: str, objection: str) -> None:
    github = FakeGitHub(tmp_path, {"kod/__init__.py": SUM})
    old = github.open_pull(1, {"kod/inne.py": "INNE: int = 1\n"})
    head = github.commit_on(old, {"kod/inne.py": "INNE: int = 2\n"}, "PR 1 po poprawce")
    git(github.checkout, "push", "--quiet", "--force", "origin", f"{head}:refs/pull/1/head")
    github.update(1, headRefOid=head)
    git(github.checkout, "branch", "deadbeef", old)
    github.comment(1, f"WERDYKT: PASS {head}")
    body = objection.format(head=head, head7=head[:7], head8=head[:8], upper=head.upper(), old7=old[:7])
    github.comment(1, body) if kind == "comment" else github.review(1, body, state=kind)

    answered = github.run("1")

    assert answered.returncode == 1, answered.stdout + answered.stderr
    assert _last_line(answered) == f"SCAL ODMOWA | #1 {head[:7]} | {OBJECTION.format(short=head[:7])}"
    assert github.merges() == []


@pytest.mark.parametrize(
    "verdicts",
    [
        [("comment", "WERDYKT: PASS {head}"), ("comment", "Werdykt: FAIL `{old}` — poprawione w nowym commicie")],
        [("comment", "WERDYKT: PASS {head}"), ("comment", "WERDYKT: FAIL {old7}")],
        [("comment", "WERDYKT: PASS {head}"), ("comment", "## V338r2\n\nWERDYKT: FAIL {old}")],
        [("comment", "**Werdykt:** FAIL {head}"), ("comment", "WERDYKT: PASS {head}")],
        [("COMMENTED", "WERDYKT: FAIL {head}"), ("comment", "WERDYKT: PASS {head}")],
        [("comment", "WERDYKT: FAIL {head}"), ("COMMENTED", "WERDYKT: PASS {head}")],
        [("comment", "WERDYKT: PASS {head}"), ("comment", "WERDYKT: FAIL {head}", "CONTRIBUTOR")],
        [("comment", "WERDYKT: PASS {head}"), ("comment", "Poprawki w {head7}\n\nWeryfikacja lokalna: SZYBKO OK")],
        [("comment", "WERDYKT: PASS {head}"), ("COMMENTED", "")],
        [("comment", "WERDYKT: PASS {head}\r\n\r\n- drobne: nazwa")],
        [("comment", "  WERDYKT: PASS {head7}  ")],
        [("comment", "WERDYKT: PASS {head}\n\nNiezależne werdykty: V1 (FAIL {old7} tylko przez czerwone CI), V1r2 PASS.\n- FAIL w r1: brak testu\nWerdykt V1: FAIL")],
        [("comment", "WERDYKT: PASS {head}"), ("comment", "Stan nocy 04:30\n- V1 (FAIL przez CI)\n- Werdykt V1: FAIL {old7}\n- FAIL {old7} poprawiony")],
        [("CHANGES_REQUESTED", "Popraw nazwę funkcji."), ("comment", "WERDYKT: PASS {head}")],
        [("comment", "WERDYKT: PASS {head}"), ("CHANGES_REQUESTED", "Popraw nazwę funkcji.", "CONTRIBUTOR")],
        [("comment", "WERDYKT: PASS {head}"), ("PENDING", "WERDYKT: FAIL {head}")],
        [("comment", "WERDYKT: PASS {head}"), ("comment", "**Werdykt: PASS** dla {old7}")],
    ],
    ids=[
        "sprzeciw-dla-starszego-commitu",
        "sprzeciw-dla-starszego-commitu-7-znakow",
        "naglowek-nad-sprzeciwem-dla-starszego-commitu",
        "pass-po-sprzeciwie",
        "pass-po-starszej-recenzji-z-fail",
        "pass-w-recenzji-po-fail",
        "sprzeciw-kontrybutora",
        "dalsza-linia-weryfikacji-bez-fail",
        "recenzja-bez-tresci",
        "pass-z-crlf",
        "pass-z-odstepami",
        "pass-koordynatora-z-lista-fail-jak-na-345",
        "status-po-pass-z-fail-dla-starszego-commitu",
        "pass-po-prosbie-o-zmiany",
        "prosba-o-zmiany-kontrybutora",
        "nieopublikowana-recenzja-z-fail",
        "nieczytelny-pass-dla-starszego-commitu",
    ],
)
def test_sprzeciw_dla_innego_commitu_starszy_niz_pass_albo_bez_prawa_zapisu_nie_blokuje(
    tmp_path: Path, verdicts: list[tuple[str, ...]]
) -> None:
    github = FakeGitHub(tmp_path, {"kod/__init__.py": SUM})
    old = github.open_pull(1, {"kod/inne.py": "INNE: int = 1\n"})
    head = github.commit_on(old, {"kod/inne.py": "INNE: int = 2\n"}, "PR 1 po poprawce")
    git(github.checkout, "push", "--quiet", "--force", "origin", f"{head}:refs/pull/1/head")
    github.update(1, headRefOid=head)
    for kind, body, *association in verdicts:
        text = body.format(head=head, head7=head[:7], old=old, old7=old[:7])
        github.comment(1, text, *association) if kind == "comment" else github.review(1, text, *association, state=kind)

    answered = github.run("1", "--bez-merge")

    assert answered.returncode == 0, answered.stdout + answered.stderr
    assert _last_line(answered).startswith(f"SCAL OK | #1 {head[:7]} | gotowy do merge'a")


@pytest.mark.parametrize(
    ("state", "draft", "fork", "reason"),
    [
        ("MERGED", False, False, "PR nie jest otwarty: MERGED"),
        ("OPEN", True, False, "PR jest szkicem"),
        ("OPEN", False, True, "PR z forka"),
    ],
)
def test_pr_zamkniety_szkic_albo_z_forka_nie_jest_scalany(
    tmp_path: Path, state: str, draft: bool, fork: bool, reason: str
) -> None:
    github = FakeGitHub(tmp_path, {"kod/__init__.py": SUM})
    head = github.open_pull(1, {"kod/inne.py": "INNE: int = 1\n"})
    github.update(1, state=state, isDraft=draft, isCrossRepository=fork)
    github.comment(1, f"WERDYKT: PASS {head}")

    answered = github.run("1")

    assert _last_line(answered) == f"SCAL ODMOWA | #1 {head[:7]} | {reason}"
    assert github.merges() == []


@pytest.mark.parametrize(
    ("main_files", "pull_files", "reason"),
    [
        ({"kod/nazwa.py": 'NAZWA = "z main"\n'}, {"kod/nazwa.py": 'NAZWA = "z PR"\n'}, "Konflikt z main {main}: kod/nazwa.py"),
        (
            {"kod/__init__.py": SUM_OF_THREE},
            {"kod/uzycie.py": "from kod import suma\n\nWYNIK = suma(1, 2)\n"},
            "Na scaleniu z main {main} pada: mypy, mypy (Windows)",
        ),
        (
            {"pyproject.toml": PYPROJECT.replace("[tool.mypy]", '[tool.ruff.lint]\nextend-select = ["B905"]\n\n[tool.mypy]')},
            {"kod/pary.py": "PARY = list(zip([1], [2]))\n"},
            "Na scaleniu z main {main} pada: ruff",
        ),
    ],
    ids=["konflikt", "mypy-na-scaleniu", "regula-ruff-wlaczona-na-main-po-ci-pr"],
)
def test_pr_ktory_nie_scala_sie_czysto_z_biezacym_main_nie_jest_scalany(
    tmp_path: Path, main_files: dict[str, str], pull_files: dict[str, str], reason: str
) -> None:
    github = FakeGitHub(tmp_path, {"kod/__init__.py": SUM, "kod/nazwa.py": 'NAZWA = "pierwsza"\n'})
    head = github.open_pull(1, pull_files)
    github.comment(1, f"WERDYKT: PASS {head}")
    main = github.push_main(main_files)

    answered = github.run("1")

    assert answered.returncode == 1, answered.stdout + answered.stderr
    assert _last_line(answered) == f"SCAL ODMOWA | #1 {head[:7]} | {reason.format(main=main[:7])}"
    assert github.merges() == []


def test_main_przesuniety_w_trakcie_sprawdzania_zatrzymuje_merge(tmp_path: Path) -> None:
    github = FakeGitHub(tmp_path, {"kod/__init__.py": SUM})
    moved = github.commit_on(github.start, {"kod/nowe.py": "NOWE: int = 1\n"}, "main w trakcie")
    pushes_main = (
        "import subprocess\n\n"
        f"subprocess.run(['git', '-C', {str(github.checkout)!r}, 'push', '--quiet', 'origin', '{moved}:refs/heads/main'], check=True)\n"
        "print('CI LOKALNIE OK')\n"
    )
    head = github.open_pull(1, {"tools/ci_lokalnie.py": pushes_main})
    github.comment(1, f"WERDYKT: PASS {head}")

    answered = github.run("1")

    assert answered.returncode == 1, answered.stdout + answered.stderr
    assert _last_line(answered) == f"SCAL ODMOWA | #1 {head[:7]} | main zmienił się w trakcie sprawdzania, uruchom ponownie"
    assert github.merges() == []


def test_baza_przesunieta_z_innego_klonu_przed_sprawdzeniem_jest_baza_scalenia(tmp_path: Path) -> None:
    github = FakeGitHub(tmp_path, {"kod/__init__.py": SUM})
    head = github.open_pull(1, {"kod/inne.py": "INNE: int = 1\n"})
    github.comment(1, f"WERDYKT: PASS {head}")
    other = tmp_path / "inny-klon"
    git(tmp_path, "clone", "--quiet", str(tmp_path / "origin.git"), str(other))
    (other / "kod" / "nowe.py").write_text("NOWE: int = 1\n", encoding="utf-8")
    moved = commit(other, "main z innego klonu")
    git(other, "push", "--quiet", "origin", "HEAD:main")

    answered = github.run("1")

    assert answered.returncode == 0, answered.stdout + answered.stderr
    assert f"| scalony do main jako {git(github.origin, 'rev-parse', 'refs/heads/main')[:7]} (baza {moved[:7]}) |" in _last_line(answered)
    assert len(github.merges()) == 1


def test_sprzatanie_po_czasie_nie_odwoluje_scalenia(tmp_path: Path) -> None:
    hangs = "import time\n\ntime.sleep(600)\n"
    github = FakeGitHub(tmp_path, {"kod/__init__.py": SUM, "tools/sprzatanie.py": hangs})
    head = github.open_pull(1, {"kod/inne.py": "INNE: int = 1\n"})
    tool = github.checkout / "tools" / "scal_pr.py"
    tool.write_text(tool.read_text(encoding="utf-8").replace("CLEANUP_TIMEOUT_S = 300", "CLEANUP_TIMEOUT_S = 1"), encoding="utf-8")
    github.comment(1, f"WERDYKT: PASS {head}")

    answered = github.run("1")

    assert answered.returncode == 0, answered.stdout + answered.stderr
    assert _last_line(answered).endswith("| UWAGA: sprzątanie przerwane po 1 s, uruchom je ponownie")
    assert len(github.merges()) == 1

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
import json, pathlib, sys

here = pathlib.Path(sys.argv[0]).parent
arguments = sys.argv[1:]
pulls = json.loads((here / "pulls.json").read_text())
if arguments[:2] == ["pr", "view"]:
    pull = pulls[arguments[2]]
    print(json.dumps({field: pull[field] for field in arguments[arguments.index("--json") + 1].split(",")}))
elif arguments[:2] == ["pr", "merge"]:
    if arguments[arguments.index("--match-head-commit") + 1] != pulls[arguments[2]]["headRefOid"]:
        sys.exit("HEAD PR zmienił się")
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
NO_PASS = "werdykt: brak komentarza „WERDYKT: PASS {short}”"
UNREADABLE = "werdykt nieczytelny dla {short}: pierwsza linia to nie „WERDYKT: PASS|FAIL <SHA>”"


class FakeGitHub:
    def __init__(self, tmp_path: Path, files: dict[str, str]) -> None:
        origin = tmp_path / "origin.git"
        git(tmp_path, "init", "--quiet", "--bare", str(origin))
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
        comments = self.pulls[str(number)]["comments"]
        assert isinstance(comments, list)
        comments.append({"body": body, "authorAssociation": association, "author": {"login": "recenzent"}})
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
    assert merged.returncode == 0, merged.stdout + merged.stderr
    assert _last_line(merged) == f"SCAL OK | #1 {head[:7]} | scalony do main {main[:7]} | sprzątanie: SPRZĄTANIE OK | 0 usuniętych"
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
        (GREEN, [("Recenzja: WERDYKT: PASS {head}", "OWNER")], NO_PASS),
        (GREEN, [("WERDYKT: PASS {head} — bez uwag", "OWNER")], UNREADABLE),
        (GREEN, [("WERDYKT: PASS {head6}", "OWNER")], UNREADABLE),
        (GREEN, [("WERDYKT: PASS {head}", "OWNER"), ("WERDYKT: FAIL {head}", "MEMBER")], "werdykt: FAIL dla {short}"),
        (
            [_check_run("COMPLETED", "FAILURE")],
            [],
            "CI: „Required CI status” FAILURE; werdykt: brak komentarza „WERDYKT: PASS {short}”",
        ),
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
        "pass-nie-w-pierwszej-linii",
        "pass-z-dopiskiem-w-pierwszej-linii",
        "pass-z-6-znakami-sha",
        "fail-po-pass",
        "wszystkie-przyczyny-naraz",
    ],
)
def test_bez_zielonego_ci_albo_werdyktu_pass_dla_head_pr_nie_jest_scalany(
    tmp_path: Path, ci: list[dict[str, str | None]], comments: list[tuple[str, str]], reason: str
) -> None:
    github = FakeGitHub(tmp_path, {"kod/__init__.py": SUM})
    old = github.open_pull(1, {"kod/inne.py": "INNE: int = 1\n"})
    head = github.commit_on(old, {"kod/inne.py": "INNE: int = 2\n"}, "PR 1 po poprawce")
    git(github.checkout, "push", "--quiet", "--force", "origin", f"{head}:refs/pull/1/head")
    github.update(1, headRefOid=head, statusCheckRollup=ci)
    for body, association in comments:
        github.comment(1, body.format(head=head, old=old, head6=head[:6]), association)

    answered = github.run("1")

    assert answered.returncode == 1, answered.stdout + answered.stderr
    assert _last_line(answered) == f"SCAL ODMOWA | #1 {head[:7]} | {reason.format(short=head[:7])}"
    assert github.merges() == []


@pytest.mark.parametrize(
    "fail",
    [
        "WERDYKT: FAIL {head} — brak testu",
        "WERDYKT: FAIL {head}.",
        "**WERDYKT: FAIL {head}**",
        "WERDYKT: FAIL",
        "Werdykt: FAIL {head}",
        "WERDYKT:  FAIL {head}",
    ],
    ids=["dopisek", "kropka", "markdown", "bez-sha", "male-litery", "dwie-spacje"],
)
def test_nieczytelny_werdykt_dla_head_po_pass_blokuje_merge(tmp_path: Path, fail: str) -> None:
    github = FakeGitHub(tmp_path, {"kod/__init__.py": SUM})
    head = github.open_pull(1, {"kod/inne.py": "INNE: int = 1\n"})
    github.comment(1, f"WERDYKT: PASS {head}")
    github.comment(1, fail.format(head=head))

    answered = github.run("1")

    assert answered.returncode == 1, answered.stdout + answered.stderr
    assert _last_line(answered) == f"SCAL ODMOWA | #1 {head[:7]} | {UNREADABLE.format(short=head[:7])}"
    assert github.merges() == []


@pytest.mark.parametrize(
    "comments",
    [
        ["WERDYKT: PASS {head}", "Werdykt: FAIL {old} — poprawione w nowym commicie"],
        ["**Werdykt:** FAIL {head}", "WERDYKT: PASS {head}"],
    ],
    ids=["nieczytelny-dla-starszego-commitu", "pass-po-nieczytelnym"],
)
def test_werdykt_nieczytelny_dla_innego_commitu_albo_starszy_niz_pass_nie_blokuje(tmp_path: Path, comments: list[str]) -> None:
    github = FakeGitHub(tmp_path, {"kod/__init__.py": SUM})
    old = github.open_pull(1, {"kod/inne.py": "INNE: int = 1\n"})
    head = github.commit_on(old, {"kod/inne.py": "INNE: int = 2\n"}, "PR 1 po poprawce")
    git(github.checkout, "push", "--quiet", "--force", "origin", f"{head}:refs/pull/1/head")
    github.update(1, headRefOid=head)
    for body in comments:
        github.comment(1, body.format(head=head, old=old))

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
    assert _last_line(answered).startswith(f"SCAL OK | #1 {head[:7]} | scalony do main {moved[:7]}")
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

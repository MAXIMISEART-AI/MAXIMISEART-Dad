"""Jedyna droga merge'a PR przez agenta: ``gh pr merge`` tylko po sprawdzeniu gotowości tuż przed nim.

Narzędzie scala PR numer N do jego bazy, gdy jednocześnie:

1. PR jest otwarty, nie jest szkicem i nie pochodzi z forka (z forka ruff i mypy biegłyby na obcym kodzie);
2. check ``Required CI status`` z GitHub Actions na HEAD PR skończył się sukcesem (jak w rulesecie ``main``:
   CheckRun z workflow, nie status commitu, który może ustawić każdy z prawem zapisu);
3. najnowszy komentarz werdyktu dla HEAD PR to ``PASS``;
4. HEAD PR scala się z bieżącą bazą z ``origin`` bez konfliktu, a ruff i mypy dla obu systemów przechodzą na
   scalonym drzewie (``scalenia_pr.merge_verdict``, jak status ``scalenie z main``, ale teraz, nie po pushu).

Komentarz werdyktu to komentarz na PR, którego pierwsza linia to dokładnie ``WERDYKT: PASS <SHA>`` albo
``WERDYKT: FAIL <SHA>``, gdzie ``<SHA>`` to HEAD PR małymi literami (pełny albo co najmniej 7 pierwszych znaków);
dalsze linie to znaleziska. Pisze go niezależny recenzent, nie autor zmiany: ``PASS`` mówi, że przegląd nie znalazł
problemów, a skille ``verify-*`` z ``tools/skille_dla_zmiany.py`` przeszły na tym SHA. Liczą się tylko komentarze
kont z prawem zapisu (``OWNER``, ``MEMBER``, ``COLLABORATOR``). Rozstrzyga najnowszy komentarz werdyktu dla
HEAD, więc ``FAIL`` po ``PASS`` odbiera zgodę, a werdykt starszego commitu nie przechodzi na nowy push.
Ścisły jest tylko ``PASS``: komentarz, którego pierwsza linia zaczyna się od „werdykt” (bez względu na wielkość
liter, znaczniki markdown i odstępy), a nie jest żadną z dwóch linii powyżej, jest werdyktem nieczytelnym. Gdy
nie podaje SHA albo któryś jego SHA wskazuje HEAD, blokuje merge tak jak ``FAIL``: literówka w ``FAIL`` nie
może zostawić ważnego ``PASS``.

Gdy któryś warunek nie zachodzi, narzędzie nie scala i kończy się linią ``SCAL ODMOWA | #N <sha> | <przyczyny>``.
Warunki 1–3 sprawdza razem i podaje wszystkie przyczyny; warunek 4 trwa dłużej, więc biegnie dopiero po nich.
Przed merge'em sprawdza, że baza w ``origin`` nie przesunęła się w trakcie sprawdzania, a ``gh pr merge
--match-head-commit`` odrzuca PR, którego HEAD zmienił się po sprawdzeniu. Po merge'u uruchamia sprzątanie
lokalnych gałęzi i worktree ``tools/sprzatanie.py``, jeśli istnieje; sprzątanie, które przekroczy czas, kończy
się ostrzeżeniem w linii ``SCAL OK``, bo PR jest już scalony. Kod 0 i ``SCAL OK`` znaczą, że PR jest scalony
(albo z ``--bez-merge``: że byłby); kod 1 to odmowa albo błąd narzędzia (``SCAL FAIL``).

Komentarze i checki pochodzą z jednego ``gh pr view --json``, które doczytuje wszystkie strony komentarzy
(sprawdzone na PR z 337 komentarzami, gh 2.101).

    .venv/bin/python tools/scal_pr.py 336               # sprawdza i scala
    .venv/bin/python tools/scal_pr.py 336 --bez-merge   # tylko sprawdza
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
import json
from pathlib import Path
import re
import subprocess
import sys

import potomne
import scalenia_pr

ROOT = Path(__file__).resolve().parents[1]
REQUIRED_CHECK = "Required CI status"
VERDICT_LINE = re.compile(r"WERDYKT: (PASS|FAIL) ([0-9a-f]{7,40})")
VERDICT_START = re.compile(r"[\s*_#>`~]*werdykt", re.IGNORECASE)
SHA_LIKE = re.compile(r"(?<![0-9a-z])[0-9a-f]{7,}(?![0-9a-z])", re.IGNORECASE)
TRUSTED = frozenset({"OWNER", "MEMBER", "COLLABORATOR"})
CLEANUP = ROOT / "tools" / "sprzatanie.py"
CLEANUP_TIMEOUT_S = 300


@dataclass(frozen=True)
class Pull:
    number: int
    title: str
    head: str
    base: str
    problems: tuple[str, ...]


class _Refused(Exception):
    pass


def _gh(*arguments: str) -> str:
    done = subprocess.run(
        ["gh", *arguments],
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=scalenia_pr.GITHUB_TIMEOUT_S,
        check=True,
    )
    return done.stdout


def _ci_problem(rollup: list[dict[str, str | None]]) -> str | None:
    results = []
    for check in rollup:
        if check.get("name") == REQUIRED_CHECK and check.get("workflowName"):
            completed = check.get("status") == "COMPLETED"
            results.append((check.get("conclusion") if completed else check.get("status")) or "?")
    if not results:
        return f"CI: brak „{REQUIRED_CHECK}” z GitHub Actions na HEAD"
    failed = [result for result in results if result != "SUCCESS"]
    return f"CI: „{REQUIRED_CHECK}” {', '.join(failed)}" if failed else None


def _verdict_problem(comments: list[dict[str, object]], head: str) -> str | None:
    latest = None
    for comment in comments:
        if comment["authorAssociation"] not in TRUSTED:
            continue
        line = str(comment["body"]).partition("\n")[0].strip()
        found = VERDICT_LINE.fullmatch(line)
        if found:
            if head.startswith(found[2]):
                latest = found[1]
        elif VERDICT_START.match(line):
            named = [sha.lower()[:40] for sha in SHA_LIKE.findall(line)]
            if not named or any(head.startswith(sha) for sha in named):
                latest = "nieczytelny"
    short = head[:7]
    if latest is None:
        return f"werdykt: brak komentarza „WERDYKT: PASS {short}”"
    if latest == "nieczytelny":
        return f"werdykt nieczytelny dla {short}: pierwsza linia to nie „WERDYKT: PASS|FAIL <SHA>”"
    return None if latest == "PASS" else f"werdykt: FAIL dla {short}"


def _pull(number: int) -> Pull:
    fields = "number,title,state,isDraft,isCrossRepository,baseRefName,headRefOid,statusCheckRollup,comments"
    pull = json.loads(_gh("pr", "view", str(number), "--json", fields))
    problems = []
    if pull["state"] != "OPEN":
        problems.append(f"PR nie jest otwarty: {pull['state']}")
    if pull["isDraft"]:
        problems.append("PR jest szkicem")
    if pull["isCrossRepository"]:
        problems.append("PR z forka")
    problems += filter(None, [_ci_problem(pull["statusCheckRollup"]), _verdict_problem(pull["comments"], pull["headRefOid"])])
    return Pull(number, pull["title"], pull["headRefOid"], pull["baseRefName"], tuple(problems))


def _remote_base(base: str) -> str:
    listed = potomne.run(["git", "ls-remote", "origin", f"refs/heads/{base}"], cwd=ROOT, timeout=scalenia_pr.GITHUB_TIMEOUT_S)
    listed.check_returncode()
    return listed.stdout.partition("\t")[0]


def _check(pull: Pull) -> str:
    """SHA bazy, z którą scalenie przeszło."""

    if pull.problems:
        raise _Refused("; ".join(pull.problems))
    checked = scalenia_pr.PullRequest(pull.number, pull.title, pull.head)
    base = scalenia_pr.fetch(pull.base, [checked])
    where = f"{pull.base} {base[:7]}"
    print(f"== #{pull.number} {pull.head[:7]} na {where}", flush=True)
    with potomne.commit_copy(ROOT, base) as copy:
        verdict = scalenia_pr.merge_verdict(copy, where, base, None, checked)
    if verdict.state != "success":
        raise _Refused(verdict.description)
    return base


def _clean_up() -> str:
    if not CLEANUP.exists():
        return f"sprzątanie pominięte: brak {CLEANUP.relative_to(ROOT).as_posix()}"
    try:
        done = potomne.run([sys.executable, str(CLEANUP)], cwd=ROOT, timeout=CLEANUP_TIMEOUT_S, echo=True)
    except subprocess.TimeoutExpired:
        return f"UWAGA: sprzątanie przerwane po {CLEANUP_TIMEOUT_S} s, uruchom je ponownie"
    result = done.stdout.rstrip().rpartition("\n")[2]
    return f"sprzątanie: {result or f'kod {done.returncode}'}"


def _merge(number: int, *, merge: bool) -> int:
    pull = _pull(number)
    where = f"#{pull.number} {pull.head[:7]}"
    try:
        base = _check(pull)
        if merge and _remote_base(pull.base) != base:
            raise _Refused(f"{pull.base} zmienił się w trakcie sprawdzania, uruchom ponownie")
    except _Refused as refusal:
        print(f"SCAL ODMOWA | {where} | {refusal}")
        return 1
    if not merge:
        print(f"SCAL OK | {where} | gotowy do merge'a z {pull.base} {base[:7]}, bez merge'a (--bez-merge)")
        return 0
    _gh("pr", "merge", str(number), "--merge", "--match-head-commit", pull.head)
    print(f"SCAL OK | {where} | scalony do {pull.base} {base[:7]} | {_clean_up()}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("numer", type=int, help="Numer PR.")
    parser.add_argument("--bez-merge", action="store_true", help="Sprawdź gotowość, ale nie scalaj.")
    args = parser.parse_args(argv)
    try:
        return _merge(args.numer, merge=not args.bez_merge)
    except subprocess.CalledProcessError as error:
        command = " ".join(str(part) for part in error.cmd)
        print(f"SCAL FAIL | {command}: {(error.stderr or error.stdout or '').strip()}")
    except (subprocess.TimeoutExpired, OSError) as error:
        print(f"SCAL FAIL | {error}")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())

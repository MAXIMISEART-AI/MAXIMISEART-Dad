"""Jedyna droga merge'a PR przez agenta: ``gh pr merge`` tylko po sprawdzeniu gotowości tuż przed nim.

Narzędzie scala PR numer N do jego bazy, gdy jednocześnie:

1. PR jest otwarty, nie jest szkicem i nie pochodzi z forka (z forka ruff i mypy biegłyby na obcym kodzie);
2. check ``Required CI status`` z GitHub Actions na HEAD PR skończył się sukcesem (jak w rulesecie ``main``:
   CheckRun z workflow, nie status commitu, który może ustawić każdy z prawem zapisu);
3. najnowszy werdykt dla HEAD PR to ``PASS``;
4. HEAD PR scala się z bieżącą bazą z ``origin`` bez konfliktu, a ruff i mypy dla obu systemów przechodzą na
   scalonym drzewie (``scalenia_pr.merge_verdict``, jak status ``scalenie z main``, ale teraz, nie po pushu).

Werdykty to komentarze i recenzje PR kont z prawem zapisu (``OWNER``, ``MEMBER``, ``COLLABORATOR``), w kolejności
utworzenia. Zgoda to komentarz albo recenzja, której pierwsza niepusta linia to dokładnie ``WERDYKT: PASS <SHA>``,
gdzie ``<SHA>`` to HEAD PR małymi literami (pełny albo co najmniej 7 pierwszych znaków); dalsze linie to
znaleziska. Pisze ją niezależny recenzent, nie autor zmiany: ``PASS`` mówi, że przegląd nie znalazł problemów,
a skille ``verify-*`` z ``tools/skille_dla_zmiany.py`` przeszły na tym SHA. Ścisła jest tylko zgoda. Sprzeciwem
jest każdy inny werdykt, którego linia po zamianie na odstęp wszystkiego, co nie jest literą ani cyfrą (markdown,
emoji, cytat, interpunkcja, BOM, znaki zerowej szerokości), zawiera słowo ``FAIL`` bez względu na wielkość liter
albo zaczyna się od „werdykt”, „weryfikacj” lub „verdict”. Liczy się pierwsza niepusta linia i każda dalsza, która
zaczyna się od takiego słowa i zawiera ``FAIL`` (nagłówek nad werdyktem). Sprzeciw nie dotyczy HEAD tylko wtedy,
gdy linia podaje SHA innego commitu (co najmniej 7 znaków hex małymi literami, które git zna jako początek SHA
commitu), a nie podaje HEAD;
liczby i słowa, które nie są commitem, go nie zwalniają. Rozstrzyga najnowszy werdykt dla HEAD: sprzeciw po
``PASS`` odbiera zgodę, nowszy ``PASS`` ją przywraca, a werdykt starszego commitu nie przechodzi na nowy push.
Komentarz edytowany liczy się z treścią po edycji, ale w miejscu utworzenia, a ukryty komentarz nadal się liczy.

Gdy któryś warunek nie zachodzi, narzędzie nie scala i kończy się linią ``SCAL ODMOWA | #N <sha> | <przyczyny>``.
Warunki 1–3 sprawdza razem i podaje wszystkie przyczyny; warunek 4 trwa dłużej, więc biegnie dopiero po nich.
Przed merge'em sprawdza, że baza w ``origin`` nie przesunęła się w trakcie sprawdzania, a ``gh pr merge
--match-head-commit`` odrzuca PR, którego HEAD zmienił się po sprawdzeniu. Po merge'u uruchamia sprzątanie
lokalnych gałęzi i worktree ``tools/sprzatanie.py``, jeśli istnieje; sprzątanie, które przekroczy czas, kończy
się ostrzeżeniem w linii ``SCAL OK``, bo PR jest już scalony. Kod 0 i ``SCAL OK`` znaczą, że PR jest scalony
(albo z ``--bez-merge``: że byłby); kod 1 to odmowa albo błąd narzędzia (``SCAL FAIL``).

Komentarze, recenzje i checki pochodzą z jednego ``gh pr view --json``, które doczytuje wszystkie strony
komentarzy (sprawdzone na PR z 337 komentarzami, gh 2.101). SHA werdyktów sprawdza git po pobraniu HEAD PR.

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
PASS_LINE = re.compile(r"WERDYKT: PASS ([0-9a-f]{7,40})")
VERDICT_WORDS = ("werdykt", "weryfikacj", "verdict")
SHA = re.compile(r"[0-9a-f]{7,}")
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
    verdicts: tuple[dict[str, object], ...]


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


def _words(line: str) -> list[str]:
    return "".join(char if char.isalnum() else " " for char in line).split()


def _fail(words: list[str]) -> bool:
    return "fail" in (word.lower() for word in words)


def _verdict_word(words: list[str]) -> bool:
    return words[0].lower().startswith(VERDICT_WORDS)


def _known_commit(sha: str) -> bool:
    found = subprocess.run(
        ["git", "rev-parse", "--verify", "--quiet", f"{sha}^{{commit}}"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )
    return found.stdout.startswith(sha)


def _against_head(words: list[str], head: str) -> bool:
    shas = [word for word in words if SHA.fullmatch(word)]
    return any(head.startswith(sha) for sha in shas) or not any(_known_commit(sha) for sha in shas)


def _verdict_problem(verdicts: list[dict[str, object]], head: str) -> str | None:
    """Przyczyna odmowy z werdyktów w kolejności utworzenia; ``head`` musi być w repozytorium."""

    latest = None
    for verdict in verdicts:
        if verdict["authorAssociation"] not in TRUSTED:
            continue
        lines = [line.strip() for line in str(verdict["body"]).split("\n") if _words(line)]
        if not lines:
            continue
        found = PASS_LINE.fullmatch(lines[0])
        if found:
            if head.startswith(found[1]):
                latest = "PASS"
            continue
        first, *rest = map(_words, lines)
        objecting = [first] if _fail(first) or _verdict_word(first) else []
        objecting += [words for words in rest if _verdict_word(words) and _fail(words)]
        if any(_against_head(words, head) for words in objecting):
            latest = "sprzeciw"
    short = head[:7]
    if latest is None:
        return f"werdykt: brak komentarza ani recenzji „WERDYKT: PASS {short}”"
    return None if latest == "PASS" else f"werdykt: sprzeciw dla {short} bez nowszego „WERDYKT: PASS {short}”"


def _pull(number: int) -> Pull:
    fields = "number,title,state,isDraft,isCrossRepository,baseRefName,headRefOid,statusCheckRollup,comments,reviews"
    pull = json.loads(_gh("pr", "view", str(number), "--json", fields))
    problems = []
    if pull["state"] != "OPEN":
        problems.append(f"PR nie jest otwarty: {pull['state']}")
    if pull["isDraft"]:
        problems.append("PR jest szkicem")
    if pull["isCrossRepository"]:
        problems.append("PR z forka")
    problems += filter(None, [_ci_problem(pull["statusCheckRollup"])])
    verdicts = [*pull["comments"], *pull["reviews"]]
    verdicts.sort(key=lambda verdict: verdict.get("createdAt") or verdict.get("submittedAt") or "")
    return Pull(number, pull["title"], pull["headRefOid"], pull["baseRefName"], tuple(problems), tuple(verdicts))


def _remote_base(base: str) -> str:
    listed = potomne.run(["git", "ls-remote", "origin", f"refs/heads/{base}"], cwd=ROOT, timeout=scalenia_pr.GITHUB_TIMEOUT_S)
    listed.check_returncode()
    return listed.stdout.partition("\t")[0]


def _check(pull: Pull) -> str:
    """SHA bazy, z którą scalenie przeszło."""

    checked = scalenia_pr.PullRequest(pull.number, pull.title, pull.head)
    base = scalenia_pr.fetch(pull.base, [checked])
    problems = [*pull.problems, *filter(None, [_verdict_problem(list(pull.verdicts), pull.head)])]
    if problems:
        raise _Refused("; ".join(problems))
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

"""Jedyna droga merge'a PR przez agenta: ``gh pr merge`` tylko po sprawdzeniu gotowości tuż przed nim.

Narzędzie scala PR numer N do jego bazy, gdy jednocześnie:

1. PR jest otwarty, nie jest szkicem i nie pochodzi z forka (z forka ruff i mypy biegłyby na obcym kodzie);
2. check ``Required CI status`` z GitHub Actions na HEAD PR skończył się sukcesem (jak w rulesecie ``main``:
   CheckRun z workflow, nie status commitu, który może ustawić każdy z prawem zapisu);
3. najnowszy werdykt dla HEAD PR to ``PASS``;
4. HEAD PR scala się z bieżącą bazą z ``origin`` bez konfliktu, a ruff i mypy dla obu systemów przechodzą na
   scalonym drzewie (``scalenia_pr.merge_verdict``, jak status ``scalenie z main``, ale teraz, nie po pushu).

Mutacje zmienionych linii nie biegną na PR i nie czeka na nie: biegną nocą na ``main`` (ADR 0021,
``tools/mutacje_nocne.py``).

Werdykty to komentarze i recenzje PR kont z prawem zapisu (``OWNER``, ``MEMBER``, ``COLLABORATOR``), w kolejności
utworzenia; nieopublikowana recenzja (``PENDING``) się nie liczy. Werdykt to komentarz albo recenzja, której pierwsza
niepusta linia, bez odstępów na brzegach, to dokładnie ``WERDYKT: PASS <SHA>`` (zgoda) albo ``WERDYKT: FAIL <SHA>``
(sprzeciw), gdzie ``<SHA>`` to pełny SHA HEAD PR małymi literami; dalsze linie to znaleziska i ich nie czyta.
Sprzeciwem jest też recenzja w stanie ``CHANGES_REQUESTED``. Inny tekst, także ``FAIL`` w prozie albo werdykt ze
skróconym SHA, nie jest werdyktem. Zgodę pisze niezależny recenzent, nie autor zmiany: ``PASS`` mówi, że przegląd
nie znalazł problemów, a skille ``verify-*`` z linii ``SKILLE VERIFY`` ``tools/skille_dla_zmiany.py`` przeszły na
tym SHA (ich polecenia z linii ``LICZY CI`` w CI, reszta workflow u agenta). Rozstrzyga najnowszy werdykt dla HEAD:
sprzeciw po ``PASS`` odbiera zgodę, nowszy ``PASS`` ją przywraca, a werdykt starszego commitu nie przechodzi na nowy
push. Komentarz edytowany liczy się z treścią po edycji, ale w miejscu utworzenia, a ukryty komentarz nadal się liczy.

Gdy któryś warunek nie zachodzi, narzędzie nie scala i kończy się linią ``SCAL ODMOWA | #N <sha> | <przyczyny>``.
Warunki 1–3 sprawdza razem i podaje wszystkie przyczyny; warunek 4 trwa dłużej, więc biegnie dopiero po nich.
Przed merge'em sprawdza, że baza w ``origin`` nie przesunęła się w trakcie sprawdzania, a ``gh pr merge
--match-head-commit`` odrzuca PR, którego HEAD zmienił się po sprawdzeniu. Po merge'u uruchamia
``tools/sprzatanie.py``, jeśli istnieje, i podaje ostatnią linię jego raportu: bez ``--usun`` sprzątanie niczego nie
usuwa, tylko mówi, które lokalne gałęzie i worktree można usunąć. Sprzątanie, które przekroczy czas, kończy się
ostrzeżeniem w linii ``SCAL OK``, bo PR jest już scalony.

Po merge'u do domyślnej gałęzi repozytorium, przed sprzątaniem, zamyka jego otwarte issues, które opis PR wskazuje
słowem „Naprawia” na początku linii, po najwyżej trzech spacjach i znaczniku listy ``-`` albo ``*`` ze spacją:
``Naprawia #490``, kilka numerów (``Naprawia #490, #491``, ``#490 i #491``, ``oraz``) i kilka linii. GitHub tego słowa
nie zna, więc bez narzędzia takie issues zostawały otwarte. Każde dostaje komentarz z numerem PR i pełnym SHA commitu
merge'a, a linia ``SCAL OK`` podaje ``zamknięte: #N``. Nie zamyka: „naprawia” w środku zdania (także „nie naprawia
#N”), ``#N`` bez „Naprawia”, tekstu w bloku albo fragmencie kodu, cytatu ani komentarza HTML, numeru PR, issue już
zamkniętego, issues, które GitHub zamyka sam (``closingIssuesReferences``: ``Closes``, ``Fixes``, ``Resolves``), ani
odwołań do innego repozytorium, np. ``Naprawia MAXIMISEART-AI/MAXIMISEART-Dad-zgloszenia#12, #13``, w którym ``#13``
też należy do Zgłoszeń: zamknięte Zgłoszenie mówi Centrum taty, że poprawka czeka na aktualizację, a merge do ``main``
to jeszcze nie Wydanie. Jak w CommonMark, linia wcięta o cztery spacje albo tabulatorem (także po znaczniku listy o
pięć spacji) to blok kodu, a blok z płotem kończy tylko płot z tym samym znakiem, nie krótszy i bez tekstu po nim.
O domyślną gałąź pyta GitHuba (``gh repo view``) tylko wtedy, gdy opis ma takie numery; gdy jej nie poda, narzędzie
niczego nie zamyka, tylko ostrzega ``UWAGA: GitHub nie podał domyślnej gałęzi, nie zamknięto #N, zamknij ręcznie``.
Jak GitHub przy ``Closes``, merge do innej gałęzi (stos PR-ów) niczego nie zamyka, a linia podaje ``bez zamykania #N:
baza <gałąź> to nie <domyślna>``. Gdy GitHub po merge'u nie poda commitu merge'a, narzędzie nie zamyka, bo nie wie,
czy PR wszedł do gałęzi (np. czeka w kolejce merge'a), tylko ostrzega ``UWAGA: GitHub nie podał commitu merge'a, nie
zamknięto #N, zamknij ręcznie``. Każdy błąd przy zamykaniu (``gh`` z błędem albo po czasie, odpowiedź bez stanu
issue) kończy się ostrzeżeniem ``UWAGA: nie zamknięto #N, zamknij ręcznie`` w linii ``SCAL OK`` i kodem 0, bo PR jest
już scalony. Z ``--bez-merge`` niczego nie zamyka, a linia podaje ``po merge'u zamknie: #N``.

Kod 0 i ``SCAL OK`` znaczą, że PR jest scalony (albo z ``--bez-merge``: że byłby); linia po merge'u podaje SHA
commitu merge'a i bazy, z którą sprawdziła scalenie. Kod 1 to odmowa albo błąd narzędzia (``SCAL FAIL``).

Komentarze, recenzje i checki pochodzą z jednego ``gh pr view --json``, które doczytuje wszystkie strony
komentarzy (sprawdzone na PR z 337 komentarzami, gh 2.101).

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
VERDICT_LINE = re.compile(r"WERDYKT: (PASS|FAIL) ([0-9a-f]{40})")
TRUSTED = frozenset({"OWNER", "MEMBER", "COLLABORATOR"})
CLEANUP = ROOT / "tools" / "sprzatanie.py"
CLEANUP_TIMEOUT_S = 300
_REFERENCE = r"(?:[\w.-]+/[\w.-]+)?#\d+"
FIXES = re.compile(
    rf"^ {{0,3}}(?:[-*](?: {{1,4}}|\t))?naprawia[ \t]+({_REFERENCE}(?:[ \t]*(?:,|\bi\b|\boraz\b)[ \t]*{_REFERENCE})*)",
    re.IGNORECASE | re.MULTILINE,
)
REFERENCE = re.compile(r"(?:([\w.-]+/[\w.-]+))?#(\d+)")
HIDDEN = re.compile(
    r"^ {0,3}(`{3,}).*?(?:^ {0,3}\1`*[ \t]*\r?$|\Z)|^ {0,3}(~{3,}).*?(?:^ {0,3}\2~*[ \t]*\r?$|\Z)|<!--.*?(?:-->|\Z)"
    r"|(?<!`)(`+)(?!`)(?:(?!\n[ \t]*\n).)*?(?<!`)\3(?!`)",
    re.MULTILINE | re.DOTALL,
)


@dataclass(frozen=True)
class Pull:
    number: int
    title: str
    head: str
    base: str
    problems: tuple[str, ...]
    verdicts: tuple[dict[str, object], ...]
    repository: str
    fixes: tuple[int, ...]


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


def _verdict(verdict: dict[str, object], head: str) -> str | None:
    """``PASS`` albo ``FAIL`` dla ``head``; ``None``, gdy komentarz albo recenzja nie jest werdyktem dla ``head``."""

    if verdict["authorAssociation"] not in TRUSTED or verdict.get("state") == "PENDING":
        return None
    if verdict.get("state") == "CHANGES_REQUESTED":
        return "FAIL"
    lines = [line.strip() for line in str(verdict["body"]).splitlines() if line.strip()]
    found = VERDICT_LINE.fullmatch(lines[0]) if lines else None
    return found[1] if found and found[2] == head else None


def _verdict_problem(verdicts: tuple[dict[str, object], ...], head: str) -> str | None:
    """Przyczyna odmowy z najnowszego werdyktu dla ``head`` z werdyktów w kolejności utworzenia."""

    latest = None
    for verdict in verdicts:
        latest = _verdict(verdict, head) or latest
    if latest is None:
        return f"werdykt: brak komentarza ani recenzji „WERDYKT: PASS {head}”"
    return None if latest == "PASS" else f"werdykt: FAIL dla {head[:7]} bez nowszego „WERDYKT: PASS {head}”"


def fixed_issues(body: str, repository: str) -> tuple[int, ...]:
    """Numery z linii „Naprawia #N” opisu PR, które wskazują ``repository`` (``właściciel/nazwa``), bez ukrytego tekstu."""

    numbers: list[int] = []
    # Ukryty tekst zastępuje znak, a nie nic, żeby „Naprawia” za fragmentem kodu nie zaczynało linii.
    for listed in FIXES.finditer(HIDDEN.sub("\0", body)):
        owner = repository
        for reference in REFERENCE.finditer(listed[1]):
            owner = reference[1] or owner
            if owner.casefold() == repository.casefold() and int(reference[2]) not in numbers:
                numbers.append(int(reference[2]))
    return tuple(numbers)


def _pull(number: int) -> Pull:
    fields = (
        "number,title,state,isDraft,isCrossRepository,baseRefName,headRefOid,statusCheckRollup,comments,reviews,"
        "url,body,closingIssuesReferences"
    )
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
    repository = "/".join(pull["url"].split("/")[3:5])
    closed_by_github = {
        issue["number"]
        for issue in pull["closingIssuesReferences"]
        if f"{issue['repository']['owner']['login']}/{issue['repository']['name']}".casefold() == repository.casefold()
    }
    fixes = tuple(issue for issue in fixed_issues(pull["body"], repository) if issue not in closed_by_github)
    return Pull(
        number,
        pull["title"],
        pull["headRefOid"],
        pull["baseRefName"],
        tuple(problems),
        tuple(verdicts),
        repository,
        fixes,
    )


def _remote_base(base: str) -> str:
    listed = potomne.run(["git", "ls-remote", "origin", f"refs/heads/{base}"], cwd=ROOT, timeout=scalenia_pr.GITHUB_TIMEOUT_S)
    listed.check_returncode()
    return listed.stdout.partition("\t")[0]


def _check(pull: Pull) -> str:
    """SHA bazy, z którą scalenie przeszło."""

    checked = scalenia_pr.PullRequest(pull.number, pull.title, pull.head)
    base = scalenia_pr.fetch(pull.base, [checked])
    problems = [*pull.problems, *filter(None, [_verdict_problem(pull.verdicts, pull.head)])]
    if problems:
        raise _Refused("; ".join(problems))
    where = f"{pull.base} {base[:7]}"
    print(f"== #{pull.number} {pull.head[:7]} na {where}", flush=True)
    with potomne.commit_copy(ROOT, base) as copy:
        verdict = scalenia_pr.merge_verdict(copy, where, base, None, checked)
    if verdict.state != "success":
        raise _Refused(verdict.description)
    return base


def _close_fixed(pull: Pull, *, merged: bool, merge_commit: str | None) -> str:
    """Zamyka otwarte issues z ``pull.fixes`` z komentarzem o merge'u, a przed merge'em tylko je podaje."""

    if not pull.fixes:
        return ""
    listed = ", ".join(f"#{number}" for number in pull.fixes)
    try:
        default_branch = str(json.loads(_gh("repo", "view", pull.repository, "--json", "defaultBranchRef"))["defaultBranchRef"]["name"])
    except Exception:  # noqa: BLE001 - po merge'u każdy błąd to tylko ostrzeżenie w linii SCAL OK, bo PR jest już scalony
        unread = f"nie zamknięto {listed}, zamknij ręcznie" if merged else f"nie sprawdzono {listed}"
        return f" | UWAGA: GitHub nie podał domyślnej gałęzi, {unread}"
    if pull.base != default_branch:
        return f" | bez zamykania {listed}: baza {pull.base} to nie {default_branch}"
    closes = merged and merge_commit is not None
    open_issues, failed = [], []
    for number in pull.fixes:
        try:
            issue = json.loads(_gh("api", f"repos/{pull.repository}/issues/{number}"))
            if "pull_request" in issue or issue["state"] != "open":
                continue
            if closes:
                comment = f"Naprawione przez #{pull.number}, scalone jako {merge_commit}."
                _gh("issue", "close", str(number), "--repo", pull.repository, "--comment", comment)
            open_issues.append(f"#{number}")
        except Exception:  # noqa: BLE001 - po merge'u każdy błąd to tylko ostrzeżenie w linii SCAL OK, bo PR jest już scalony
            failed.append(f"#{number}")
    if merged and not closes:
        missed = [*open_issues, *failed]
        return f" | UWAGA: GitHub nie podał commitu merge'a, nie zamknięto {', '.join(missed)}, zamknij ręcznie" if missed else ""
    done, warning = ("zamknięte", "UWAGA: nie zamknięto {}, zamknij ręcznie") if merged else (
        "po merge'u zamknie", "UWAGA: nie sprawdzono {}"
    )
    parts = [f"{done}: {', '.join(open_issues)}"] if open_issues else []
    parts += [warning.format(", ".join(failed))] if failed else []
    return "".join(f" | {part}" for part in parts)


def _merge_commit(number: int) -> str | None:
    """SHA commitu merge'a scalonego PR albo ``None``, gdy GitHub go nie podał."""

    try:
        return str(json.loads(_gh("pr", "view", str(number), "--json", "mergeCommit"))["mergeCommit"]["oid"])
    except Exception:  # noqa: BLE001 - PR jest już scalony, a brak SHA podaje linia SCAL OK
        return None


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
        print(f"SCAL OK | {where} | gotowy do merge'a z {pull.base} {base[:7]}, bez merge'a (--bez-merge){_close_fixed(pull, merged=False, merge_commit=None)}")
        return 0
    _gh("pr", "merge", str(number), "--merge", "--match-head-commit", pull.head)
    merge_commit = _merge_commit(number)
    closed = _close_fixed(pull, merged=True, merge_commit=merge_commit)
    print(f"SCAL OK | {where} | scalony do {pull.base} jako {(merge_commit or '?')[:7]} (baza {base[:7]}){closed} | {_clean_up()}")
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

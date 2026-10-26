"""Jedyna droga merge'a PR przez agenta: ``gh pr merge`` tylko po sprawdzeniu gotowości tuż przed nim.

Narzędzie scala PR numer N do jego bazy, gdy jednocześnie:

1. PR jest otwarty, nie jest szkicem i nie pochodzi z forka (z forka ruff i mypy biegłyby na obcym kodzie);
2. check ``Required CI status`` z GitHub Actions na HEAD PR skończył się sukcesem (jak w rulesecie ``main``:
   CheckRun z workflow, nie status commitu, który może ustawić każdy z prawem zapisu);
3. najnowszy werdykt dla HEAD PR to ``PASS``;
4. HEAD PR scala się z bieżącą bazą z ``origin`` bez konfliktu, a ruff i mypy dla obu systemów przechodzą na
   scalonym drzewie (``scalenia_pr.merge_verdict``, jak status ``scalenie z main``, ale teraz, nie po pushu).
5. Change mutations runu z zielonym Required skończyły się, a ``PASS`` z warunku 3 omawia każdą przeżytą mutację.

Change mutations (``tools/mutacje_zmiany.py``) startują po zielonym Required i go nie blokują, więc pilnuje ich to
narzędzie (ADR 0020), a każda niepewność to odmowa. Run z zielonym Required bez żadnego checku Change mutations jest
„w toku”: zadanie, które czeka na Required, nie ma jeszcze checku, a pominięte zostawia check ``SKIPPED`` z nazwą
``Change mutations (${{ matrix.part }}/3)``. Czy run ma mutacje, mówi artefakt ``plan`` runu (``mutacje_zmiany``);
plan, którego nie da się pobrać (błąd ``gh``, wygasły artefakt), to odmowa. Przy 0 mutacji checki części nie mają
znaczenia. Gdy plan ma mutacje, każda z części ``Change mutations (1/3)``–``(3/3)`` musi mieć check (inaczej odmowa
„w toku”), ``COMPLETED`` (też „w toku”) z ``SUCCESS`` albo ``FAILURE``; ``SKIPPED`` i check z nazwą-szablonem nie
wystarczą. Część z ``FAILURE`` musi mieć w artefakcie ``mutacje-zmiany-<k>`` listę przeżytych mutacji. Każda
przeżyta mutacja ``<id>`` (``<plik>:<linia> <opis>``, jak w linii ``NIEWYKRYTA`` jej zadania) potrzebuje w najnowszym
``PASS`` dla HEAD osobnej linii, bez odstępów na brzegach, ``MUTACJA <id> | test dodany`` albo
``MUTACJA <id> | nie warto, bo <powód>`` (Q20 z 26.10).

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
Warunki 1–3 i 5 sprawdza razem i podaje wszystkie przyczyny (5 tylko przy zielonym Required); warunek 4 trwa
dłużej, więc biegnie dopiero po nich.
Przed merge'em sprawdza, że baza w ``origin`` nie przesunęła się w trakcie sprawdzania, a ``gh pr merge
--match-head-commit`` odrzuca PR, którego HEAD zmienił się po sprawdzeniu. Po merge'u uruchamia
``tools/sprzatanie.py``, jeśli istnieje, i podaje ostatnią linię jego raportu: bez ``--usun`` sprzątanie niczego nie
usuwa, tylko mówi, które lokalne gałęzie i worktree można usunąć. Sprzątanie, które przekroczy czas, kończy się
ostrzeżeniem w linii ``SCAL OK``, bo PR jest już scalony. Kod 0 i ``SCAL OK`` znaczą, że PR jest scalony
(albo z ``--bez-merge``: że byłby); linia po merge'u podaje SHA commitu merge'a i bazy, z którą sprawdziła
scalenie. Kod 1 to odmowa albo błąd narzędzia (``SCAL FAIL``).

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
import tempfile

import potomne
import scalenia_pr

ROOT = Path(__file__).resolve().parents[1]
REQUIRED_CHECK = "Required CI status"
CHANGE_MUTATIONS = "Change mutations"
# Artefakt części k zadania Change mutations w ci.yml: ``mutacje-zmiany-<k>`` z plikiem ``--zapis`` narzędzia.
RECORD_ARTIFACT = "mutacje-zmiany-"
RECORD = "czesc.json"
# Części zadania Change mutations w ci.yml (``matrix.part``).
PARTS = tuple(f"{CHANGE_MUTATIONS} ({number}/3)" for number in (1, 2, 3))
RUN = re.compile(r"/actions/runs/(\d+)/")
PART = re.compile(r"\((\d+)/\d+\)$")
DISCUSSED = re.compile(r" \| (test dodany|nie warto, bo \S.*)")
# „Re-run failed jobs” nie powtarza zielonego zadania plan, więc nie odtwarza jego artefaktu.
PLAN_FIX = "odtwórz go przez „Re-run all jobs” tego runu albo nowy push (samo „Re-run failed jobs” planu nie odtworzy)"
VERDICT_LINE = re.compile(r"WERDYKT: (PASS|FAIL) ([0-9a-f]{40})")
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
    checks: tuple[dict[str, str | None], ...]


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


def _latest(verdicts: list[dict[str, object]], head: str) -> tuple[str, str] | None:
    """Najnowszy werdykt dla ``head`` z werdyktów w kolejności utworzenia: ``PASS`` albo ``FAIL`` i jego treść."""

    latest = None
    for verdict in verdicts:
        if (found := _verdict(verdict, head)) is not None:
            latest = found, str(verdict["body"])
    return latest


def _verdict_problem(latest: tuple[str, str] | None, head: str) -> str | None:
    if latest is None:
        return f"werdykt: brak komentarza ani recenzji „WERDYKT: PASS {head}”"
    return None if latest[0] == "PASS" else f"werdykt: FAIL dla {head[:7]} bez nowszego „WERDYKT: PASS {head}”"


def _run_of(check: dict[str, str | None]) -> str:
    found = RUN.search(check.get("detailsUrl") or "")
    return found[1] if found else "?"


def _download(run: str, folder: Path, *selection: str) -> str | None:
    """Artefakty runu do ``folder``; błąd ``gh``, także brak artefaktu, wraca jako przyczyna odmowy."""

    done = subprocess.run(
        ["gh", "run", "download", run, "--dir", str(folder), *selection],
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=scalenia_pr.GITHUB_TIMEOUT_S,
        check=False,
    )
    if done.returncode == 0:
        return None
    reason = next((line.strip() for line in reversed(done.stderr.splitlines()) if line.strip()), f"kod {done.returncode}")
    return f"artefakt {selection[-1]} runu {run} nie do pobrania: {reason}"


def _planned_mutations(run: str, folder: Path) -> tuple[int | None, str | None]:
    """Liczba mutacji z planu runu albo przyczyna odmowy, gdy jej nie ma."""

    if failed := _download(run, folder, "--name", "plan"):
        return None, f"{failed}; {PLAN_FIX}"
    try:
        return int(json.loads((folder / "plan.json").read_text(encoding="utf-8"))["mutacje_zmiany"]), None
    except (OSError, ValueError, KeyError, TypeError):
        return None, f"plan runu {run} bez liczby mutacji; {PLAN_FIX}"


def _survivors(run: str, parts: list[dict[str, str | None]], folder: Path) -> tuple[list[str], list[str]]:
    """Przeżyte mutacje części runu i przyczyny odmowy z części, które nie dały wyniku."""

    problems = []
    unfinished = [f"{check['name']} {check.get('status')}" for check in parts if check.get("status") != "COMPLETED"]
    if unfinished:
        return [], [f"Change mutations w toku: {', '.join(unfinished)}"]
    missing = _download(run, folder, "--pattern", f"{RECORD_ARTIFACT}*")
    survivors = []
    for check in parts:
        number = PART.search(str(check["name"]))
        record_file = folder / f"{RECORD_ARTIFACT}{number[1] if number else '?'}" / RECORD
        try:
            record = json.loads(record_file.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            record = {}
        conclusion = check.get("conclusion")
        if conclusion == "FAILURE" and record.get("przezyte"):
            survivors += record["przezyte"]
        elif conclusion != "SUCCESS":
            problems.append(f"{check['name']} {conclusion}: {record.get('wynik', missing or 'bez zapisu przeżytych mutacji')}")
    return survivors, problems


def _run_mutations(run: str, checks: list[dict[str, str | None]], folder: Path) -> tuple[list[str], list[str]]:
    """Przeżyte mutacje runu ``run`` z zielonym Required i przyczyny odmowy; ``checks`` to checki Change mutations runu."""

    if not checks:
        return [], [f"Change mutations w toku: run {run} nie ma jeszcze ich checku"]
    planned, failed = _planned_mutations(run, folder / "plan")
    if failed:
        return [], [failed]
    if planned == 0:
        return [], []
    by_name = {check["name"]: check for check in checks}
    if absent := [name for name in PARTS if name not in by_name]:
        return [], [f"Change mutations w toku: plan runu {run} ma {planned} mutacji, a nie ma checku {', '.join(absent)}"]
    return _survivors(run, [by_name[name] for name in PARTS], folder / "czesci")


def _discussed(survivor: str, lines: list[str]) -> bool:
    prefix = f"MUTACJA {survivor}"
    return any(line.startswith(prefix) and DISCUSSED.fullmatch(line[len(prefix) :]) for line in lines)


def _mutation_problems(checks: tuple[dict[str, str | None], ...], approval: str) -> list[str]:
    """Przyczyny odmowy z Change mutations runów, w których Required przeszedł; ``approval`` to treść ``PASS``."""

    runs = sorted({_run_of(check) for check in checks if check.get("name") == REQUIRED_CHECK and check.get("workflowName")})
    problems, survivors = [], []
    with tempfile.TemporaryDirectory(prefix="scal-pr-") as folder:
        for run in runs:
            parts = [
                check
                for check in checks
                if str(check.get("name")).startswith(CHANGE_MUTATIONS) and check.get("workflowName") and _run_of(check) == run
            ]
            found, failed = _run_mutations(run, parts, Path(folder, run))
            survivors += found
            problems += failed
    lines = [line.strip() for line in approval.splitlines()]
    if missing := [survivor for survivor in survivors if not _discussed(survivor, lines)]:
        problems.append(
            "przeżyte Change mutations bez linii „MUTACJA <id> | test dodany” albo „MUTACJA <id> | nie warto, bo <powód>” w PASS: "
            + "; ".join(missing)
        )
    return problems


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
    checks = tuple(pull["statusCheckRollup"])
    return Pull(number, pull["title"], pull["headRefOid"], pull["baseRefName"], tuple(problems), tuple(verdicts), checks)


def _remote_base(base: str) -> str:
    listed = potomne.run(["git", "ls-remote", "origin", f"refs/heads/{base}"], cwd=ROOT, timeout=scalenia_pr.GITHUB_TIMEOUT_S)
    listed.check_returncode()
    return listed.stdout.partition("\t")[0]


def _check(pull: Pull) -> str:
    """SHA bazy, z którą scalenie przeszło."""

    checked = scalenia_pr.PullRequest(pull.number, pull.title, pull.head)
    base = scalenia_pr.fetch(pull.base, [checked])
    latest = _latest(list(pull.verdicts), pull.head)
    problems = [*pull.problems, *filter(None, [_verdict_problem(latest, pull.head)])]
    if _ci_problem(list(pull.checks)) is None:
        problems += _mutation_problems(pull.checks, latest[1] if latest is not None and latest[0] == "PASS" else "")
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
    merged = json.loads(_gh("pr", "view", str(number), "--json", "mergeCommit"))["mergeCommit"]
    merge_commit = merged["oid"][:7] if merged else "?"
    print(f"SCAL OK | {where} | scalony do {pull.base} jako {merge_commit} (baza {base[:7]}) | {_clean_up()}")
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

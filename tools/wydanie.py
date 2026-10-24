"""Narzędzie Wydań: mechaniczna część „wydaj nową wersję” (skill ``wydanie``, ADR 0014).

``plan`` pobiera `main` i tagi Wydań tak jak Aktualizacja narzędzia (``tool_update.fetch_main_line``) i zapisuje
plan Wydania w pliku JSON: najnowszy commit z linii pierwszych rodziców `main` z zielonym ``Required CI status``
(czerwone, niezakończone i bez CI pomija), poprzednie Wydanie wybrane jak w Centrum, scalone PR-y od niego, sprawy
taty zamknięte jako rozwiązane w Skrzynce Zgłoszeń od jego publikacji (numer i tytuł, nigdy treść) i proponowany
numer. Niczego nie tworzy.

``wydaj`` bierze plan, plik z „Co nowego” i opcjonalnie inny numer. Bez ``--potwierdzone-przez-maksa`` tylko
pokazuje tag, commit i notkę. Z nim sprawdza jeszcze raz, że commit leży na linii `main` i ma zielone CI, a numer
jest wyższy od poprzedniego Wydania, zakłada tag z opisem, wypycha go z ``MAXIMISEART_WYDANIE=1`` (brama
pre-push) i tworzy GitHub Release z notką (``release_notes``). Ponowione po porażce kończy to samo Wydanie: tag
na tym samym commicie i istniejący Release zostają.

GitHuba pyta przez ``gh api`` z logowaniem Maksa (Skrzynka Zgłoszeń jest prywatna).

    .venv/bin/python tools/wydanie.py plan --plik ~/.t3/notes/wydanie/plan.json
    .venv/bin/python tools/wydanie.py wydaj --plan ~/.t3/notes/wydanie/plan.json --co-nowego co-nowego.txt
    .venv/bin/python tools/wydanie.py wydaj --plan … --co-nowego … --potwierdzone-przez-maksa
"""

from __future__ import annotations

import argparse
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
import enum
import json
import os
from pathlib import Path
import re
import subprocess
import sys
from typing import Final, Literal, TypeVar
import urllib.parse

from pydantic import BaseModel, TypeAdapter

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import potomne  # noqa: E402
from rozliczenia.centrum import release_notes, tool_update  # noqa: E402
from rozliczenia.centrum.release_notes import DadCase, ReleaseNotes  # noqa: E402
from rozliczenia.centrum.report_box import REPOSITORY as REPORT_BOX  # noqa: E402
from rozliczenia.centrum.tool_update import MainLine, Release  # noqa: E402

REPOSITORY: Final = tool_update.GITHUB_REPOSITORY.removeprefix("https://github.com/").removesuffix(".git")
ORIGIN: Final = "origin"
REQUIRED_CI: Final = "Required CI status"
CONFIRMED: Final = "--potwierdzone-przez-maksa"
RELEASE_OVERRIDE: Final = "MAXIMISEART_WYDANIE"
# Pliki, które działają u taty: kod narzędzia, zbudowane Centrum (frontend buduje się do src/), start i biblioteki.
DAD_FILES: Final = ("src/", "run_centrum.py", "install_centrum_shortcut.py", "requirements.txt")
FIRST: Final = (0, 1, 0)
_PUSH_TIMEOUT_S: Final = 120
_PAGE_SIZE: Final = 100
_MAX_PAGES: Final = 10

CiState = Literal["zielone", "czerwone", "w toku", "brak"]


class Bump(enum.Enum):
    MINOR = "MINOR"
    PATCH = "PATCH"


# Typ tytułu PR (Conventional Commits), który podbija MINOR, gdy PR zmienia pliki taty; każdy inny PR podbija PATCH.
BUMP_OF_TYPE: Final[Mapping[str, Bump]] = {"feat": Bump.MINOR}
NEXT: Final[Mapping[Bump, Callable[[tuple[int, int, int]], tuple[int, int, int]]]] = {
    Bump.MINOR: lambda number: (number[0], number[1] + 1, 0),
    Bump.PATCH: lambda number: (number[0], number[1], number[2] + 1),
}

_MERGE: Final = re.compile(r"Merge pull request #(?P<number>[1-9][0-9]*) from \S+")
_SQUASH: Final = re.compile(r"(?P<title>.+) \(#(?P<number>[1-9][0-9]*)\)")
_TYPE: Final = re.compile(r"(?P<type>[a-z]+)(\([^)]*\))?!?:")
_HTTP_STATUS: Final = re.compile(r"\(HTTP (?P<status>[0-9]{3})\)")


class Refused(Exception):
    """Narzędzie odmawia: ``str()`` mówi Maksowi i agentowi, czemu i co zrobić."""


@dataclass(frozen=True)
class MergedPR:
    """PR scalony do `main` od poprzedniego Wydania: numer, tytuł i czy zmienia pliki, które działają u taty."""

    number: int
    title: str
    for_dad: bool

    @property
    def bump(self) -> Bump:
        found = _TYPE.match(self.title)
        return BUMP_OF_TYPE.get(found["type"], Bump.PATCH) if found and self.for_dad else Bump.PATCH


@dataclass(frozen=True)
class SkippedCommit:
    """Nowszy commit `main`, którego CI nie jest zielone."""

    commit: str
    ci: CiState


@dataclass(frozen=True)
class PreviousRelease:
    """Poprzednie Wydanie: najnowsze na `main`, wybrane jak w Centrum."""

    release: Release
    commit: str


@dataclass(frozen=True)
class ReleasePlan:
    """Plan Wydania: co wydać, z jakim numerem i co wchodzi; niczego jeszcze nie tworzy."""

    commit: str
    previous: PreviousRelease | None
    # Tagi wyższych Wydań spoza linii `main`: Centrum je pomija, a numer nowego Wydania jest od nich wyższy.
    off_main: tuple[str, ...]
    proposed: Release
    bump: Bump | None
    changes: tuple[MergedPR, ...]
    dad_cases: tuple[DadCase, ...]
    skipped: tuple[SkippedCommit, ...]


PLAN: Final = TypeAdapter(ReleasePlan)


class _CheckRun(BaseModel):
    status: str
    conclusion: str | None


class _CheckRuns(BaseModel):
    check_runs: list[_CheckRun]


class _Issue(BaseModel):
    number: int
    title: str
    state_reason: str | None = None
    closed_at: datetime | None = None
    pull_request: object | None = None


class _GitHubRelease(BaseModel):
    html_url: str = ""
    body: str | None = None


_CHECK_RUNS: Final = TypeAdapter(_CheckRuns)
_ISSUES: Final = TypeAdapter(list[_Issue])
_RELEASE: Final = TypeAdapter(_GitHubRelease)
_Answer = TypeVar("_Answer")


def _gh(answer: TypeAdapter[_Answer], path: str, body: Mapping[str, object] | None = None) -> _Answer:
    """Odpowiedź ``gh api`` (GET, z ``body`` POST) odczytana przez ``answer``; każda porażka to ``Refused``."""

    found = _gh_found(answer, path, body)
    if found is None:
        raise Refused(f"gh api {path}: GitHub odpowiedział 404 (brak dostępu albo nie ma takiego zasobu).")
    return found


def _gh_found(answer: TypeAdapter[_Answer], path: str, body: Mapping[str, object] | None = None) -> _Answer | None:
    """Jak ``_gh``, ale 404 to ``None``."""

    sent = None if body is None else json.dumps(body)
    answered = subprocess.run(
        ["gh", "api", "--method", "GET" if sent is None else "POST", path, *([] if sent is None else ["--input", "-"])],
        input=sent,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )
    if answered.returncode != 0:
        status = _HTTP_STATUS.search(answered.stderr)
        if status is not None and status["status"] == "404":
            return None
        raise Refused(f"gh api {path}: {answered.stderr.strip() or f'kod {answered.returncode}'}")
    return answer.validate_json(answered.stdout)


def _git(root: Path, *arguments: str) -> str:
    return subprocess.run(["git", *arguments], cwd=root, capture_output=True, text=True, encoding="utf-8", check=True).stdout


def ci_state(commit: str) -> CiState:
    """Stan ``Required CI status`` commitu na GitHubie."""

    check = urllib.parse.quote(REQUIRED_CI)
    answer = _gh(_CHECK_RUNS, f"repos/{REPOSITORY}/commits/{commit}/check-runs?check_name={check}&per_page={_PAGE_SIZE}")
    runs = answer.check_runs
    if not runs:
        return "brak"
    if any(run.status != "completed" for run in runs):
        return "w toku"
    return "zielone" if all(run.conclusion == "success" for run in runs) else "czerwone"


def plan(root: Path) -> ReleasePlan:
    """Plan następnego Wydania z ``main`` w ``origin``; ``Refused``, gdy nie ma czego wydać."""

    line = _fetch(root)
    newest = line.newest()
    previous = None if newest.release is None or newest.commit is None else PreviousRelease(newest.release, newest.commit)
    skipped: list[SkippedCommit] = []
    for commit in line.tips:
        if commit == newest.commit:
            raise Refused(f"Nic do wydania: od poprzedniego Wydania żaden commit main nie ma zielonego CI ({len(skipped)} pominiętych).")
        state = ci_state(commit)
        if state == "zielone":
            break
        skipped.append(SkippedCommit(commit, state))
    else:
        raise Refused("Nic do wydania: żaden commit main nie ma zielonego CI.")
    changes = _merged_prs(root, newest.commit, commit)
    bump = None if previous is None else Bump.MINOR if any(change.bump is Bump.MINOR for change in changes) else Bump.PATCH
    number = FIRST if previous is None or bump is None else NEXT[bump](previous.release.number)
    highest = _highest(line.releases)
    if highest is not None and number <= highest.number:
        number = NEXT[bump or Bump.MINOR](highest.number)
    cases = _closed_cases(root, previous)
    return ReleasePlan(commit, previous, newest.skipped, Release(number, _tag(number)), bump, changes, cases, tuple(skipped))


def chosen_release(chosen: ReleasePlan, override: str | None) -> Release:
    """Numer Wydania: proponowany albo ``override`` (``v0.x.y`` albo ``0.x.y``), zawsze wyższy od każdego Wydania."""

    release = chosen.proposed if override is None else Release.of_tag(override if override.startswith("v") else f"v{override}")
    if release is None or release.number[0] != 0:
        raise Refused(f"Numer {override or chosen.proposed.tag} nie ma kształtu 0.MINOR.PATCH (np. 0.2.0).")
    tags = (*([] if chosen.previous is None else [chosen.previous.release.tag]), *chosen.off_main)
    highest = _highest(tags)
    if highest is not None and release.number <= highest.number:
        raise Refused(f"Numer {release.tag} nie jest wyższy od Wydania {highest.tag}.")
    return release


def publish(root: Path, chosen: ReleasePlan, summary: str, override: str | None, *, confirmed: bool) -> str:
    """Wydanie planu ``chosen`` z „Co nowego” ``summary``; bez ``confirmed`` niczego nie tworzy. Zwraca linię wyniku."""

    release = chosen_release(chosen, override)
    notes = release_notes.render(ReleaseNotes(summary, chosen.dad_cases))
    print(f"Wydanie {release.tag} na commicie {chosen.commit}\n\n{notes}", flush=True)
    if not confirmed:
        return f"WYDANIE PODGLĄD | {release.tag} | nic nie utworzono; publikacja tylko z {CONFIRMED}"
    line = _fetch(root)
    # Tag już na tym commicie w origin: Wydanie jest u taty, zostaje tylko dokończyć Release.
    if line.releases.get(release.tag) != chosen.commit:
        _check_still_releasable(line, chosen.commit, release)
        _tag_and_push(root, release, chosen.commit)
    found = _gh_found(_RELEASE, f"repos/{REPOSITORY}/releases/tags/{release.tag}")
    if found is None:
        name = ".".join(map(str, release.number))
        created = {"tag_name": release.tag, "target_commitish": chosen.commit, "name": f"Wydanie {name}", "body": notes}
        found = _gh(_RELEASE, f"repos/{REPOSITORY}/releases", created)
    return f"WYDANIE OK | {release.tag} | {chosen.commit} | {found.html_url}"


def _fetch(root: Path) -> MainLine:
    try:
        return tool_update.fetch_main_line(root, ORIGIN)
    except tool_update.GitFailed as failure:
        raise Refused(f"Nie udało się pobrać main i tagów z {ORIGIN}: {failure}.") from failure


def _highest(tags: Iterable[str]) -> Release | None:
    return max((release for tag in tags if (release := Release.of_tag(tag)) is not None), default=None)


def _check_still_releasable(line: MainLine, commit: str, release: Release) -> None:
    if commit not in line.tips:
        raise Refused(f"Commit {commit} nie leży na linii pierwszych rodziców main w {ORIGIN}.")
    state = ci_state(commit)
    if state != "zielone":
        raise Refused(f"CI commitu {commit} nie jest już zielone ({state}).")
    tagged = line.releases.get(release.tag)
    if tagged not in (None, commit):
        raise Refused(f"Tag {release.tag} już jest w {ORIGIN} na innym commicie ({tagged}).")
    others = {tag: target for tag, target in line.releases.items() if tag != release.tag}
    highest = _highest(others)
    if highest is not None and release.number <= highest.number:
        raise Refused(f"Numer {release.tag} nie jest wyższy od Wydania {highest.tag} w {ORIGIN}.")
    newest = MainLine(line.tips, others).newest()
    if newest.release is not None and newest.commit is not None and line.tips.index(commit) >= line.tips.index(newest.commit):
        raise Refused(f"Commit {commit} nie jest nowszy od commitu Wydania {newest.release.tag}.")


def _tag_and_push(root: Path, release: Release, commit: str) -> None:
    tag = f"refs/tags/{release.tag}^{{commit}}"
    local = subprocess.run(["git", "rev-parse", "--quiet", "--verify", tag], cwd=root, capture_output=True, text=True, check=False)
    if local.returncode == 0 and local.stdout.strip() != commit:
        raise Refused(f"Lokalny tag {release.tag} wskazuje inny commit ({local.stdout.strip()}); usuń go i ponów.")
    if local.returncode != 0:
        name = ".".join(map(str, release.number))
        made = potomne.run(["git", "tag", "--annotate", "--message", f"Wydanie {name}", release.tag, commit], cwd=root, timeout=60)
        if made.returncode != 0:
            raise Refused(f"git tag {release.tag}: {made.stderr.strip()}")
    pushed = potomne.run(
        ["git", "push", "--quiet", ORIGIN, f"refs/tags/{release.tag}"],
        cwd=root,
        env={**os.environ, RELEASE_OVERRIDE: "1"},
        timeout=_PUSH_TIMEOUT_S,
    )
    if pushed.returncode != 0:
        raise Refused(f"git push {release.tag}: {(pushed.stderr or pushed.stdout).strip()}")


def _merged_prs(root: Path, previous: str | None, commit: str) -> tuple[MergedPR, ...]:
    """PR-y scalone do `main` od commitu ``previous`` (bez niego) do ``commit``: merge i squash z GitHuba."""

    span = commit if previous is None else f"{previous}..{commit}"
    listed = _git(root, "log", "--first-parent", "--diff-merges=first-parent", "--name-only", "--format=%x1e%s%x1f%b%x1f", span)
    changes: list[MergedPR] = []
    for record in listed.split("\x1e")[1:]:
        subject, body, names = record.split("\x1f")
        for_dad = any(name.startswith(DAD_FILES) for name in names.split())
        if (merged := _MERGE.fullmatch(subject)) is not None:
            title = next((line.strip() for line in body.splitlines() if line.strip()), subject)
            changes.append(MergedPR(int(merged["number"]), title, for_dad))
        elif (squashed := _SQUASH.fullmatch(subject)) is not None:
            changes.append(MergedPR(int(squashed["number"]), squashed["title"], for_dad))
    return tuple(changes)


def _closed_cases(root: Path, previous: PreviousRelease | None) -> tuple[DadCase, ...]:
    """Uwagi taty i Zgłoszenia zamknięte w Skrzynce jako rozwiązane, których nie ma jeszcze w żadnej notce.

    Okno zaczyna się od commitu poprzedniego Wydania, a nie od jego publikacji: sprawa zamknięta między planem a
    publikacją poprzedniego Wydania nie trafiła do jego notki. Sprawy, które ta notka już wymienia, odpadają.
    """

    since, listed = None, frozenset[int]()
    if previous is not None:
        since = datetime.fromisoformat(_git(root, "log", "-1", "--format=%cI", previous.commit).strip())
        found = _gh_found(_RELEASE, f"repos/{REPOSITORY}/releases/tags/{previous.release.tag}")
        listed = frozenset(case.number for case in release_notes.parse(found.body or "").cases) if found else frozenset()
    cases: list[DadCase] = []
    for label in release_notes.CASE_KINDS:
        query = {"state": "closed", "labels": label, "per_page": str(_PAGE_SIZE)}
        if since is not None:
            query["since"] = since.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
        for page in range(1, _MAX_PAGES + 1):
            path = f"repos/{REPORT_BOX}/issues?{urllib.parse.urlencode({**query, 'page': str(page)})}"
            issues = _gh(_ISSUES, path)
            cases.extend(
                DadCase(issue.number, issue.title, label)
                for issue in issues
                if issue.pull_request is None
                and issue.state_reason == "completed"
                and issue.closed_at is not None
                and (since is None or issue.closed_at > since)
                and issue.number not in listed
            )
            if len(issues) < _PAGE_SIZE:
                break
        else:
            raise Refused(f"Skrzynka Zgłoszeń ma więcej niż {_MAX_PAGES * _PAGE_SIZE} zamkniętych spraw z etykietą {label}.")
    return tuple(sorted(cases, key=lambda case: case.number))


def _tag(number: tuple[int, int, int]) -> str:
    return "v" + ".".join(map(str, number))


def _report(chosen: ReleasePlan) -> str:
    previous = "brak (pierwsze Wydanie)" if chosen.previous is None else f"{chosen.previous.release.tag} ({chosen.previous.commit[:9]})"
    lines = [
        f"Commit: {chosen.commit}",
        f"Poprzednie Wydanie: {previous}",
        f"Proponowany numer: {chosen.proposed.tag}" + ("" if chosen.bump is None else f" ({chosen.bump.value})"),
        f"Wyższe Wydania spoza linii main (Centrum je pomija): {', '.join(chosen.off_main) or 'brak'}",
        f"Pominięte nowsze commity main: {', '.join(f'{skip.commit[:9]} ({skip.ci})' for skip in chosen.skipped) or 'brak'}",
        f"Scalone PR-y ({len(chosen.changes)}):",
        *(f"  #{change.number} [{change.bump.value}{', u taty' if change.for_dad else ''}] {change.title}" for change in chosen.changes),
        f"Rozwiązane sprawy taty ({len(chosen.dad_cases)}):",
        *(f"  {release_notes.CASE_KINDS[case.label]} #{case.number}: {case.title}" for case in chosen.dad_cases),
    ]
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0] if __doc__ else None)
    parser.add_argument("--repozytorium", type=Path, default=ROOT, help="Checkout z remote origin (domyślnie ten).")
    commands = parser.add_subparsers(dest="polecenie", required=True)
    planned = commands.add_parser("plan", help="Plan następnego Wydania; niczego nie tworzy.")
    planned.add_argument("--plik", type=Path, required=True, help="Plik JSON, do którego trafia plan.")
    released = commands.add_parser("wydaj", help="Wydanie z planu; bez potwierdzenia tylko podgląd.")
    released.add_argument("--plan", type=Path, required=True)
    released.add_argument("--co-nowego", type=Path, required=True, help="Plik z „Co nowego” dla taty (2-5 zdań).")
    released.add_argument("--numer", help="Inny numer niż proponowany, np. 0.3.0; musi być wyższy od poprzedniego.")
    released.add_argument(CONFIRMED, dest="confirmed", action="store_true", help="Maks potwierdził numer, notkę i weryfikację.")
    arguments = parser.parse_args(argv)
    root: Path = arguments.repozytorium.resolve()
    try:
        if arguments.polecenie == "plan":
            chosen = plan(root)
            arguments.plik.parent.mkdir(parents=True, exist_ok=True)
            arguments.plik.write_bytes(PLAN.dump_json(chosen, indent=2))
            print(_report(chosen), flush=True)
            print(f"PLAN OK | {chosen.proposed.tag} | {chosen.commit} | plik={arguments.plik}", flush=True)
            return 0
        chosen = PLAN.validate_json(arguments.plan.read_bytes())
        summary = arguments.co_nowego.read_text(encoding="utf-8")
        print(publish(root, chosen, summary, arguments.numer, confirmed=arguments.confirmed), flush=True)
        return 0
    except (Refused, ValueError, OSError, subprocess.SubprocessError) as refusal:
        print(f"WYDANIE ODMOWA | {refusal}", flush=True)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

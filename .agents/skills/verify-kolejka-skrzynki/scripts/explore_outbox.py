"""Exhaustively check that the Kolejka Skrzynki Zgłoszeń delivers every part of every wysyłka.

The checker runs the real ``outbox.Outbox`` (its ``_drain`` and ``_send_all``) and the real ``KeyedBox`` against an
in-memory Skrzynka Zgłoszeń, on a real queue folder in a temporary directory. Each call the code makes to the
Skrzynka, the write of the delivery marker and the removal of a queue file is one indivisible step. Before every step
the checker may let it succeed, let the network fail before the Skrzynka sees it (``Unreachable``), let the Skrzynka
accept it and lose the answer (``Unreachable`` after the effect), fail the file call with ``OSError``, or kill the
process. Between two passes of the queue it may also restart Centrum. It tries every such schedule within the bounds
of a scope, re-running the code from scratch once per schedule, and after the failures run out it lets the queue pass
until it is empty. Then it checks:

- WSZYSTKIE_CZESCI: every part of every wysyłka is in the Skrzynka, in an issue of its target (decision 12 in
  ADR 0015: „Wysyłka jest co najmniej raz”).
- JEDNO_ISSUE: one problem has one open Zgłoszenie and one period has one issue okresu; a wysyłka to a new issue
  (Uwaga taty) opens one issue. ADR 0015 accepts a second issue of a NewIssue after a lost answer.
- KOLEJKA_PUSTA: the queue folder is empty once failures stop.
- BEZ_WYJATKU: no pass ends in an exception that ``_drain`` logs as ``nieoczekiwany-wyjatek``.

Nothing in ``outbox.py`` or ``keyed_box.py`` is replaced. The Skrzynka behind ``KeyedBox`` is the in-memory
``MemoryBox`` (GitHub's issues and comments), the clock never moves, ``send_in_background`` runs the pass in the
checker's thread, and the key is always there and accepted.
"""

from __future__ import annotations

import argparse
import pathlib
import shutil
import sys
import tempfile
from collections.abc import Callable, Iterator, Sequence
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

sys.path.insert(0, str(Path(__file__).resolve().parents[4] / "src"))

from rozliczenia.centrum import outbox as outbox_module
from rozliczenia.centrum.keyed_box import KeyedBox
from rozliczenia.centrum.log import CentrumLog
from rozliczenia.centrum.outbox import (
    KnownIssue,
    NewIssue,
    Outbox,
    PeriodThread,
    Post,
    ReportIssue,
)
from rozliczenia.centrum.report_box import (
    Closure,
    CommentOutcome,
    Commented,
    Issue,
    IssuesOutcome,
    Label,
    SendOutcome,
    Sent,
    Unreachable,
)

KEY = "github_pat_SYNTETYCZNY_KLUCZ"
# Passes beyond one per failure until the queue must be empty; a pass without a failure delivers or removes each file.
EXTRA_PASSES = 3
DRAIN_FAILURE = "wysyłka do Skrzynki Zgłoszeń"


class Crash(BaseException):
    """The process dies at this step (Dad closes Centrum, the computer switches off)."""


@dataclass
class _Issue:
    label: Label
    title: str
    body: str
    comments: list[str] = field(default_factory=list)
    closed: bool = False


class MemoryBox:
    """The Skrzynka Zgłoszeń behind ``KeyedBox``: GitHub issues with labels, bodies and comments, numbered from 1."""

    def __init__(self, scheduler: Scheduler) -> None:
        self.issues: dict[int, _Issue] = {}
        self._scheduler = scheduler
        self._comment_ids = 0

    def open_issue(
        self, label: Label, title: str, body: str, *, key: str
    ) -> SendOutcome:
        what = f"open_issue({label}, {_part_name(body)})"
        failure = self._scheduler.box_write(what)
        if failure == "unreachable":
            return Unreachable()
        number = len(self.issues) + 1
        self.issues[number] = _Issue(label, title, body)
        self._scheduler.say(
            f"Skrzynka zakłada issue #{number}"
            + (", odpowiedź ginie (Unreachable)" if failure else "")
        )
        return Unreachable() if failure else Sent(number)

    def comment(self, number: int, body: str, *, key: str) -> CommentOutcome:
        failure = self._scheduler.box_write(f"comment(#{number}, {_part_name(body)})")
        if failure == "unreachable":
            return Unreachable()
        self.issues[number].comments.append(body)
        self._comment_ids += 1
        self._scheduler.say(
            f"Skrzynka dopisuje komentarz do #{number}"
            + (", odpowiedź ginie (Unreachable)" if failure else "")
        )
        return (
            Unreachable()
            if failure
            else Commented(
                self._comment_ids, f"https://skrzynka/{number}#{self._comment_ids}"
            )
        )

    def labelled_issues(
        self, label: Label, *, include_closed: bool, key: str
    ) -> IssuesOutcome:
        if self._scheduler.box_read(f"labelled_issues({label})"):
            return Unreachable()
        found = tuple(
            Issue(
                number, issue.body, Closure("completed", None) if issue.closed else None
            )
            for number, issue in self.issues.items()
            if issue.label == label and (include_closed or not issue.closed)
        )
        self._scheduler.say(
            f"Skrzynka zwraca issue {label}: {[issue.number for issue in found] or 'brak'}"
        )
        return found


Choice = Literal["ok", "unreachable", "lost", "oserror", "kill", "next", "restart"]


@dataclass(frozen=True)
class Bounds:
    unreachable: int
    lost: int
    disk: int
    kills: int


class Scheduler:
    """Picks one option at each step from the schedule prefix, then the first option; records what it could pick."""

    def __init__(self, prefix: Sequence[int], bounds: Bounds) -> None:
        self._prefix = prefix
        self.taken: list[int] = []
        self.options: list[int] = []
        self.left = {
            "unreachable": bounds.unreachable,
            "lost": bounds.lost,
            "oserror": bounds.disk,
            "kill": bounds.kills,
        }
        self.trace: list[str] = []

    def say(self, line: str) -> None:
        self.trace.append(line)

    def _pick(self, offered: Sequence[Choice]) -> Choice:
        allowed = [choice for choice in offered if self.left.get(choice, 1) > 0]
        position = len(self.taken)
        index = self._prefix[position] if position < len(self._prefix) else 0
        self.taken.append(index)
        self.options.append(len(allowed))
        chosen = allowed[index]
        if chosen in self.left:
            self.left[chosen] -= 1
        return chosen

    def _killed(self, chosen: Choice, what: str) -> None:
        if chosen == "kill":
            self.say(f"proces ginie przed {what}")
            raise Crash

    def box_read(self, what: str) -> bool:
        chosen = self._pick(("ok", "unreachable", "kill"))
        self._killed(chosen, what)
        if chosen == "unreachable":
            self.say(f"{what}: brak sieci (Unreachable)")
        return chosen == "unreachable"

    def box_write(self, what: str) -> Literal["unreachable", "lost"] | None:
        chosen = self._pick(("ok", "unreachable", "lost", "kill"))
        self._killed(chosen, what)
        if chosen == "unreachable":
            self.say(f"{what}: brak sieci (Unreachable), Skrzynka nic nie dostaje")
            return "unreachable"
        if chosen == "lost":
            self.say(what)
            return "lost"
        self.say(what)
        return None

    def disk(self, what: str) -> bool:
        chosen = self._pick(("ok", "oserror", "kill"))
        self._killed(chosen, what)
        if chosen == "oserror":
            self.say(f"{what}: OSError")
        return chosen == "oserror"

    def restart(self) -> bool:
        chosen = self._pick(("next", "restart")) if self.left["kill"] else "next"
        if chosen == "restart":
            self.left["kill"] -= 1
        return chosen == "restart"


def _part_name(text: str) -> str:
    return next(
        (line for line in text.splitlines() if line.startswith("część ")), "treść"
    )


@dataclass(frozen=True)
class Scope:
    description: str
    posts: tuple[Post, ...]
    issues: tuple[tuple[Label, str, str], ...]
    bounds: Bounds


REPORT = ReportIssue(
    "- Odcisk problemu: 4f1c2d", "Zgłoszenie: Przebieg rozliczeń zatrzymany"
)
THREAD = PeriodThread(
    "kontrola-ilosci",
    "- Kontrola ilości okresu: 08_14_09_2026",
    "new_issue",
    "Kontrola ilości 08_14_09_2026",
)
NOTE = NewIssue("uwaga-taty", "Uwaga taty: brakuje zlecenia")
KNOWN = KnownIssue("uwaga-taty", 1)


def _post(
    target: ReportIssue | PeriodThread | NewIssue | KnownIssue, run_id: str, count: int
) -> Post:
    first = f"{REPORT.line}\n" if isinstance(target, ReportIssue) else ""
    parts = tuple(
        f"{first if number == 1 else ''}część {number}/{count} wysyłki {run_id}"
        for number in range(1, count + 1)
    )
    return Post(target, "08_14_09_2026", run_id, None, parts)


BOUNDS = Bounds(unreachable=2, lost=1, disk=1, kills=1)
SCOPES = {
    "zgloszenie": Scope(
        "Zgłoszenie (ReportIssue) w jednej części, jak dziś każde.",
        (_post(REPORT, "zgl", 1),),
        (),
        BOUNDS,
    ),
    "zgloszenie-w-czesciach": Scope(
        "Zgłoszenie (ReportIssue) w trzech częściach, gdyby treść przekroczyła komentarz.",
        (_post(REPORT, "zgl", 3),),
        (),
        BOUNDS,
    ),
    "watek-okresu": Scope(
        "Dwie Kontrole ilości do jednego issue okresu (PeriodThread), w dwóch i jednej części.",
        (_post(THREAD, "kontrola-a", 2), _post(THREAD, "kontrola-b", 1)),
        (),
        BOUNDS,
    ),
    "nowe-issue": Scope(
        "Uwaga taty (NewIssue) w dwóch częściach.",
        (_post(NOTE, "uwaga", 2),),
        (),
        BOUNDS,
    ),
    "znane-issue": Scope(
        "Komentarz do istniejącego issue Uwagi taty (KnownIssue) w dwóch częściach.",
        (_post(KNOWN, "logi", 2),),
        (("uwaga-taty", "Uwaga taty", "treść Uwagi"),),
        BOUNDS,
    ),
}

# (scope, rule): why it is reported but does not fail the check. Each must break in its scope, or the check fails.
KNOWN_FINDINGS: dict[tuple[str, str], str] = {
    ("zgloszenie-w-czesciach", "WSZYSTKIE_CZESCI"): (
        "ponowna próba po przerwanej wysyłce Zgłoszenia znajduje issue założone przez pierwszą i przejmuje je bez "
        "komentarzy (_deliver_report), więc części, których pierwsza nie dopisała, nigdy nie trafiają do Skrzynki"
    ),
}
ACCEPTED_RISKS: dict[tuple[str, str], str] = {
    ("nowe-issue", "JEDNO_ISSUE"): (
        "ADR 0015: „Wysyłka jest co najmniej raz: zerwane połączenie po utworzeniu issue może dać drugie issue”"
    ),
}


class _Log(CentrumLog):
    def __init__(self, path: Path, failures: list[str]) -> None:
        super().__init__(path)
        self._failures = failures

    def unexpected_failure(self, failure: BaseException, *, where: str) -> None:
        super().unexpected_failure(failure, where=where)
        if where == DRAIN_FAILURE:
            self._failures.append(f"{type(failure).__name__}: {failure}")


class _Clock:
    def __call__(self) -> float:
        return 0.0

    def after(self, seconds: float, wake: Callable[[], None]) -> None:
        """The checker runs the next pass itself."""


@contextmanager
def _intercepted(scheduler: Scheduler, queue: Path) -> Iterator[None]:
    """The marker write and the removal of queue files as steps of ``scheduler``."""

    names = vars(outbox_module)
    replace = names["replace_atomically"]
    unlink = pathlib.Path.unlink

    def marker(path: Path, text: str) -> None:
        if scheduler.disk(f"zapis znacznika dostarczenia {path.name[-24:]}"):
            raise PermissionError("plik zablokowany")
        replace(path, text)
        scheduler.say("znacznik dostarczenia zapisany")

    def removal(path: Path, missing_ok: bool = False) -> None:
        if path.parent == queue and path.suffix == ".json":
            if scheduler.disk(f"usunięcie pliku kolejki {path.name[-24:]}"):
                raise PermissionError("plik zablokowany")
            scheduler.say("plik kolejki usunięty")
        unlink(path, missing_ok=missing_ok)

    names["replace_atomically"] = marker
    pathlib.Path.unlink = removal  # type: ignore[method-assign,assignment]
    try:
        yield
    finally:
        names["replace_atomically"] = replace
        pathlib.Path.unlink = unlink  # type: ignore[method-assign]


@dataclass(frozen=True)
class Violation:
    rule: str
    detail: str
    trace: tuple[str, ...]


def _check(
    scope: Scope, box: MemoryBox, queue: Path, failures: list[str]
) -> list[tuple[str, str]]:
    broken: list[tuple[str, str]] = []
    for post in scope.posts:
        target = post.target
        if isinstance(target, KnownIssue):
            mine = [box.issues[target.number]]
        elif isinstance(target, NewIssue):
            mine = [
                issue
                for issue in box.issues.values()
                if issue.label == target.label and issue.title == target.title
            ]
        else:
            mine = [
                issue
                for issue in box.issues.values()
                if issue.label == target.label
                and target.line in issue.body.splitlines()
            ]
        texts = [text for issue in mine for text in (issue.body, *issue.comments)]
        missing = [
            f"{number}/{len(post.parts)}"
            for number, part in enumerate(post.parts, 1)
            if not any(part in text for text in texts)
        ]
        if missing:
            broken.append(
                (
                    "WSZYSTKIE_CZESCI",
                    f"w Skrzynce nie ma części {', '.join(missing)} wysyłki {post.run_id}",
                )
            )
        if (
            not isinstance(target, KnownIssue)
            and len([issue for issue in mine if not issue.closed]) > 1
        ):
            broken.append(
                (
                    "JEDNO_ISSUE",
                    f"wysyłka {post.run_id} ma {len(mine)} issue: {sorted(n for n, i in box.issues.items() if i in mine)}",
                )
            )
    left = sorted(path.name for path in queue.glob("*.json"))
    if left:
        broken.append(
            (
                "KOLEJKA_PUSTA",
                f"po ustaniu awarii w kolejce zostaje {len(left)} plik(ów)",
            )
        )
    if failures:
        broken.append(
            ("BEZ_WYJATKU", f"przejście kolejki kończy się wyjątkiem: {failures[0]}")
        )
    return list(dict.fromkeys(broken))


def _state(
    box: MemoryBox, queue: Path, outbox: Outbox, scheduler: Scheduler, passes: int
) -> object:
    """What decides every future of a pass boundary: the Skrzynka, the queue files, the failures and passes left."""

    files = {
        path.name: path.read_text(encoding="utf-8") for path in queue.glob("*.json")
    }
    return (
        tuple(
            (n, i.label, i.title, i.body, tuple(i.comments), i.closed)
            for n, i in sorted(box.issues.items())
        ),
        tuple(sorted(files.values())),
        tuple(sorted(files[name] for name in outbox._undeleted if name in files)),
        tuple(sorted(scheduler.left.items())),
        passes,
    )


def execute(
    scope: Scope, prefix: Sequence[int], work: Path, visited: set[object]
) -> tuple[Scheduler, list[Violation]]:
    """One schedule: write the wysyłki, then passes and restarts as ``prefix`` picks until failures run out.

    A schedule that reaches a pass boundary already explored, past the steps it replays from ``prefix``, stops
    there: the code is deterministic, so that state has the same futures, and the schedules that branch after it
    from the first visit check them.
    """

    shutil.rmtree(work, ignore_errors=True)
    queue = work / "config" / "zgloszenia" / "kolejka"
    scheduler = Scheduler(prefix, scope.bounds)
    box = MemoryBox(scheduler)
    for label, title, body in scope.issues:
        box.issues[len(box.issues) + 1] = _Issue(label, title, body)
    failures: list[str] = []

    def started() -> Outbox:
        outbox = Outbox(
            queue,
            KeyedBox(box, lambda: KEY, clock=_Clock()),
            _Log(work / "centrum.log", failures),
            clock=_Clock(),
        )
        outbox.send_in_background = lambda: None  # type: ignore[method-assign]
        return outbox

    def drive(outbox: Outbox) -> None:
        outbox._draining = True
        outbox._drain()

    outbox = started()
    for post in scope.posts:
        assert outbox.post(post), "zapis wysyłki do kolejki"
    scheduler.say("wysyłki czekają w kolejce; przejście kolejki")
    bounds = scope.bounds
    passes = (
        bounds.unreachable + bounds.lost + bounds.disk + bounds.kills + EXTRA_PASSES
    )
    with _intercepted(scheduler, queue):
        while any(queue.glob("*.json")) and passes:
            state = _state(box, queue, outbox, scheduler, passes)
            if state in visited and len(scheduler.taken) >= len(prefix):
                return scheduler, []
            visited.add(state)
            passes -= 1
            try:
                drive(outbox)
            except Crash:
                outbox = started()
                scheduler.say("Centrum startuje znów (resume): przejście kolejki")
                outbox.resume()
                continue
            if any(queue.glob("*.json")):
                if scheduler.restart():
                    scheduler.say("Centrum startuje znów (resume): przejście kolejki")
                    outbox = started()
                    outbox.resume()
                else:
                    scheduler.say("po RETRY_S: następne przejście kolejki")
    trace = tuple(scheduler.trace)
    return scheduler, [
        Violation(rule, detail, trace)
        for rule, detail in _check(scope, box, queue, failures)
    ]


def next_prefix(scheduler: Scheduler) -> list[int] | None:
    for position in range(len(scheduler.taken) - 1, -1, -1):
        if scheduler.taken[position] + 1 < scheduler.options[position]:
            return [*scheduler.taken[:position], scheduler.taken[position] + 1]
    return None


@dataclass
class ScopeReport:
    name: str
    schedules: int = 0
    shortest: dict[str, Violation] = field(default_factory=dict)


def explore(name: str) -> ScopeReport:
    scope = SCOPES[name]
    report = ScopeReport(name)
    with tempfile.TemporaryDirectory(prefix="kolejka-skrzynki-") as directory:
        prefix: list[int] | None = []
        visited: set[object] = set()
        while prefix is not None:
            scheduler, violations = execute(
                scope, prefix, Path(directory) / "praca", visited
            )
            report.schedules += 1
            for violation in violations:
                known = report.shortest.get(violation.rule)
                if known is None or len(violation.trace) < len(known.trace):
                    report.shortest[violation.rule] = violation
            prefix = next_prefix(scheduler)
    return report


@dataclass(frozen=True)
class Outcome:
    lines: list[str]
    exit_code: int


def summarize(reports: Sequence[ScopeReport], *, strict: bool = False) -> Outcome:
    lines: list[str] = []
    new = known = accepted = gone = 0
    for report in reports:
        lines.append(
            f"== {report.name}: {SCOPES[report.name].description} Harmonogramy: {report.schedules}."
        )
        for rule, violation in sorted(report.shortest.items()):
            key = (report.name, rule)
            if key in KNOWN_FINDINGS and not strict:
                known += 1
                lines.append(f"   znane ustalenie {rule}: {KNOWN_FINDINGS[key]}")
            elif key in ACCEPTED_RISKS and not strict:
                accepted += 1
                lines.append(f"   zaakceptowane ryzyko {rule}: {ACCEPTED_RISKS[key]}")
            else:
                new += 1
                lines.append(f"   NOWE NARUSZENIE {rule}")
            lines.append(f"   {violation.detail}")
            lines.extend(
                f"   {number}. {step}"
                for number, step in enumerate(violation.trace, start=1)
            )
        for key in (*KNOWN_FINDINGS, *ACCEPTED_RISKS):
            if key[0] == report.name and key[1] not in report.shortest:
                gone += 1
                lines.append(
                    f"   ZNALEZISKO ZNIKNĘŁO {key[1]}: usuń je z KNOWN_FINDINGS albo ACCEPTED_RISKS i z SKILL.md"
                )
    lines.append("")
    if new or gone:
        lines.append(
            f"KOLEJKA: NOWE NARUSZENIE ({new})"
            if new
            else f"KOLEJKA: ZNALEZISKO ZNIKNĘŁO ({gone})"
        )
        return Outcome(lines, 1)
    counts = [
        f"ZNANE USTALENIA: {known}" if known else "",
        f"ZAAKCEPTOWANE RYZYKA: {accepted}" if accepted else "",
    ]
    lines.append(", ".join(["KOLEJKA OK", *filter(None, counts)]))
    return Outcome(lines, 0)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Exhaustive check that the Kolejka Skrzynki Zgłoszeń delivers every part."
    )
    parser.add_argument(
        "--scope",
        choices=sorted(SCOPES),
        action="append",
        help="one scope; default: all",
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help="report known findings and accepted risks as violations too",
    )
    arguments = parser.parse_args(argv)
    outcome = summarize(
        [explore(name) for name in (arguments.scope or SCOPES)], strict=arguments.strict
    )
    print("\n".join(outcome.lines))
    return outcome.exit_code


if __name__ == "__main__":
    raise SystemExit(main())

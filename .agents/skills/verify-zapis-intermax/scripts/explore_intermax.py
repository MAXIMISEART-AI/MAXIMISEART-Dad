"""Exhaustively check how Uporządkowanie INTERMAX replaces the Rejestr zleceń and keeps its Kopia INTERMAX.

The checker runs the real ``intermax_ordering.order_register()`` on a synthetic INTERMAX (``tests/fixtures/intermax.py``)
in a real folder. Five steps of the code are points where the checker picks what happens first:

- after ``Register.read`` has read INTERMAX;
- ``workbook_files.is_open_in_excel`` on INTERMAX (in ``check`` and in ``before_replace``);
- ``intermax_copies.make_copy``, which may also raise ``OSError``;
- ``os.replace`` of the written temporary file over INTERMAX (``workbook_save.write_atomically``), which may also raise
  ``OSError``, and always raises ``PermissionError`` while Excel has INTERMAX open, as on Windows;
- ``intermax_copies.keep_newest``, which may also raise ``OSError``.

At each point a worker may first save a change to INTERMAX on another computer, which OneDrive puts in place as a new
file, Dad may open INTERMAX in Excel (the ``~$`` lock file), the step may fail, or the process may die. The checker
tries every such schedule within the bounds and checks:

- BEZ_UTRATY_ZMIAN: when the run replaces INTERMAX, it replaces the bytes it read. ADR 0019: the run „zmienia tylko
  Surowe zlecenia”, and every other part and row „zostają bajt w bajt”.
- KOPIA_ZASTAPIONEGO: when the run replaces INTERMAX, a Kopia INTERMAX holds exactly the bytes it replaced
  (ADR 0019: „Przed każdą podmianą powstaje Kopia INTERMAX”).
- ZATRZYMANIE_BEZ_SLADU: a run that stops (``StopError``) leaves INTERMAX as it was, no temporary file next to it and
  no new Kopia (docstring of ``order_register``).
- SUKCES: a run that returns has replaced INTERMAX and left no temporary file.
- BEZ_WYJATKU: the run ends with a summary or a ``StopError``, or the process dies; nothing else escapes.

Nothing in the product code is replaced; the checker only wraps the five functions to pick at their points.
"""

from __future__ import annotations

import argparse
import os
import shutil
import sys
import tempfile
from collections.abc import Callable, Iterator, Sequence
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Literal

sys.path.insert(0, str(Path(__file__).resolve().parents[4] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parents[4]))

from rozliczenia import intermax_copies, intermax_file, workbook_files, workbook_save
from rozliczenia.intermax_ordering import order_register
from rozliczenia.message import StopError

from tests.fixtures.intermax import Intermax, Order

NOW = datetime(2026, 10, 25, 20, 0, 0)
AFTER_READ = "pracownik po odczycie"
NAME = "INTERMAX.xlsx"

Actor = Literal["pracownik", "excel"]
Choice = Literal["ok", "pracownik", "excel", "oserror", "kill"]


class Crash(BaseException):
    """The process dies at this step (Dad closes Centrum, the computer switches off)."""


@dataclass(frozen=True)
class Bounds:
    worker: int = 1
    excel: int = 1
    oserror: int = 1
    kills: int = 1


class Scheduler:
    """Picks one option at each point from the schedule prefix, then the first option; records what it could pick."""

    def __init__(
        self, prefix: Sequence[int], bounds: Bounds, act: Callable[[Actor], None]
    ) -> None:
        self._prefix = prefix
        self._act = act
        self.taken: list[int] = []
        self.options: list[int] = []
        self.left: dict[Choice, int] = {
            "pracownik": bounds.worker,
            "excel": bounds.excel,
            "oserror": bounds.oserror,
            "kill": bounds.kills,
        }
        self.trace: list[str] = []
        self.faults: list[tuple[str, str]] = []

    def say(self, line: str) -> None:
        self.trace.append(line)

    def _pick(self, offered: Sequence[Choice], step: str) -> Choice:
        allowed = [choice for choice in offered if self.left.get(choice, 1) > 0]
        position = len(self.taken)
        index = self._prefix[position] if position < len(self._prefix) else 0
        self.taken.append(index)
        self.options.append(len(allowed))
        chosen = allowed[index]
        if chosen in self.left:
            self.left[chosen] -= 1
            self.faults.append((chosen, step))
        return chosen

    def point(self, step: str, *, can_fail: bool) -> None:
        """Before ``step``: actors may act first (each at most once), then the step may fail or the process die."""

        while True:
            offered: list[Choice] = ["ok", "pracownik", "excel", "kill"]
            if can_fail:
                offered.insert(3, "oserror")
            chosen = self._pick(offered, step)
            if chosen == "kill":
                self.say(f"proces ginie przed: {step}")
                raise Crash
            if chosen == "oserror":
                self.say(f"{step}: OSError")
                raise PermissionError("plik zablokowany")
            if chosen == "ok":
                return
            self._act(chosen)


@dataclass
class World:
    folder: Path
    copies: Path
    worker_bytes: bytes
    current: bytes
    """What INTERMAX holds as far as anyone but the run knows: the original or the worker's version."""
    read: bytes | None = None
    replaced: bytes | None = None
    written: bytes | None = None

    @property
    def register(self) -> Path:
        return self.folder / NAME

    @property
    def lock(self) -> Path:
        return workbook_files.excel_lock_file(self.register)


@contextmanager
def _points(world: World, scheduler: Scheduler) -> Iterator[None]:
    """Wraps the five functions; restores them afterwards."""

    real_read: Callable[
        [type[intermax_file.Register], Path], intermax_file.Register
    ] = intermax_file.Register.read.__func__  # type: ignore[attr-defined]
    real_open = workbook_files.is_open_in_excel
    real_copy = intermax_copies.make_copy
    real_keep = intermax_copies.keep_newest
    save_names = vars(workbook_save)
    real_os = save_names["os"]

    def read(cls: type[intermax_file.Register], path: Path) -> intermax_file.Register:
        register = real_read(cls, path)
        if path == world.register:
            world.read = register.content
            scheduler.say("Register.read czyta INTERMAX")
            scheduler.point("po odczycie INTERMAX", can_fail=False)
        return register

    def is_open(path: Path) -> bool:
        if path == world.register:
            scheduler.point("is_open_in_excel(INTERMAX)", can_fail=False)
        return real_open(path)

    def make_copy(content: bytes, directory: Path, moment: datetime) -> Path:
        scheduler.point("make_copy (Kopia INTERMAX)", can_fail=True)
        made = real_copy(content, directory, moment)
        scheduler.say(f"Kopia INTERMAX zapisana: {made.name}")
        return made

    def keep_newest(directory: Path) -> None:
        scheduler.point("keep_newest (stare Kopie)", can_fail=True)
        real_keep(directory)

    def replace(source: Any, target: Any) -> None:
        if Path(target) != world.register:
            real_os.replace(source, target)
            return
        scheduler.point("os.replace pliku tymczasowego na INTERMAX", can_fail=True)
        if world.lock.exists():
            scheduler.say(
                "os.replace: PermissionError, Excel trzyma INTERMAX (Windows)"
            )
            raise PermissionError("Excel trzyma INTERMAX")
        world.replaced = world.register.read_bytes()
        real_os.replace(source, target)
        world.written = world.register.read_bytes()
        scheduler.say("os.replace podmienia INTERMAX")

    intermax_file.Register.read = classmethod(read)  # type: ignore[method-assign,assignment]
    workbook_files.is_open_in_excel = is_open
    intermax_copies.make_copy = make_copy
    intermax_copies.keep_newest = keep_newest
    save_names["os"] = SimpleNamespace(replace=replace, close=real_os.close)
    try:
        yield
    finally:
        intermax_file.Register.read = classmethod(real_read)  # type: ignore[method-assign,assignment]
        workbook_files.is_open_in_excel = real_open
        intermax_copies.make_copy = real_copy
        intermax_copies.keep_newest = real_keep
        save_names["os"] = real_os


def _synthetic(work: Path) -> tuple[bytes, bytes]:
    """The original INTERMAX and the version a worker saves on another computer: one more ordered order above."""

    original, worker = Intermax(), Intermax()
    worker.ordered = (
        *original.ordered,
        Order(datetime(2026, 10, 20, 11), "jan.nowak", 4),
    )
    paths = (work / "oryginal.xlsx", work / "pracownik.xlsx")
    original.write(paths[0])
    worker.write(paths[1])
    return paths[0].read_bytes(), paths[1].read_bytes()


Outcome = Literal["podsumowanie", "zatrzymanie", "zginal", "wyjatek"]


@dataclass(frozen=True)
class Violation:
    rule: str
    detail: str
    trace: tuple[str, ...]
    kind: Literal["known", "new"]


def _check(world: World, outcome: Outcome, failure: str) -> list[tuple[str, str]]:
    broken: list[tuple[str, str]] = []
    left = sorted(
        path.name
        for path in world.folder.iterdir()
        if path.name not in (NAME, world.lock.name)
    )
    copies = (
        [path.read_bytes() for path in world.copies.iterdir()]
        if world.copies.exists()
        else []
    )
    if world.replaced is not None:
        if world.replaced != world.read:
            broken.append(
                (
                    "BEZ_UTRATY_ZMIAN",
                    "podmiana zastąpiła INTERMAX z cudzą zmianą, której run nie czytał",
                )
            )
        if world.replaced not in copies:
            broken.append(
                (
                    "KOPIA_ZASTAPIONEGO",
                    "żadna Kopia INTERMAX nie ma bajtów, które podmiana zastąpiła",
                )
            )
    if outcome == "zatrzymanie":
        if world.register.read_bytes() != world.current:
            broken.append(
                ("ZATRZYMANIE_BEZ_SLADU", "Zatrzymanie zostawia zmieniony INTERMAX")
            )
        if left:
            broken.append(
                (
                    "ZATRZYMANIE_BEZ_SLADU",
                    f"Zatrzymanie zostawia pliki obok INTERMAX: {left}",
                )
            )
        if copies:
            broken.append(
                (
                    "ZATRZYMANIE_BEZ_SLADU",
                    f"Zatrzymanie zostawia Kopię INTERMAX ({len(copies)})",
                )
            )
    if outcome == "podsumowanie":
        if world.written is None:
            broken.append(("SUKCES", "wynik bez podmiany INTERMAX"))
        if left:
            broken.append(("SUKCES", f"po wyniku zostają pliki obok INTERMAX: {left}"))
    if outcome == "wyjatek":
        broken.append(
            ("BEZ_WYJATKU", f"order_register kończy się wyjątkiem: {failure}")
        )
    return list(dict.fromkeys(broken))


def _worker_after_read(faults: Sequence[tuple[str, str]]) -> bool:
    """The worker's change arrived after ``Register.read`` and before ``os.replace``."""

    return any(kind == AFTER_READ for kind, _ in faults)


# (rule): the finding, and after which faults it is excused; the same rule broken otherwise is a new violation.
KNOWN_FINDINGS: dict[str, tuple[str, Callable[[Sequence[tuple[str, str]]], bool]]] = {
    "BEZ_UTRATY_ZMIAN": (
        "Uporządkowanie nie sprawdza przed os.replace, czy INTERMAX ma wciąż bajty, które przeczytało: zmiana "
        "pracownika z innego komputera, którą OneDrive wgrał w trakcie, przepada",
        _worker_after_read,
    ),
    "KOPIA_ZASTAPIONEGO": (
        "Kopia INTERMAX powstaje z bajtów przeczytanych na początku (register.content), więc nie ma też zmiany "
        "pracownika, która przyszła w trakcie",
        _worker_after_read,
    ),
}


def execute(
    prefix: Sequence[int], work: Path, original: bytes, worker: bytes, bounds: Bounds
) -> tuple[Scheduler, list[Violation]]:
    shutil.rmtree(work / "OneDrive", ignore_errors=True)
    shutil.rmtree(work / "Kopie INTERMAX", ignore_errors=True)
    folder = work / "OneDrive"
    folder.mkdir()
    world = World(folder, work / "Kopie INTERMAX", worker, original)
    world.register.write_bytes(original)

    def act(actor: Actor) -> None:
        if actor == "pracownik":
            scheduler.say(
                "pracownik zapisuje zmianę na innym komputerze, OneDrive podmienia INTERMAX"
            )
            incoming = folder / ".onedrive-przychodzi.tmp"
            incoming.write_bytes(world.worker_bytes)
            os.replace(incoming, world.register)
            world.current = world.worker_bytes
            if world.read is not None:
                scheduler.faults.append((AFTER_READ, ""))
        else:
            scheduler.say("tata otwiera INTERMAX w Excelu (plik ~$)")
            world.lock.write_bytes(b"tata")

    scheduler = Scheduler(prefix, bounds, act)
    outcome: Outcome = "podsumowanie"
    failure = ""
    with _points(world, scheduler):
        try:
            order_register(world.register, world.copies, now=lambda: NOW)
            scheduler.say("order_register zwraca podsumowanie")
        except StopError as stop:
            outcome = "zatrzymanie"
            scheduler.say(f"Zatrzymanie: {stop.message.code}")
        except Crash:
            outcome = "zginal"
        except Exception as error:  # noqa: BLE001 - BEZ_WYJATKU: every other exception is a finding
            outcome = "wyjatek"
            failure = f"{type(error).__name__}: {error}"
            scheduler.say(f"wyjątek {failure}")
    trace = tuple(scheduler.trace)
    violations = []
    for rule, detail in _check(world, outcome, failure):
        known = KNOWN_FINDINGS.get(rule)
        kind: Literal["known", "new"] = (
            "known" if known and known[1](scheduler.faults) else "new"
        )
        violations.append(Violation(rule, detail, trace, kind))
    return scheduler, violations


def next_prefix(scheduler: Scheduler) -> list[int] | None:
    for position in range(len(scheduler.taken) - 1, -1, -1):
        if scheduler.taken[position] + 1 < scheduler.options[position]:
            return [*scheduler.taken[:position], scheduler.taken[position] + 1]
    return None


@dataclass
class Report:
    schedules: int = 0
    shortest: dict[tuple[str, str], Violation] = field(default_factory=dict)


def explore(bounds: Bounds | None = None) -> Report:
    bounds = bounds or Bounds()
    report = Report()
    with tempfile.TemporaryDirectory(prefix="zapis-intermax-") as directory:
        work = Path(directory).resolve()  # order_register resolves the path of INTERMAX
        original, worker = _synthetic(work)
        prefix: list[int] | None = []
        while prefix is not None:
            scheduler, violations = execute(prefix, work, original, worker, bounds)
            report.schedules += 1
            for violation in violations:
                key = (violation.rule, violation.kind)
                seen = report.shortest.get(key)
                if seen is None or len(violation.trace) < len(seen.trace):
                    report.shortest[key] = violation
            prefix = next_prefix(scheduler)
    return report


def summarize(report: Report, *, strict: bool = False) -> tuple[list[str], int]:
    lines = [f"Harmonogramy: {report.schedules}."]
    new = known = 0
    for (rule, kind), violation in sorted(report.shortest.items()):
        if kind == "known" and not strict:
            known += 1
            lines.append(f"znane ustalenie {rule}: {KNOWN_FINDINGS[rule][0]}")
        else:
            new += 1
            lines.append(f"NOWE NARUSZENIE {rule}")
        lines.append(f"   {violation.detail}")
        lines.extend(
            f"   {number}. {step}"
            for number, step in enumerate(violation.trace, start=1)
        )
    gone = [rule for rule in KNOWN_FINDINGS if (rule, "known") not in report.shortest]
    lines.extend(
        f"ZNALEZISKO ZNIKNĘŁO {rule}: usuń je z KNOWN_FINDINGS i z SKILL.md"
        for rule in gone
    )
    lines.append("")
    if new:
        lines.append(f"INTERMAX: NOWE NARUSZENIE ({new})")
        return lines, 1
    if gone and not strict:
        lines.append(f"INTERMAX: ZNALEZISKO ZNIKNĘŁO ({len(gone)})")
        return lines, 1
    lines.append(f"INTERMAX OK, ZNANE USTALENIA: {known}" if known else "INTERMAX OK")
    return lines, 0


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Exhaustive check of how Uporządkowanie INTERMAX replaces INTERMAX."
    )
    parser.add_argument(
        "--strict", action="store_true", help="report known findings as violations too"
    )
    arguments = parser.parse_args(argv)
    lines, code = summarize(explore(), strict=arguments.strict)
    print("\n".join(lines))
    return code


if __name__ == "__main__":
    raise SystemExit(main())

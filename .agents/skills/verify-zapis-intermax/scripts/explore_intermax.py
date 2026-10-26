"""Exhaustively check how Uporządkowanie INTERMAX replaces the Rejestr zleceń and keeps its Kopie INTERMAX.

The checker runs the real ``intermax_ordering.order_register()`` on a synthetic INTERMAX (``tests/fixtures/intermax.py``)
in a real folder, next to a Kopie folder that already holds ``KEPT`` older Kopie. Seven steps of the code are points
where the checker picks what happens first:

- after ``Register.read`` has read INTERMAX;
- ``workbook_files.is_open_in_excel`` on INTERMAX (in ``check``, in ``Register.read`` and in ``before_replace``);
- the write of the temporary file next to INTERMAX (``intermax_file.save``), which may raise ``OSError``;
- the check of that file (``Register.check``), which may find it does not match (``WriteMismatch``);
- ``intermax_copies.make_copy``, which may raise ``OSError``;
- ``os.replace`` of the temporary file over INTERMAX (``workbook_save.write_atomically``), which may raise ``OSError``,
  and always raises ``PermissionError`` while Excel has INTERMAX open, as on Windows;
- ``intermax_copies.keep_newest``, which may raise ``OSError``.

At each point a worker may first save a change to INTERMAX on another computer, which OneDrive puts in place as a new
file (not while Excel holds INTERMAX: OneDrive then keeps a conflict copy beside it), Dad may open INTERMAX in Excel
(the ``~$`` lock file), the step may fail, or the process may die. The checker tries every such schedule within the
bounds and checks:

- BEZ_UTRATY_ZMIAN: when the run replaces INTERMAX, it replaces the bytes it read. ADR 0019: the run „zmienia tylko
  Surowe zlecenia”, and every other part and row „zostają bajt w bajt”.
- KOPIA_ZASTAPIONEGO: when the run replaces INTERMAX, a Kopia INTERMAX holds exactly the bytes it replaced
  (ADR 0019: „Przed każdą podmianą powstaje Kopia INTERMAX”).
- ZATRZYMANIE_BEZ_SLADU: a run that stops (``StopError``), or raises any other exception, leaves INTERMAX as it was,
  no temporary file next to it, and
  the Kopie folder with the same Kopie, names and bytes, as before (docstring of ``order_register``).
- SUKCES: a run that returns a summary has replaced INTERMAX and left no temporary file.
- KOPIE_NAJNOWSZE: after a summary, the Kopie folder holds the ``KEPT`` newest Kopie by name, the new one among them,
  unless removing older ones failed, which ``order_register`` turns into a warning.
- BEZ_WYJATKU: the run ends with a summary or a ``StopError``, or the process dies; nothing else escapes.

Nothing in the product code is replaced; the checker only wraps the steps to pick at their points. A killed process
is a ``BaseException`` raised at a point, so ``finally`` blocks still run, which a real kill would skip.
"""

from __future__ import annotations

import argparse
import os
import pathlib
import shutil
import sys
import tempfile
from collections.abc import Callable, Iterator, Sequence
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Literal

sys.path.insert(0, str(Path(__file__).resolve().parents[4] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parents[4]))

from rozliczenia import intermax_copies, intermax_file, workbook_files, workbook_save
from rozliczenia.intermax_file import WriteMismatch
from rozliczenia.intermax_ordering import order_register
from rozliczenia.message import StopError

from tests.fixtures.intermax import Intermax, Order

NOW = datetime(2026, 10, 25, 20, 0, 0)
NAME = "INTERMAX.xlsx"
TEMPORARY = f".{Path(NAME).stem}."
AFTER_READ = "pracownik po odczycie, przed podmianą"
INJECTED = "plik zablokowany"

Actor = Literal["pracownik", "excel"]
Choice = Literal["ok", "pracownik", "excel", "oserror", "niezgodny", "kill"]


class Crash(BaseException):
    """The process dies at this step (Dad closes Centrum, the computer switches off)."""


@dataclass(frozen=True)
class Bounds:
    worker: int = 1
    excel: int = 1
    oserror: int = 1
    mismatch: int = 1
    kills: int = 1


class Scheduler:
    """Picks one option at each point from the schedule prefix, then the first option; records what it could pick."""

    def __init__(
        self,
        prefix: Sequence[int],
        bounds: Bounds,
        act: Callable[[Actor], None],
        locked: Callable[[], bool],
    ) -> None:
        self._prefix = prefix
        self._act = act
        self._locked = locked
        self.taken: list[int] = []
        self.options: list[int] = []
        self.left: dict[Choice, int] = {
            "pracownik": bounds.worker,
            "excel": bounds.excel,
            "oserror": bounds.oserror,
            "niezgodny": bounds.mismatch,
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

    def point(
        self, step: str, *, fails: Literal["oserror", "niezgodny"] | None = None
    ) -> None:
        """Before ``step``: actors may act first (each at most once), then the step may fail or the process die."""

        while True:
            offered: list[Choice] = ["ok", "excel", "kill"]
            if not self._locked():
                offered.insert(1, "pracownik")
            if fails is not None:
                offered.insert(-1, fails)
            chosen = self._pick(offered, step)
            if chosen == "kill":
                self.say(f"proces ginie przed: {step}")
                raise Crash
            if chosen == "oserror":
                self.say(f"{step}: OSError")
                raise PermissionError(INJECTED)
            if chosen == "niezgodny":
                self.say(f"{step}: zapis się nie zgadza (WriteMismatch)")
                raise WriteMismatch("syntetyczna niezgodność")
            if chosen == "ok":
                return
            self._act(chosen)


@dataclass
class World:
    folder: Path
    copies: Path
    original: bytes
    worker_bytes: bytes
    current: bytes
    """What INTERMAX holds as far as anyone but the run knows: the original or the worker's version."""
    old_copies: dict[str, bytes]
    read: bytes | None = None
    replaced: bytes | None = None
    written: bytes | None = None
    keep_failed: bool = False
    failure: str = ""

    @property
    def register(self) -> Path:
        return self.folder / NAME

    @property
    def lock(self) -> Path:
        return workbook_files.excel_lock_file(self.register)

    def kopie(self) -> dict[str, bytes]:
        return (
            {path.name: path.read_bytes() for path in self.copies.iterdir()}
            if self.copies.exists()
            else {}
        )


@contextmanager
def _points(world: World, scheduler: Scheduler) -> Iterator[None]:
    """Wraps the seven steps; restores them afterwards."""

    real_read: Callable[
        [type[intermax_file.Register], Path], intermax_file.Register
    ] = intermax_file.Register.read.__func__  # type: ignore[attr-defined]
    real_check = intermax_file.Register.check
    real_open = workbook_files.is_open_in_excel
    real_copy = intermax_copies.make_copy
    real_keep = intermax_copies.keep_newest
    real_write_bytes = pathlib.Path.write_bytes
    save_names = vars(workbook_save)
    real_os = save_names["os"]

    def read(cls: type[intermax_file.Register], path: Path) -> intermax_file.Register:
        register = real_read(cls, path)
        if path == world.register:
            world.read = register.content
            scheduler.say("Register.read czyta INTERMAX")
            scheduler.point("po odczycie INTERMAX")
        return register

    def check(self: intermax_file.Register, *arguments: Any) -> None:
        scheduler.point("Register.check sprawdza plik tymczasowy", fails="niezgodny")
        real_check(self, *arguments)

    def is_open(path: Path) -> bool:
        if path == world.register:
            scheduler.point("is_open_in_excel(INTERMAX)")
        return real_open(path)

    def write_bytes(path: Path, data: Any) -> int:
        if path.parent == world.folder and path.name.startswith(TEMPORARY):
            scheduler.point("zapis pliku tymczasowego obok INTERMAX", fails="oserror")
        return real_write_bytes(path, data)

    def make_copy(content: bytes, directory: Path, moment: datetime) -> Path:
        scheduler.point("make_copy (Kopia INTERMAX)", fails="oserror")
        made = real_copy(content, directory, moment)
        scheduler.say(f"Kopia INTERMAX zapisana: {made.name}")
        return made

    def keep_newest(directory: Path) -> None:
        try:
            scheduler.point("keep_newest (stare Kopie)", fails="oserror")
        except OSError:
            world.keep_failed = True
            raise
        real_keep(directory)

    def replace(source: Any, target: Any) -> None:
        if Path(target) != world.register:
            real_os.replace(source, target)
            return
        scheduler.point("os.replace pliku tymczasowego na INTERMAX", fails="oserror")
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
    intermax_file.Register.check = check  # type: ignore[method-assign,assignment]
    workbook_files.is_open_in_excel = is_open
    intermax_copies.make_copy = make_copy
    intermax_copies.keep_newest = keep_newest
    pathlib.Path.write_bytes = write_bytes  # type: ignore[method-assign,assignment]
    save_names["os"] = SimpleNamespace(replace=replace, close=real_os.close)
    try:
        yield
    finally:
        intermax_file.Register.read = classmethod(real_read)  # type: ignore[method-assign,assignment]
        intermax_file.Register.check = real_check  # type: ignore[method-assign]
        workbook_files.is_open_in_excel = real_open
        intermax_copies.make_copy = real_copy
        intermax_copies.keep_newest = real_keep
        pathlib.Path.write_bytes = real_write_bytes  # type: ignore[method-assign]
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


def _old_copies() -> dict[str, bytes]:
    """``KEPT`` Kopie from earlier days, each with its own bytes, named as ``make_copy`` names them."""

    return {
        f"INTERMAX przed uporządkowaniem {NOW - timedelta(days=day):%Y-%m-%d %H-%M-%S}.xlsx": f"stara Kopia {day}".encode()
        for day in range(1, intermax_copies.KEPT + 1)
    }


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
    kopie = world.kopie()
    if world.replaced is not None:
        if world.replaced != world.read:
            broken.append(
                (
                    "BEZ_UTRATY_ZMIAN",
                    "podmiana zastąpiła INTERMAX z cudzą zmianą, której run nie czytał",
                )
            )
        if world.replaced not in kopie.values():
            broken.append(
                (
                    "KOPIA_ZASTAPIONEGO",
                    "żadna Kopia INTERMAX nie ma bajtów, które podmiana zastąpiła",
                )
            )
    if outcome in ("zatrzymanie", "wyjatek"):
        who = "Zatrzymanie" if outcome == "zatrzymanie" else "Wyjątek"
        if world.register.read_bytes() != world.current:
            broken.append(
                ("ZATRZYMANIE_BEZ_SLADU", f"{who} zostawia zmieniony INTERMAX")
            )
        if left:
            broken.append(
                (
                    "ZATRZYMANIE_BEZ_SLADU",
                    f"{who} zostawia pliki obok INTERMAX: {left}",
                )
            )
        if kopie != world.old_copies:
            broken.append(
                (
                    "ZATRZYMANIE_BEZ_SLADU",
                    f"{who} zmienia Kopie INTERMAX: {sorted(set(kopie) ^ set(world.old_copies))}",
                )
            )
    if outcome == "podsumowanie":
        if world.written is None:
            broken.append(("SUKCES", "wynik bez podmiany INTERMAX"))
        if left:
            broken.append(("SUKCES", f"po wyniku zostają pliki obok INTERMAX: {left}"))
        expected = sorted({*world.old_copies, *(set(kopie) - set(world.old_copies))})
        if not world.keep_failed and sorted(kopie) != expected[-intermax_copies.KEPT :]:
            broken.append(
                (
                    "KOPIE_NAJNOWSZE",
                    f"po wyniku zostają Kopie {sorted(kopie)} zamiast {intermax_copies.KEPT} najnowszych",
                )
            )
    if outcome == "wyjatek":
        broken.append(
            ("BEZ_WYJATKU", f"order_register kończy się wyjątkiem: {failure}")
        )
    return list(dict.fromkeys(broken))


def _worker_change_lost(world: World, faults: Sequence[tuple[str, str]]) -> bool:
    """A worker's change arrived after the read and before the replace, and the replace put the run's file over it."""

    return (
        any(kind == AFTER_READ for kind, _ in faults)
        and world.read == world.original
        and world.replaced == world.worker_bytes
    )


def _copy_of_what_was_read(world: World, faults: Sequence[tuple[str, str]]) -> bool:
    """The same story, and the Kopia holds the bytes the run read, as ``make_copy(register.content, …)`` makes it."""

    return _worker_change_lost(world, faults) and world.read in world.kopie().values()


def _temporary_write_failed(world: World, faults: Sequence[tuple[str, str]]) -> bool:
    """``OSError`` from writing the temporary file, which nothing between it and ``order_register`` catches."""

    return (
        ("oserror", "zapis pliku tymczasowego obok INTERMAX") in faults
        and world.replaced is None
        and world.failure == f"PermissionError: {INJECTED}"
    )


# rule: the finding, and the story after which it is excused; the same rule broken otherwise is a new violation.
KNOWN_FINDINGS: dict[
    str, tuple[str, Callable[[World, Sequence[tuple[str, str]]], bool]]
] = {
    "BEZ_UTRATY_ZMIAN": (
        "Uporządkowanie nie sprawdza przed os.replace, czy INTERMAX ma wciąż bajty, które przeczytało: zmiana "
        "pracownika z innego komputera, którą OneDrive wgrał w trakcie, przepada",
        _worker_change_lost,
    ),
    "KOPIA_ZASTAPIONEGO": (
        "Kopia INTERMAX powstaje z bajtów przeczytanych na początku (register.content), więc nie ma też zmiany "
        "pracownika, która przyszła w trakcie",
        _copy_of_what_was_read,
    ),
    "BEZ_WYJATKU": (
        "OSError z zapisu pliku tymczasowego (pełny dysk, plik zablokowany przez OneDrive albo antywirus) wychodzi z "
        "order_register jako nieoczekiwany wyjątek: write_atomically łapie OSError z utworzenia pliku tymczasowego i z os.replace, ale nie z zapisu "
        "jego treści, a "
        "order_register tylko WriteMismatch, UnsupportedShape i WorkbookSaveError",
        _temporary_write_failed,
    ),
}


def execute(
    prefix: Sequence[int], work: Path, original: bytes, worker: bytes, bounds: Bounds
) -> tuple[Scheduler, list[Violation]]:
    shutil.rmtree(work / "OneDrive", ignore_errors=True)
    shutil.rmtree(work / "Kopie INTERMAX", ignore_errors=True)
    folder = work / "OneDrive"
    folder.mkdir()
    world = World(
        folder, work / "Kopie INTERMAX", original, worker, original, _old_copies()
    )
    world.register.write_bytes(original)
    world.copies.mkdir()
    for name, content in world.old_copies.items():
        (world.copies / name).write_bytes(content)

    def act(actor: Actor) -> None:
        if actor == "pracownik":
            scheduler.say(
                "pracownik zapisuje zmianę na innym komputerze, OneDrive podmienia INTERMAX"
            )
            incoming = folder / ".onedrive-przychodzi.tmp"
            incoming.write_bytes(world.worker_bytes)
            os.replace(incoming, world.register)
            world.current = world.worker_bytes
            if world.read is not None and world.replaced is None:
                scheduler.faults.append((AFTER_READ, ""))
        else:
            scheduler.say("tata otwiera INTERMAX w Excelu (plik ~$)")
            world.lock.write_bytes(b"tata")

    scheduler = Scheduler(prefix, bounds, act, world.lock.exists)
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
            failure = world.failure = f"{type(error).__name__}: {error}"
            scheduler.say(f"wyjątek {failure}")
    trace = tuple(scheduler.trace)
    violations = []
    for rule, detail in _check(world, outcome, failure):
        known = KNOWN_FINDINGS.get(rule)
        kind: Literal["known", "new"] = (
            "known" if known and known[1](world, scheduler.faults) else "new"
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

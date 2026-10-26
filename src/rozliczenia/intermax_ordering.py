"""Uporządkowanie INTERMAX: Surowe zlecenia dnia na dole Rejestru zleceń stają się uporządkowanym dniem.

Jedyną operacją publiczną jest ``order_register()``. Silnik sekwencjonuje cztery etapy i jako jedyny tłumaczy fakty
rozpoznania, planu dnia i zapisu na Komunikaty: Sprawdzanie (INTERMAX jest i nie jest otwarty w Excelu), Odczyt
danych (``intermax_file.Register``), Planowanie (``raw_orders.recognize`` w każdym arkuszu zleceń i
``raw_orders.plan_day`` z widokiem na dzisiejszy dzień z ``now``) i Zapisywanie (``intermax_file.save`` z Kopią
INTERMAX z ``intermax_copies`` przed podmianą). Nie ma podglądu bez zapisu ani Decyzji taty. Zatrzymania zgłasza jako ``StopError``, a wynik nie zawiera
danych klientów.
"""

from __future__ import annotations

import time
from collections.abc import Callable, Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass, field, replace
from datetime import date, datetime
from pathlib import Path
from types import MappingProxyType

from openpyxl.utils.cell import get_column_letter

from . import intermax_copies, intermax_file, raw_orders, workbook_files
from . import intermax_messages as messages
from .domain import ProgressObserver, ProgressPhase
from .intermax_file import HeldByOneDrive, OrderSheet, Register, UnsupportedShape, Waiting, WriteMismatch
from .message import Message, StopError
from .phase_runner import PhaseRunner
from .raw_orders import (
    AboveOrdered,
    DayOrdered,
    DayPlan,
    Obstacle,
    RawBlock,
    SeveralDays,
    Undated,
    WithoutWorker,
)
from .workbook_files import WorkbookError
from .workbook_save import WorkbookSaveError

__all__ = ["OrderingSummary", "order_register"]


@dataclass
class OrderingSummary:
    """Podsumowanie Uporządkowania INTERMAX bez danych klientów: dzień, liczba zleceń i Wykonawców, nazwa Kopii."""

    day: date
    order_count: int
    worker_count: int
    copy_name: str
    warnings: list[Message] = field(default_factory=list)
    phase_durations_ms: Mapping[ProgressPhase, int] = field(default_factory=lambda: MappingProxyType({}))


@contextmanager
def _stops(explain: Callable[[], Message], *errors: type[Exception]) -> Iterator[None]:
    try:
        yield
    except errors as error:
        raise StopError(explain()) from error


def order_register(
    register_path: Path,
    copies_directory: Path,
    *,
    now: Callable[[], datetime],
    waiting: Waiting,
    observer: ProgressObserver | None = None,
    clock: Callable[[], float] = time.perf_counter,
) -> OrderingSummary:
    """Porządkuje Surowe zlecenia dnia w INTERMAX ``register_path``.

    Zgłasza ``StopError``, gdy nie można działać bezpiecznie; INTERMAX zostaje wtedy nietknięty. Przed podmianą
    INTERMAX powstaje Kopia INTERMAX w ``copies_directory`` z nazwą z ``now()``; gdy podmiana się nie uda, Kopia
    znika. Po udanym zapisie zostaje 10 najnowszych Kopii, a nieudane usunięcie starszych to ostrzeżenie: INTERMAX
    jest już uporządkowany. ``clock`` to zegar w sekundach, z którego liczone są czasy etapów, a ``waiting`` zegar
    i przerwa krótkiej ponownej próby podmiany, której odmawia OneDrive.
    """

    phases = PhaseRunner(observer, clock=clock)
    register_path = register_path.expanduser().resolve()

    def check() -> None:
        try:
            workbook_files.ensure_available(register_path)
        except WorkbookError as error:
            raise StopError(messages.register_unusable(error)) from error

    phases.check(check)

    def read() -> Register:
        try:
            register = Register.read(register_path)
        except WorkbookError as error:
            raise StopError(messages.register_unusable(error)) from error
        if not register.order_sheets:
            raise StopError(messages.no_order_sheet(register_path))
        return register

    register = phases.read(read)

    def plan() -> tuple[OrderSheet, RawBlock, DayPlan]:
        found: list[tuple[OrderSheet, RawBlock | Obstacle]] = []
        for candidate in register.order_sheets:
            with _stops(lambda: messages.unsupported_shape(register_path, candidate.name), UnsupportedShape):
                recognized = raw_orders.recognize(candidate.rows_from_bottom(), candidate.columns)
            if recognized is not None:
                found.append((candidate, recognized))
        if not found:
            raise StopError(messages.no_raw_orders(register_path, register.order_sheets[0].name))
        if len(found) > 1:
            raise StopError(messages.raw_orders_in_several_sheets(register_path, [sheet.name for sheet, _ in found]))
        [(sheet, recognized)] = found
        if not isinstance(recognized, RawBlock):
            raise StopError(_obstacle(register_path, sheet.name, recognized))
        return sheet, recognized, raw_orders.plan_day(recognized, sheet.rows_from_bottom(), sheet.columns, now().date())

    sheet, block, day = phases.plan(plan, issue_count=lambda _: 0)
    copies: list[Path] = []
    warnings: list[Message] = []

    def before_replace() -> None:
        if workbook_files.is_open_in_excel(register_path):
            raise StopError(messages.register_open(register_path))
        with _stops(lambda: messages.copy_failed(copies_directory), OSError):
            copies.append(intermax_copies.make_copy(register.content, copies_directory, now()))

    def save() -> None:
        with (
            _stops(lambda: messages.write_check_failed(register_path), WriteMismatch),
            _stops(lambda: messages.unsupported_shape(register_path, sheet.name), UnsupportedShape),
        ):
            try:
                intermax_file.save(register, sheet, block, day, before_replace=before_replace, waiting=waiting)
            except WorkbookSaveError as error:
                for copy in copies:
                    copy.unlink()
                raise StopError(messages.register_open(register_path)) from error
            except HeldByOneDrive as error:
                for copy in copies:
                    copy.unlink()
                raise StopError(messages.register_syncing(register_path)) from error
        try:
            intermax_copies.keep_newest(copies_directory)
        except OSError:
            warnings.append(messages.old_copies_kept(copies_directory))

    phases.save(save)
    summary = OrderingSummary(day.day, len(day.placements), day.worker_count, copies[0].name, warnings)
    return replace(summary, phase_durations_ms=phases.durations_ms())


def _obstacle(register: Path, sheet: str, obstacle: Obstacle) -> Message:
    match obstacle:
        case AboveOrdered(row, ordered_row):
            return messages.raw_order_above_ordered(register, sheet, row, ordered_row)
        case Undated(row, column):
            return messages.raw_order_without_value(register, sheet, row, get_column_letter(column), worker=False)
        case WithoutWorker(row, column):
            return messages.raw_order_without_value(register, sheet, row, get_column_letter(column), worker=True)
        case SeveralDays(days, first_row, last_row):
            return messages.several_days(register, sheet, days, first_row, last_row)
        case DayOrdered(day, first_row, last_row):
            return messages.day_already_ordered(register, sheet, day, first_row, last_row)


def register_problem(register_path: Path) -> Message | None:
    """Komunikat, którym Sprawdzanie albo Odczyt danych zatrzymałyby Uporządkowanie INTERMAX; ``None``, gdy przechodzą.

    Tylko czyta, więc Diagnoza sprawdza INTERMAX tą samą regułą co proces. ``Register.read`` sprawdza najpierw to
    samo co Sprawdzanie i daje ten sam Komunikat, więc wystarcza sam.
    """

    try:
        register = Register.read(register_path)
    except WorkbookError as error:
        return messages.register_unusable(error)
    return None if register.order_sheets else messages.no_order_sheet(register_path)

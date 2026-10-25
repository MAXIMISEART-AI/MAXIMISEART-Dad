"""Uporządkowanie INTERMAX: Surowe zlecenia dnia na dole Rejestru zleceń stają się uporządkowanym dniem.

Jedyną operacją publiczną jest ``order_register()``. Silnik sekwencjonuje cztery etapy i jako jedyny tłumaczy fakty
rozpoznania, planu dnia i zapisu na Komunikaty: Sprawdzanie (INTERMAX jest i nie jest otwarty w Excelu), Odczyt
danych (``intermax_file.Register``), Planowanie (``raw_orders.recognize`` i ``raw_orders.plan_day``) i Zapisywanie
(``intermax_file.save`` z Kopią INTERMAX z ``intermax_copies`` przed podmianą). Nie ma podglądu bez zapisu ani
Decyzji taty. Zatrzymania zgłasza jako ``StopError``, a wynik nie zawiera danych klientów.
"""

from __future__ import annotations

import time
from collections.abc import Callable, Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass, field, replace
from datetime import date, datetime
from pathlib import Path
from types import MappingProxyType

from . import intermax_copies, intermax_file, raw_orders, workbook_files
from . import intermax_messages as messages
from .domain import ProgressObserver, ProgressPhase
from .intermax_file import OrderSheet, Register, UnsupportedShape, WriteMismatch
from .message import Message, StopError
from .phase_runner import PhaseRunner
from .raw_orders import DayPlan, RawBlock
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
    store: Callable[[Path, bytes], None],
    observer: ProgressObserver | None = None,
    clock: Callable[[], float] = time.perf_counter,
) -> OrderingSummary:
    """Porządkuje Surowe zlecenia dnia w INTERMAX ``register_path``.

    Zgłasza ``StopError``, gdy nie można działać bezpiecznie; INTERMAX zostaje wtedy nietknięty. Przed podmianą
    INTERMAX powstaje Kopia INTERMAX w ``copies_directory`` z nazwą z ``now()``, a po udanym zapisie zostaje 10
    najnowszych Kopii. ``store`` zapisuje bajty pliku tymczasowego obok INTERMAX, który przed podmianą jest
    sprawdzany. ``clock`` to zegar w sekundach, z którego liczone są czasy etapów.
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
        sheet = register.order_sheets[0]
        for candidate in register.order_sheets:
            with _stops(lambda: messages.unsupported_shape(register_path, candidate.name), UnsupportedShape):
                block = raw_orders.recognize(candidate.rows_from_bottom(), candidate.columns)
            if isinstance(block, RawBlock):
                return candidate, block, raw_orders.plan_day(block)
        raise StopError(messages.no_raw_orders(register_path, sheet.name))

    sheet, block, day = phases.plan(plan, issue_count=lambda _: 0)
    copies: list[Path] = []

    def before_replace() -> None:
        if workbook_files.is_open_in_excel(register_path):
            raise StopError(messages.register_open(register_path))
        with _stops(lambda: messages.copy_failed(copies_directory), OSError):
            copies.append(intermax_copies.make_copy(register.content, copies_directory, now()))

    def save() -> None:
        with (
            _stops(lambda: messages.write_check_failed(register_path), WriteMismatch),
            _stops(lambda: messages.unsupported_shape(register_path, sheet.name), UnsupportedShape),
            _stops(lambda: messages.register_open(register_path), WorkbookSaveError),
        ):
            intermax_file.save(register, sheet, block, day, store=store, before_replace=before_replace)
        intermax_copies.keep_newest(copies_directory)

    phases.save(save)
    summary = OrderingSummary(day.day, len(day.placements), day.worker_count, copies[0].name)
    return replace(summary, phase_durations_ms=phases.durations_ms())

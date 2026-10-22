"""Wybór zleceń okresu i reguły zleceń w Przygotowaniu pliku zbiorczego (etap Planowanie).

Zakres okresu w Rejestrze to wiersze od pierwszego do ostatniego zlecenia
okresu w arkuszu ze zleceniami. W tym zakresie wiersz z danymi bez poprawnej
daty zatrzymuje proces, a całkowicie puste wiersze są liczone jako pominięte.
Moduł wewnętrzny Przygotowania pliku zbiorczego; operacją publiczną pozostaje
``collective_preparation.prepare_collective_file()``.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path

from . import preparation_messages as messages
from .message import Message, StopError
from .preparation_register import DATE, SUCCESSFUL, WORKER, RegisterSheet, cell_value, is_blank
from .settlement_period import SettlementPeriod
from .workbook_files import DataRow
from .worker_config import normalize_text

_SUCCESSFUL_VALUE = "tak"
_UNSUCCESSFUL_VALUE = "nie"
_BLANK_WORKER_LABEL = "(pusty)"


@dataclass(frozen=True)
class PeriodOrder:
    """Zlecenie okresu: wiersz Rejestru i jego data z ``DATA GODZ. POCZ.``."""

    row: DataRow
    started: datetime

    @property
    def row_number(self) -> int:
        return self.row.number

    @property
    def is_successful(self) -> bool:
        return normalize_text(cell_value(self.row, SUCCESSFUL)) == _SUCCESSFUL_VALUE


@dataclass(frozen=True)
class Plan:
    period: SettlementPeriod
    sheet: str
    orders: list[PeriodOrder]
    skipped_empty_rows: int

    @property
    def orders_per_day(self) -> dict[date, int]:
        first_day = self.period.start.date()
        counts = {first_day + timedelta(days=offset): 0 for offset in range(7)}
        for order in self.orders:
            counts[order.started.date()] += 1
        return counts

    @property
    def successful_orders(self) -> list[PeriodOrder]:
        return [order for order in self.orders if order.is_successful]


def plan_period_orders(
    register_path: Path,
    sheets: Sequence[RegisterSheet],
    period: SettlementPeriod,
    config_path: Path,
    worker_mapping: Mapping[str, str],
) -> Plan:
    """Wybiera zlecenia okresu po dacie, w kolejności Rejestru, i sprawdza reguły zleceń."""

    register = _period_sheet(register_path, sheets, period)
    orders: list[PeriodOrder] = []
    undated_rows: list[int] = []
    for row in register.rows:
        started = _order_date(cell_value(row, DATE))
        if started is None:
            undated_rows.append(row.number)
        elif period.start <= started < period.end:
            orders.append(PeriodOrder(row, started))
    if not orders:
        raise StopError(messages.no_period_orders(register_path, register.name, period.token))
    first_row, last_row = orders[0].row_number, orders[-1].row_number
    undated_between = [row for row in undated_rows if first_row < row < last_row]
    if undated_between:
        raise StopError(messages.rows_without_date(register_path, register.name, undated_between))
    _check_successful_values(register_path, register, orders)
    unknown_workers = _unknown_workers(orders, worker_mapping)
    if unknown_workers:
        raise StopError(messages.unknown_workers(register_path, register.name, config_path, unknown_workers))
    skipped_empty_rows = sum(1 for row in register.empty_rows if first_row < row < last_row)
    return Plan(period, register.name, orders, skipped_empty_rows)


def period_warnings(register_path: Path, plan: Plan) -> list[Message]:
    """Ostrzeżenie o niepełnym okresie, gdy żadne zlecenie okresu nie jest z poniedziałku."""

    monday = plan.period.monday
    last_order_day = max(order.started.date() for order in plan.orders)
    if last_order_day >= monday:
        return []
    return [messages.incomplete_period(register_path, plan.sheet, plan.period.token, last_order_day, monday)]


def _order_date(value: object) -> datetime | None:
    if isinstance(value, datetime):
        return value
    if isinstance(value, date):
        return datetime(value.year, value.month, value.day)
    return None


def _in_period(row: DataRow, period: SettlementPeriod) -> bool:
    started = _order_date(cell_value(row, DATE))
    return started is not None and period.start <= started < period.end


def _check_successful_values(register_path: Path, register: RegisterSheet, orders: Sequence[PeriodOrder]) -> None:
    """Zatrzymanie, gdy zlecenie okresu nie ma ``tak`` ani ``nie`` w ``SKUTECZNE``: puste komórki i inne wartości."""

    empty_rows: list[int] = []
    other_values: list[messages.CellContent] = []
    for order in orders:
        value = cell_value(order.row, SUCCESSFUL)
        if normalize_text(value) in (_SUCCESSFUL_VALUE, _UNSUCCESSFUL_VALUE):
            continue
        if is_blank(value):
            empty_rows.append(order.row_number)
        else:
            other_values.append(messages.CellContent(order.row_number, value))
    if empty_rows or other_values:
        raise StopError(
            messages.invalid_successful_values(
                register_path, register.name, register.column_letter(SUCCESSFUL), empty_rows, other_values
            )
        )


def _period_sheet(register_path: Path, sheets: Sequence[RegisterSheet], period: SettlementPeriod) -> RegisterSheet:
    """Jedyny arkusz Rejestru ze zleceniami okresu; bez takiego arkusza pierwszy arkusz ze zleceniami."""

    with_orders = [sheet for sheet in sheets if any(_in_period(row, period) for row in sheet.rows)]
    if len(with_orders) > 1:
        raise StopError(
            messages.period_orders_in_many_sheets(register_path, [sheet.name for sheet in with_orders], period.token)
        )
    return (with_orders or list(sheets))[0]


def _unknown_workers(
    orders: Sequence[PeriodOrder], worker_mapping: Mapping[str, str]
) -> list[tuple[str, list[int]]]:
    """Wykonawcy Zleceń skutecznych spoza konfiguracji wykonawców, z numerami wierszy Rejestru."""

    unknown: dict[str, tuple[str, list[int]]] = {}
    for order in orders:
        worker = cell_value(order.row, WORKER)
        key = normalize_text(worker)
        if not order.is_successful or key in worker_mapping:
            continue
        label = str(worker).strip() if key else _BLANK_WORKER_LABEL
        unknown.setdefault(key, (label, []))[1].append(order.row_number)
    return list(unknown.values())

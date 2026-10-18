"""Wzorce i pliki okresu w Przygotowaniu pliku zbiorczego.

Moduł sprawdza oba wzorce (Sprawdzanie), ocenia, czy zlecenia zmieszczą się we
wzorcach (Planowanie), i zapisuje Rozliczenie wewnętrzne oraz Plik zbiorczy
razem do Folderu okresu (Zapisywanie). Każdy problem ze wzorcem jest typowanym
zatrzymaniem ``PreparationError``. Moduł wewnętrzny Przygotowania pliku
zbiorczego; operacją publiczną pozostaje
``collective_preparation.prepare_collective_file()``.
"""

from __future__ import annotations

import os
import tempfile
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from copy import copy
from dataclasses import dataclass
from pathlib import Path
from typing import cast

from openpyxl import load_workbook
from openpyxl.cell.cell import Cell
from openpyxl.styles import Alignment, Border, Font, PatternFill, Protection
from openpyxl.utils import get_column_letter
from openpyxl.workbook.workbook import Workbook
from openpyxl.worksheet.dimensions import Dimension
from openpyxl.worksheet.filters import AutoFilter
from openpyxl.worksheet.worksheet import Worksheet

from . import collective_file, workbook_files
from . import preparation_messages as messages
from .engine import normalize_text
from .preparation_messages import PreparationMessage
from .preparation_plan import PeriodOrder
from .preparation_register import COLUMNS, UNREADABLE_WORKBOOK_ERRORS, CellFormat, header_columns, is_blank


@dataclass(frozen=True)
class _TemplateLayout:
    """Gdzie we wzorcu jest nagłówek i od którego wiersza trafiają zlecenia."""

    header_row: int
    first_data_row: int
    last_header_column: int | None  # ``None``: cały wiersz nagłówka


_INTERNAL = _TemplateLayout(header_row=1, first_data_row=2, last_header_column=None)
_COLLECTIVE = _TemplateLayout(
    header_row=collective_file.HEADER_ROW,
    first_data_row=collective_file.FIRST_DATA_ROW,
    last_header_column=collective_file.INPUT_COLUMNS[-1],
)


@dataclass(frozen=True)
class PeriodFiles:
    """Ścieżki obu wzorców i obu plików okresu w Folderze okresu."""

    internal_template: Path
    collective_template: Path
    period_directory: Path
    period: str

    @property
    def internal_settlement_file(self) -> Path:
        return self.period_directory / f"Rozliczenie wew. {self.period}.xlsx"

    @property
    def collective_file(self) -> Path:
        return collective_file.path_for_period(self.period_directory, self.period)

    @property
    def filenames(self) -> tuple[str, str]:
        return (self.internal_settlement_file.name, self.collective_file.name)


def check_templates(files: PeriodFiles) -> None:
    """Sprawdzanie: oba wzorce istnieją, nie są otwarte, dają się odczytać i mają oczekiwane nagłówki.

    Wzorzec pliku zbiorczego ma ponadto WYKONAWCA w H17, bo stamtąd czyta go Przebieg rozliczeń.
    """

    _ensure_template_available(files.internal_template)
    with _open_template(files.internal_template, _INTERNAL):
        pass
    _ensure_template_available(files.collective_template)
    with _open_template(files.collective_template, _COLLECTIVE) as (_, sheet, _):
        try:
            collective_file.check_layout(sheet)
        except collective_file.LayoutError as exc:
            if exc.worker_column is None:
                raise messages.template_without_header(
                    files.collective_template, sheet.title, collective_file.HEADER_ROW, "WYKONAWCA"
                ) from exc
            raise messages.template_with_worker_outside_h(
                files.collective_template, sheet.title, exc.worker_column
            ) from exc


def _ensure_template_available(template_path: Path) -> None:
    workbook_files.ensure_available(
        template_path,
        missing=messages.template_missing,
        open_in_excel=messages.template_open_in_excel,
    )


def ensure_period_files_absent(files: PeriodFiles) -> None:
    """Nienadpisywanie: żaden z dwóch plików okresu nie istnieje jeszcze w Folderze okresu."""

    for target in (files.internal_settlement_file, files.collective_file):
        if target.exists() or target.is_symlink():
            raise messages.period_file_exists(files.period_directory, target.name)


def plan_period_files(files: PeriodFiles, order_count: int, successful_count: int) -> list[PreparationMessage]:
    """Planowanie: zlecenia zmieszczą się we wzorcach; zwraca ostrzeżenia Pliku zbiorczego.

    Scalone komórki w wierszach, do których trafią zlecenia, są zatrzymaniem.
    Wzorca pliku zbiorczego nie wydłużamy, więc za mało wierszy z zerami to ostrzeżenie.
    """

    with _open_template(files.internal_template, _INTERNAL) as (_, sheet, positions):
        _ensure_rows_writable(files.internal_template, sheet, positions, _INTERNAL.first_data_row, order_count)
    with _open_template(files.collective_template, _COLLECTIVE) as (_, sheet, positions):
        _ensure_rows_writable(files.collective_template, sheet, positions, _COLLECTIVE.first_data_row, successful_count)
        zero_row_count = _zero_row_count(sheet)
    if successful_count <= zero_row_count:
        return []
    return [
        messages.too_few_zero_rows(
            files.collective_file.name,
            successful_count,
            zero_row_count,
            _COLLECTIVE.first_data_row + zero_row_count,
        )
    ]


def write_period_files(
    files: PeriodFiles,
    staging_parent: Path,
    orders: Sequence[PeriodOrder],
    successful_orders: Sequence[PeriodOrder],
) -> None:
    """Zapisywanie: przygotowuje oba pliki w katalogu tymczasowym i publikuje je razem.

    Błąd nie zostawia żadnego z plików ani nowo założonego Folderu okresu.
    """

    try:
        with tempfile.TemporaryDirectory(prefix=f".{files.period}.staging-", dir=staging_parent) as staging:
            staged_directory = Path(staging) / files.period
            staged_directory.mkdir()
            internal_name, collective_name = files.filenames
            _write_period_file(files.internal_template, _INTERNAL, staged_directory / internal_name, orders)
            _write_period_file(
                files.collective_template,
                _COLLECTIVE,
                staged_directory / collective_name,
                successful_orders,
                recalculate_on_open=True,
            )
            _publish(staged_directory, files)
    except (OSError, workbook_files.WorkbookSaveError) as exc:
        raise messages.write_failed(files.period_directory) from exc


@contextmanager
def _open_template(
    template_path: Path, layout: _TemplateLayout
) -> Iterator[tuple[Workbook, Worksheet, list[int]]]:
    """Wzorzec z arkuszem roboczym i kolumnami ``COLUMNS``; problem ze wzorcem to zatrzymanie."""

    try:
        workbook = load_workbook(template_path, read_only=False, data_only=False, keep_links=True)
    except UNREADABLE_WORKBOOK_ERRORS as exc:
        raise messages.template_unreadable(template_path) from exc
    try:
        sheet = workbook.active
        if not isinstance(sheet, Worksheet):
            raise messages.template_unreadable(template_path)
        header = [
            sheet.cell(layout.header_row, column).value
            for column in range(1, (layout.last_header_column or sheet.max_column) + 1)
        ]
        yield workbook, sheet, _target_columns(template_path, sheet.title, layout.header_row, header)
    finally:
        workbook.close()


def _target_columns(template_path: Path, sheet_title: str, header_row: int, header: Sequence[object]) -> list[int]:
    """Kolumny wzorca dla ``COLUMNS``, rozpoznane wyłącznie po nagłówku docelowym."""

    columns = header_columns(header)
    positions: list[int] = []
    for column in COLUMNS:
        position = columns.get(normalize_text(column.target_header))
        if position is None:
            raise messages.template_without_header(template_path, sheet_title, header_row, column.target_header)
        positions.append(position)
    return positions


def _ensure_rows_writable(
    template_path: Path, sheet: Worksheet, positions: Sequence[int], first_row: int, row_count: int
) -> None:
    """Zatrzymanie, gdy komórki, do których trafią zlecenia, są scalone we wzorcu."""

    if row_count == 0:
        return
    last_row = first_row + row_count - 1
    for merged in sheet.merged_cells.ranges:
        overlaps_rows = merged.min_row <= last_row and merged.max_row >= first_row
        if overlaps_rows and any(merged.min_col <= position <= merged.max_col for position in positions):
            raise messages.template_with_merged_cells(template_path, sheet.title, merged.coord)


def _is_zero(value: object) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and value == 0


def _zero_row_count(sheet: Worksheet) -> int:
    """Liczba kolejnych wierszy danych Wzorca pliku zbiorczego z zerami w kolumnach ilości."""

    quantity_columns = collective_file.QUANTITY_COLUMNS
    count = 0
    for values in sheet.iter_rows(
        min_row=_COLLECTIVE.first_data_row,
        min_col=quantity_columns[0],
        max_col=quantity_columns[-1],
        values_only=True,
    ):
        if not any(_is_zero(value) for value in values):
            break
        count += 1
    return count


def _apply_template_style(sheet: Worksheet, cell: Cell) -> None:
    """Komórka bez własnego stylu we wzorcu dostaje styl wiersza, a bez niego styl kolumny, jak przy wpisaniu w Excelu."""

    if cell.has_style:
        return
    row_dimension = sheet.row_dimensions.get(cell.row)  # bez tworzenia wymiaru, którego nie ma we wzorcu
    if row_dimension is not None and row_dimension.has_style:
        _copy_dimension_style(row_dimension, cell)
        return
    for dimension in sheet.column_dimensions.values():
        if dimension.min is not None and dimension.max is not None and dimension.min <= cell.column <= dimension.max:
            if dimension.has_style:
                _copy_dimension_style(dimension, cell)
            return


def _copy_dimension_style(dimension: Dimension, cell: Cell) -> None:
    cell.font = cast(Font, copy(dimension.font))
    cell.border = cast(Border, copy(dimension.border))
    cell.alignment = cast(Alignment, copy(dimension.alignment))
    cell.protection = cast(Protection, copy(dimension.protection))


def _apply_register_format(cell: Cell, cell_format: CellFormat) -> None:
    """Wyróżnienia i format liczby z Rejestru; krój i rozmiar czcionki zostają z wzorca."""

    font = cast(Font, copy(cell.font))
    font.color = copy(cell_format.color)
    font.b = cell_format.bold
    font.i = cell_format.italic
    cell.font = font
    cell.fill = copy(cell_format.fill) if cell_format.fill is not None else PatternFill()
    cell.number_format = cell_format.number_format


def _set_autofilter(sheet: Worksheet, header_row: int, order_count: int) -> None:
    """Autofiltr na nagłówek i faktyczne wiersze danych; zakres zapisany we wzorcu jest ignorowany."""

    header_columns_present = [
        column for column, cell in enumerate(sheet[header_row], start=1) if not is_blank(cell.value)
    ]
    first_column = get_column_letter(min(header_columns_present))
    last_column = get_column_letter(max(header_columns_present))
    sheet.auto_filter = AutoFilter(ref=f"{first_column}{header_row}:{last_column}{header_row + order_count}")


def _write_period_file(
    template_path: Path,
    layout: _TemplateLayout,
    target: Path,
    orders: Sequence[PeriodOrder],
    *,
    recalculate_on_open: bool = False,
) -> None:
    """Kopia wzorca ze zleceniami od pierwszego wiersza danych; odwołania zewnętrzne zostają 1:1."""

    with _open_template(template_path, layout) as (workbook, sheet, positions):
        _ensure_rows_writable(template_path, sheet, positions, layout.first_data_row, len(orders))
        for row, order in enumerate(orders, start=layout.first_data_row):
            for position, register_cell in zip(positions, order.row.cells):
                cell = sheet.cell(row, position)
                if not isinstance(cell, Cell):  # scalona komórka; wykluczona przez _ensure_rows_writable
                    raise messages.template_with_merged_cells(template_path, sheet.title, cell.coordinate)
                _apply_template_style(sheet, cell)
                cell.value = register_cell.value  # type: ignore[assignment]
                _apply_register_format(cell, register_cell.format)
        _set_autofilter(sheet, layout.header_row, len(orders))
        if recalculate_on_open:
            workbook_files.request_full_recalculation(workbook)
        workbook_files.save_workbook(workbook, target, external_links_from=template_path)


def _publish(staged_directory: Path, files: PeriodFiles) -> None:
    """Przenosi oba pliki do Folderu okresu razem; przy błędzie nie zostawia żadnego."""

    ensure_period_files_absent(files)
    period_directory = files.period_directory
    if not period_directory.exists():
        staged_directory.rename(period_directory)
        return
    published: list[Path] = []
    try:
        for filename in files.filenames:
            target = period_directory / filename
            os.rename(staged_directory / filename, target)
            published.append(target)
    except OSError:
        for target in published:
            target.unlink(missing_ok=True)
        raise

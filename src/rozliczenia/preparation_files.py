"""Wzorce i pliki okresu w Przygotowaniu pliku zbiorczego.

Moduł sprawdza oba wzorce (Sprawdzanie), ocenia, czy zlecenia zmieszczą się we
wzorcach (Planowanie), i zapisuje Rozliczenie wewnętrzne oraz Plik zbiorczy
razem do Folderu okresu (Zapisywanie). Każdy problem ze wzorcem jest typowanym
zatrzymaniem ``StopError``. Moduł wewnętrzny Przygotowania pliku
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

from openpyxl.cell.cell import Cell
from openpyxl.styles import Alignment, Border, Font, PatternFill, Protection
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.dimensions import Dimension
from openpyxl.worksheet.filters import AutoFilter
from openpyxl.worksheet.worksheet import Worksheet

from . import workbook_files
from . import preparation_messages as messages
from .message import Message, StopError
from .period_folder import PeriodFolder
from .preparation_plan import PeriodOrder
from .preparation_register import COLUMNS, CellFormat, header_columns, is_blank
from .workbook_files import Layout, Problem, TemplateSheet, WorkbookError
from .worker_config import normalize_text


@dataclass(frozen=True)
class PeriodFiles:
    """Ścieżki obu wzorców i Folder okresu, w którym powstają oba pliki okresu.

    ``PeriodFolder`` wymaga sprawdzonego okresu, więc wartość powstaje dopiero po sprawdzeniu tokenu.
    """

    internal_template: Path
    collective_template: Path
    folder: PeriodFolder

    @property
    def filenames(self) -> tuple[str, str]:
        """Rozliczenie wewnętrzne i Plik zbiorczy, w kolejności publikacji."""

        return (self.folder.internal_settlement.name, self.folder.collective_file.name)


def check_internal_template(template_path: Path) -> None:
    """Wzorzec rozliczenia wewnętrznego istnieje, nie jest otwarty, daje się odczytać i ma nagłówki."""

    with _template(template_path, Layout.INTERNAL):
        pass


def check_collective_template(template_path: Path) -> None:
    """Wzorzec pliku zbiorczego jak ``check_internal_template`` i z WYKONAWCA w H17."""

    with _template(template_path, Layout.COLLECTIVE) as (sheet, _):
        try:
            sheet.check_worker_header()
        except WorkbookError as exc:
            if exc.worker_column is None:
                raise StopError(
                    messages.template_without_header(template_path, sheet.title, sheet.header_row, "WYKONAWCA")
                ) from exc
            raise StopError(
                messages.template_with_worker_outside_h(template_path, sheet.title, exc.worker_column)
            ) from exc


def ensure_period_files_absent(files: PeriodFiles) -> None:
    """Nienadpisywanie: żaden z dwóch plików okresu nie istnieje jeszcze w Folderze okresu."""

    folder = files.folder
    try:
        for target in (folder.internal_settlement, folder.collective_file):
            if target.exists() or target.is_symlink():
                raise StopError(messages.period_file_exists(folder.directory, target.name))
    except OSError as exc:
        raise StopError(messages.folder_inaccessible(folder.directory)) from exc


def plan_period_files(files: PeriodFiles, order_count: int, successful_count: int) -> list[Message]:
    """Planowanie: zlecenia zmieszczą się we wzorcach; zwraca ostrzeżenia Pliku zbiorczego.

    Scalone komórki w wierszach, do których trafią zlecenia, są zatrzymaniem.
    Wzorca pliku zbiorczego nie wydłużamy, więc za mało wierszy z zerami to ostrzeżenie.
    """

    with _template(files.internal_template, Layout.INTERNAL) as (sheet, positions):
        _ensure_rows_writable(files.internal_template, sheet, positions, order_count)
    with _template(files.collective_template, Layout.COLLECTIVE) as (sheet, positions):
        _ensure_rows_writable(files.collective_template, sheet, positions, successful_count)
        zero_row_count = sheet.zero_row_count()
        first_row_without_zeros = sheet.data_row(zero_row_count)
    if successful_count <= zero_row_count:
        return []
    return [
        messages.too_few_zero_rows(
            files.folder.collective_file.name,
            successful_count,
            zero_row_count,
            first_row_without_zeros,
        )
    ]


def write_period_files(
    files: PeriodFiles,
    orders: Sequence[PeriodOrder],
    successful_orders: Sequence[PeriodOrder],
) -> None:
    """Zapisywanie: przygotowuje oba pliki w katalogu tymczasowym i publikuje je razem.

    Katalog tymczasowy leży w folderze okresów, obok Folderu okresu. Błąd nie
    zostawia żadnego z plików ani nowo założonego Folderu okresu, chyba że
    zatrzymanie wskazuje plik, którego nie udało się usunąć. Katalogu
    tymczasowego, którego nie da się usunąć (np. trzyma go OneDrive), nie
    zgłaszamy: nie jest plikiem okresu, a po publikacji oba pliki już są.
    """

    folder = files.folder
    try:
        with tempfile.TemporaryDirectory(
            prefix=f".{folder.period.token}.staging-", dir=folder.periods_directory, ignore_cleanup_errors=True
        ) as staging:
            staged_directory = Path(staging) / folder.directory.name
            staged_directory.mkdir()
            internal_name, collective_name = files.filenames
            _write_period_file(files.internal_template, Layout.INTERNAL, staged_directory / internal_name, orders)
            _write_period_file(
                files.collective_template,
                Layout.COLLECTIVE,
                staged_directory / collective_name,
                successful_orders,
                recalculate_on_open=True,
            )
            _publish(staged_directory, files)
    except (OSError, workbook_files.WorkbookSaveError) as exc:
        raise StopError(messages.write_failed(folder.directory)) from exc


@contextmanager
def _template(
    template_path: Path, layout: Layout, target: Path | None = None, *, recalculate_on_open: bool = False
) -> Iterator[tuple[TemplateSheet, list[int]]]:
    """Wzorzec z kolumnami ``COLUMNS``; problem z otwarciem wzorca to zatrzymanie.

    Z ``target`` to plik z Wzorca zapisany pod ``target`` przy wyjściu z bloku.
    Zły układ tłumaczy ``check_collective_template``, bo zna arkusz.
    """

    try:
        with (
            workbook_files.open_template(template_path, layout)
            if target is None
            else workbook_files.file_from_template(template_path, target, layout, recalculate=recalculate_on_open)
        ) as sheet:
            yield sheet, _target_columns(template_path, sheet.title, sheet.header_row, sheet.header())
    except WorkbookError as error:
        if error.problem is Problem.MISSING:
            raise StopError(messages.template_missing(template_path)) from error
        if error.problem is Problem.OPEN_IN_EXCEL:
            raise StopError(messages.template_open_in_excel(template_path)) from error
        raise StopError(messages.template_unreadable(template_path)) from error


def _target_columns(template_path: Path, sheet_title: str, header_row: int, header: Sequence[object]) -> list[int]:
    """Kolumny wzorca dla ``COLUMNS``, rozpoznane wyłącznie po nagłówku docelowym."""

    columns = header_columns(header)
    positions: list[int] = []
    for column in COLUMNS:
        position = columns.get(normalize_text(column.target_header))
        if position is None:
            raise StopError(
                messages.template_without_header(template_path, sheet_title, header_row, column.target_header)
            )
        positions.append(position)
    return positions


def _ensure_rows_writable(
    template_path: Path, sheet: TemplateSheet, positions: Sequence[int], row_count: int
) -> None:
    """Zatrzymanie, gdy komórki, do których trafią zlecenia, są scalone we wzorcu."""

    if row_count == 0:
        return
    first_row, last_row = sheet.data_row(0), sheet.data_row(row_count - 1)
    for merged in sheet.worksheet.merged_cells.ranges:
        overlaps_rows = merged.min_row <= last_row and merged.max_row >= first_row
        if overlaps_rows and any(merged.min_col <= position <= merged.max_col for position in positions):
            raise StopError(messages.template_with_merged_cells(template_path, sheet.title, merged.coord))


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
    layout: Layout,
    target: Path,
    orders: Sequence[PeriodOrder],
    *,
    recalculate_on_open: bool = False,
) -> None:
    """Plik z Wzorca ze zleceniami od pierwszego wiersza danych; odwołania zewnętrzne zostają 1:1.

    Zapisana komórka ma Hiperłącze komórki Rejestru albo żadne: hiperłącze komórki Wzorca nie zostaje.
    """

    with _template(template_path, layout, target, recalculate_on_open=recalculate_on_open) as (sheet, positions):
        _ensure_rows_writable(template_path, sheet, positions, len(orders))
        for index, order in enumerate(orders):
            for position, register_cell in zip(positions, order.row.cells):
                cell = sheet.worksheet.cell(sheet.data_row(index), position)
                if not isinstance(cell, Cell):  # scalona komórka; wykluczona przez _ensure_rows_writable
                    raise StopError(messages.template_with_merged_cells(template_path, sheet.title, cell.coordinate))
                _apply_template_style(sheet.worksheet, cell)
                link = register_cell.hyperlink
                # Przed wartością: openpyxl wpisuje adres jako wartość pustej komórki.
                cell.hyperlink = None if link is None else link.address
                cell.value = register_cell.value  # type: ignore[assignment]
                _apply_register_format(cell, register_cell.format)
        _set_autofilter(sheet.worksheet, sheet.header_row, len(orders))


def _publish(staged_directory: Path, files: PeriodFiles) -> None:
    """Przenosi oba pliki do Folderu okresu razem; przy błędzie nie zostawia żadnego.

    Jeśli już przeniesionego pliku nie da się usunąć, zatrzymanie wskazuje ten plik.
    """

    ensure_period_files_absent(files)
    period_directory = files.folder.directory
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
            try:
                target.unlink(missing_ok=True)
            except OSError as exc:
                raise StopError(messages.write_failed_with_file_left(period_directory, target.name)) from exc
        raise

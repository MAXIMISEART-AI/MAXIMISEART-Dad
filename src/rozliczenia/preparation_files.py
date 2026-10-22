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
from dataclasses import dataclass
from pathlib import Path
from typing import cast

from openpyxl.cell.cell import Cell
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.filters import AutoFilter
from openpyxl.worksheet.worksheet import Worksheet

from . import workbook_files
from .highlights import PLAIN, Highlights
from .hyperlinks import Hyperlink
from . import preparation_messages as messages
from .message import Message, StopError
from .period_folder import PeriodFolder
from .preparation_plan import PeriodOrder
from .preparation_register import COLUMNS, RegisterCell, header_columns, is_blank
from .row_look import GENERAL, wraps
from .workbook_files import Layout, Problem, TemplateOutline, TemplateSheet, WorkbookError
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

    _outline(template_path, Layout.INTERNAL)


def check_collective_template(template_path: Path) -> None:
    """Wzorzec pliku zbiorczego jak ``check_internal_template`` i z WYKONAWCA w H17."""

    outline, _ = _outline(template_path, Layout.COLLECTIVE)
    try:
        outline.check_worker_header()
    except WorkbookError as exc:
        if exc.worker_column is None:
            raise StopError(
                messages.template_without_header(template_path, outline.title, outline.header_row, "WYKONAWCA")
            ) from exc
        raise StopError(messages.template_with_worker_outside_h(template_path, outline.title, exc.worker_column)) from exc


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

    internal, positions = _outline(files.internal_template, Layout.INTERNAL)
    _ensure_rows_writable(files.internal_template, internal, _written_columns(Layout.INTERNAL, positions), order_count)
    collective, positions = _outline(files.collective_template, Layout.COLLECTIVE)
    _ensure_rows_writable(
        files.collective_template, collective, _written_columns(Layout.COLLECTIVE, positions), successful_count
    )
    if successful_count <= collective.zero_row_count:
        return []
    return [
        messages.too_few_zero_rows(
            files.folder.collective_file.name,
            successful_count,
            collective.zero_row_count,
            collective.data_row(collective.zero_row_count),
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


def _outline(template_path: Path, layout: Layout) -> tuple[TemplateOutline, list[int]]:
    """Wzorzec do Sprawdzania i Planowania z kolumnami ``COLUMNS``; problem z otwarciem wzorca to zatrzymanie.

    Zły układ tłumaczy ``check_collective_template``, bo zna arkusz.
    """

    try:
        outline = workbook_files.read_template_outline(template_path, layout)
    except WorkbookError as error:
        raise _template_stop(template_path, error) from error
    return outline, _target_columns(template_path, outline.title, outline.header_row, outline.header)


@contextmanager
def _file_from_template(
    template_path: Path, layout: Layout, target: Path, *, recalculate_on_open: bool
) -> Iterator[tuple[TemplateSheet, list[int]]]:
    """Plik z Wzorca z kolumnami ``COLUMNS``, zapisany pod ``target`` przy wyjściu z bloku."""

    try:
        with workbook_files.file_from_template(template_path, target, layout, recalculate=recalculate_on_open) as sheet:
            yield sheet, _target_columns(template_path, sheet.title, sheet.header_row, sheet.header())
    except WorkbookError as error:
        raise _template_stop(template_path, error) from error


def _template_stop(template_path: Path, error: WorkbookError) -> StopError:
    if error.problem is Problem.MISSING:
        return StopError(messages.template_missing(template_path))
    if error.problem is Problem.OPEN_IN_EXCEL:
        return StopError(messages.template_open_in_excel(template_path))
    return StopError(messages.template_unreadable(template_path))


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


def _written_columns(layout: Layout, positions: Sequence[int]) -> range:
    """Kolumny zapisanego Wiersza danych od A: kolumny wyglądu, a gdy nagłówek Wzorca leży dalej, także do niego."""

    return range(1, max(layout.look_columns, *positions) + 1)


def _ensure_rows_writable(template_path: Path, sheet: TemplateOutline | TemplateSheet, columns: range, row_count: int) -> None:
    """Zatrzymanie, gdy komórki, do których trafią zlecenia albo Wygląd Wiersza danych, są scalone we wzorcu."""

    if row_count == 0:
        return
    first_row, last_row = sheet.data_row(0), sheet.data_row(row_count - 1)
    for merged in sheet.merged_ranges:
        overlaps_rows = merged.min_row <= last_row and merged.max_row >= first_row
        if overlaps_rows and merged.min_col <= columns[-1] and merged.max_col >= columns[0]:
            raise StopError(messages.template_with_merged_cells(template_path, sheet.title, merged.coord))


def _highlights(cell: RegisterCell) -> Highlights:
    """Wyróżnienia komórki Rejestru w pliku okresu."""

    cell_format = cell.format
    return Highlights(cell_format.fill, cell_format.color, cell_format.bold, cell_format.italic)


def _set_autofilter(sheet: Worksheet, header_row: int, order_count: int) -> None:
    """Autofiltr na nagłówek i faktyczne wiersze danych; zakres zapisany we wzorcu jest ignorowany."""

    header_columns_present = [
        column for column, cell in enumerate(sheet[header_row], start=1) if not is_blank(cell.value)
    ]
    first_column = get_column_letter(min(header_columns_present))
    last_column = get_column_letter(max(header_columns_present))
    sheet.auto_filter = AutoFilter(ref=f"{first_column}{header_row}:{last_column}{header_row + order_count}")


def _written_as_copy(template_path: Path, target: Path, orders: Sequence[PeriodOrder]) -> bool:
    """Plik zbiorczy kopią Wzorca (ADR 0008), jak Rozliczenia pracowników; ``False``: kształt dla openpyxl.

    Wynik ma te same wartości, Wygląd Wiersza danych, Hiperłącza i autofiltr co zapis przez openpyxl,
    a formuły, ``calcChain`` i reszta Wzorca zostają bajt w bajt.
    """

    try:
        template = workbook_files.CollectiveFileTemplate.read(template_path)
    except WorkbookError as error:
        raise _template_stop(template_path, error) from error
    if template is None:
        return False
    columns = header_columns(template.header)
    positions = [columns.get(normalize_text(column.target_header)) for column in COLUMNS]
    if sorted(position or 0 for position in positions) != list(range(1, len(COLUMNS) + 1)):
        return False  # zatrzymanie z nazwą arkusza zgłasza droga przez openpyxl
    return template.create(target, [_collective_row(order, cast(list[int], positions)) for order in orders])


def _collective_row(order: PeriodOrder, positions: Sequence[int]) -> workbook_files.CollectiveFileRow:
    values: list[object] = [None] * len(positions)
    highlights = [PLAIN] * len(positions)
    hyperlinks: dict[int, Hyperlink] = {}
    number_formats = [GENERAL] * len(positions)
    for position, cell in zip(positions, order.row.cells, strict=True):
        values[position - 1] = cell.value
        highlights[position - 1] = _highlights(cell)
        number_formats[position - 1] = cell.format.number_format
        if cell.hyperlink is not None:
            hyperlinks[position] = cell.hyperlink
    return workbook_files.CollectiveFileRow(tuple(values), tuple(highlights), hyperlinks, tuple(number_formats))


def _write_period_file(
    template_path: Path,
    layout: Layout,
    target: Path,
    orders: Sequence[PeriodOrder],
    *,
    recalculate_on_open: bool = False,
) -> None:
    """Plik z Wzorca ze zleceniami od pierwszego wiersza danych; odwołania zewnętrzne zostają 1:1.

    Każda komórka kolumn wyglądu dostaje Wygląd Wiersza danych; komórka bez wartości z Rejestru (np. ``zwrot``)
    sam wygląd, a jej treść zostaje z Wzorca. Zapisana komórka ma Hiperłącze komórki Rejestru albo żadne:
    hiperłącze komórki Wzorca nie zostaje.
    """

    if layout is Layout.COLLECTIVE and _written_as_copy(template_path, target, orders):
        return

    with _file_from_template(template_path, layout, target, recalculate_on_open=recalculate_on_open) as (sheet, positions):
        columns = _written_columns(layout, positions)
        _ensure_rows_writable(template_path, sheet, columns, len(orders))
        look = sheet.row_look(columns[-1])
        for index, order in enumerate(orders):
            number = sheet.data_row(index)
            sheet.fit_height(number)
            sources = dict(zip(positions, order.row.cells))
            for position in columns:
                cell = sheet.worksheet.cell(number, position)
                if not isinstance(cell, Cell):  # scalona komórka; wykluczona przez _ensure_rows_writable
                    raise StopError(messages.template_with_merged_cells(template_path, sheet.title, cell.coordinate))
                if position not in sources:
                    look.cell(position, PLAIN, GENERAL, wrapped=False).apply(cell)
                    continue
                register_cell = sources[position]
                link = register_cell.hyperlink
                # Przed wartością: openpyxl wpisuje adres jako wartość pustej komórki.
                cell.hyperlink = None if link is None else link.address
                cell.value = register_cell.value  # type: ignore[assignment]
                highlights = _highlights(register_cell)
                wrapped = wraps(register_cell.value)
                look.cell(position, highlights, register_cell.format.number_format, wrapped=wrapped).apply(cell)
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

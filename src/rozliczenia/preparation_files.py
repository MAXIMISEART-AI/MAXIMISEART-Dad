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
from dataclasses import dataclass, replace
from pathlib import Path

from openpyxl.utils import column_index_from_string

from . import preparation_messages as messages
from .message import Message, StopError
from .period_folder import PeriodFolder
from .preparation_plan import CollectiveRow, PeriodOrder
from .preparation_register import COLUMNS
from .quantity_rules import FromDescription, WithoutRule
from .workbook_files import (
    DataRow,
    Layout,
    MergedCells,
    MissingHeader,
    Problem,
    TemplateFile,
    WorkbookError,
    WorkbookSaveError,
)

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

    with _template_stops(template_path):
        _template(template_path, Layout.INTERNAL_SETTLEMENT).check()


def check_collective_template(template_path: Path) -> None:
    """Wzorzec pliku zbiorczego jak ``check_internal_template`` i z WYKONAWCA w H17."""

    with _template_stops(template_path):
        _template(template_path, Layout.COLLECTIVE_FILE).check()


def ensure_period_files_absent(files: PeriodFiles) -> None:
    """Nienadpisywanie: żaden z dwóch plików okresu nie istnieje jeszcze w Folderze okresu."""

    folder = files.folder
    try:
        for target in (folder.internal_settlement, folder.collective_file):
            if target.exists() or target.is_symlink():
                raise StopError(messages.period_file_exists(folder.directory, target.name))
    except OSError as exc:
        raise StopError(messages.folder_inaccessible(folder.directory)) from exc


def plan_period_files(files: PeriodFiles, order_count: int, collective_rows: Sequence[CollectiveRow]) -> list[Message]:
    """Planowanie: zlecenia zmieszczą się we wzorcach; zwraca ostrzeżenia Pliku zbiorczego.

    Scalone komórki w wierszach, do których trafią zlecenia, są zatrzymaniem.
    Wzorca pliku zbiorczego nie wydłużamy, więc za mało wierszy z zerami to ostrzeżenie. Ostrzeżenia ilości
    wskazują wiersze Pliku zbiorczego, w których tata uzupełnia Ilości usług, i zawsze przypominają o kolumnach
    z opisu technika.
    """

    collective_filename = files.folder.collective_file.name
    with _template_stops(files.internal_template):
        _template(files.internal_template, Layout.INTERNAL_SETTLEMENT).plan(order_count)
    with _template_stops(files.collective_template):
        collective = _template(files.collective_template, Layout.COLLECTIVE_FILE).plan(len(collective_rows))
    warnings: list[Message] = []
    if len(collective_rows) > collective.zero_row_count:
        warnings.append(
            messages.too_few_zero_rows(
                collective_filename,
                len(collective_rows),
                collective.zero_row_count,
                collective.first_row_without_zeros,
            )
        )
    numbered = list(zip(collective.data_rows, collective_rows, strict=True))
    without_rule = [number for number, row in numbered if isinstance(row.rule_result, WithoutRule)]
    from_description = [number for number, row in numbered if isinstance(row.rule_result, FromDescription)]
    if without_rule:
        warnings.append(messages.unknown_devices(collective_filename, without_rule))
    if from_description:
        warnings.append(messages.rows_from_description(collective_filename, from_description))
    warnings.append(messages.columns_from_description(collective_filename))
    return warnings


def write_period_files(
    files: PeriodFiles,
    orders: Sequence[PeriodOrder],
    collective_rows: Sequence[CollectiveRow],
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
            _write_period_file(
                files.internal_template,
                Layout.INTERNAL_SETTLEMENT,
                staged_directory / internal_name,
                [order.row for order in orders],
            )
            _write_period_file(
                files.collective_template,
                Layout.COLLECTIVE_FILE,
                staged_directory / collective_name,
                [_with_quantities(row) for row in collective_rows],
            )
            _publish(staged_directory, files)
    except (OSError, WorkbookSaveError) as exc:
        raise StopError(messages.write_failed(folder.directory)) from exc


def _template(template_path: Path, layout: Layout) -> TemplateFile:
    """Wzorzec pliku okresu z kolumnami ``COLUMNS`` pod ich nagłówkami docelowymi."""

    return TemplateFile(template_path, layout, [column.target_header for column in COLUMNS])


@contextmanager
def _template_stops(template_path: Path) -> Iterator[None]:
    """Wzorzec, którego nie da się użyć, to zatrzymanie z Komunikatem Przygotowania."""

    try:
        yield
    except WorkbookError as error:
        raise _template_stop(template_path, error) from error


def _template_stop(template_path: Path, error: WorkbookError) -> StopError:
    if error.problem is Problem.MISSING:
        return StopError(messages.template_missing(template_path))
    if error.problem is Problem.OPEN_IN_EXCEL:
        return StopError(messages.template_open_in_excel(template_path))
    fault = error.fault
    if isinstance(fault, MissingHeader) and fault.found_in is not None:
        return StopError(messages.template_with_worker_outside_h(template_path, fault.sheet, fault.found_in))
    if isinstance(fault, MissingHeader):
        return StopError(messages.template_without_header(template_path, fault.sheet, fault.row, fault.header))
    if isinstance(fault, MergedCells):
        return StopError(messages.template_with_merged_cells(template_path, fault.sheet, fault.cells))
    return StopError(messages.template_unreadable(template_path))


def _write_period_file(template_path: Path, layout: Layout, target: Path, rows: Sequence[DataRow]) -> None:
    """Plik z Wzorca z Wierszami danych od pierwszego Wiersza danych (ADR 0008)."""

    with _template_stops(template_path):
        _template(template_path, layout).create(target, rows)


def _with_quantities(row: CollectiveRow) -> DataRow:
    """Wiersz Rejestru z Ilościami usług zlecenia z Planowania."""

    quantities = row.rule_result.quantities
    return replace(
        row.order.row, quantities={column_index_from_string(column): value for column, value in quantities.items()}
    )


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

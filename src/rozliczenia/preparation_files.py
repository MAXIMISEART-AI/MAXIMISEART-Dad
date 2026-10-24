"""Wzorce i pliki okresu w Przygotowaniu pliku zbiorczego.

Moduł podaje oba wzorce z kolumnami Rejestru zleceń (``period_template``, sprawdzane w ``input_checks``), ocenia,
czy zlecenia zmieszczą się we wzorcach, i podaje fakty o wierszach Pliku zbiorczego (Planowanie), a potem zapisuje
Rozliczenie wewnętrzne oraz Plik zbiorczy razem do Folderu okresu (Zapisywanie). Planowanie i Zapisywanie
zatrzymują się ``StopError``. Moduł wewnętrzny Przygotowania pliku zbiorczego; operacją publiczną pozostaje
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
from .message import StopError
from .period_folder import PeriodFolder
from .preparation_plan import CollectiveRow, PeriodOrder
from .preparation_register import COLUMNS
from .quantity_rules import DESCRIPTION_COLUMNS, FromDescription, WithoutRule
from .template_file import Layout, TemplateFile
from .workbook_files import DataRow, WorkbookError
from .workbook_save import WorkbookSaveError

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


def ensure_period_files_absent(files: PeriodFiles) -> None:
    """Nienadpisywanie: żaden z dwóch plików okresu nie istnieje jeszcze w Folderze okresu."""

    folder = files.folder
    try:
        for target in (folder.internal_settlement, folder.collective_file):
            if target.exists() or target.is_symlink():
                raise StopError(messages.period_file_exists(folder.directory, target.name))
    except OSError as exc:
        raise StopError(messages.folder_inaccessible(folder.directory)) from exc


@dataclass(frozen=True)
class CollectiveFilePlan:
    """Fakty Planowania o Pliku zbiorczym, z numerami jego wierszy (nie wierszy Rejestru zleceń).

    ``rows_without_rule`` mają składnik ``URZĄDZENIA`` nieznany Regułom ilości, ``rows_from_description`` rozlicza
    się z opisu technika, a kolumn ``description_columns`` Reguły ilości nie wypełniają w żadnym wierszu.
    """

    successful_count: int
    zero_row_count: int
    first_row_without_zeros: int
    rows_without_rule: tuple[int, ...]
    rows_from_description: tuple[int, ...]
    description_columns: tuple[str, ...]

    @property
    def too_few_zero_rows(self) -> bool:
        """Wzorca pliku zbiorczego nie wydłużamy, więc dolne Zlecenia skuteczne trafiają do wierszy bez zer."""

        return self.successful_count > self.zero_row_count

    @property
    def quantities_to_complete(self) -> bool:
        """Tata uzupełnia Ilości usług w Pliku zbiorczym przed Przebiegiem rozliczeń."""

        return bool(self.rows_without_rule or self.rows_from_description or self.description_columns)


def plan_period_files(
    files: PeriodFiles, order_count: int, collective_rows: Sequence[CollectiveRow]
) -> CollectiveFilePlan:
    """Planowanie: zlecenia zmieszczą się we wzorcach; scalone komórki w ich wierszach są zatrzymaniem."""

    with _template_stops():
        period_template(files.internal_template, Layout.INTERNAL_SETTLEMENT).plan(order_count)
        collective = period_template(files.collective_template, Layout.COLLECTIVE_FILE).plan(len(collective_rows))
    numbered = list(zip(collective.data_rows, collective_rows, strict=True))
    return CollectiveFilePlan(
        successful_count=len(collective_rows),
        zero_row_count=collective.zero_row_count,
        first_row_without_zeros=collective.first_row_without_zeros,
        rows_without_rule=tuple(number for number, row in numbered if isinstance(row.rule_result, WithoutRule)),
        rows_from_description=tuple(
            number for number, row in numbered if isinstance(row.rule_result, FromDescription)
        ),
        description_columns=DESCRIPTION_COLUMNS,
    )


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


def period_template(template_path: Path, layout: Layout) -> TemplateFile:
    """Wzorzec pliku okresu z kolumnami ``COLUMNS`` pod ich nagłówkami docelowymi."""

    return TemplateFile(template_path, layout, [column.target_header for column in COLUMNS])


@contextmanager
def _template_stops() -> Iterator[None]:
    """Wzorzec, którego nie da się użyć, to zatrzymanie z Komunikatem Przygotowania."""

    try:
        yield
    except WorkbookError as error:
        raise StopError(messages.template_unusable(error)) from error


def _write_period_file(template_path: Path, layout: Layout, target: Path, rows: Sequence[DataRow]) -> None:
    """Plik z Wzorca z Wierszami danych od pierwszego Wiersza danych (ADR 0008)."""

    with _template_stops():
        period_template(template_path, layout).create(target, rows)


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

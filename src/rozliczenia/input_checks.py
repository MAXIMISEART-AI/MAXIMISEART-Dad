"""Sprawdzanie plików taty w obu procesach, to samo w Diagnozie i Konfiguracji Centrum rozliczeń.

Rejestr zleceń i Wzorce czytają czytniki (``Readers``), które proces i Centrum dostają jako zależność. Błąd
czytnika (``WorkbookError``, ``PeriodFolderError``, ``WorkerConfigError``) moduł sam tłumaczy na Komunikat
procesu, który z tego pliku korzysta: proces zatrzymuje się nim (``StopError``), a Diagnoza i Konfiguracja
pokazują go jako przyczynę albo problem pliku.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Final

from . import preparation_files, preparation_register, settlement_files, settlement_messages, workbook_files
from . import preparation_messages as messages
from .message import Message, StopError
from .period_folder import (
    PeriodFolder,
    PeriodFolderError,
    PeriodFolderInaccessible,
    PeriodFolderLookupError,
    locate_period_folder,
)
from .preparation_files import PeriodFiles
from .preparation_register import RegisterSheet
from .settlement_period import SettlementPeriod, parse_period_token
from .template_file import TemplateFile
from .workbook_files import Problem, WorkbookError
from .worker_config import WorkerConfigError, load_worker_mapping


@dataclass(frozen=True)
class Readers:
    """Czytniki Rejestru zleceń i Wzorców; błąd pliku zgłaszają jako ``WorkbookError``.

    Produkcyjne czytają pliki (``FILE_READERS``), a test i weryfikacja podstawiają czytnik, który się psuje.
    Ten sam obiekt dostają Uruchomienie procesu i Diagnoza, więc usterka czytnika trafia do obu.
    """

    register: Callable[[Path, SettlementPeriod | None], list[RegisterSheet]]
    """Arkusze ze zleceniami Rejestru, z ``period`` tylko wiersze, których data może leżeć w okresie.

    Rejestr, którego nie ma albo który jest otwarty w Excelu, to też ``WorkbookError``.
    """
    template: Callable[[TemplateFile], None]
    """Sprawdzanie Wzorca: istnieje, nie jest otwarty, daje się odczytać i ma układ swojego pliku."""


FILE_READERS: Final = Readers(register=preparation_register.read_register, template=TemplateFile.check)


@dataclass(frozen=True)
class TemplateProblem:
    """Wzorzec nie przechodzi Sprawdzania: rodzaj problemu i Komunikat procesu, który z niego tworzy pliki."""

    problem: Problem
    message: Message


@dataclass(frozen=True)
class ProcessTemplate:
    """Wzorzec, z którego proces tworzy pliki, z Komunikatem tego procesu o Wzorcu, którego nie da się użyć."""

    file: TemplateFile
    _explain: Callable[[WorkbookError], Message]

    @classmethod
    def internal(cls, path: Path) -> ProcessTemplate:
        return cls(preparation_files.internal_template(path), messages.template_unusable)

    @classmethod
    def collective(cls, path: Path) -> ProcessTemplate:
        return cls(preparation_files.collective_template(path), messages.template_unusable)

    @classmethod
    def worker(cls, path: Path) -> ProcessTemplate:
        return cls(TemplateFile.worker_settlement(path), settlement_messages.worker_template_unusable)

    def problem(self, readers: Readers) -> TemplateProblem | None:
        """``None``, gdy Wzorzec przechodzi Sprawdzanie."""

        try:
            readers.template(self.file)
        except WorkbookError as error:
            return TemplateProblem(error.problem, self._explain(error))
        return None

    def checked(self, readers: Readers) -> TemplateFile:
        """Wzorzec po Sprawdzaniu, z którego Zapisywanie tworzy pliki; zatrzymanie, gdy go nie przechodzi."""

        found = self.problem(readers)
        if found is not None:
            raise StopError(found.message)
        return self.file


def check_preparation(
    register: Path,
    periods_directory: Path,
    period: str,
    config: Path,
    *,
    internal_template: Path,
    collective_template: Path,
    readers: Readers,
) -> tuple[PeriodFiles, dict[str, str]]:
    """Sprawdzanie Przygotowania pliku zbiorczego: pliki okresu i Wykonawcy albo zatrzymanie."""

    settlement_period = _parse_period(period)
    with _stops(messages.register_unusable):
        workbook_files.ensure_available(register)
    ProcessTemplate.internal(internal_template).checked(readers)
    ProcessTemplate.collective(collective_template).checked(readers)
    if not periods_directory.is_dir():
        raise StopError(messages.periods_directory_missing(periods_directory))
    files = PeriodFiles(
        internal_template, collective_template, _locate_period_folder(periods_directory, settlement_period)
    )
    preparation_files.ensure_period_files_absent(files)
    return files, _worker_mapping(config, messages.worker_config_problem)


def read_register(register: Path, period: SettlementPeriod | None, readers: Readers) -> list[RegisterSheet]:
    """Arkusze ze zleceniami Rejestru zleceń albo zatrzymanie, gdy Rejestru nie da się odczytać albo nie ma nagłówków."""

    with _stops(messages.register_unusable):
        return readers.register(register, period)


def register_problem(register: Path, readers: Readers) -> Message | None:
    """Komunikat, którym Przygotowanie zatrzymałoby się na Rejestrze zleceń: otwarty w Excelu, nieczytelny, bez nagłówków."""

    try:
        read_register(register, None, readers)
    except StopError as stop:
        return stop.message
    return None


def check_settlement(
    source: Path, config: Path, worker_template: Path, readers: Readers
) -> tuple[PeriodFolder, dict[str, str], TemplateFile]:
    """Sprawdzanie Przebiegu rozliczeń: Folder okresu Pliku zbiorczego, Wykonawcy i sprawdzony Wzorzec albo zatrzymanie."""

    with _stops(settlement_messages.collective_file_unusable):
        workbook_files.ensure_available(source)
    try:
        folder = PeriodFolder.from_collective_file(source)
    except PeriodFolderError as error:
        raise StopError(settlement_messages.collective_file_invalid(source, error.message)) from error
    settlement_files.ensure_worker_settlements_absent(folder.worker_settlements)
    mapping = _worker_mapping(config, settlement_messages.worker_config_problem)
    return folder, mapping, ProcessTemplate.worker(worker_template).checked(readers)


def workers(config: Path) -> dict[str, str] | Message:
    """Wykonawcy z konfiguracji wykonawców albo Komunikat, którym zatrzymałby się na niej Przebieg rozliczeń."""

    try:
        return _worker_mapping(config, settlement_messages.worker_config_problem)
    except StopError as stop:
        return stop.message


@contextmanager
def _stops(explain: Callable[[WorkbookError], Message]) -> Iterator[None]:
    try:
        yield
    except WorkbookError as error:
        raise StopError(explain(error)) from error


def _worker_mapping(config: Path, explain: Callable[[Path, WorkerConfigError], Message]) -> dict[str, str]:
    try:
        return load_worker_mapping(config)
    except WorkerConfigError as error:
        raise StopError(explain(config, error)) from error


def _parse_period(token: str) -> SettlementPeriod:
    try:
        return parse_period_token(token)
    except ValueError as error:
        raise StopError(messages.invalid_period_token(token)) from error


def _locate_period_folder(periods_directory: Path, period: SettlementPeriod) -> PeriodFolder:
    try:
        return locate_period_folder(periods_directory, period)
    except PeriodFolderLookupError as error:
        raise StopError(messages.period_folder_lookup_problem(error)) from error
    except PeriodFolderInaccessible as error:
        raise StopError(messages.folder_inaccessible(error.folder)) from error

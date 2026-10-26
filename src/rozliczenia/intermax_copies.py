"""Kopie INTERMAX: stan Rejestru zleceń sprzed Uporządkowania INTERMAX albo sprzed przywrócenia Kopii, poza OneDrive.

Kopia ma nazwę z chwili zegara procesu, ``INTERMAX przed uporządkowaniem RRRR-MM-DD GG-MM-SS.xlsx`` albo
``INTERMAX przed przywróceniem RRRR-MM-DD GG-MM-SS.xlsx``, i bajty INTERMAX sprzed zapisu. Po udanym zapisie zostaje
``KEPT`` najnowszych Kopii obu nazw według chwili z nazwy; inne pliki w folderze zostają. Folder leży na dysku
narzędzia, więc OneDrive nie synchronizuje codziennie dużego pliku.

``restore`` przywraca Kopię, którą wymienia ``listed``: INTERMAX dostaje jej bajty po Kopii stanu bieżącego, tą samą
atomową podmianą z ponowną próbą co zapis Uporządkowania (``intermax_file.restore``).
"""

from __future__ import annotations

import os
import re
import zipfile
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime
from io import BytesIO
from pathlib import Path
from typing import Final, Literal

from . import TOOL_ROOT, intermax_file, workbook_files
from . import intermax_messages as messages
from .intermax_file import HeldByOneDrive, Waiting, WriteMismatch
from .message import Message, StopError
from .workbook_files import WorkbookError
from .workbook_save import WorkbookSaveError

KEPT: Final = 10
Before = Literal["ordering", "restore"]
_PREFIXES: Final[Mapping[Before, str]] = {
    "ordering": "INTERMAX przed uporządkowaniem ",
    "restore": "INTERMAX przed przywróceniem ",
}
_NAME: Final = re.compile(r"INTERMAX przed (uporządkowaniem|przywróceniem) (\d{4}-\d{2}-\d{2} \d{2}-\d{2}-\d{2})\.xlsx")
_MOMENT: Final = "%Y-%m-%d %H-%M-%S"


@dataclass(frozen=True)
class Copy:
    """Kopia INTERMAX w folderze Kopii: plik, chwila z nazwy w czasie komputera i to, przed czym powstała."""

    path: Path
    moment: datetime
    before: Before


def default_directory() -> Path:
    """Folder Kopii INTERMAX w katalogu narzędzia na dysku lokalnym."""

    return TOOL_ROOT / "Kopie INTERMAX"


def _copy(path: Path) -> Copy | None:
    found = _NAME.fullmatch(path.name)
    if found is None:
        return None
    try:
        moment = datetime.strptime(found[2], _MOMENT).astimezone()
    except ValueError:  # nazwa z nieistniejącą datą albo godziną nie pochodzi od narzędzia
        return None
    return Copy(path, moment, "ordering" if found[1] == "uporządkowaniem" else "restore")


def listed(directory: Path) -> list[Copy]:
    """Kopie INTERMAX w ``directory`` od najnowszej; brak folderu to brak Kopii, inny błąd odczytu to ``OSError``."""

    try:
        paths = list(directory.iterdir())
    except FileNotFoundError:
        return []
    copies = [copy for copy in map(_copy, paths) if copy is not None]
    return sorted(copies, key=lambda copy: (copy.moment, copy.path.name), reverse=True)


def make_copy(content: bytes, directory: Path, moment: datetime, before: Before = "ordering") -> Path:
    """Kopia INTERMAX z bajtów ``content`` z nazwą z ``moment``; ``OSError``, gdy jej nie ma w całości.

    Kopia o tej samej nazwie już istnieje: ``FileExistsError``, istniejąca zostaje.
    """

    directory.mkdir(exist_ok=True)
    path = directory / f"{_PREFIXES[before]}{moment:{_MOMENT}}.xlsx"
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_BINARY", 0))
    try:
        with os.fdopen(descriptor, "wb") as file:
            file.write(content)
    except OSError:
        path.unlink()
        raise
    return path


def keep_newest(directory: Path) -> None:
    """Usuwa Kopie INTERMAX obu nazw starsze niż ``KEPT`` najnowszych według chwili z nazwy."""

    for copy in listed(directory)[KEPT:]:
        copy.path.unlink()


@dataclass(frozen=True)
class Restored:
    """Przywrócona Kopia, Kopia stanu sprzed przywrócenia i ostrzeżenia (starsze Kopie zostały)."""

    restored: Copy
    previous: Copy
    warnings: list[Message]


def _parts(content: bytes) -> list[str]:
    """Nazwy części archiwum zip ``content``; bajty, które nie są zipem, nie mają żadnej."""

    try:
        with zipfile.ZipFile(BytesIO(content)) as archive:
            return archive.namelist()
    except zipfile.BadZipFile:
        return []


def restore(
    name: str, register: Path, directory: Path, *, now: Callable[[], datetime], waiting: Waiting
) -> Restored:
    """Przywraca do INTERMAX ``register`` Kopię INTERMAX ``name``, którą ``listed`` wymienia w ``directory``.

    Najpierw powstaje Kopia stanu bieżącego z nazwą ``INTERMAX przed przywróceniem`` z ``now()``, potem INTERMAX
    dostaje atomowo bajty wybranej Kopii, a po udanej podmianie zostaje ``KEPT`` najnowszych Kopii. ``StopError``,
    gdy nie można przywrócić bezpiecznie (INTERMAX otwarty w Excelu albo trzymany przez OneDrive, Kopii nie ma albo
    jest uszkodzona, nie powstała Kopia stanu bieżącego albo w tej samej sekundzie przywrócono już inną Kopię);
    INTERMAX i Kopie zostają wtedy takie, jak były. Nieudane
    usunięcie starszych Kopii to ostrzeżenie: INTERMAX jest już przywrócony.
    """

    try:
        chosen = next((copy for copy in listed(directory) if copy.path.name == name), None)
    except OSError as error:
        raise StopError(messages.copies_unreadable(directory)) from error
    if chosen is None:
        raise StopError(messages.copy_missing(directory, name))
    try:
        current = workbook_files.workbook_content(register)
    except WorkbookError as error:
        raise StopError(messages.restore_register_unusable(error)) from error
    try:
        content = workbook_files.workbook_content(chosen.path)
    except WorkbookError as error:
        raise StopError(messages.copy_unusable(error)) from error
    if "xl/workbook.xml" not in _parts(content):  # skoroszyt Excela; treści arkuszy nie sprawdza
        raise StopError(messages.copy_damaged(chosen.path))
    made: list[Path] = []

    def before_replace() -> None:
        moment = now()
        if workbook_files.is_open_in_excel(register):
            raise StopError(messages.restore_register_open(register))
        try:
            made.append(make_copy(current, directory, moment, "restore"))
        except FileExistsError as error:
            raise StopError(messages.restored_moment_ago(directory)) from error
        except OSError as error:
            raise StopError(messages.restore_copy_failed(directory)) from error

    try:
        intermax_file.restore(register, current, content, before_replace=before_replace, waiting=waiting)
    except BaseException as failure:
        for path in made:
            path.unlink()
        match failure:
            case WorkbookSaveError() if workbook_files.is_open_in_excel(register):
                raise StopError(messages.restore_register_open(register)) from failure
            case HeldByOneDrive():
                raise StopError(messages.restore_register_syncing(register)) from failure
            case WorkbookSaveError() | WriteMismatch() | OSError():
                raise StopError(messages.restore_failed(register)) from failure
        raise
    warnings: list[Message] = []
    try:
        keep_newest(directory)
    except OSError:
        warnings.append(messages.old_copies_kept_after_restore(directory))
    previous = _copy(made[0])
    assert previous is not None, "make_copy nazywa Kopię tak, jak ją rozpoznaje _NAME"
    return Restored(chosen, previous, warnings)

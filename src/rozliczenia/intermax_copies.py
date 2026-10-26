"""Kopie INTERMAX: stan Rejestru zleceń sprzed Uporządkowania INTERMAX w folderze narzędzia, poza OneDrive.

Kopia ma nazwę z chwili zegara procesu, ``INTERMAX przed uporządkowaniem RRRR-MM-DD GG-MM-SS.xlsx``, i bajty
INTERMAX, z których proces uporządkował dzień. Po udanym zapisie zostaje ``KEPT`` najnowszych Kopii; inne
pliki w folderze zostają. Folder leży na dysku narzędzia, więc OneDrive nie synchronizuje codziennie dużego pliku.
"""

from __future__ import annotations

import os
import re
from datetime import datetime
from pathlib import Path
from typing import Final

from . import TOOL_ROOT

KEPT: Final = 10
_PREFIX: Final = "INTERMAX przed uporządkowaniem "
_NAME: Final = re.compile(re.escape(_PREFIX) + r"\d{4}-\d{2}-\d{2} \d{2}-\d{2}-\d{2}\.xlsx")


def default_directory() -> Path:
    """Folder Kopii INTERMAX w katalogu narzędzia na dysku lokalnym."""

    return TOOL_ROOT / "Kopie INTERMAX"


def make_copy(content: bytes, directory: Path, moment: datetime) -> Path:
    """Kopia INTERMAX z bajtów ``content`` z nazwą z ``moment``; ``OSError``, gdy jej nie ma w całości.

    Kopia o tej samej nazwie już istnieje: ``FileExistsError``, istniejąca zostaje.
    """

    directory.mkdir(exist_ok=True)
    path = directory / f"{_PREFIX}{moment:%Y-%m-%d %H-%M-%S}.xlsx"
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_BINARY", 0))
    try:
        with os.fdopen(descriptor, "wb") as file:
            file.write(content)
    except OSError:
        path.unlink()
        raise
    return path


def keep_newest(directory: Path) -> None:
    """Usuwa Kopie INTERMAX starsze niż ``KEPT`` najnowszych; nazwa z datą i godziną układa je w czasie."""

    copies = sorted(path for path in directory.iterdir() if _NAME.fullmatch(path.name))
    for path in copies[:-KEPT]:
        path.unlink()

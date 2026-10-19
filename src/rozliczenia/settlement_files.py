"""Zapisywanie Przebiegu rozliczeń: Folder rozliczeń pracowników powstaje cały albo wcale.

Rozliczenia pracowników powstają w folderze tymczasowym obok Pliku zbiorczego,
w Folderze okresu. Gotowy folder tymczasowy staje się Folderem rozliczeń
pracowników jedną zmianą nazwy. Nienadpisywanie jest sprawdzane przed startem
Przebiegu rozliczeń i ponownie tuż przed publikacją. Po nieudanym zapisie nie
zostaje ani folder tymczasowy, ani niepełny Folder rozliczeń pracowników.

Publikacja Przygotowania pliku zbiorczego jest osobna (``preparation_files``).
"""

from __future__ import annotations

import tempfile
from collections.abc import Callable
from dataclasses import replace
from pathlib import Path

from . import settlement_messages
from .domain import WorkerResult
from .message import StopError

__all__ = ["ensure_worker_settlements_absent", "write_worker_settlements"]


def ensure_worker_settlements_absent(target_directory: Path) -> None:
    """Nienadpisywanie: zatrzymuje Przebieg rozliczeń, jeśli Folder rozliczeń pracowników już istnieje."""

    if target_directory.exists() or target_directory.is_symlink():
        raise StopError(settlement_messages.worker_settlements_exist(target_directory))


def write_worker_settlements(
    target_directory: Path, write: Callable[[Path], list[WorkerResult]]
) -> list[WorkerResult]:
    """Publikuje Rozliczenia pracowników zapisane przez ``write`` w folderze tymczasowym.

    ``write`` dostaje folder tymczasowy i zwraca wyniki z plikami w nim. Wynik
    to te same wyniki z plikami w opublikowanym Folderze rozliczeń pracowników.
    Błąd zapisu zatrzymuje Przebieg rozliczeń Komunikatem bez publikacji.
    """

    try:
        with tempfile.TemporaryDirectory(
            prefix=f".{target_directory.name}.staging-",
            dir=target_directory.parent,
        ) as staging_name:
            staging_directory = Path(staging_name)
            results = write(staging_directory)
            ensure_worker_settlements_absent(target_directory)
            try:
                staging_directory.rename(target_directory)
            except OSError as exc:
                raise StopError(settlement_messages.publish_failed(target_directory)) from exc
            return [replace(result, output_file=target_directory / result.output_file.name) for result in results]
    except OSError as exc:
        raise StopError(settlement_messages.write_failed(target_directory)) from exc

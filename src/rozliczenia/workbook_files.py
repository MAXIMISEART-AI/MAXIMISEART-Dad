"""Skoroszyty na dysku: blokada Excela i bezpieczny zapis."""

from __future__ import annotations

import os
import tempfile
import zipfile
import zlib
from enum import Enum
from pathlib import Path
from xml.etree.ElementTree import ParseError

from openpyxl.utils.exceptions import InvalidFileException
from openpyxl.workbook.workbook import Workbook


_EXTERNAL_LINKS_PREFIX = "xl/externalLinks/"
_ExternalLinkParts = dict[str, tuple[zipfile.ZipInfo, bytes]]
_WORKBOOK_FILE_ERRORS = (OSError, InvalidFileException, ValueError, zipfile.BadZipFile)

# Błędy openpyxl przy pliku, który nie jest poprawnym skoroszytem .xlsx: przy otwieraniu, a w trybie
# tylko do odczytu także przy czytaniu wierszy, bo arkusz jest wtedy parsowany leniwie.
UNREADABLE_WORKBOOK_ERRORS = (
    OSError,
    InvalidFileException,
    zipfile.BadZipFile,
    KeyError,
    ValueError,
    zlib.error,
    ParseError,
)


class WorkbookSaveError(Exception):
    """Skoroszyt nie został zapisany; plik docelowy pozostał bez zmian."""


class ExternalLinksError(WorkbookSaveError):
    """Nie można przygotować ani przywrócić części ``xl/externalLinks/*``."""


def is_open_in_excel(path: Path) -> bool:
    """Rozpoznaje skoroszyt otwarty w desktopowym Excelu po pliku blokady ``~$…``."""

    return path.with_name(f"~${path.name}").exists()


class Availability(Enum):
    """Czy skoroszyt da się użyć: jest na dysku i nie jest otwarty w Excelu."""

    AVAILABLE = "dostępny"
    MISSING = "brak"
    OPEN_IN_EXCEL = "otwarty w Excelu"


def availability(path: Path) -> Availability:
    """Stan skoroszytu; miejsce wywołania samo decyduje, czy i jakim Komunikatem się zatrzymać."""

    if not path.is_file():
        return Availability.MISSING
    if is_open_in_excel(path):
        return Availability.OPEN_IN_EXCEL
    return Availability.AVAILABLE


def request_full_recalculation(workbook: Workbook) -> None:
    """Excel przeliczy formuły przy otwarciu; openpyxl nie zapisuje wyników formuł."""

    calculation = getattr(workbook, "calculation", None)
    if calculation is not None:
        calculation.calcMode = "auto"
        calculation.fullCalcOnLoad = True
        calculation.forceFullCalc = True


def save_workbook(
    workbook: Workbook,
    target: Path,
    *,
    external_links_from: Path | None = None,
) -> None:
    """Atomowo zapisuje skoroszyt, zachowując 1:1 jego odwołania zewnętrzne.

    openpyxl nie zapisuje wiernie części ``xl/externalLinks/*``, więc są one
    kopiowane bajtowo z ``external_links_from`` (domyślnie z ``target``, który
    musi wtedy istnieć). ``target`` zmienia się dopiero po udanym zapisie całości.
    """

    links_source = external_links_from if external_links_from is not None else target
    try:
        parts = _external_link_parts(links_source)
    except _WORKBOOK_FILE_ERRORS as exc:
        raise ExternalLinksError(
            f"Nie można odczytać odwołań zewnętrznych: {links_source.name}"
        ) from exc

    try:
        file_descriptor, temporary_name = tempfile.mkstemp(
            prefix=f".{target.stem}.", suffix=".xlsx", dir=target.parent
        )
        os.close(file_descriptor)
    except OSError as exc:
        raise WorkbookSaveError(f"Nie można zapisać skoroszytu: {target.name}") from exc
    temporary_path = Path(temporary_name)
    try:
        try:
            workbook.save(temporary_path)
        except _WORKBOOK_FILE_ERRORS as exc:
            raise WorkbookSaveError(f"Nie można zapisać skoroszytu: {target.name}") from exc
        try:
            _restore_external_link_parts(temporary_path, parts)
        except _WORKBOOK_FILE_ERRORS as exc:
            raise ExternalLinksError(
                f"Nie można przywrócić odwołań zewnętrznych: {target.name}"
            ) from exc
        try:
            os.replace(temporary_path, target)
        except OSError as exc:
            raise WorkbookSaveError(f"Nie można zapisać skoroszytu: {target.name}") from exc
    finally:
        temporary_path.unlink(missing_ok=True)


def _external_link_parts(path: Path) -> _ExternalLinkParts:
    """Pobiera oryginalne relacje zewnętrzne, których openpyxl nie zapisuje 1:1."""

    with zipfile.ZipFile(path, "r") as archive:
        return {
            info.filename: (info, archive.read(info.filename))
            for info in archive.infolist()
            if info.filename.startswith(_EXTERNAL_LINKS_PREFIX)
        }


def _restore_external_link_parts(path: Path, parts: _ExternalLinkParts) -> None:
    """Przywraca cały fragment externalLinks bez zmiany arkuszy i danych."""

    if not parts:
        return
    file_descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.stem}.links.", suffix=".xlsx", dir=path.parent
    )
    os.close(file_descriptor)
    temporary_path = Path(temporary_name)
    try:
        with zipfile.ZipFile(path, "r") as source, zipfile.ZipFile(temporary_path, "w") as target:
            for info in source.infolist():
                if info.filename.startswith(_EXTERNAL_LINKS_PREFIX):
                    continue
                target.writestr(info, source.read(info.filename))
            for info, data in parts.values():
                target.writestr(info, data)
        os.replace(temporary_path, path)
    finally:
        temporary_path.unlink(missing_ok=True)

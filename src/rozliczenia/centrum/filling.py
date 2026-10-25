"""Uzupełnienie pliku zbiorczego w Centrum: Ilości do uzupełnienia okresu jako zasób tylko do odczytu (ADR 0016).

Każde żądanie czyta zapisany Plik zbiorczy jedynym odczytem skoroszytu, także gdy trzyma go Excel, i przelicza
Ilości do uzupełnienia w silniku (``quantities_to_fill``); Centrum nigdy nie zmienia pliku. Na żywo (``live_file``):
tani znacznik zapisu, a podczas nieudanych prób przez minutę ostatni dobry odczyt z godziną.
Przeglądarka dostaje tylko numery wierszy, stan „zrobione” i liczniki kolumn. Nieudany odczyt to Komunikat, który
nazywa Plik zbiorczy, i wpis w dzienniku Centrum z przyczyną, bez treści wierszy.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from fastapi import APIRouter

from rozliczenia import collective_file
from rozliczenia.centrum import contract, fill_messages
from rozliczenia.centrum.cloud_files import CloudFiles
from rozliczenia.centrum.live_file import GoodRead, LastGoodReads, saved_version
from rozliczenia.centrum.log import CentrumLog
from rozliczenia.centrum.period_board import located_period_folder, requested_period
from rozliczenia.message import Message
from rozliczenia.order_facts import MissingHeaders
from rozliczenia.quantities_to_fill import NumberedOrder, quantities_to_fill
from rozliczenia.settings import SettingsStore
from rozliczenia.workbook_files import WorkbookError, excel_lock_file


def filling_router(
    store: SettingsStore, log: CentrumLog, cloud_files: CloudFiles, *, clock: Callable[[], float]
) -> APIRouter:
    router = APIRouter(prefix="/api/periods", tags=["okresy"])
    reads: LastGoodReads[tuple[NumberedOrder, ...]] = LastGoodReads(clock=clock)

    def collective_file_of(token: str) -> Path:
        periods_directory = store.load().periods_directory
        if periods_directory is None or not periods_directory.is_dir():
            raise contract.Refusal(409, "Najpierw wskaż folder okresów.")
        return located_period_folder(periods_directory, requested_period(token)).collective_file

    @router.get(
        "/{token}/quantities-to-fill", operation_id="getQuantitiesToFill", responses=contract.NOT_FOUND_OR_CONFLICT
    )
    def quantities(token: str) -> contract.QuantitiesToFill:
        path = collective_file_of(token)
        version = saved_version(path)
        found = _attempt(path, cloud_files)
        if not isinstance(found, _Unreadable):
            return _ready(reads.succeeded(path, found, version))
        failing = reads.failed(path)
        if failing.first:
            log.fill_unreadable(
                period=token, cause=found.message.code, excel_lock=_excel_lock(path), failure=found.type
            )
        if failing.kept is not None:
            return _ready(failing.kept)
        return contract.QuantitiesToFillProblem(
            state="problem", message=contract.Message.of(found.message), version=version
        )

    @router.get(
        "/{token}/collective-file-version",
        operation_id="getCollectiveFileVersion",
        responses=contract.NOT_FOUND_OR_CONFLICT,
    )
    def collective_file_version(token: str) -> contract.CollectiveFileVersion:
        """Znacznik zapisu Pliku zbiorczego bez otwierania skoroszytu: strona porównuje go z ``read.version``."""

        return contract.CollectiveFileVersion(version=saved_version(collective_file_of(token)))

    return router


@dataclass(frozen=True)
class _Unreadable:
    """Odczyt Pliku zbiorczego bez Ilości do uzupełnienia: Komunikat i typ błędu dla dziennika (``-`` bez niego)."""

    message: Message
    type: str


def _attempt(path: Path, cloud_files: CloudFiles) -> tuple[NumberedOrder, ...] | _Unreadable:
    try:
        read = collective_file.read_numbered_orders(path)
    except WorkbookError as error:
        message = (
            fill_messages.only_in_cloud(path)
            if cloud_files.online_only(path)
            else fill_messages.collective_file_unusable(error)
        )
        return _Unreadable(message, type(error.__cause__).__name__ if error.__cause__ else "-")
    if isinstance(read, MissingHeaders):
        return _Unreadable(fill_messages.headers_missing(path, read.headers), "-")
    return read


def _ready(read: GoodRead[tuple[NumberedOrder, ...]]) -> contract.QuantitiesToFillReady:
    found = quantities_to_fill(read.value)
    return contract.QuantitiesToFillReady(
        state="ready",
        read=contract.CollectiveFileRead(version=read.version, read_at=read.read_at, retrying=read.retrying),
        kinds=[
            contract.KindToFill(
                kind=kind.kind,
                rows=[contract.RowToFill(row=row.number, done=row.done) for row in kind.rows],
                done=kind.done,
            )
            for kind in found.kinds
        ],
        description_columns=[
            contract.DescriptionColumn(column=column, rows=rows) for column, rows in found.description_filled.items()
        ],
    )


def _excel_lock(path: Path) -> str:
    """``tak`` albo ``nie`` tylko wtedy, gdy system odpowiedział o pliku blokady; inaczej ``nieznany``.

    ``stat`` sprawdza prawa jak każdy odczyt, także ACL w Windows, gdzie ``os.access`` ich nie widzi.
    """

    try:
        excel_lock_file(path).stat()
    except FileNotFoundError:
        return "nie"
    except OSError:
        return "nieznany"
    return "tak"

"""Uzupełnienie pliku zbiorczego w Centrum: Ilości do uzupełnienia okresu jako zasób tylko do odczytu (ADR 0016).

Każde żądanie czyta zapisany Plik zbiorczy jedynym odczytem skoroszytu, także gdy trzyma go Excel, i przelicza
Ilości do uzupełnienia w silniku (``quantities_to_fill``); Centrum nigdy nie zmienia pliku. Na żywo (``live_file``):
tani znacznik zapisu, a podczas nieudanych prób przez minutę ostatni dobry odczyt z godziną.
Podsumowanie dostaje tylko numery wierszy, stan „zrobione” i liczniki kolumn, a strona rodzaju też teksty
wiersza, komórki N:AP i nazwy pozycji cennika, nigdy adres, numer zlecenia ani UMOWA. Nieudany odczyt to
Komunikat, który nazywa Plik zbiorczy, i wpis w dzienniku Centrum z przyczyną, bez treści wierszy.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path

from fastapi import APIRouter

from rozliczenia import collective_file
from rozliczenia.centrum import contract, fill_messages
from rozliczenia.centrum.cloud_files import CloudFiles
from rozliczenia.centrum.live_file import GoodRead, LastGoodReads, saved_version
from rozliczenia.centrum.log import CentrumLog
from rozliczenia.centrum.period_board import located_period_folder, requested_period
from rozliczenia.collective_file import NumberedOrders
from rozliczenia.message import Message
from rozliczenia.order_facts import MissingHeaders
from rozliczenia.quantities_to_fill import FillKind, KindToFill, quantities_to_fill
from rozliczenia.settings import SettingsStore
from rozliczenia.workbook_files import WorkbookError, excel_lock_file


def filling_router(
    store: SettingsStore, log: CentrumLog, cloud_files: CloudFiles, *, clock: Callable[[], float]
) -> APIRouter:
    router = APIRouter(prefix="/api/periods", tags=["okresy"])
    reads: LastGoodReads[NumberedOrders] = LastGoodReads(clock=clock)

    def collective_file_of(token: str) -> Path:
        periods_directory = store.load().periods_directory
        if periods_directory is None or not periods_directory.is_dir():
            raise contract.Refusal(409, "Najpierw wskaż folder okresów.")
        return located_period_folder(periods_directory, requested_period(token)).collective_file

    def read(token: str) -> GoodRead[NumberedOrders] | contract.QuantitiesToFillProblem:
        path = collective_file_of(token)
        attempt = reads.attempt(path)
        found = _attempt(path, cloud_files)
        if not isinstance(found, _Unreadable):
            return reads.succeeded(path, found, attempt)
        failing = reads.failed(path, attempt, cause=found.message.code)
        if failing.new_cause:
            log.fill_unreadable(
                period=token, cause=found.message.code, excel_lock=_excel_lock(path), failure=found.type
            )
        if failing.kept is not None:
            return failing.kept
        return contract.QuantitiesToFillProblem(
            state="problem", message=contract.Message.of(found.message), version=attempt.version
        )

    @router.get(
        "/{token}/quantities-to-fill", operation_id="getQuantitiesToFill", responses=contract.NOT_FOUND_OR_CONFLICT
    )
    def quantities(token: str) -> contract.QuantitiesToFill:
        found = read(token)
        if isinstance(found, contract.QuantitiesToFillProblem):
            return found
        return _ready(found)

    @router.get(
        "/{token}/quantities-to-fill/{kind}", operation_id="getKindTable", responses=contract.NOT_FOUND_OR_CONFLICT
    )
    def kind_table(token: str, kind: FillKind) -> contract.KindTable:
        found = read(token)
        if isinstance(found, contract.QuantitiesToFillProblem):
            return found
        [listed] = (listed for listed in quantities_to_fill(found.value.rows).kinds if listed.kind is kind)
        return _table(listed, found)

    @router.get(
        "/{token}/collective-file-version",
        operation_id="getCollectiveFileVersion",
        responses=contract.NOT_FOUND_OR_CONFLICT,
    )
    def collective_file_version(token: str) -> contract.CollectiveFileVersion:
        """Znacznik zapisu Pliku zbiorczego bez otwierania skoroszytu: strona porównuje go z ``read.version``."""

        return contract.CollectiveFileVersion(version=saved_version(collective_file_of(token)))

    @router.get("/{token}/without-quantity", operation_id="getWithoutQuantity", responses=contract.NOT_FOUND_OR_CONFLICT)
    def rows_without_quantity(token: str) -> contract.WithoutQuantity:
        """Wiersze bez ilości dla okna „Uruchomić z zapisem?” Przebiegu rozliczeń tego okresu.

        Tylko na żądanie wybranego okresu, bo odczyt trwa u taty ponad sekundę. Nieudany odczyt nie blokuje startu;
        Komunikat i wpis w dzienniku daje strona Uzupełnienia, a sam Przebieg rozliczeń nazywa plik.
        """

        periods_directory = store.load().periods_directory
        if periods_directory is None or not periods_directory.is_dir():
            raise contract.Refusal(409, "Najpierw wskaż folder okresów.")
        return _without_quantity(located_period_folder(periods_directory, requested_period(token)).collective_file)

    return router


def without_quantity_sentence(rows: Sequence[int]) -> str | None:
    """„1 wiersz bez ilości: 20”, „3 wiersze bez ilości: 18, 19, 20”, „12 wierszy bez ilości: …”; ``None`` bez wierszy."""

    if not rows:
        return None
    count = len(rows)
    few = count % 10 in (2, 3, 4) and count % 100 not in (12, 13, 14)
    word = "wiersz" if count == 1 else "wiersze" if few else "wierszy"
    return f"{count} {word} bez ilości: {', '.join(map(str, rows))}"


def _without_quantity(path: Path) -> contract.WithoutQuantity:
    try:
        found = collective_file.read_numbered_orders(path)
    except WorkbookError:
        return contract.WithoutQuantityUnread(state="unread")
    if isinstance(found, MissingHeaders):
        return contract.WithoutQuantityUnread(state="unread")
    rows = list(quantities_to_fill(found.rows).without_quantity)
    return contract.WithoutQuantityRead(state="read", rows=rows, sentence=without_quantity_sentence(rows))


def _ready(read: GoodRead[NumberedOrders]) -> contract.QuantitiesToFillReady:
    found = quantities_to_fill(read.value.rows)
    return contract.QuantitiesToFillReady(
        state="ready",
        read=_stamp(read),
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


def _table(listed: KindToFill, read: GoodRead[NumberedOrders]) -> contract.KindTableReady:
    return contract.KindTableReady(
        state="ready",
        read=_stamp(read),
        kind=listed.kind,
        columns=[contract.PriceListItem(column=column, name=name) for column, name in read.value.price_list.items()],
        rows=[
            contract.KindTableRow(
                row=row.number,
                state=row.state,
                worker=row.texts.worker,
                devices=row.texts.devices,
                activities=row.texts.activities,
                completed=row.texts.completed,
                cells=[contract.KindTableCell(source=cell.source, value=cell.value) for cell in row.cells],
            )
            for row in listed.rows
        ],
    )


def _stamp(read: GoodRead[NumberedOrders]) -> contract.CollectiveFileRead:
    return contract.CollectiveFileRead(version=read.version, read_at=read.read_at, retrying=read.retrying)


@dataclass(frozen=True)
class _Unreadable:
    """Odczyt Pliku zbiorczego bez Ilości do uzupełnienia: Komunikat i typ błędu dla dziennika (``-`` bez niego)."""

    message: Message
    type: str


def _attempt(path: Path, cloud_files: CloudFiles) -> NumberedOrders | _Unreadable:
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

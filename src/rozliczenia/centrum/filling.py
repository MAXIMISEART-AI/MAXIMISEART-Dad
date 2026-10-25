"""Uzupełnienie pliku zbiorczego w Centrum: Ilości do uzupełnienia okresu jako zasób tylko do odczytu (ADR 0016).

Każde żądanie czyta zapisany Plik zbiorczy jedynym odczytem skoroszytu, także gdy trzyma go Excel, i przelicza
Ilości do uzupełnienia w silniku (``quantities_to_fill``); Centrum nic nie przechowuje i nigdy nie zmienia pliku.
Przeglądarka dostaje tylko numery wierszy, stan „zrobione” i liczniki kolumn. Nieudany odczyt to Komunikat, który
nazywa Plik zbiorczy, i wpis w dzienniku Centrum z przyczyną, bez treści wierszy.
"""

from __future__ import annotations

from collections.abc import Sequence
import os
from pathlib import Path

from fastapi import APIRouter

from rozliczenia import collective_file
from rozliczenia.centrum import contract, fill_messages
from rozliczenia.centrum.cloud_files import CloudFiles
from rozliczenia.centrum.log import CentrumLog
from rozliczenia.centrum.period_board import located_period_folder, requested_period
from rozliczenia.order_facts import MissingHeaders
from rozliczenia.quantities_to_fill import QuantitiesToFill, quantities_to_fill
from rozliczenia.settings import SettingsStore
from rozliczenia.workbook_files import WorkbookError, is_open_in_excel


def filling_router(store: SettingsStore, log: CentrumLog, cloud_files: CloudFiles) -> APIRouter:
    router = APIRouter(prefix="/api/periods", tags=["okresy"])

    @router.get(
        "/{token}/quantities-to-fill", operation_id="getQuantitiesToFill", responses=contract.NOT_FOUND_OR_CONFLICT
    )
    def quantities(token: str) -> contract.QuantitiesToFill:
        periods_directory = store.load().periods_directory
        if periods_directory is None or not periods_directory.is_dir():
            raise contract.Refusal(409, "Najpierw wskaż folder okresów.")
        path = located_period_folder(periods_directory, requested_period(token)).collective_file
        try:
            read = collective_file.read_numbered_orders(path)
        except WorkbookError as error:
            message = (
                fill_messages.only_in_cloud(path)
                if cloud_files.online_only(path)
                else fill_messages.collective_file_unusable(error)
            )
            failure = type(error.__cause__).__name__ if error.__cause__ else "-"
        else:
            if not isinstance(read, MissingHeaders):
                return _ready(quantities_to_fill(read))
            message, failure = fill_messages.headers_missing(path, read.headers), "-"
        log.fill_unreadable(period=token, cause=message.code, excel_lock=_excel_lock(path), failure=failure)
        return contract.QuantitiesToFillProblem(state="problem", message=contract.Message.of(message))

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
        read = collective_file.read_numbered_orders(path)
    except WorkbookError:
        return contract.WithoutQuantityUnread(state="unread")
    if isinstance(read, MissingHeaders):
        return contract.WithoutQuantityUnread(state="unread")
    rows = list(quantities_to_fill(read).without_quantity)
    return contract.WithoutQuantityRead(state="read", rows=rows, sentence=without_quantity_sentence(rows))


def _ready(found: QuantitiesToFill) -> contract.QuantitiesToFillReady:
    return contract.QuantitiesToFillReady(
        state="ready",
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
    # W folderze bez dostępu pliku blokady nie widać, więc „nie” byłoby zgadywaniem.
    if not os.access(path.parent, os.X_OK):
        return "nieznany"
    return "tak" if is_open_in_excel(path) else "nie"


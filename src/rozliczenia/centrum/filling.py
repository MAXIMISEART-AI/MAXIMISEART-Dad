"""Uzupełnienie pliku zbiorczego w Centrum: Ilości do uzupełnienia okresu jako zasób tylko do odczytu (ADR 0016).

Każde żądanie czyta zapisany Plik zbiorczy jedynym odczytem skoroszytu, także gdy trzyma go Excel, i przelicza
Ilości do uzupełnienia w silniku (``quantities_to_fill``); Centrum nic nie przechowuje i nigdy nie zmienia pliku.
Podsumowanie dostaje tylko numery wierszy, stan „zrobione” i liczniki kolumn, a strona rodzaju też teksty
wiersza, komórki N:AP i nazwy pozycji cennika, nigdy adres, numer zlecenia ani UMOWA. Nieudany odczyt to
Komunikat, który nazywa Plik zbiorczy, i wpis w dzienniku Centrum z przyczyną, bez treści wierszy.
"""

from __future__ import annotations

import os
from pathlib import Path

from fastapi import APIRouter

from rozliczenia import collective_file
from rozliczenia.centrum import contract, fill_messages
from rozliczenia.centrum.cloud_files import CloudFiles
from rozliczenia.centrum.log import CentrumLog
from rozliczenia.centrum.period_board import located_period_folder, requested_period
from rozliczenia.collective_file import NumberedOrders
from rozliczenia.order_facts import N_AP, MissingHeaders
from rozliczenia.quantities_to_fill import FillKind, KindToFill, QuantitiesToFill, quantities_to_fill
from rozliczenia.settings import SettingsStore
from rozliczenia.workbook_files import WorkbookError, is_open_in_excel


def filling_router(store: SettingsStore, log: CentrumLog, cloud_files: CloudFiles) -> APIRouter:
    router = APIRouter(prefix="/api/periods", tags=["okresy"])

    def read(token: str) -> NumberedOrders | contract.QuantitiesToFillProblem:
        periods_directory = store.load().periods_directory
        if periods_directory is None or not periods_directory.is_dir():
            raise contract.Refusal(409, "Najpierw wskaż folder okresów.")
        path = located_period_folder(periods_directory, requested_period(token)).collective_file
        try:
            found = collective_file.read_numbered_orders(path)
        except WorkbookError as error:
            message = (
                fill_messages.only_in_cloud(path)
                if cloud_files.online_only(path)
                else fill_messages.collective_file_unusable(error)
            )
            failure = type(error.__cause__).__name__ if error.__cause__ else "-"
        else:
            if not isinstance(found, MissingHeaders):
                return found
            message, failure = fill_messages.headers_missing(path, found.headers), "-"
        log.fill_unreadable(period=token, cause=message.code, excel_lock=_excel_lock(path), failure=failure)
        return contract.QuantitiesToFillProblem(state="problem", message=contract.Message.of(message))

    @router.get(
        "/{token}/quantities-to-fill", operation_id="getQuantitiesToFill", responses=contract.NOT_FOUND_OR_CONFLICT
    )
    def quantities(token: str) -> contract.QuantitiesToFill:
        found = read(token)
        if isinstance(found, contract.QuantitiesToFillProblem):
            return found
        return _ready(quantities_to_fill(found.rows))

    @router.get(
        "/{token}/quantities-to-fill/{kind}", operation_id="getKindTable", responses=contract.NOT_FOUND_OR_CONFLICT
    )
    def kind_table(token: str, kind: FillKind) -> contract.KindTable:
        found = read(token)
        if isinstance(found, contract.QuantitiesToFillProblem):
            return found
        [listed] = (listed for listed in quantities_to_fill(found.rows).kinds if listed.kind is kind)
        return _table(listed, found.price_list)

    return router


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


def _table(listed: KindToFill, price_list: tuple[str, ...]) -> contract.KindTableReady:
    return contract.KindTableReady(
        state="ready",
        kind=listed.kind,
        columns=[contract.PriceListItem(column=column, name=name) for column, name in zip(N_AP, price_list, strict=True)],
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


def _excel_lock(path: Path) -> str:
    # W folderze bez dostępu pliku blokady nie widać, więc „nie” byłoby zgadywaniem.
    if not os.access(path.parent, os.X_OK):
        return "nieznany"
    return "tak" if is_open_in_excel(path) else "nie"


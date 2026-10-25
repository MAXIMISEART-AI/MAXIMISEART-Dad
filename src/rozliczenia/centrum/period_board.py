"""Tablica okresów: Foldery okresu z folderu okresów i ich Status okresu, wyliczane przy każdym odczycie.

Nie ma bazy ani pamięci podręcznej. Foldery okresu, ścieżki ich plików,
obserwację plików i Status okresu z nazwą zna silnik (``period_folder``);
treści skoroszytów Centrum nie czyta. Tu są tylko podpowiedzi następnego
kroku (podpowiedź podglądu deklaruje proces w ``run_view``) oraz etykiety i wybór plików do otwarcia.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import date
from pathlib import Path

from fastapi import APIRouter

from rozliczenia.centrum import contract, run_view
from rozliczenia.centrum.platform import Platform
from rozliczenia.settings import SettingsStore
from rozliczenia.period_folder import (
    PeriodFolder,
    PeriodFolderLookupError,
    PeriodFolders,
    PeriodStatus,
    locate_period_folder,
    month_folder_label,
    period_status_label,
    reading,
    scan_period_folders,
)
from rozliczenia.settlement_period import SettlementPeriod, last_complete_period, parse_period_token

_NEXT_STEPS: dict[PeriodStatus, contract.NextStep] = {
    "no_period_files": contract.ProcessStep(
        action="prepare_collective_file",
        label="Przygotuj plik zbiorczy",
        hint="Z Rejestru zleceń powstaną Rozliczenie wewnętrzne i Plik zbiorczy.",
        preview_hint=run_view.PREPARATION.preview_hint,
    ),
    "collective_file_prepared": contract.ProcessStep(
        action="create_worker_settlements",
        label="Utwórz rozliczenia pracowników",
        hint="Najpierw uzupełnij Plik zbiorczy w Excelu, zapisz go i zamknij.",
        preview_hint=run_view.SETTLEMENT.preview_hint,
    ),
    "worker_settlements_ready": contract.ClosedStep(
        action="none",
        label="Okres zamknięty",
        hint="Rozliczenia pracowników są w Folderze okresu.",
    ),
}


def _row(folder: PeriodFolder, *, last_complete: bool) -> contract.PeriodRow:
    period = folder.period
    observation = folder.observe()
    status = observation.status
    return contract.PeriodRow(
        token=period.token,
        tuesday=period.tuesday,
        monday=period.monday,
        status=status,
        status_label=period_status_label(status),
        period_folder_exists=observation.period_folder_exists,
        internal_settlement_exists=observation.internal_settlement_exists,
        collective_file_exists=observation.collective_file_exists,
        worker_settlements_folder_exists=observation.worker_settlements_folder_exists,
        worker_settlement_count=observation.worker_settlement_count,
        last_complete=last_complete,
        next_step=_NEXT_STEPS[status],
    )


def read_board(periods_directory: Path | None, today: date) -> contract.PeriodBoard:
    if periods_directory is None:
        return contract.BoardNotSet(state="not_set")
    if not periods_directory.is_dir():
        return contract.BoardMissing(state="missing", name=periods_directory.name)
    last_complete = last_complete_period(today)
    folders = {folder.period: folder for folder in scan_period_folders(periods_directory).found()}
    folders.setdefault(last_complete, PeriodFolder(periods_directory, last_complete))
    newest_first = sorted(folders.values(), key=lambda folder: folder.period.tuesday, reverse=True)
    rows = [_row(folder, last_complete=folder.period == last_complete) for folder in newest_first]
    return contract.BoardReady(
        state="ready",
        periods=rows,
        last_prepared_period=next((row.token for row in rows if row.collective_file_exists), None),
    )


def observed_period_folder(folders: PeriodFolders, period: SettlementPeriod) -> PeriodFolder:
    """Folder okresu do pokazania Statusu okresu; brak albo kilka miejsc nie jest tu zatrzymaniem.

    Gdy Folderu okresu nie ma, obserwacja dotyczy nieistniejącego folderu w
    samym folderze okresów; gdy jest w kilku miejscach, pierwszego z nich.
    Zatrzymuje dopiero akcja, która potrzebuje jednego Folderu okresu.
    """

    try:
        return folders.locate(period)
    except PeriodFolderLookupError as error:
        return PeriodFolder(error.locations[0] if error.locations else folders.periods_directory, period)


def requested_period(token: str) -> SettlementPeriod:
    """Okres z tokenu żądania przeglądarki; zły token to odmowa 404."""

    try:
        return parse_period_token(token)
    except ValueError:
        raise contract.Refusal(404, "Nie ma takiego okresu.") from None


def located_period_folder(periods_directory: Path, period: SettlementPeriod) -> PeriodFolder:
    """Jeden Folder okresu dla akcji Centrum; brak albo kilka miejsc to odmowa ze wskazówką dla taty."""

    try:
        return locate_period_folder(periods_directory, period)
    except PeriodFolderLookupError as error:
        token = period.token
        if not error.locations:
            raise contract.Refusal(
                404, f"Nie ma folderu {token} w żadnym folderze miesiąca. Załóż go w folderze INEA właściwego miesiąca."
            ) from None
        months = ", ".join(month_folder_label(error.periods_directory, location) for location in error.locations)
        raise contract.Refusal(
            409, f"Folder {token} jest w więcej niż jednym folderze miesiąca ({months}). Zostaw go tylko w jednym."
        ) from None


_TARGET_LABELS: dict[contract.OpenTarget, str] = {
    "internal_settlement": "Rozliczenie wewnętrzne",
    "collective_file": "Plik zbiorczy",
    "period_folder": "Folder okresu",
    "worker_settlements_folder": "Folder rozliczeń pracowników",
}


def periods_router(store: SettingsStore, platform: Platform, today: Callable[[], date]) -> APIRouter:
    router = APIRouter(prefix="/api/periods", tags=["okresy"])

    @router.get("", operation_id="getPeriodBoard")
    def board() -> contract.PeriodBoard:
        return read_board(store.load().periods_directory, today())

    def requested_folder(token: str) -> PeriodFolder:
        periods_directory = store.load().periods_directory
        if periods_directory is None or not periods_directory.is_dir():
            raise contract.Refusal(409, "Najpierw wskaż folder okresów.")
        return located_period_folder(periods_directory, requested_period(token))

    @router.post("/{token}/open", operation_id="openPeriodPath", responses=contract.NOT_FOUND_OR_CONFLICT)
    def open_period_path(token: str, request: contract.OpenRequest) -> contract.Opened:
        folder = requested_folder(token)
        path = {
            "internal_settlement": folder.internal_settlement,
            "collective_file": folder.collective_file,
            "period_folder": folder.directory,
            "worker_settlements_folder": folder.worker_settlements,
        }[request.target]
        with reading(folder.directory):
            exists = path.exists()
        if not exists:
            raise contract.Refusal(404, f"{_TARGET_LABELS[request.target]} okresu {token} jeszcze nie istnieje.")
        platform.open_path(path)
        return contract.Opened(name=path.name)

    @router.post(
        "/{token}/worker-settlements/open",
        operation_id="openWorkerSettlement",
        responses=contract.NOT_FOUND_OR_CONFLICT,
    )
    def open_worker_settlement(token: str, request: contract.WorkerSettlementRequest) -> contract.Opened:
        folder = requested_folder(token)
        path = folder.worker_settlement(request.worker)
        # Nazwa Wykonawcy z „/”, „\” albo „..” wyprowadziłaby ścieżkę poza Folder rozliczeń pracowników.
        inside = path.parent == folder.worker_settlements
        with reading(folder.directory):
            exists = inside and path.is_file()
        if not exists:
            raise contract.Refusal(404, f"Rozliczenia pracownika {request.worker} nie ma w okresie {token}.")
        platform.open_path(path)
        return contract.Opened(name=path.name)

    return router

"""Tablica okresów: Foldery okresu z folderu okresów i ich Status okresu, wyliczane przy każdym odczycie.

Nie ma bazy ani pamięci podręcznej. Foldery okresu, ścieżki ich plików,
obserwację plików i Status okresu z nazwą zna silnik (``period_folder``);
treści skoroszytów Centrum nie czyta. Tu są tylko podpowiedzi następnego
kroku oraz etykiety i wybór plików do otwarcia.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import date
from pathlib import Path
from typing import Any

from fastapi import APIRouter

from rozliczenia.centrum import contract
from rozliczenia.centrum.platform import Platform
from rozliczenia.centrum.settings import SettingsStore
from rozliczenia.period_folder import PeriodFolder, PeriodStatus, find_period_folders, period_status_label
from rozliczenia.settlement_period import last_complete_period, parse_period_token

_NEXT_STEPS: dict[PeriodStatus, contract.NextStep] = {
    "no_period_files": contract.NextStep(
        action="prepare_collective_file",
        label="Przygotuj plik zbiorczy",
        hint="Z Rejestru zleceń powstaną Rozliczenie wewnętrzne i Plik zbiorczy.",
    ),
    "collective_file_prepared": contract.NextStep(
        action="create_worker_settlements",
        label="Utwórz rozliczenia pracowników",
        hint="Najpierw uzupełnij Plik zbiorczy w Excelu, zapisz go i zamknij.",
    ),
    "worker_settlements_ready": contract.NextStep(
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
    last_complete = PeriodFolder(periods_directory, last_complete_period(today))
    folders = set(find_period_folders(periods_directory)) | {last_complete}
    newest_first = sorted(folders, key=lambda folder: folder.period.tuesday, reverse=True)
    rows = [_row(folder, last_complete=folder == last_complete) for folder in newest_first]
    return contract.BoardReady(
        state="ready",
        periods=rows,
        last_prepared_period=next((row.token for row in rows if row.collective_file_exists), None),
    )


_TARGET_LABELS: dict[contract.OpenTarget, str] = {
    "internal_settlement": "Rozliczenie wewnętrzne",
    "collective_file": "Plik zbiorczy",
    "period_folder": "Folder okresu",
    "worker_settlements_folder": "Folder rozliczeń pracowników",
}
_PROBLEMS: dict[int | str, dict[str, Any]] = {404: {"model": contract.Problem}, 409: {"model": contract.Problem}}


def periods_router(store: SettingsStore, platform: Platform, today: Callable[[], date]) -> APIRouter:
    router = APIRouter(prefix="/api/periods", tags=["okresy"])

    @router.get("", operation_id="getPeriodBoard")
    def board() -> contract.PeriodBoard:
        return read_board(store.load().periods_directory, today())

    @router.post("/{token}/open", operation_id="openPeriodPath", responses=_PROBLEMS)
    def open_period_path(token: str, request: contract.OpenRequest) -> contract.Opened:
        periods_directory = store.load().periods_directory
        if periods_directory is None or not periods_directory.is_dir():
            raise contract.Refusal(409, "Najpierw wskaż folder okresów.")
        try:
            period = parse_period_token(token)
        except ValueError:
            raise contract.Refusal(404, "Nie ma takiego okresu.") from None
        folder = PeriodFolder(periods_directory, period)
        path = {
            "internal_settlement": folder.internal_settlement,
            "collective_file": folder.collective_file,
            "period_folder": folder.directory,
            "worker_settlements_folder": folder.worker_settlements,
        }[request.target]
        if not path.exists():
            raise contract.Refusal(404, f"{_TARGET_LABELS[request.target]} okresu {token} jeszcze nie istnieje.")
        platform.open_path(path)
        return contract.Opened(name=path.name)

    return router

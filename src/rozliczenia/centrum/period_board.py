"""Tablica okresów: Foldery okresu z folderu okresów i ich Status okresu, wyliczane przy każdym odczycie.

Nie ma bazy ani pamięci podręcznej. Ścieżki plików okresu zna silnik
(``period_folder``), a Status okresu wylicza z obecności plików
(``period_status``); treści skoroszytów Centrum nie czyta. Tu są tylko
etykiety, podpowiedzi następnego kroku i wybór pliku do otwarcia.
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
from rozliczenia.period_folder import PeriodFolder
from rozliczenia.period_status import PeriodStatus, period_status
from rozliczenia.settlement_period import SettlementPeriod, last_complete_period, parse_period_token

_STATUS_LABELS: dict[PeriodStatus, str] = {
    "no_period_files": "Brak plików okresu",
    "collective_file_prepared": "Plik zbiorczy przygotowany",
    "worker_settlements_ready": "Rozliczenia pracowników gotowe",
}
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


def status_label(status: PeriodStatus) -> str:
    return _STATUS_LABELS[status]


def _row(folder: PeriodFolder, *, last_complete: bool) -> contract.PeriodRow:
    period = folder.period
    has_worker_settlements = folder.worker_settlements.is_dir()
    status = period_status(folder)
    return contract.PeriodRow(
        token=period.token,
        tuesday=period.tuesday,
        monday=period.monday,
        status=status,
        status_label=_STATUS_LABELS[status],
        period_folder_exists=folder.directory.is_dir(),
        internal_settlement_exists=folder.internal_settlement.is_file(),
        collective_file_exists=folder.collective_file.is_file(),
        worker_settlements_folder_exists=has_worker_settlements,
        worker_settlement_count=folder.count_worker_settlements() if has_worker_settlements else 0,
        last_complete=last_complete,
        next_step=_NEXT_STEPS[status],
    )


def read_board(periods_directory: Path | None, today: date) -> contract.PeriodBoard:
    if periods_directory is None:
        return contract.BoardNotSet(state="not_set")
    if not periods_directory.is_dir():
        return contract.BoardMissing(state="missing", name=periods_directory.name)
    last_complete = last_complete_period(today)
    periods = set(_period_folders(periods_directory)) | {last_complete}
    newest_first = sorted(periods, key=lambda period: period.tuesday, reverse=True)
    rows = [
        _row(PeriodFolder(periods_directory, period), last_complete=period == last_complete) for period in newest_first
    ]
    return contract.BoardReady(
        state="ready",
        periods=rows,
        last_prepared_period=next((row.token for row in rows if row.collective_file_exists), None),
    )


def _period_folders(periods_directory: Path) -> list[SettlementPeriod]:
    periods = []
    for entry in periods_directory.iterdir():
        if not entry.is_dir():
            continue
        try:
            periods.append(parse_period_token(entry.name))
        except ValueError:
            continue
    return periods


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

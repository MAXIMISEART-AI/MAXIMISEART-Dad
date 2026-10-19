"""Tablica okresów: Foldery okresu z folderu okresów i ich Status okresu, wyliczane przy każdym odczycie.

Nie ma bazy ani pamięci podręcznej. Status okresu wynika tylko z obecności
plików, których nazwy zna silnik; treści skoroszytów Centrum nie czyta.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

from fastapi import APIRouter

from rozliczenia import collective_file
from rozliczenia.centrum import contract
from rozliczenia.centrum.platform import Platform
from rozliczenia.centrum.settings import SettingsStore
from rozliczenia.engine import count_worker_settlements, worker_settlements_directory
from rozliczenia.preparation_files import internal_settlement_path
from rozliczenia.settlement_period import SettlementPeriod, last_complete_period, parse_period_token

_STATUS_LABELS: dict[contract.PeriodStatus, str] = {
    "no_period_files": "Brak plików okresu",
    "collective_file_prepared": "Plik zbiorczy przygotowany",
    "worker_settlements_ready": "Rozliczenia pracowników gotowe",
}
_NEXT_STEPS: dict[contract.PeriodStatus, contract.NextStep] = {
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


def status_label(status: contract.PeriodStatus) -> str:
    return _STATUS_LABELS[status]


@dataclass(frozen=True)
class PeriodFolder:
    """Folder okresu i ścieżki jego plików, wyliczone z folderu okresów i tokenu."""

    period: SettlementPeriod
    directory: Path

    @classmethod
    def of(cls, periods_directory: Path, period: SettlementPeriod) -> PeriodFolder:
        return cls(period, periods_directory / period.token)

    @property
    def internal_settlement(self) -> Path:
        return internal_settlement_path(self.directory, self.period.token)

    @property
    def collective_file(self) -> Path:
        return collective_file.path_for_period(self.directory, self.period.token)

    @property
    def worker_settlements(self) -> Path:
        return worker_settlements_directory(self.directory, self.period.token)

    def row(self, *, last_complete: bool) -> contract.PeriodRow:
        has_collective_file = self.collective_file.is_file()
        has_worker_settlements = self.worker_settlements.is_dir()
        status: contract.PeriodStatus = (
            "worker_settlements_ready"
            if has_worker_settlements
            else "collective_file_prepared"
            if has_collective_file
            else "no_period_files"
        )
        return contract.PeriodRow(
            token=self.period.token,
            tuesday=self.period.tuesday,
            monday=self.period.monday,
            status=status,
            status_label=_STATUS_LABELS[status],
            period_folder_exists=self.directory.is_dir(),
            internal_settlement_exists=self.internal_settlement.is_file(),
            collective_file_exists=has_collective_file,
            worker_settlements_folder_exists=has_worker_settlements,
            worker_settlement_count=(
                count_worker_settlements(self.worker_settlements, self.period.token) if has_worker_settlements else 0
            ),
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
    return contract.BoardReady(
        state="ready",
        periods=[
            PeriodFolder.of(periods_directory, period).row(last_complete=period == last_complete)
            for period in newest_first
        ],
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
        folder = PeriodFolder.of(periods_directory, period)
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

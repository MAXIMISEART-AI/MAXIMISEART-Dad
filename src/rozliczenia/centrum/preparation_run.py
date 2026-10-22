"""Przygotowanie pliku zbiorczego z Centrum rozliczeń: wybór okresu, wejście procesu z ustawień i wynik.

Rejestr zleceń i folder okresów pochodzą z ustawień, okres z listy ostatnich
pełnych okresów.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any, Final

from rozliczenia.centrum import contract, run_view
from rozliczenia.centrum.configuration import ConfigurationFiles
from rozliczenia.centrum.metrics import previewed_periods
from rozliczenia.centrum.period_board import observed_period_folder, requested_period
from rozliczenia.centrum.runs import PreparedRun
from rozliczenia.collective_preparation import PreparationSummary
from rozliczenia.settings import Settings, SettingsStore
from rozliczenia.period_folder import PeriodFolders, period_status_label, scan_period_folders
from rozliczenia.preparation_process import PreparationInputs
from rozliczenia.process_run import Process
from rozliczenia.settlement_period import SettlementPeriod, last_complete_period
from rozliczenia.telemetry import MetricsStore

_KEY: Final[contract.ProcessKey] = "preparation"
_VIEW: Final = run_view.PREPARATION
_CHOSEN_WEEKS: Final = 8


@dataclass(frozen=True)
class PreparationEntry:
    """Przygotowanie pliku zbiorczego jako proces uruchamiany z Centrum (``runs.ProcessEntry``)."""

    store: SettingsStore
    configuration: ConfigurationFiles
    process: Process[PreparationInputs, PreparationSummary]
    today: Callable[[], date]

    @property
    def key(self) -> contract.ProcessKey:
        return _KEY

    def setup(self) -> contract.ProcessSetup:
        settings = self.store.load()
        last_complete = last_complete_period(self.today())
        periods = [SettlementPeriod(last_complete.tuesday - timedelta(weeks=week)) for week in range(_CHOSEN_WEEKS)]
        previewed = previewed_periods(MetricsStore(self.process.metrics_path(), self.process.counter_names))
        folders = scan_period_folders(settings.periods_directory) if settings.periods_directory is not None else None
        return contract.ProcessSetup(
            process=_KEY,
            title=self.process.name,
            creates="Rozliczenie wewnętrzne i Plik zbiorczy",
            reminder=_VIEW.reminder,
            confirms_readiness=_VIEW.confirms_readiness,
            preview_hint=_VIEW.preview_hint,
            periods=[
                _choice(folders, period, last_complete=period == last_complete, previewed=period.token in previewed)
                for period in periods
            ],
            preselected_period=last_complete.token,
            blocker=_blocker(settings),
        )

    def prepare(self, request: contract.RunRequest) -> PreparedRun[Any, Any]:
        settings = self.store.load()
        blocker = _blocker(settings)
        if blocker is not None or settings.register is None or settings.periods_directory is None:
            raise contract.Refusal(409, blocker or "Najpierw wskaż Rejestr zleceń i folder okresów.")
        period = requested_period(request.period).token
        inputs = PreparationInputs(
            settings.register,
            settings.periods_directory,
            period,
            dry_run=request.dry_run,
            config_path=self.configuration.worker_config,
            internal_template_path=self.configuration.internal_template,
            collective_template_path=self.configuration.collective_template,
        )
        return PreparedRun(
            key=_KEY,
            period=period,
            process=self.process,
            inputs=inputs,
            metrics_path=self.process.metrics_path(),
            done="Plik zbiorczy przygotowany",
            view=_VIEW,
        )


def _blocker(settings: Settings) -> str | None:
    missing = [
        name
        for name, path in (("Rejestr zleceń", settings.register), ("folder okresów", settings.periods_directory))
        if path is None
    ]
    return f"Najpierw wskaż {' i '.join(missing)}." if missing else None


def _choice(
    folders: PeriodFolders | None, period: SettlementPeriod, *, last_complete: bool, previewed: bool
) -> contract.PeriodChoice:
    status = observed_period_folder(folders, period).observe().status if folders is not None else "no_period_files"
    return contract.PeriodChoice(
        token=period.token,
        tuesday=period.tuesday,
        monday=period.monday,
        status_label=period_status_label(status),
        last_complete=last_complete,
        previewed=previewed,
        collective_file=None,
    )


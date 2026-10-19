"""Przygotowanie pliku zbiorczego z Centrum rozliczeń: wybór okresu, wejście procesu z ustawień i wynik.

Rejestr zleceń i folder okresów pochodzą z ustawień, okres z listy ostatnich
pełnych okresów. Proces prowadzi rdzeń Uruchomienia procesu z tym samym opisem
procesu co CLI (``preparation_cli.PROCESS``), więc liczby, ostrzeżenia,
komunikaty i rekord metryk są te same.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path
from typing import Any, Final

from rozliczenia import preparation_cli
from rozliczenia.centrum import contract
from rozliczenia.centrum.configuration import ConfigurationFiles
from rozliczenia.centrum.metrics import PROCESS_NAMES, previewed_periods
from rozliczenia.centrum.runs import PreparedRun
from rozliczenia.centrum.settings import CentrumSettings, SettingsStore
from rozliczenia.collective_preparation import PreparationSummary
from rozliczenia.period_folder import PeriodFolder, period_status_label
from rozliczenia.settlement_period import SettlementPeriod, last_complete_period, parse_period_token
from rozliczenia.telemetry import MetricsStore

_PROCESS: Final = preparation_cli.PROCESS
_KEY: Final[contract.ProcessKey] = "preparation"
_CHOSEN_WEEKS: Final = 8


@dataclass(frozen=True)
class PreparationEntry:
    """Przygotowanie pliku zbiorczego jako proces uruchamiany z Centrum (``runs.ProcessEntry``)."""

    store: SettingsStore
    configuration: ConfigurationFiles
    metrics_path: Path
    today: Callable[[], date]

    @property
    def key(self) -> contract.ProcessKey:
        return _KEY

    def setup(self) -> contract.ProcessSetup:
        settings = self.store.load()
        last_complete = last_complete_period(self.today())
        periods = [SettlementPeriod(last_complete.tuesday - timedelta(weeks=week)) for week in range(_CHOSEN_WEEKS)]
        previewed = previewed_periods(MetricsStore(self.metrics_path, _PROCESS.counter_names))
        return contract.ProcessSetup(
            process=_KEY,
            title=PROCESS_NAMES[_KEY],
            creates="Rozliczenie wewnętrzne i Plik zbiorczy",
            reminder="Zapisz i zamknij Rejestr zleceń w Excelu",
            periods=[
                _choice(settings, period, last_complete=period == last_complete, previewed=period.token in previewed)
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
        try:
            period = parse_period_token(request.period).token
        except ValueError:
            raise contract.Refusal(404, "Nie ma takiego okresu.") from None
        inputs = preparation_cli.PreparationInputs(
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
            title=PROCESS_NAMES[_KEY],
            period=period,
            process=_PROCESS,
            inputs=inputs,
            metrics_path=self.metrics_path,
            done="Plik zbiorczy przygotowany",
            summary=_summary,
            warnings=lambda summary: summary.warnings,
        )


def _blocker(settings: CentrumSettings) -> str | None:
    missing = [
        name
        for name, path in (("Rejestr zleceń", settings.register), ("folder okresów", settings.periods_directory))
        if path is None
    ]
    return f"Najpierw wskaż {' i '.join(missing)}." if missing else None


def _choice(
    settings: CentrumSettings, period: SettlementPeriod, *, last_complete: bool, previewed: bool
) -> contract.PeriodChoice:
    periods_directory = settings.periods_directory
    status = (
        PeriodFolder(periods_directory, period).observe().status if periods_directory is not None else "no_period_files"
    )
    return contract.PeriodChoice(
        token=period.token,
        tuesday=period.tuesday,
        monday=period.monday,
        status_label=period_status_label(status),
        last_complete=last_complete,
        previewed=previewed,
        collective_file=None,
    )


def _summary(summary: PreparationSummary) -> contract.PreparationSummary:
    return contract.PreparationSummary(
        process="preparation",
        period=summary.period,
        period_order_count=summary.period_order_count,
        successful_order_count=summary.successful_order_count,
        skipped_empty_rows=summary.skipped_empty_rows,
        orders_per_day=[contract.Count(label=label, count=count) for label, count in summary.labeled_orders_per_day()],
        internal_settlement_file=summary.internal_settlement_file.name,
        collective_file=summary.collective_file.name,
    )

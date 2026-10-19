"""Przygotowanie pliku zbiorczego z Centrum rozliczeń: wybór okresu, wejście procesu z ustawień i wynik.

Rejestr zleceń i folder okresów pochodzą z ustawień, okres z listy ostatnich
pełnych okresów. Proces prowadzi rdzeń Uruchomienia procesu z tym samym opisem
procesu co CLI (``preparation_cli.CENTRUM_PROCESS``), więc liczby, ostrzeżenia,
linie i rekord metryk są te same.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import date, timedelta
from typing import Final

from rozliczenia import preparation_cli
from rozliczenia.centrum import contract
from rozliczenia.centrum.period_board import PeriodFolder, status_label
from rozliczenia.centrum.runs import PreparedRun, run_result
from rozliczenia.centrum.settings import CentrumSettings, SettingsStore
from rozliczenia.centrum.tool_paths import ToolPaths
from rozliczenia.collective_preparation import PreparationSummary
from rozliczenia.preparation_messages import PreparationMessage
from rozliczenia.process_run import Interlocutor, run_process
from rozliczenia.settlement_period import SettlementPeriod, last_complete_period, parse_period_token

_PROCESS: Final = preparation_cli.CENTRUM_PROCESS
_CHOSEN_WEEKS: Final = 8


class PreparationEntry:
    """Przygotowanie pliku zbiorczego jako proces uruchamiany z Centrum (``runs.ProcessEntry``)."""

    key: Final[contract.ProcessKey] = "preparation"

    def __init__(self, store: SettingsStore, tool_paths: ToolPaths, today: Callable[[], date]) -> None:
        self._store = store
        self._tool_paths = tool_paths
        self._today = today

    def setup(self) -> contract.ProcessSetup:
        settings = self._store.load()
        last_complete = last_complete_period(self._today())
        periods = [SettlementPeriod(last_complete.tuesday - timedelta(weeks=week)) for week in range(_CHOSEN_WEEKS)]
        return contract.ProcessSetup(
            process=self.key,
            title=_PROCESS.title,
            creates="Rozliczenie wewnętrzne i Plik zbiorczy",
            reminder="Zapisz i zamknij Rejestr zleceń w Excelu",
            periods=[_choice(settings, period, last_complete=period == last_complete) for period in periods],
            preselected_period=last_complete.token,
            blocker=_blocker(settings),
        )

    def prepare(self, request: contract.RunRequest) -> PreparedRun:
        settings = self._store.load()
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
            config_path=self._tool_paths.worker_config,
            internal_template_path=self._tool_paths.internal_template,
            collective_template_path=self._tool_paths.collective_template,
        )
        metrics_path = self._tool_paths.preparation_metrics

        def conduct(interlocutor: Interlocutor) -> contract.RunResult:
            outcome = run_process(_PROCESS, inputs, interlocutor, metrics_path=metrics_path)
            summary = outcome.summary
            return run_result(
                outcome,
                dry_run=inputs.dry_run,
                done="Plik zbiorczy przygotowany",
                summary=None if summary is None else _summary(summary),
                warnings=[] if summary is None else [_message(warning) for warning in summary.warnings],
            )

        return PreparedRun(self.key, _PROCESS.title, period, request.dry_run, conduct)


def _blocker(settings: CentrumSettings) -> str | None:
    missing = [
        name
        for name, path in (("Rejestr zleceń", settings.register), ("folder okresów", settings.periods_directory))
        if path is None
    ]
    return f"Najpierw wskaż {' i '.join(missing)}." if missing else None


def _choice(settings: CentrumSettings, period: SettlementPeriod, *, last_complete: bool) -> contract.PeriodChoice:
    periods_directory = settings.periods_directory
    label = (
        PeriodFolder.of(periods_directory, period).row(last_complete=last_complete).status_label
        if periods_directory is not None and periods_directory.is_dir()
        else status_label("no_period_files")
    )
    return contract.PeriodChoice(
        token=period.token,
        tuesday=period.tuesday,
        monday=period.monday,
        status_label=label,
        last_complete=last_complete,
    )


def _summary(summary: PreparationSummary) -> contract.PreparationSummary:
    return contract.PreparationSummary(
        period=summary.period,
        period_order_count=summary.period_order_count,
        successful_order_count=summary.successful_order_count,
        skipped_empty_rows=summary.skipped_empty_rows,
        orders_per_day=[
            contract.Count(label=preparation_cli.day_label(day), count=count)
            for day, count in summary.orders_per_day.items()
        ],
        internal_settlement_file=summary.internal_settlement_file.name,
        collective_file=summary.collective_file.name,
    )


def _message(message: PreparationMessage) -> contract.Message:
    return contract.Message(what=message.what, where=message.where, action=message.action)

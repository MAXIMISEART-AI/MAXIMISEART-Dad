"""Przebieg rozliczeń z Centrum rozliczeń: wybór okresu, wejście procesu z ustawień i wynik.

Plik zbiorczy wynika z folderu okresów i okresu; tata go nie wskazuje. Do
wyboru są okresy ze Statusem okresu „Plik zbiorczy przygotowany”. Kliknięcie
„Uruchom” jest potwierdzeniem Gotowości: Centrum nie zgaduje jej z pliku ani
nie blokuje startu.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import date
from typing import Any, Final

from rozliczenia.centrum import contract, run_view
from rozliczenia.centrum.configuration import ConfigurationFiles
from rozliczenia.centrum.metrics import previewed_periods
from rozliczenia.centrum.period_board import located_period_folder, read_board, requested_period
from rozliczenia.centrum.runs import PreparedRun
from rozliczenia.domain import SettlementSummary
from rozliczenia.settings import SettingsStore
from rozliczenia.period_folder import PeriodStatus, collective_file_name, period_status_label
from rozliczenia.settlement_period import SettlementPeriod, last_complete_period
from rozliczenia.process_run import Process
from rozliczenia.settlement_process import SettlementInputs
from rozliczenia.telemetry import MetricsStore

_KEY: Final[contract.ProcessKey] = "settlement"
_VIEW: Final = run_view.SETTLEMENT
_ELIGIBLE: Final[PeriodStatus] = "collective_file_prepared"


@dataclass(frozen=True)
class SettlementEntry:
    """Przebieg rozliczeń jako proces uruchamiany z Centrum (``runs.ProcessEntry``)."""

    store: SettingsStore
    configuration: ConfigurationFiles
    process: Process[SettlementInputs, SettlementSummary]
    today: Callable[[], date]

    @property
    def key(self) -> contract.ProcessKey:
        return _KEY

    def setup(self) -> contract.ProcessSetup:
        periods_directory = self.store.load().periods_directory
        board = read_board(periods_directory, self.today())
        rows = [row for row in board.periods if row.status == _ELIGIBLE] if board.state == "ready" else []
        preselected = next(
            (row.token for row in rows if row.last_complete),
            rows[0].token if rows else last_complete_period(self.today()).token,
        )
        previewed = previewed_periods(MetricsStore(self.process.metrics_path(), self.process.counter_names))
        return contract.ProcessSetup(
            process=_KEY,
            title=self.process.name,
            creates="Rozliczenia pracowników",
            reminder=_VIEW.reminder,
            confirms_readiness=_VIEW.confirms_readiness,
            preview_hint=_VIEW.preview_hint,
            periods=[_choice(row, previewed=row.token in previewed) for row in rows],
            preselected_period=preselected,
            blocker=_blocker(board, rows),
        )

    def prepare(self, request: contract.RunRequest) -> PreparedRun[Any, Any]:
        periods_directory = self.store.load().periods_directory
        if periods_directory is None:
            raise contract.Refusal(409, "Najpierw wskaż folder okresów.")
        period = requested_period(request.period)
        source = located_period_folder(periods_directory, period).collective_file
        inputs = SettlementInputs(
            source,
            dry_run=request.dry_run,
            config_path=self.configuration.worker_config,
            worker_template_path=self.configuration.worker_template,
        )

        return PreparedRun(
            key=_KEY,
            period=period.token,
            process=self.process,
            inputs=inputs,
            metrics_path=self.process.metrics_path(),
            done="Rozliczenia pracowników gotowe",
            view=_VIEW,
        )


def _choice(row: contract.PeriodRow, *, previewed: bool) -> contract.PeriodChoice:
    return contract.PeriodChoice(
        token=row.token,
        tuesday=row.tuesday,
        monday=row.monday,
        status_label=row.status_label,
        last_complete=row.last_complete,
        previewed=previewed,
        collective_file=collective_file_name(SettlementPeriod(row.tuesday)),
    )


def _blocker(board: contract.PeriodBoard, rows: list[contract.PeriodRow]) -> str | None:
    if board.state == "not_set":
        return "Najpierw wskaż folder okresów."
    if board.state == "missing":
        return f"Nie ma już folderu okresów {board.name}. Wskaż go ponownie."
    if not rows:
        return f"Żaden okres nie ma Statusu „{period_status_label(_ELIGIBLE)}”. Najpierw przygotuj plik zbiorczy."
    return None


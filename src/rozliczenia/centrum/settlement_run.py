"""Przebieg rozliczeń z Centrum rozliczeń: wybór okresu, wejście procesu z ustawień i wynik.

Plik zbiorczy wynika z folderu okresów i okresu; tata go nie wskazuje. Do
wyboru są okresy ze Statusem okresu „Plik zbiorczy przygotowany”. Kliknięcie
„Uruchom” jest potwierdzeniem Gotowości: Centrum nie zgaduje jej z pliku ani
nie blokuje startu. Proces prowadzi rdzeń Uruchomienia procesu z tym samym
opisem procesu co CLI (``cli.PROCESS``), więc liczby, komunikaty i rekord
metryk są te same. Terminal pokazuje zatrzymanie jedną linią, Centrum ten sam
komunikat w trzech częściach.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any, Final

from rozliczenia import cli, settlement_messages
from rozliczenia.centrum import contract
from rozliczenia.centrum.configuration import ConfigurationFiles
from rozliczenia.centrum.metrics import PROCESS_NAMES, previewed_periods
from rozliczenia.centrum.period_board import read_board
from rozliczenia.centrum.runs import Endings, PreparedRun
from rozliczenia.centrum.settings import SettingsStore
from rozliczenia.domain import SettlementSummary
from rozliczenia.period_folder import PeriodFolder, PeriodStatus, collective_file_name, period_status_label
from rozliczenia.settlement_period import SettlementPeriod, last_complete_period, parse_period_token
from rozliczenia.telemetry import MetricsStore

_PROCESS: Final = cli.PROCESS
_KEY: Final[contract.ProcessKey] = "settlement"
_ELIGIBLE: Final[PeriodStatus] = "collective_file_prepared"
_ENDINGS: Final = Endings(
    unexpected=settlement_messages.unexpected_failure(),
    plan_not_shown=settlement_messages.plan_not_shown(),
    summary_not_shown=settlement_messages.summary_not_shown(),
)


@dataclass(frozen=True)
class SettlementEntry:
    """Przebieg rozliczeń jako proces uruchamiany z Centrum (``runs.ProcessEntry``)."""

    store: SettingsStore
    configuration: ConfigurationFiles
    metrics_path: Path
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
        previewed = previewed_periods(MetricsStore(self.metrics_path, _PROCESS.counter_names))
        return contract.ProcessSetup(
            process=_KEY,
            title=PROCESS_NAMES[_KEY],
            creates="Rozliczenia pracowników",
            reminder="Zapisz i zamknij Plik zbiorczy w Excelu",
            periods=[_choice(row, previewed=row.token in previewed) for row in rows],
            preselected_period=preselected,
            blocker=_blocker(board, rows),
        )

    def prepare(self, request: contract.RunRequest) -> PreparedRun[Any, Any]:
        periods_directory = self.store.load().periods_directory
        if periods_directory is None:
            raise contract.Refusal(409, "Najpierw wskaż folder okresów.")
        try:
            period = parse_period_token(request.period)
        except ValueError:
            raise contract.Refusal(404, "Nie ma takiego okresu.") from None
        source = PeriodFolder(periods_directory, period).collective_file
        inputs = cli.SettlementInputs(
            source,
            dry_run=request.dry_run,
            config_path=self.configuration.worker_config,
            worker_template_path=self.configuration.worker_template,
        )

        def warnings(summary: SettlementSummary) -> list[settlement_messages.SettlementMessage]:
            return [settlement_messages.issue_message(issue, source) for issue in summary.issues]

        return PreparedRun(
            key=_KEY,
            title=PROCESS_NAMES[_KEY],
            period=period.token,
            process=_PROCESS,
            inputs=inputs,
            metrics_path=self.metrics_path,
            done="Rozliczenia pracowników gotowe",
            endings=_ENDINGS,
            summary=_summary,
            warnings=warnings,
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


def _summary(summary: SettlementSummary) -> contract.SettlementSummary:
    return contract.SettlementSummary(
        process="settlement",
        period=summary.period,
        worker_settlements_folder=summary.target_directory.name,
        rows=summary.total_rows,
        written_count=summary.written_count,
        planned_count=summary.planned_count,
        empty_count=summary.empty_count,
        skipped_count=summary.skipped_count,
        files=[
            contract.WorkerFile(worker_name=result.worker_name, file=result.output_file.name, rows=result.rows)
            for result in summary.results
        ],
    )

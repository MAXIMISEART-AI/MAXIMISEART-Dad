"""Przebieg rozliczeń z Centrum rozliczeń: wybór okresu, wejście procesu z ustawień i wynik.

Plik zbiorczy wynika z folderu okresów i okresu; tata go nie wskazuje. Do
wyboru są okresy ze Statusem okresu „Plik zbiorczy przygotowany”. Kliknięcie
„Uruchom” jest potwierdzeniem Gotowości: Centrum nie zgaduje jej z pliku ani
nie blokuje startu. Proces prowadzi rdzeń Uruchomienia procesu z tym samym
opisem procesu co CLI (``cli.CENTRUM_PROCESS``), więc liczby, linie i rekord
metryk są te same.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Final

from rozliczenia import cli, collective_file
from rozliczenia.centrum import contract
from rozliczenia.centrum.configuration import ConfigurationFiles
from rozliczenia.centrum.period_board import PeriodFolder, read_board
from rozliczenia.centrum.run_origins import CentrumRuns
from rozliczenia.centrum.runs import PreparedRun, run_result
from rozliczenia.centrum.settings import SettingsStore
from rozliczenia.domain import Issue, SettlementSummary
from rozliczenia.process_run import Interlocutor, run_process
from rozliczenia.settlement_messages import issue_message
from rozliczenia.settlement_period import last_complete_period, parse_period_token
from rozliczenia.telemetry import MetricsStore

_PROCESS: Final = cli.CENTRUM_PROCESS
TITLE: Final = "Przebieg rozliczeń"
_ELIGIBLE: Final[contract.PeriodStatus] = "collective_file_prepared"


class SettlementEntry:
    """Przebieg rozliczeń jako proces uruchamiany z Centrum (``runs.ProcessEntry``)."""

    key: Final[contract.ProcessKey] = "settlement"

    def __init__(
        self,
        store: SettingsStore,
        configuration: ConfigurationFiles,
        metrics_path: Path,
        centrum_runs: CentrumRuns,
        today: Callable[[], date],
    ) -> None:
        self._store = store
        self._configuration = configuration
        self._metrics_path = metrics_path
        self._centrum_runs = centrum_runs
        self._today = today

    def setup(self) -> contract.ProcessSetup:
        board = read_board(self._store.load().periods_directory, self._today())
        rows = [row for row in board.periods if row.status == _ELIGIBLE] if board.state == "ready" else []
        preselected = next(
            (row.token for row in rows if row.last_complete),
            rows[0].token if rows else last_complete_period(self._today()).token,
        )
        return contract.ProcessSetup(
            process=self.key,
            title=TITLE,
            creates="Rozliczenia pracowników",
            reminder="Zapisz i zamknij Plik zbiorczy w Excelu",
            periods=[_choice(row) for row in rows],
            preselected_period=preselected,
            blocker=_blocker(board, rows),
        )

    def prepare(self, request: contract.RunRequest) -> PreparedRun:
        periods_directory = self._store.load().periods_directory
        if periods_directory is None:
            raise contract.Refusal(409, "Najpierw wskaż folder okresów.")
        try:
            period = parse_period_token(request.period)
        except ValueError:
            raise contract.Refusal(404, "Nie ma takiego okresu.") from None
        source = PeriodFolder.of(periods_directory, period).collective_file
        inputs = cli.SettlementInputs(
            source,
            dry_run=request.dry_run,
            config_path=self._configuration.worker_config,
            worker_template_path=self._configuration.worker_template,
        )
        metrics_path = self._metrics_path
        centrum_runs = self._centrum_runs

        def conduct(interlocutor: Interlocutor) -> contract.RunOutcome:
            since = datetime.now(timezone.utc)
            outcome = run_process(_PROCESS, inputs, interlocutor, metrics_path=metrics_path)
            centrum_runs.remember(
                "settlement", MetricsStore(metrics_path, _PROCESS.counter_names), since, datetime.now(timezone.utc)
            )
            summary = outcome.summary
            return run_result(
                outcome,
                dry_run=inputs.dry_run,
                done="Rozliczenia pracowników gotowe",
                summary=None if summary is None else _summary(summary),
                warnings=[] if summary is None else [_issue(issue, source) for issue in summary.issues],
            )

        return PreparedRun(self.key, TITLE, period.token, request.dry_run, conduct)


def _choice(row: contract.PeriodRow) -> contract.PeriodChoice:
    return contract.PeriodChoice(
        token=row.token,
        tuesday=row.tuesday,
        monday=row.monday,
        status_label=row.status_label,
        last_complete=row.last_complete,
        collective_file=collective_file.path_for_period(Path(row.token), row.token).name,
    )


def _blocker(board: contract.PeriodBoard, rows: list[contract.PeriodRow]) -> str | None:
    if board.state == "not_set":
        return "Najpierw wskaż folder okresów."
    if board.state == "missing":
        return f"Nie ma już folderu okresów {board.name}. Wskaż go ponownie."
    if not rows:
        return "Żaden okres nie ma Statusu „Plik zbiorczy przygotowany”. Najpierw przygotuj plik zbiorczy."
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


def _issue(issue: Issue, source: Path) -> contract.RunMessage:
    message = issue_message(issue, source)
    return contract.RunMessage(what=message.what, where=message.where, action=message.action)

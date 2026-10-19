"""CLI Przebiegu rozliczeń (uruchamiane przez ``run.py``).

Opisuje proces dla Uruchomienia procesu (``process_run``): wejście procesu
(``SettlementInputs``), argumenty i wybór Pliku zbiorczego w terminalu,
wywołanie silnika i fakty zakończenia, a dla terminala linie statusu i
podsumowania. Inny rozmówca niż terminal podaje gotowe ``SettlementInputs``
do ``run_process(PROCESS, ...)`` razem z własnym widokiem podsumowania.
Terminal pokazuje zatrzymanie jedną linią (``Message.terminal_line``); ten sam
Komunikat w trzech częściach dostaje każdy rozmówca w ``Stop.message``.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass, field
from datetime import date
from functools import partial
from pathlib import Path
from typing import TextIO

from . import engine, settlement_messages
from . import settings as settings_file
from .decision import Conversation
from .domain import ProgressObserver, SettlementSummary
from .engine import default_worker_template_path
from .message import StopError
from .period_folder import (
    COLLECTIVE_FILE_PATTERN,
    PeriodFolder,
    PeriodFolderError,
    PeriodFolderLookupError,
    locate_period_folder,
)
from .process_run import Finished, Process, Stop, TerminalSummary, TerminalView, run
from .progress_presentation import format_counter_line
from .telemetry import COUNTER_NAMES, UNKNOWN_PERIOD
from .terminal_conversation import TerminalConversation, ask_period
from .worker_config import default_config_path

def default_metrics_path() -> Path:
    return Path(__file__).resolve().parents[2] / ".rozliczenia-metrics.jsonl"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Rozdziela plik zbiorczy na szablony pracowników.")
    parser.add_argument("--source", type=Path, help=f"Ścieżka do pliku {COLLECTIVE_FILE_PATTERN}")
    parser.add_argument("--config", type=Path, default=default_config_path())
    parser.add_argument(
        "--worker-template",
        type=Path,
        default=default_worker_template_path(),
        help="Ścieżka do wspólnego Wzorca rozliczenia pracownika używanego do tworzenia skoroszytów pracowników.",
    )
    parser.add_argument(
        "--metrics",
        type=Path,
        default=default_metrics_path(),
        help="Lokalny plik historii metryk JSONL.",
    )
    parser.add_argument("--dry-run", action="store_true", help="Sprawdź plan bez zapisywania plików.")
    return parser


def _period_label(source: Path) -> str:
    try:
        return PeriodFolder.from_collective_file(source.expanduser().resolve()).period.token
    except PeriodFolderError:
        return UNKNOWN_PERIOD


@dataclass(frozen=True)
class SettlementInputs:
    """Wejście procesu Przebiegu rozliczeń, niezależne od argumentów CLI.

    Okres wynika z nazwy Pliku zbiorczego (``nieznany``, gdy się nie da).
    Konfiguracja wykonawców i wzorzec mają te same domyślne ścieżki co CLI.
    """

    source: Path
    dry_run: bool = False
    config_path: Path = field(default_factory=default_config_path)
    worker_template_path: Path = field(default_factory=default_worker_template_path)

    @property
    def period(self) -> str:
        return _period_label(self.source)


def _source_from_settings(periods_directory: Path, today: date, conversation: TerminalConversation) -> Path:
    """Plik zbiorczy okresu, o który terminal pyta z propozycją, w Folderze okresu z folderu okresów taty."""

    period = ask_period(
        today,
        conversation,
        not_entered=settlement_messages.period_not_entered(),
        invalid_token=settlement_messages.invalid_period_token,
    )
    try:
        return locate_period_folder(periods_directory, period).collective_file
    except PeriodFolderLookupError as exc:
        raise StopError(settlement_messages.period_folder_lookup_problem(exc)) from exc


def _gather(today: date | None, args: argparse.Namespace, conversation: TerminalConversation) -> SettlementInputs:
    """``--source``, potem okres z pytania w folderze okresów z Ustawień taty, a bez nich okno wyboru pliku."""

    periods_directory = None if args.source else settings_file.load_settings().existing_periods_directory
    if periods_directory is not None:
        source: Path | None = _source_from_settings(periods_directory, today or date.today(), conversation)
    else:
        source = args.source or conversation.choose_file(
            "Wybierz plik zbiorczy rozliczenia",
            [("Plik zbiorczy Excel", COLLECTIVE_FILE_PATTERN), ("Excel", "*.xlsx")],
        )
    if source is None:
        raise StopError(settlement_messages.collective_file_not_selected())
    return SettlementInputs(
        source, dry_run=args.dry_run, config_path=args.config, worker_template_path=args.worker_template
    )


def _execute(
    inputs: SettlementInputs, observer: ProgressObserver, _conversation: Conversation
) -> SettlementSummary:
    return engine.run_settlements(
        inputs.source,
        inputs.config_path,
        dry_run=inputs.dry_run,
        worker_template_path=inputs.worker_template_path,
        observer=observer,
    )


def _summary_lines(summary: SettlementSummary, *, dry_run: bool) -> list[str]:
    counters = {
        "written": summary.written_count,
        "empty": summary.empty_count,
        "planned": summary.planned_count,
    }
    lines = [
        f"Liczniki: {format_counter_line(counters)}",
        f"Wiersze danych: {summary.total_rows}",
        f"Zapisane szablony: {summary.written_count}",
        f"Puste szablony: {summary.empty_count}",
    ]
    if summary.planned_count:
        lines.append(f"Planowane szablony: {summary.planned_count}")
    if dry_run:
        lines.extend(
            [
                f"Okres rozliczeniowy: {summary.period}",
                f"Folder rozliczeń pracowników: {summary.target_directory}",
                "Plan plików:",
            ]
        )
        for result in summary.results:
            detail = f"Wiersze do uzupełnienia: {result.rows}"
            if not result.rows:
                detail += " | Pusty skoroszyt"
            lines.append(f"- {result.output_file.name} | {detail}")
        lines.append("DRY-RUN: Nic nie zapisano")
    lines.append(f"Problemy: {len(summary.issues)}")
    lines.extend(f"- {issue.message}" for issue in summary.issues)
    return lines


def _finished(summary: SettlementSummary) -> Finished:
    return Finished(
        result="OK" if summary.ok else "WYMAGA_SPRAWDZENIA",
        counters={
            "templates_total": summary.template_count,
            "templates_completed": summary.template_count,
            "rows": summary.total_rows,
            "written": summary.written_count,
            "empty": summary.empty_count,
            "planned": summary.planned_count,
            # Licznik ze schematu metryk sprzed usunięcia pominiętych szablonów; zawsze 0,
            # żeby stare i nowe rekordy miały te same klucze.
            "skipped": 0,
            "issues": len(summary.issues),
        },
        phase_durations_ms=summary.phase_durations_ms,
    )


def _terminal_summary(inputs: SettlementInputs, summary: SettlementSummary) -> TerminalSummary:
    return TerminalSummary(
        status_lines=[
            f"Status semantyczny: {'OK' if summary.ok else 'OSTRZEŻENIE'}",
            f"Status końcowy: {'OK' if summary.ok else 'Wymaga sprawdzenia'}",
        ],
        summary_lines=_summary_lines(summary, dry_run=inputs.dry_run),
    )


def _stop_lines(stop: Stop) -> list[str]:
    """Zatrzymanie jedną linią po „Nie wykonano: ”; niepokazane podsumowanie albo plan bez tego przedrostka."""

    lines = stop.message.terminal_lines
    if stop.kind != "after_engine":
        lines = [f"Nie wykonano: {line}" for line in lines]
    return ["Status semantyczny: BŁĄD", *lines]


# Opis Przebiegu rozliczeń dla rdzenia Uruchomienia procesu, wspólny dla każdego rozmówcy.
# ``title`` to nagłówek podglądu w terminalu („Rozliczenia | okres | tryb”), bez zmian od pierwszej wersji.
def _process(today: date | None) -> Process[SettlementInputs, SettlementSummary]:
    return Process(
        title="Rozliczenia",
        shows_templates=True,
        parser=build_parser,
        counter_names=COUNTER_NAMES,
        metrics_failure_tail="proces rozliczeń zakończył się niezależnie.",
        gather=partial(_gather, today),
        execute=_execute,
        finished=_finished,
        unexpected_failure=settlement_messages.unexpected_failure(),
        plan_not_shown=settlement_messages.plan_not_shown(),
        summary_not_shown=settlement_messages.summary_not_shown(),
    )


PROCESS = _process(None)
# Jak terminal pokazuje zakończenie Przebiegu rozliczeń; inny rozmówca renderuje ``Outcome`` po swojemu.
_TERMINAL: TerminalView[SettlementInputs, SettlementSummary] = TerminalView(
    summary=_terminal_summary, stop=_stop_lines
)


def main(
    argv: list[str] | None = None,
    *,
    output: TextIO | None = None,
    input_stream: TextIO | None = None,
    metrics_path: Path | None = None,
    today: date | None = None,
) -> int:
    """Uruchamia Przebieg rozliczeń; ``0`` OK, ``2`` Wymaga sprawdzenia, ``1`` błąd."""

    return run(
        _process(today), _TERMINAL, argv, output=output, input_stream=input_stream, metrics_path=metrics_path
    )


if __name__ == "__main__":
    raise SystemExit(main())

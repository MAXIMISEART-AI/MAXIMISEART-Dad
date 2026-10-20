"""CLI Przebiegu rozliczeń (uruchamiane przez ``run.py``).

Argumenty, wybór Pliku zbiorczego w terminalu oraz linie statusu i
podsumowania (``CliEntry``). Opis procesu wspólny z Centrum rozliczeń jest w
``settlement_process``. Terminal pokazuje zatrzymanie jedną linią (``Message.terminal_line``); ten sam
Komunikat w trzech częściach dostaje każdy rozmówca w ``Stop.message``.
"""

from __future__ import annotations

import argparse
from datetime import date
from functools import partial
from pathlib import Path
from typing import TextIO

from . import settlement_messages
from . import settings as settings_file
from .domain import SettlementSummary
from .engine import default_worker_template_path
from .message import StopError
from .period_folder import (
    COLLECTIVE_FILE_PATTERN,
    PeriodFolderLookupError,
    locate_period_folder,
)
from .process_run import CliEntry, Stop, TerminalSummary, run
from .progress_presentation import format_counter_line
from .settlement_process import PROCESS, SettlementInputs, default_metrics_path
from .terminal_conversation import TerminalConversation, ask_period
from .worker_config import default_config_path


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


def _entry(today: date | None) -> CliEntry[SettlementInputs, SettlementSummary]:
    return CliEntry(parser=build_parser, gather=partial(_gather, today), summary=_terminal_summary, stop=_stop_lines)


def main(
    argv: list[str] | None = None,
    *,
    output: TextIO | None = None,
    input_stream: TextIO | None = None,
    today: date | None = None,
) -> int:
    """Uruchamia Przebieg rozliczeń; ``0`` OK, ``2`` Wymaga sprawdzenia, ``1`` błąd."""

    return run(PROCESS, _entry(today), argv, output=output, input_stream=input_stream)


if __name__ == "__main__":
    raise SystemExit(main())

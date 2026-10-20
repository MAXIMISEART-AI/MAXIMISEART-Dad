"""CLI Przygotowania pliku zbiorczego (osobne wejście, uruchamiane przez ``run_preparation.py``).

Argumenty, wybór Rejestru zleceń, folderu okresów i okresu w terminalu oraz
linie statusu i podsumowania (``CliEntry``). Opis procesu wspólny z Centrum
rozliczeń jest w ``preparation_process``.
"""

from __future__ import annotations

import argparse
from datetime import date
from functools import partial
from pathlib import Path
from typing import TextIO

from . import settings as settings_file
from . import preparation_messages as messages
from .collective_preparation import (
    PreparationSummary,
    default_collective_template_path,
    default_internal_template_path,
)
from .message import Message, StopError
from .preparation_process import PROCESS, PreparationInputs, default_metrics_path
from .process_run import CliEntry, Stop, TerminalSummary, run
from .terminal_conversation import TerminalConversation, ask_period
from .worker_config import default_config_path


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Tworzy Rozliczenie wewnętrzne i Plik zbiorczy okresu z Rejestru zleceń."
    )
    parser.add_argument("--register", type=Path, help="Plik Rejestru zleceń; bez niego okno wyboru pliku.")
    parser.add_argument(
        "--periods-directory",
        type=Path,
        help="Folder okresów z Folderami okresu; bez niego folder z Ustawień Centrum albo okno wyboru folderu.",
    )
    parser.add_argument(
        "--period",
        help="Token okresu, np. 08_14_09_2026; bez niego pytanie z propozycją ostatniego pełnego okresu.",
    )
    parser.add_argument("--config", type=Path, default=default_config_path(), help="Konfiguracja wykonawców.")
    parser.add_argument(
        "--internal-template",
        type=Path,
        default=default_internal_template_path(),
        help="Wzorzec rozliczenia wewnętrznego.",
    )
    parser.add_argument(
        "--collective-template",
        type=Path,
        default=default_collective_template_path(),
        help="Wzorzec pliku zbiorczego.",
    )
    parser.add_argument(
        "--metrics",
        type=Path,
        default=default_metrics_path(),
        help="Lokalny plik historii metryk JSONL Przygotowania pliku zbiorczego.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Sprawdź wszystko i pokaż plan bez tworzenia plików ani folderów.",
    )
    return parser


def _message_lines(message: Message) -> list[str]:
    first, *rest = message.text.splitlines()
    return [f"- {first}", *(f"  {line}" for line in rest)]


def _summary_lines(summary: PreparationSummary, *, dry_run: bool) -> list[str]:
    lines = [
        f"Okres: {summary.period}",
        f"Zlecenia okresu: {summary.period_order_count}",
        f"Zlecenia skuteczne: {summary.successful_order_count}",
        f"Pominięte puste wiersze: {summary.skipped_empty_rows}",
        f"{messages.ORDERS_PER_DAY}:",
        *(f"- {label}: {count}" for label, count in summary.labeled_orders_per_day()),
        f"Ostrzeżenia: {len(summary.warnings)}",
    ]
    for warning in summary.warnings:
        lines.extend(_message_lines(warning))
    lines.append(f"Rozliczenie wewnętrzne: {summary.internal_settlement_file.name}")
    lines.append(f"Plik zbiorczy: {summary.collective_file.name}")
    if dry_run:
        lines.append("DRY-RUN: Nic nie zapisano")
    return lines


def _gather(today: date | None, args: argparse.Namespace, conversation: TerminalConversation) -> PreparationInputs:
    """Argumenty, potem Ustawienia taty z Centrum rozliczeń, a okno wyboru tylko dla tego, czego nie wskazano."""

    settings = settings_file.load_settings()
    register_path = (
        args.register
        or settings.existing_register
        or conversation.choose_file(
            "Wybierz plik Rejestru zleceń", [("Rejestr zleceń Excel", "ZLECENIA*.xlsx"), ("Excel", "*.xlsx")]
        )
    )
    if register_path is None:
        raise StopError(messages.register_not_selected())
    periods_directory = (
        args.periods_directory
        or settings.existing_periods_directory
        or conversation.choose_folder("Wybierz folder okresów (np. Załączniki albo INEA)")
    )
    if periods_directory is None:
        raise StopError(messages.periods_directory_not_selected())
    period = args.period or ask_period(
        today or date.today(),
        conversation,
        not_entered=messages.period_not_entered(),
        invalid_token=messages.invalid_period_token,
    ).token
    return PreparationInputs(
        register_path,
        periods_directory,
        period,
        dry_run=args.dry_run,
        config_path=args.config,
        internal_template_path=args.internal_template,
        collective_template_path=args.collective_template,
    )


def _terminal_summary(inputs: PreparationInputs, summary: PreparationSummary) -> TerminalSummary:
    return TerminalSummary(
        status_lines=["Status końcowy: OK"], summary_lines=_summary_lines(summary, dry_run=inputs.dry_run)
    )


def _stop_lines(stop: Stop) -> list[str]:
    """``ZATRZYMANO``, gdy nie powstał żaden plik z komunikatem zatrzymania; inaczej ``BŁĄD``."""

    return [f"Status końcowy: {'ZATRZYMANO' if stop.kind == 'stop' else 'BŁĄD'}", *stop.message.terminal_lines]


def _entry(today: date | None) -> CliEntry[PreparationInputs, PreparationSummary]:
    return CliEntry(parser=build_parser, gather=partial(_gather, today), summary=_terminal_summary, stop=_stop_lines)


def main(
    argv: list[str] | None = None,
    *,
    output: TextIO | None = None,
    input_stream: TextIO | None = None,
    today: date | None = None,
) -> int:
    """Uruchamia Przygotowanie pliku zbiorczego; ``0`` sukces, ``1`` zatrzymanie, błąd albo odmowa."""

    return run(PROCESS, _entry(today), argv, output=output, input_stream=input_stream)


if __name__ == "__main__":
    raise SystemExit(main())

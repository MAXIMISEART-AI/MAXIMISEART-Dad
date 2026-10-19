"""CLI Przygotowania pliku zbiorczego (osobne wejście, uruchamiane przez ``run_preparation.py``).

Opisuje proces dla Uruchomienia procesu (``process_run``): wejście procesu
(``PreparationInputs``), argumenty i wybór Rejestru zleceń, folderu okresów i
okresu w terminalu, wywołanie silnika i fakty zakończenia, a dla terminala
linie statusu i podsumowania. Inny rozmówca niż terminal podaje gotowe
``PreparationInputs`` do ``run_process(PROCESS, ...)`` razem z własnym
widokiem podsumowania.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass, field
from datetime import date
from functools import partial
from pathlib import Path
from typing import TextIO

from . import collective_preparation
from . import settings as settings_file
from . import preparation_messages as messages
from .collective_preparation import (
    PreparationSummary,
    default_collective_template_path,
    default_internal_template_path,
)
from .decision import Conversation
from .domain import ProgressObserver
from .message import Message, StopError
from .process_run import Finished, Process, Stop, TerminalSummary, TerminalView, run
from .terminal_conversation import TerminalConversation, ask_period
from .worker_config import default_config_path

_TITLE = "Przygotowanie pliku zbiorczego"
# Liczniki historii metryk Przygotowania pliku zbiorczego (inne niż Przebiegu rozliczeń).
_COUNTERS = frozenset({"period_orders", "successful_orders", "skipped_empty_rows", "warnings"})


def default_metrics_path() -> Path:
    """Osobna lokalna historia metryk, obok historii Przebiegu rozliczeń."""

    return Path(__file__).resolve().parents[2] / ".przygotowanie-pliku-zbiorczego-metrics.jsonl"


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


@dataclass(frozen=True)
class PreparationInputs:
    """Wejście procesu Przygotowania pliku zbiorczego, niezależne od argumentów CLI.

    Konfiguracja wykonawców i oba wzorce mają te same domyślne ścieżki co CLI.
    """

    register_path: Path
    periods_directory: Path
    period: str
    dry_run: bool = False
    config_path: Path = field(default_factory=default_config_path)
    internal_template_path: Path = field(default_factory=default_internal_template_path)
    collective_template_path: Path = field(default_factory=default_collective_template_path)


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


def _execute(inputs: PreparationInputs, observer: ProgressObserver, conversation: Conversation) -> PreparationSummary:
    return collective_preparation.prepare_collective_file(
        inputs.register_path,
        inputs.periods_directory,
        inputs.period,
        inputs.config_path,
        internal_template_path=inputs.internal_template_path,
        collective_template_path=inputs.collective_template_path,
        dry_run=inputs.dry_run,
        observer=observer,
        conversation=conversation,
    )


def _finished(summary: PreparationSummary) -> Finished:
    return Finished(
        result="OK",
        counters={
            "period_orders": summary.period_order_count,
            "successful_orders": summary.successful_order_count,
            "skipped_empty_rows": summary.skipped_empty_rows,
            "warnings": len(summary.warnings),
        },
        phase_durations_ms=summary.phase_durations_ms,
    )


def _terminal_summary(inputs: PreparationInputs, summary: PreparationSummary) -> TerminalSummary:
    return TerminalSummary(
        status_lines=["Status końcowy: OK"], summary_lines=_summary_lines(summary, dry_run=inputs.dry_run)
    )


def _stop_lines(stop: Stop) -> list[str]:
    """``ZATRZYMANO``, gdy nie powstał żaden plik z komunikatem zatrzymania; inaczej ``BŁĄD``."""

    return [f"Status końcowy: {'ZATRZYMANO' if stop.kind == 'stop' else 'BŁĄD'}", *stop.message.terminal_lines]


def _process(today: date | None) -> Process[PreparationInputs, PreparationSummary]:
    return Process(
        title=_TITLE,
        shows_templates=False,
        parser=build_parser,
        counter_names=_COUNTERS,
        metrics_failure_tail="Przygotowanie pliku zbiorczego zakończyło się niezależnie.",
        gather=partial(_gather, today),
        execute=_execute,
        finished=_finished,
        unexpected_failure=messages.unexpected_failure(),
        plan_not_shown=messages.plan_not_shown(),
        summary_not_shown=messages.summary_not_shown(),
    )


# Opis Przygotowania pliku zbiorczego dla rdzenia Uruchomienia procesu, wspólny dla każdego rozmówcy.
PROCESS = _process(None)
# Jak terminal pokazuje zakończenie Przygotowania pliku zbiorczego.
_TERMINAL: TerminalView[PreparationInputs, PreparationSummary] = TerminalView(
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
    """Uruchamia Przygotowanie pliku zbiorczego; ``0`` sukces, ``1`` zatrzymanie, błąd albo odmowa."""

    return run(
        _process(today), _TERMINAL, argv, output=output, input_stream=input_stream, metrics_path=metrics_path
    )


if __name__ == "__main__":
    raise SystemExit(main())

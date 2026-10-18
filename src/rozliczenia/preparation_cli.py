"""CLI Przygotowania pliku zbiorczego (osobne wejście, uruchamiane przez ``run_preparation.py``).

Opisuje proces dla Uruchomienia procesu (``process_run``): wejście procesu
(``PreparationInputs``), argumenty i wybór Rejestru zleceń, folderu okresów i
okresu w terminalu, wywołanie silnika oraz linie statusu i podsumowania.
Inny rozmówca niż terminal podaje gotowe ``PreparationInputs`` do
``run_process(PROCESS, ...)``.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass, field
from datetime import date, timedelta
from functools import partial
from pathlib import Path
from typing import TextIO

from . import collective_preparation
from . import preparation_messages as messages
from .collective_preparation import (
    PreparationError,
    PreparationSummary,
    default_collective_template_path,
    default_internal_template_path,
)
from .domain import ProgressObserver
from .engine import default_config_path
from .preparation_messages import PreparationMessage, plan_not_shown, summary_not_shown, unexpected_failure
from .process_run import Conversation, Finished, Process, Stop, run
from .settlement_period import SettlementPeriod, last_complete_period, parse_period_token
from .terminal_conversation import TerminalConversation

_TITLE = "Przygotowanie pliku zbiorczego"
# Liczniki historii metryk Przygotowania pliku zbiorczego (inne niż Przebiegu rozliczeń).
_COUNTERS = frozenset({"period_orders", "successful_orders", "skipped_empty_rows", "warnings"})
_WEEKDAY_LABELS = ("pon", "wt", "śr", "czw", "pt", "sob", "niedz")


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
        help="Folder okresów, w którym powstaje Folder okresu; bez niego okno wyboru folderu.",
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


def _orders_per_day_lines(orders_per_day: dict[date, int]) -> list[str]:
    """Linie ``- wt 08.09.2026: 1`` dla każdego dnia okresu, w kolejności dat."""

    return [
        f"- {_WEEKDAY_LABELS[day.weekday()]} {day:%d.%m.%Y}: {count}"
        for day, count in orders_per_day.items()
    ]


def _message_lines(message: PreparationMessage) -> list[str]:
    first, *rest = message.text.splitlines()
    return [f"- {first}", *(f"  {line}" for line in rest)]


def _summary_lines(summary: PreparationSummary, *, dry_run: bool) -> list[str]:
    lines = [
        f"Okres: {summary.period}",
        f"Zlecenia okresu: {summary.period_order_count}",
        f"Zlecenia skuteczne: {summary.successful_order_count}",
        f"Pominięte puste wiersze: {summary.skipped_empty_rows}",
        "Zlecenia na dzień:",
        *_orders_per_day_lines(summary.orders_per_day),
        f"Ostrzeżenia: {len(summary.warnings)}",
    ]
    for warning in summary.warnings:
        lines.extend(_message_lines(warning))
    lines.append(f"Rozliczenie wewnętrzne: {summary.internal_settlement_file.name}")
    lines.append(f"Plik zbiorczy: {summary.collective_file.name}")
    if dry_run:
        lines.append("DRY-RUN: Nic nie zapisano")
    return lines


def _period_label(period: SettlementPeriod) -> str:
    return f"{period.token} (wtorek {period.tuesday:%d.%m.%Y} – poniedziałek {period.monday:%d.%m.%Y})"


def _ask_period(today: date, conversation: TerminalConversation) -> str:
    """Proponuje ostatni pełny okres; Enter go potwierdza, inny poprawny token go zastępuje."""

    proposed = last_complete_period(today)
    previous = SettlementPeriod(proposed.tuesday - timedelta(days=7))
    conversation.say(
        f"Proponowany okres: {_period_label(proposed)}",
        f"Enter potwierdza ten okres. Inny okres wpisz jak w nazwie folderu, np. {previous.token}.",
    )
    while True:
        answer = conversation.ask("Okres: ")
        if answer is None:
            raise messages.period_not_entered()
        if not answer:
            return proposed.token
        try:
            return parse_period_token(answer).token
        except ValueError:
            conversation.say(*messages.invalid_period_token(answer).message.text.splitlines())


class _IncompletePeriodQuestion:
    """Decyzja po Planowaniu: przy niepełnym okresie pyta tatę o kontynuację.

    Silnik wywołuje ją z planem między Planowaniem a Zapisywaniem. Decyzję
    podejmuje tata przez rozmówcę (``Conversation.confirm``). Odmowa to
    ``PreparationError``.
    """

    def __init__(self, conversation: Conversation) -> None:
        self._conversation = conversation

    def __call__(self, plan: PreparationSummary) -> None:
        warning = next((item for item in plan.warnings if item.code == messages.INCOMPLETE_PERIOD), None)
        if warning is None:
            return
        lines = [
            "Ostrzeżenie: niepełny okres",
            *warning.text.splitlines(),
            "Zlecenia na dzień:",
            *_orders_per_day_lines(plan.orders_per_day),
        ]
        if not self._conversation.confirm(lines, "Kontynuować mimo niepełnego okresu?"):
            raise messages.incomplete_period_refused(plan.period)


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
    register_path = args.register or conversation.choose_file(
        "Wybierz plik Rejestru zleceń", [("Rejestr zleceń Excel", "ZLECENIA*.xlsx"), ("Excel", "*.xlsx")]
    )
    if register_path is None:
        raise messages.register_not_selected()
    periods_directory = args.periods_directory or conversation.choose_folder("Wybierz folder okresów (np. INEA)")
    if periods_directory is None:
        raise messages.periods_directory_not_selected()
    period = args.period or _ask_period(today or date.today(), conversation)
    return PreparationInputs(
        register_path,
        periods_directory,
        period,
        dry_run=args.dry_run,
        config_path=args.config,
        internal_template_path=args.internal_template,
        collective_template_path=args.collective_template,
    )


def _execute(
    inputs: PreparationInputs, observer: ProgressObserver, conversation: Conversation
) -> PreparationSummary:
    return collective_preparation.prepare_collective_file(
        inputs.register_path,
        inputs.periods_directory,
        inputs.period,
        inputs.config_path,
        internal_template_path=inputs.internal_template_path,
        collective_template_path=inputs.collective_template_path,
        dry_run=inputs.dry_run,
        observer=observer,
        confirm_plan=_IncompletePeriodQuestion(conversation),
    )


def _finished(inputs: PreparationInputs, summary: PreparationSummary) -> Finished:
    return Finished(
        status_lines=["Status końcowy: OK"],
        summary_lines=_summary_lines(summary, dry_run=inputs.dry_run),
        result="OK",
        counters={
            "period_orders": summary.period_order_count,
            "successful_orders": summary.successful_order_count,
            "skipped_empty_rows": summary.skipped_empty_rows,
            "warnings": len(summary.warnings),
        },
        phase_durations_ms=summary.phase_durations_ms,
    )


def _stop_lines(error: Exception) -> list[str]:
    """Linie Co się stało / Gdzie / Co zrobić z ``PreparationError``."""

    return str(error).splitlines()


def _stopped(stop: Stop) -> list[str]:
    """``ZATRZYMANO``, gdy nie powstał żaden plik z komunikatem zatrzymania; inaczej ``BŁĄD``."""

    if stop.kind == "stop":
        return ["Status końcowy: ZATRZYMANO", *stop.lines]
    if stop.kind == "unexpected":
        message = unexpected_failure()
    else:
        message = plan_not_shown() if stop.dry_run else summary_not_shown()
    return ["Status końcowy: BŁĄD", *message.text.splitlines()]


def _process(today: date | None) -> Process[PreparationInputs, PreparationSummary]:
    return Process(
        title=_TITLE,
        shows_templates=False,
        parser=build_parser,
        counter_names=_COUNTERS,
        metrics_failure_tail="Przygotowanie pliku zbiorczego zakończyło się niezależnie.",
        stop_type=PreparationError,
        stop_lines=_stop_lines,
        gather=partial(_gather, today),
        execute=_execute,
        finished=_finished,
        stopped=_stopped,
    )


# Opis Przygotowania pliku zbiorczego dla rdzenia Uruchomienia procesu.
PROCESS = _process(None)


def main(
    argv: list[str] | None = None,
    *,
    output: TextIO | None = None,
    input_stream: TextIO | None = None,
    metrics_path: Path | None = None,
    today: date | None = None,
) -> int:
    """Uruchamia Przygotowanie pliku zbiorczego; ``0`` sukces, ``1`` zatrzymanie, błąd albo odmowa."""

    return run(_process(today), argv, output=output, input_stream=input_stream, metrics_path=metrics_path)


if __name__ == "__main__":
    raise SystemExit(main())

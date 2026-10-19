"""CLI Przebiegu rozliczeń (uruchamiane przez ``run.py``).

Opisuje proces dla Uruchomienia procesu (``process_run``): wejście procesu
(``SettlementInputs``), argumenty i wybór Pliku zbiorczego w terminalu,
wywołanie silnika oraz linie statusu i podsumowania. Inny rozmówca niż
terminal podaje gotowe ``SettlementInputs`` do ``run_process(PROCESS, ...)``.
Terminal pokazuje zatrzymanie jedną linią (``Message.terminal_line``); ten sam
Komunikat w trzech częściach dostaje każdy rozmówca w ``Stop.message``.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass, field
from pathlib import Path
from typing import TextIO

from . import collective_file, engine, settlement_messages
from .domain import ProgressObserver, SettlementSummary
from .message import StopError
from .engine import (
    default_config_path,
    default_worker_template_path,
    period_from_source,
)
from .process_run import Conversation, Finished, Process, Stop, run
from .progress_presentation import format_counter_line
from .telemetry import COUNTER_NAMES, UNKNOWN_PERIOD
from .terminal_conversation import TerminalConversation

_UNEXPECTED_FAILURE = (
    "Wystąpił nieoczekiwany błąd; folder rozliczeń pracowników nie został opublikowany. "
    "Uruchom ponownie; jeśli błąd wraca, przekaż to osobie utrzymującej narzędzie."
)
_SUMMARY_NOT_SHOWN = (
    "Rozliczenia pracowników powstały, ale nie udało się pokazać podsumowania. "
    "Sprawdź Folder okresu i przekaż ten komunikat osobie utrzymującej narzędzie."
)
_PLAN_NOT_SHOWN = (
    "Nie udało się pokazać planu. DRY-RUN: Nic nie zapisano. "
    "Przekaż ten komunikat osobie utrzymującej narzędzie."
)


def default_metrics_path() -> Path:
    return Path(__file__).resolve().parents[2] / ".rozliczenia-metrics.jsonl"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Rozdziela plik zbiorczy na szablony pracowników.")
    parser.add_argument("--source", type=Path, help=f"Ścieżka do pliku {collective_file.NAME_GLOB}")
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
        return period_from_source(source.expanduser().resolve())
    except StopError:
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


def _gather(args: argparse.Namespace, conversation: TerminalConversation) -> SettlementInputs:
    source = args.source or conversation.choose_file(
        "Wybierz plik zbiorczy rozliczenia",
        [("Plik zbiorczy Excel", collective_file.NAME_GLOB), ("Excel", "*.xlsx")],
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
        "skipped": summary.skipped_count,
    }
    lines = [
        f"Liczniki: {format_counter_line(counters)}",
        f"Wiersze danych: {summary.total_rows}",
        f"Zapisane szablony: {summary.written_count}",
        f"Puste szablony: {summary.empty_count}",
        f"Pominięte szablony: {summary.skipped_count}",
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


def _finished(inputs: SettlementInputs, summary: SettlementSummary) -> Finished:
    return Finished(
        status_lines=[
            f"Status semantyczny: {'OK' if summary.ok else 'OSTRZEŻENIE'}",
            f"Status końcowy: {'OK' if summary.ok else 'Wymaga sprawdzenia'}",
        ],
        summary_lines=_summary_lines(summary, dry_run=inputs.dry_run),
        result="OK" if summary.ok else "WYMAGA_SPRAWDZENIA",
        counters={
            "templates_total": summary.template_count,
            "templates_completed": summary.template_count,
            "rows": summary.total_rows,
            "written": summary.written_count,
            "empty": summary.empty_count,
            "planned": summary.planned_count,
            "skipped": summary.skipped_count,
            "issues": len(summary.issues),
        },
        phase_durations_ms=summary.phase_durations_ms,
    )


def _stopped(stop: Stop) -> list[str]:
    if stop.kind == "after_engine":
        return ["Status semantyczny: BŁĄD", _PLAN_NOT_SHOWN if stop.dry_run else _SUMMARY_NOT_SHOWN]
    lines = stop.lines if stop.kind == "stop" else (_UNEXPECTED_FAILURE,)
    return ["Status semantyczny: BŁĄD", *(f"Nie wykonano: {line}" for line in lines)]


# Opis Przebiegu rozliczeń dla rdzenia Uruchomienia procesu, wspólny dla każdego rozmówcy.
# ``title`` to nagłówek podglądu w terminalu („Rozliczenia | okres | tryb”), bez zmian od pierwszej wersji.
PROCESS: Process[SettlementInputs, SettlementSummary] = Process(
    title="Rozliczenia",
    shows_templates=True,
    parser=build_parser,
    counter_names=COUNTER_NAMES,
    metrics_failure_tail="proces rozliczeń zakończył się niezależnie.",
    gather=_gather,
    execute=_execute,
    finished=_finished,
    stopped=_stopped,
)


def main(
    argv: list[str] | None = None,
    *,
    output: TextIO | None = None,
    metrics_path: Path | None = None,
) -> int:
    """Uruchamia Przebieg rozliczeń; ``0`` OK, ``2`` Wymaga sprawdzenia, ``1`` błąd."""

    return run(PROCESS, argv, output=output, metrics_path=metrics_path)


if __name__ == "__main__":
    raise SystemExit(main())

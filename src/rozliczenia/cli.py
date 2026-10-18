"""CLI Przebiegu rozliczeń (uruchamiane przez ``run.py``).

Opisuje proces dla Uruchomienia procesu (``process_run``): argumenty, wybór
Pliku zbiorczego, wywołanie silnika oraz linie statusu i podsumowania.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from pathlib import Path
from typing import TextIO

from . import collective_file, engine
from .domain import ProgressObserver, SettlementSummary
from .engine import (
    SettlementError,
    default_config_path,
    default_worker_template_path,
    period_from_source,
)
from .process_run import Conversation, Finished, Process, Stop, run
from .progress_presentation import format_counter_line
from .telemetry import COUNTER_NAMES, UNKNOWN_PERIOD

_UNEXPECTED_FAILURE = (
    "Wystąpił nieoczekiwany błąd; folder rozliczeń pracowników nie został opublikowany. "
    "Uruchom ponownie; jeśli błąd wraca, przekaż to osobie utrzymującej narzędzie."
)
_SUMMARY_NOT_SHOWN = (
    "Rozliczenia pracowników powstały, ale nie udało się pokazać podsumowania. "
    "Sprawdź Folder okresu i przekaż ten komunikat osobie utrzymującej narzędzie."
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


@dataclass(frozen=True)
class _Inputs:
    source: Path
    period: str
    args: argparse.Namespace


def _period_label(source: Path) -> str:
    try:
        return period_from_source(source.expanduser().resolve())
    except SettlementError:
        return UNKNOWN_PERIOD


def _gather(args: argparse.Namespace, conversation: Conversation) -> _Inputs:
    source = args.source or conversation.choose_file(
        "Wybierz plik zbiorczy rozliczenia",
        [("Plik zbiorczy Excel", collective_file.NAME_GLOB), ("Excel", "*.xlsx")],
    )
    if source is None:
        raise SettlementError("Nie wybrano pliku zbiorczego.")
    return _Inputs(source, _period_label(source), args)


def _execute(inputs: _Inputs, observer: ProgressObserver, _conversation: Conversation) -> SettlementSummary:
    args = inputs.args
    return engine.run_settlements(
        inputs.source,
        args.config,
        dry_run=args.dry_run,
        worker_template_path=args.worker_template,
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


def _finished(inputs: _Inputs, summary: SettlementSummary) -> Finished:
    return Finished(
        status_lines=[
            f"Status semantyczny: {'OK' if summary.ok else 'OSTRZEŻENIE'}",
            f"Status końcowy: {'OK' if summary.ok else 'Wymaga sprawdzenia'}",
        ],
        summary_lines=_summary_lines(summary, dry_run=inputs.args.dry_run),
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


def _stop_lines(error: Exception) -> list[str]:
    """Jednoliniowy komunikat ``SettlementError``."""

    return [str(error)]


def _stopped(stop: Stop) -> list[str]:
    if stop.kind == "after_engine":
        return ["Status semantyczny: BŁĄD", _SUMMARY_NOT_SHOWN]
    lines = stop.lines if stop.kind == "stop" else (_UNEXPECTED_FAILURE,)
    return ["Status semantyczny: BŁĄD", *(f"Nie wykonano: {line}" for line in lines)]


_PROCESS: Process[_Inputs, SettlementSummary] = Process(
    title="Rozliczenia",
    shows_templates=True,
    parser=build_parser,
    counter_names=COUNTER_NAMES,
    metrics_failure_tail="proces rozliczeń zakończył się niezależnie.",
    stop_type=SettlementError,
    stop_lines=_stop_lines,
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

    return run(_PROCESS, argv, output=output, metrics_path=metrics_path)


if __name__ == "__main__":
    raise SystemExit(main())

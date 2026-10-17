"""CLI Przygotowania pliku zbiorczego (osobne wejście, uruchamiane przez ``run_preparation.py``)."""

from __future__ import annotations

import argparse
from datetime import date, datetime, timezone
import sys
import time
from pathlib import Path
from typing import Any, TextIO

from .cli import Dashboard, default_config_path
from .collective_preparation import (
    PreparationError,
    PreparationSummary,
    default_collective_template_path,
    default_internal_template_path,
    prepare_collective_file,
)
from .domain import PHASES, ProgressPhase
from .phase_runner import elapsed_ms_since
from .preparation_messages import PreparationMessage, unexpected_failure
from .telemetry import METRICS_SCHEMA_VERSION, PERIOD_PATTERN, MetricsStore

_TITLE = "Przygotowanie pliku zbiorczego"
# Liczniki historii metryk Przygotowania pliku zbiorczego (inne niż Przebiegu rozliczeń).
_COUNTERS = ("period_orders", "successful_orders", "skipped_empty_rows", "warnings")
_COUNTER_NAMES = frozenset(_COUNTERS)
_WEEKDAY_LABELS = ("pon", "wt", "śr", "czw", "pt", "sob", "niedz")


def default_metrics_path() -> Path:
    """Osobna lokalna historia metryk, obok historii Przebiegu rozliczeń."""

    return Path(__file__).resolve().parents[2] / ".przygotowanie-pliku-zbiorczego-metrics.jsonl"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Tworzy Rozliczenie wewnętrzne i Plik zbiorczy okresu z Rejestru zleceń."
    )
    parser.add_argument("--register", type=Path, required=True, help="Plik Rejestru zleceń.")
    parser.add_argument(
        "--periods-directory",
        type=Path,
        required=True,
        help="Folder okresów, w którym powstaje Folder okresu.",
    )
    parser.add_argument("--period", required=True, help="Token okresu, np. 08_14_09_2026.")
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


def _metrics_period(period: str) -> str:
    return period if PERIOD_PATTERN.fullmatch(period) else "nieznany"


def _metric_record(
    *,
    mode: str,
    period: str,
    summary: PreparationSummary | None,
    dashboard: Dashboard,
    total_elapsed_ms: int,
    started_at: str,
) -> dict[str, Any]:
    counters = dict.fromkeys(_COUNTERS, 0)
    phase_durations: dict[ProgressPhase, int] = dict(dashboard.state.snapshot.phase_durations_ms)
    if summary is not None:
        counters.update(
            {
                "period_orders": summary.period_order_count,
                "successful_orders": summary.successful_order_count,
                "skipped_empty_rows": summary.skipped_empty_rows,
                "warnings": len(summary.warnings),
            }
        )
        phase_durations.update(summary.phase_durations_ms)
    return {
        "schema_version": METRICS_SCHEMA_VERSION,
        "started_at": started_at,
        "mode": mode,
        "period": _metrics_period(period),
        "completed": summary is not None,
        "result": "OK" if summary is not None else "BLAD_KRYTYCZNY",
        "total_duration_ms": total_elapsed_ms,
        "phase_durations_ms": {phase: phase_durations.get(ProgressPhase(phase), 0) for phase in PHASES},
        "counters": counters,
    }


def main(
    argv: list[str] | None = None,
    *,
    output: TextIO | None = None,
    metrics_path: Path | None = None,
) -> int:
    """Uruchamia Przygotowanie pliku zbiorczego; ``0`` sukces, ``1`` zatrzymanie albo błąd."""

    output = output or sys.stdout
    args = build_parser().parse_args(argv)
    mode = "DRY-RUN" if args.dry_run else "RUN"
    started_at = datetime.now(timezone.utc).isoformat()
    started = time.perf_counter()
    metrics_store = MetricsStore(metrics_path or args.metrics, _COUNTER_NAMES)

    dashboard = Dashboard(output, mode, args.period, title=_TITLE, shows_templates=False)
    dashboard.start()
    summary: PreparationSummary | None = None
    stop: tuple[str, PreparationMessage] | None = None
    try:
        summary = prepare_collective_file(
            args.register,
            args.periods_directory,
            args.period,
            args.config,
            internal_template_path=args.internal_template,
            collective_template_path=args.collective_template,
            dry_run=args.dry_run,
            observer=dashboard,
        )
    except PreparationError as error:
        stop = ("ZATRZYMANO", error.message)
    except Exception:
        stop = ("BŁĄD", unexpected_failure())

    total_elapsed_ms = elapsed_ms_since(started)
    dashboard.stop()
    if stop is not None:
        status, message = stop
        dashboard.print_line(f"Status końcowy: {status}")
        for line in message.text.splitlines():
            dashboard.print_line(line)
        dashboard.print_line(f"Czas uruchomienia: {total_elapsed_ms} ms")
    else:
        assert summary is not None
        dashboard.print_line("Status końcowy: OK")
        dashboard.print_line(f"Czas uruchomienia: {total_elapsed_ms} ms")
        for line in _summary_lines(summary, dry_run=args.dry_run):
            dashboard.print_line(line)

    record = _metric_record(
        mode=mode,
        period=args.period,
        summary=summary,
        dashboard=dashboard,
        total_elapsed_ms=total_elapsed_ms,
        started_at=started_at,
    )
    try:
        metrics_store.append(record)
        dashboard.print_statistics(metrics_store.read(), counter_names=_COUNTER_NAMES)
    except (OSError, UnicodeError, ValueError):
        dashboard.print_warning("Nie zapisano metryk; Przygotowanie pliku zbiorczego zakończyło się niezależnie.")
    return 0 if summary is not None else 1


if __name__ == "__main__":
    raise SystemExit(main())

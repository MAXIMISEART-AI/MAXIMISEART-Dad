"""Interfejs tekstowy, dashboard i lokalna obserwowalność procesu."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import os
from pathlib import Path
import sys
import time
from typing import Any, TextIO

from .domain import PHASES, ProgressEvent, ProgressPhase, SettlementSummary
from .engine import SettlementError, period_from_source, run_settlements
from .progress import (
    ProgressNotice,
    ProgressProjection,
)
from .plain_progress import PlainProgressAdapter
from .progress_presentation import format_counter_line
from .rich_progress import Console, Live, RichProgressAdapter
from .telemetry import (
    METRICS_SCHEMA_VERSION,
    MetricsStore,
    comparable_records,
    statistics_for,
)


def _summary_counter_line(summary: SettlementSummary) -> str:
    return format_counter_line(
        {
            "written": summary.written_count,
            "empty": summary.empty_count,
            "planned": summary.planned_count,
            "skipped": summary.skipped_count,
        }
    )


def default_config_path() -> Path:
    return Path(__file__).resolve().parents[2] / "config" / "worker_mapping.yaml"


def default_metrics_path() -> Path:
    return Path(__file__).resolve().parents[2] / ".rozliczenia-metrics.jsonl"


def choose_source_file() -> Path:
    """Pokazuje lokalny wybór pliku, gdy launcher nie podał argumentu."""

    try:
        import tkinter as tk
        from tkinter import filedialog

        root = tk.Tk()
        root.withdraw()
        selected = filedialog.askopenfilename(
            title="Wybierz plik zbiorczy rozliczenia",
            filetypes=[("Plik zbiorczy Excel", "Rozliczenie * - zbiorcze.xlsx"), ("Excel", "*.xlsx")],
        )
        root.destroy()
        if selected:
            return Path(selected)
    except Exception:
        pass
    raise SettlementError("Nie wybrano pliku zbiorczego.")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Rozdziela plik zbiorczy na szablony pracowników.")
    parser.add_argument("--source", type=Path, help="Ścieżka do pliku ... - zbiorcze.xlsx")
    parser.add_argument("--config", type=Path, default=default_config_path())
    parser.add_argument(
        "--metrics",
        type=Path,
        default=default_metrics_path(),
        help="Lokalny plik historii metryk JSONL.",
    )
    parser.add_argument("--dry-run", action="store_true", help="Sprawdź plan bez zapisywania plików.")
    return parser


class Dashboard:
    """Rich dashboard with a line-oriented fallback for non-interactive output."""

    def __init__(self, output: TextIO, mode: str, period: str):
        self.output = output
        self.state = ProgressProjection(mode, period)
        self.plain_adapter = PlainProgressAdapter(self._line)
        self.rich_adapter = RichProgressAdapter()
        self._output_failed = False
        try:
            self.console: Any | None = Console(file=output) if Console is not None else None
        except Exception:
            self.console = None
        self.interactive = (
            self._supports_live_output(output)
            and self.console is not None
            and self.console.color_system is not None
        )
        self.live: Any | None = None

    @staticmethod
    def _supports_live_output(output: TextIO) -> bool:
        if os.environ.get("NO_COLOR") is not None or os.environ.get("TERM") == "dumb":
            return False
        try:
            return bool(output.isatty())
        except (AttributeError, OSError):
            return False

    def start(self) -> None:
        if self.interactive and Live is not None:
            try:
                self.live = Live(self.render(), console=self.console, auto_refresh=False)
                self.live.start(refresh=True)
                return
            except Exception:
                self._disable_rich()
        elif self.interactive:
            self._disable_rich()
        self.plain_adapter.start(self.state.snapshot)

    def __call__(self, event: ProgressEvent) -> None:
        update = self.state.update(event)
        if self._output_failed:
            raise OSError("Terminal output is unavailable.")
        if self.interactive:
            try:
                if self.live is None:
                    raise RuntimeError("Rich dashboard did not start.")
                self.live.update(self.rich_adapter.render(update.snapshot, update.notice), refresh=True)
                return
            except Exception:
                self._disable_rich()
                self.plain_adapter.start(update.snapshot)
        self.plain_adapter.update(update.snapshot, update.notice)
        if self._output_failed:
            raise OSError("Terminal output is unavailable.")

    def finish(self, summary: SettlementSummary | None, error: Exception | None, total_elapsed_ms: int) -> None:
        if self.live is not None:
            try:
                self.live.stop()
            except Exception:
                self._disable_rich()
            else:
                self.live = None
        if error is not None:
            self._line("Status semantyczny: BŁĄD")
            self._line(f"Nie wykonano: {error}")
            self._line(f"Czas uruchomienia: {total_elapsed_ms} ms")
            return
        assert summary is not None
        status = "OK" if summary.ok else "Wymaga sprawdzenia"
        self._line(f"Status semantyczny: {'OK' if summary.ok else 'OSTRZEŻENIE'}")
        self._line(f"Status końcowy: {status}")
        self._line(f"Czas uruchomienia: {total_elapsed_ms} ms")
        self._line(f"Liczniki: {_summary_counter_line(summary)}")
        self._line(f"Wiersze danych: {summary.total_rows}")
        self._line(f"Zapisane szablony: {summary.written_count}")
        self._line(f"Puste szablony: {summary.empty_count}")
        self._line(f"Pominięte szablony: {summary.skipped_count}")
        if summary.planned_count:
            self._line(f"Planowane szablony: {summary.planned_count}")
            self._line("DRY-RUN: Nic nie zapisano")
        self._line(f"Problemy: {len(summary.issues)}")
        for issue in summary.issues:
            self._line(f"- {issue.message}")

    def print_warning(self, message: str) -> None:
        self._line(f"Ostrzeżenie: {message}")

    def print_statistics(self, records: list[dict[str, Any]]) -> None:
        labels = {"total": "całe uruchomienie"}
        for mode in ("RUN", "DRY-RUN"):
            comparable = comparable_records(records, mode)
            stats = statistics_for(records, mode)
            if stats is None:
                continue
            self._line(f"Statystyki {mode} | próbek: {len(comparable)}")
            for name, (p50, p95) in stats.items():
                self._line(f"{labels.get(name, name)} | P50: {p50} ms | P95: {p95} ms")

    def render(self, notice: ProgressNotice | None = None) -> Any:
        return self.rich_adapter.render(self.state.snapshot, notice)

    def _disable_rich(self) -> None:
        live, self.live = self.live, None
        if live is not None:
            try:
                live.stop()
            except Exception:
                pass
        self.interactive = False
        self.console = None

    def _line(self, message: str) -> None:
        if self._output_failed:
            return
        try:
            if self.interactive and self.console is not None:
                self.console.print(message)
            else:
                self.output.write(f"{message}\n")
        except (OSError, UnicodeError, ValueError):
            self._output_failed = True


def _period_label(source: Path) -> str:
    try:
        return period_from_source(source.expanduser().resolve())
    except SettlementError:
        return "nieznany"


def _metric_record(
    *,
    mode: str,
    period: str,
    summary: SettlementSummary | None,
    dashboard: Dashboard | None,
    completed: bool,
    total_elapsed_ms: int,
    started_at: str,
) -> dict[str, Any]:
    snapshot = dashboard.state.snapshot if dashboard else None
    counters = snapshot.metric_counters() if snapshot else {
        "templates_total": 0,
        "templates_completed": 0,
        "rows": 0,
        "written": 0,
        "empty": 0,
        "planned": 0,
        "skipped": 0,
    }
    if summary is None:
        counters["issues"] = (snapshot.issue_count if snapshot else 0) + 1
        result = "BLAD_KRYTYCZNY"
    else:
        counters.update(
            {
                "templates_total": summary.template_count,
                "templates_completed": summary.template_count,
                "rows": summary.total_rows,
                "written": summary.written_count,
                "empty": summary.empty_count,
                "planned": summary.planned_count,
                "skipped": summary.skipped_count,
                "issues": len(summary.issues),
            }
        )
        result = "OK" if summary.ok else "WYMAGA_SPRAWDZENIA"
    phase_durations = snapshot.phase_durations_ms if snapshot else {ProgressPhase(phase): 0 for phase in PHASES}
    return {
        "schema_version": METRICS_SCHEMA_VERSION,
        "started_at": started_at,
        "mode": mode,
        "period": period,
        "completed": completed,
        "result": result,
        "total_duration_ms": total_elapsed_ms,
        "phase_durations_ms": {str(phase): duration for phase, duration in phase_durations.items()},
        "counters": counters,
    }


def main(
    argv: list[str] | None = None,
    *,
    output: TextIO | None = None,
    metrics_path: Path | None = None,
) -> int:
    output = output or sys.stdout
    args = build_parser().parse_args(argv)
    mode = "DRY-RUN" if args.dry_run else "RUN"
    started_at = datetime.now(timezone.utc).isoformat()
    started = time.perf_counter()
    metrics_store = MetricsStore(metrics_path or args.metrics)

    try:
        source = args.source or choose_source_file()
        period = _period_label(source)
    except SettlementError as exc:
        dashboard = Dashboard(output, mode, "nieznany")
        dashboard.start()
        total_elapsed_ms = max(0, round((time.perf_counter() - started) * 1000))
        dashboard.finish(None, exc, total_elapsed_ms)
        record = _metric_record(
            mode=mode,
            period="nieznany",
            summary=None,
            dashboard=dashboard,
            completed=False,
            total_elapsed_ms=total_elapsed_ms,
            started_at=started_at,
        )
        try:
            metrics_store.append(record)
        except (OSError, UnicodeError, ValueError):
            dashboard.print_warning("Nie zapisano metryk.")
        return 1

    dashboard = Dashboard(output, mode, period)
    dashboard.start()
    summary: SettlementSummary | None = None
    error: Exception | None = None
    try:
        summary = run_settlements(
            source,
            args.config,
            dry_run=args.dry_run,
            observer=dashboard,
        )
    except Exception as exc:
        error = exc

    total_elapsed_ms = max(0, round((time.perf_counter() - started) * 1000))
    dashboard.finish(summary, error, total_elapsed_ms)
    record = _metric_record(
        mode=mode,
        period=period,
        summary=summary,
        dashboard=dashboard,
        completed=summary is not None,
        total_elapsed_ms=total_elapsed_ms,
        started_at=started_at,
    )
    try:
        metrics_store.append(record)
        records = metrics_store.read()
        dashboard.print_statistics(records)
    except (OSError, UnicodeError, ValueError):
        dashboard.print_warning("Nie zapisano metryk; proces rozliczeń zakończył się niezależnie.")

    if error is not None:
        return 1
    assert summary is not None
    return 0 if summary.ok else 2


if __name__ == "__main__":
    raise SystemExit(main())

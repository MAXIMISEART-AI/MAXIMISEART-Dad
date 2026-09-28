"""Interfejs tekstowy, dashboard i lokalna obserwowalność procesu."""

from __future__ import annotations

import argparse
from collections import deque
from datetime import datetime, timezone
import os
from pathlib import Path
import sys
import time
from typing import Any, TextIO

try:
    from rich.console import Console as RichConsole, Group as RichGroup
    from rich.live import Live as RichLive
    from rich.panel import Panel as RichPanel
    from rich.table import Table as RichTable
    from rich.text import Text as RichText

    Console: Any = RichConsole
    Group: Any = RichGroup
    Live: Any = RichLive
    Panel: Any = RichPanel
    Table: Any = RichTable
    Text: Any = RichText
except ImportError:
    Console = Group = Live = Panel = Table = Text = None

from .domain import PHASES, SKIPPED_STATUSES, ProgressEvent, SettlementSummary
from .engine import SettlementError, period_from_source, run_settlements
from .telemetry import (
    METRICS_SCHEMA_VERSION,
    MetricsStore,
    comparable_records,
    statistics_for,
)


OPERATION_STATUS_PRESENTATION: dict[str, tuple[str, str]] = {
    "ZAPISANO": ("OK", "green"),
    "PUSTY_SZABLON": ("OK", "green"),
    "PLAN": ("OK", "green"),
    "ZABLOKOWANY": ("OSTRZEŻENIE", "yellow"),
    "ZLY_SZABLON": ("BŁĄD", "red"),
    "POMINIĘTO": ("BŁĄD", "red"),
}


def operation_status_presentation(status: str | None) -> tuple[str, str]:
    """Zwraca semantyczny status i opcjonalny styl dla pojedynczej operacji."""

    return OPERATION_STATUS_PRESENTATION.get(status or "", ("OSTRZEŻENIE", "yellow"))


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


class DashboardState:
    def __init__(self, mode: str, period: str):
        self.mode = mode
        self.period = period
        self.phase_states = {phase: "oczekuje" for phase in PHASES}
        self.phase_durations_ms = {phase: 0 for phase in PHASES}
        self.template_total = 0
        self.templates_completed = 0
        self.rows = 0
        self.operation_counts: dict[str, int] = {}
        self.current_worker: str | None = None
        self.current_phase: str | None = None
        self.recent_operations: deque[ProgressEvent] = deque(maxlen=5)
        self.total_elapsed_ms = 0
        self.issue_count = 0

    def update(self, event: ProgressEvent) -> None:
        self.total_elapsed_ms = event.elapsed_ms or self.total_elapsed_ms
        if event.state == "START":
            self.phase_states[event.phase] = "aktywny"
        elif event.state == "END":
            self.phase_states[event.phase] = "gotowe"
            if event.phase_elapsed_ms is not None:
                self.phase_durations_ms[event.phase] = event.phase_elapsed_ms
        elif event.state == "PLAN_READY":
            self.template_total = event.template_total
            self.issue_count = event.issue_count
        elif event.state == "ISSUE_COUNT":
            self.issue_count = event.issue_count
        elif event.state == "WORKER_START":
            self.current_worker = event.worker_name
            self.current_phase = event.phase
        elif event.state == "WORKER_END":
            self.templates_completed = event.template_index
            self.rows += event.rows
            self.issue_count = event.issue_count
            status = event.status or "NIEZNANY"
            self.operation_counts[status] = self.operation_counts.get(status, 0) + 1
            self.recent_operations.append(event)
            self.current_worker = None
            self.current_phase = None

    def metric_counters(self) -> dict[str, int]:
        counts = self.operation_counts
        return {
            "templates_total": self.template_total,
            "templates_completed": self.templates_completed,
            "rows": self.rows,
            "written": counts.get("ZAPISANO", 0),
            "empty": counts.get("PUSTY_SZABLON", 0),
            "planned": counts.get("PLAN", 0),
            "skipped": sum(counts.get(status, 0) for status in SKIPPED_STATUSES),
        }


class Dashboard:
    """Rich dashboard with a line-oriented fallback for non-interactive output."""

    def __init__(self, output: TextIO, mode: str, period: str):
        self.output = output
        self.state = DashboardState(mode, period)
        self.console: Any | None = Console(file=output) if Console is not None else None
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
            self.live = Live(self.render(), console=self.console, refresh_per_second=8)
            self.live.start(refresh=True)
            return
        self._line(f"Rozliczenia | okres: {self.state.period} | tryb: {self.state.mode}")
        self._line("Status: uruchomiono")
        self._line("Ostatnie operacje:")

    def __call__(self, event: ProgressEvent) -> None:
        self.state.update(event)
        if self.interactive:
            if self.live is not None:
                self.live.update(self.render(), refresh=True)
            return
        if event.state == "START":
            self._line(f"Etap: {event.phase}")
        elif event.state == "PLAN_READY":
            self._line(f"Szablony pracownika: 0/{event.template_total}")
        elif event.state == "WORKER_START":
            self._line(f"WYKONAWCA: {event.worker_name} | etap: {event.phase}")
        elif event.state == "WORKER_END":
            self._line(f"Postęp szablonów: {self._progress_line()}")
            self._line(f"Liczniki: {self._counter_line()}")
            status_label, _ = operation_status_presentation(event.status)
            self._line(
                f"Ostatnia operacja: {event.worker_name} | {event.status} | "
                f"status: {status_label} | "
                f"wiersze: {event.rows} | czas: {event.worker_elapsed_ms or 0} ms"
            )

    def finish(self, summary: SettlementSummary | None, error: Exception | None, total_elapsed_ms: int) -> None:
        if self.live is not None:
            self.live.stop()
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
        self._line(f"Liczniki: {self._counter_line()}")
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

    def render(self):
        assert Console is not None
        assert Group is not None
        assert Panel is not None
        assert Table is not None
        assert Text is not None
        phases = Table.grid(padding=(0, 1))
        phases.add_column()
        phases.add_column()
        for phase in PHASES:
            phase_state = self.state.phase_states[phase]
            state_style = {"aktywny": "bold yellow", "gotowe": "bold green"}.get(phase_state, "dim")
            phases.add_row(Text(f"[{phase_state}]", style=state_style), phase)

        progress = self._progress_line()
        current = self.state.current_worker or "brak"
        current_phase = self.state.current_phase or "oczekuje"
        operations = Table.grid(padding=(0, 1))
        operations.add_column()
        operations.add_column()
        for event in self.state.recent_operations:
            status_label, status_style = operation_status_presentation(event.status)
            operations.add_row(
                event.worker_name or "-",
                Text(
                    f"{status_label}: {event.status} ({event.rows} wierszy)",
                    style=status_style,
                ),
            )
        if not self.state.recent_operations:
            operations.add_row("-", "brak")

        body = Group(
            phases,
            f"Postęp szablonów: {progress}",
            f"Liczniki: {self._counter_line()}",
            f"Bieżący WYKONAWCA: {current} | etap: {current_phase}",
            Panel(operations, title="Ostatnie operacje"),
            f"Wiersze danych: {self.state.rows} | Czas: {self.state.total_elapsed_ms} ms",
        )
        return Panel(body, title=f"Rozliczenia | {self.state.period} | {self.state.mode}")

    def _progress_line(self) -> str:
        if not self.state.template_total:
            return "oczekuje na liczbę szablonów"
        percentage = round(self.state.templates_completed / self.state.template_total * 100)
        return f"{self.state.templates_completed}/{self.state.template_total} ({percentage}%)"

    def _counter_line(self) -> str:
        counters = self.state.metric_counters()
        return (
            f"zapisano: {counters['written']} | "
            f"puste: {counters['empty']} | "
            f"planowane: {counters['planned']} | "
            f"pominięte: {counters['skipped']}"
        )

    def _line(self, message: str) -> None:
        if self.interactive and self.console is not None:
            self.console.print(message)
        else:
            self.output.write(f"{message}\n")


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
    counters = dashboard.state.metric_counters() if dashboard else {
        "templates_total": 0,
        "templates_completed": 0,
        "rows": 0,
        "written": 0,
        "empty": 0,
        "planned": 0,
        "skipped": 0,
    }
    if summary is None:
        counters["issues"] = (dashboard.state.issue_count if dashboard else 0) + 1
        result = "BLAD_KRYTYCZNY"
    else:
        counters.update(
            {
                "templates_total": summary.template_count,
                "rows": summary.total_rows,
                "written": summary.written_count,
                "empty": summary.empty_count,
                "planned": summary.planned_count,
                "skipped": summary.skipped_count,
                "issues": len(summary.issues),
            }
        )
        result = "OK" if summary.ok else "WYMAGA_SPRAWDZENIA"
    phase_durations = dashboard.state.phase_durations_ms if dashboard else {phase: 0 for phase in PHASES}
    return {
        "schema_version": METRICS_SCHEMA_VERSION,
        "started_at": started_at,
        "mode": mode,
        "period": period,
        "completed": completed,
        "result": result,
        "total_duration_ms": total_elapsed_ms,
        "phase_durations_ms": dict(phase_durations),
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
        output.write(f"Nie wykonano: {exc}\n")
        record = _metric_record(
            mode=mode,
            period="nieznany",
            summary=None,
            dashboard=None,
            completed=False,
            total_elapsed_ms=max(0, round((time.perf_counter() - started) * 1000)),
            started_at=started_at,
        )
        try:
            metrics_store.append(record)
        except (OSError, UnicodeError, ValueError):
            output.write("Ostrzeżenie: Nie zapisano metryk.\n")
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

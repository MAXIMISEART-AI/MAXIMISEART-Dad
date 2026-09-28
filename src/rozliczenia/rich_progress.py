"""Rich dashboard rendering for shared settlement progress snapshots."""

from __future__ import annotations

from typing import Any

from .domain import PHASES, ProgressPhase
from .progress import PhaseState, ProgressNotice, ProgressNoticeKind, ProgressSnapshot
from .progress_presentation import (
    counter_line,
    operation_status_presentation,
    progress_line,
)

Console: Any
Live: Any
Panel: Any
Table: Any
Text: Any
Group: Any

try:
    from rich.console import Console as RichConsole
    from rich.live import Live as RichLive
    from rich.panel import Panel as RichPanel
    from rich.table import Table as RichTable
    from rich.text import Text as RichText

    from rich.console import Group as RichGroup

    Console = RichConsole
    Live = RichLive
    Panel = RichPanel
    Table = RichTable
    Text = RichText
    Group = RichGroup
except ImportError:
    Console = Live = Panel = Table = Text = Group = None


class RichProgressAdapter:
    """Render a complete Rich view from an immutable snapshot and safe notice."""

    def render(self, snapshot: ProgressSnapshot, notice: ProgressNotice | None = None) -> Any:
        if any(component is None for component in (Console, Group, Panel, Table, Text)):
            raise RuntimeError("Rich is not available.")

        phases = Table.grid(padding=(0, 1))
        phases.add_column()
        phases.add_column()
        phases.add_column()
        phase_labels = {
            PhaseState.PENDING: "oczekuje",
            PhaseState.RUNNING: "aktywny",
            PhaseState.COMPLETED: "gotowe",
            PhaseState.FAILED: "przerwany",
        }
        for phase in PHASES:
            progress_phase = ProgressPhase(phase)
            phase_state = snapshot.phase_states[progress_phase]
            state_label = phase_labels[phase_state]
            state_style = {"aktywny": "bold yellow", "gotowe": "bold green", "przerwany": "bold red"}.get(
                state_label, "dim"
            )
            phase_duration = (
                f"{snapshot.phase_durations_ms[progress_phase]} ms"
                if phase_state in (PhaseState.COMPLETED, PhaseState.FAILED)
                else "—"
            )
            phases.add_row(Text(f"[{state_label}]", style=state_style), phase, phase_duration)

        operations = Table.grid(padding=(0, 1))
        operations.add_column()
        operations.add_column()
        for operation in snapshot.recent_operations:
            status_label, status_style = operation_status_presentation(operation.status)
            operations.add_row(
                operation.worker_name or "-",
                Text(
                    f"{status_label}: {operation.status} ({operation.rows} wierszy, "
                    f"czas: {operation.worker_elapsed_ms or 0} ms)",
                    style=status_style,
                ),
            )
        if not snapshot.recent_operations:
            operations.add_row("-", "brak")

        failure_detail = None
        if notice is not None and notice.kind is ProgressNoticeKind.FAILED:
            if snapshot.current_worker and notice.template_index and notice.template_total:
                failure_detail = (
                    f"Przerwano przy szablonie pracownika: "
                    f"{notice.template_index}/{notice.template_total}"
                )

        body = Group(
            phases,
            f"Postęp szablonów: {progress_line(snapshot)}",
            f"Liczniki: {counter_line(snapshot)}",
            f"Bieżący WYKONAWCA: {snapshot.current_worker or 'brak'} | "
            f"etap: {snapshot.current_phase or 'oczekuje'}",
            *([failure_detail] if failure_detail is not None else []),
            Panel(operations, title="Ostatnie operacje"),
            f"Wiersze danych: {snapshot.rows} | Czas: {snapshot.total_elapsed_ms} ms",
        )
        return Panel(body, title=f"Rozliczenia | {snapshot.period} | {snapshot.mode}")

"""Line-oriented rendering of shared settlement progress snapshots."""

from __future__ import annotations

from typing import Callable

from .domain import PhaseFailed, PhaseStarted, PlanReady, ProgressEvent, WorkerEnded, WorkerFailed, WorkerStarted
from .progress import ProgressSnapshot
from .progress_presentation import counter_line, operation_status_presentation, progress_line


class PlainProgressAdapter:
    """Render safe progress snapshots as ordinary terminal lines."""

    def __init__(self, line: Callable[[str], None], *, title: str = "Rozliczenia", shows_templates: bool = True):
        self._line = line
        self._title = title
        self._shows_templates = shows_templates

    def start(self, snapshot: ProgressSnapshot) -> None:
        self._line(f"{self._title} | okres: {snapshot.period} | tryb: {snapshot.mode}")
        self._line("Status: uruchomiono")
        if self._shows_templates:
            self._line("Ostatnie operacje:")

    def update(self, snapshot: ProgressSnapshot, event: ProgressEvent) -> None:
        phase = snapshot.current_phase or "oczekuje"
        if isinstance(event, PhaseStarted):
            self._line(f"Etap: {phase}")
        elif isinstance(event, PlanReady) and self._shows_templates:
            self._line(f"Szablony pracownika: 0/{snapshot.template_total}")
        elif isinstance(event, WorkerStarted):
            worker_name = snapshot.current_worker or "brak"
            self._line(f"WYKONAWCA: {worker_name} | etap: {phase}")
        elif isinstance(event, WorkerEnded):
            operation = snapshot.recent_operations[-1]
            self._line(f"Postęp szablonów: {progress_line(snapshot)}")
            self._line(f"Liczniki: {counter_line(snapshot)}")
            status_label, _ = operation_status_presentation(operation.status)
            self._line(
                f"Ostatnia operacja: {operation.worker_name} | {operation.status} | "
                f"status: {status_label} | "
                f"wiersze: {operation.rows} | czas: {operation.worker_elapsed_ms or 0} ms"
            )
        elif isinstance(event, (PhaseFailed, WorkerFailed)):
            if snapshot.current_worker:
                template_position = (
                    f" | Szablon pracownika: {event.template_index}/{event.template_total}"
                    if isinstance(event, WorkerFailed)
                    else ""
                )
                self._line(
                    f"Etap przerwany: {phase} | WYKONAWCA: {snapshot.current_worker}{template_position}"
                )
            else:
                self._line(f"Etap przerwany: {phase}")

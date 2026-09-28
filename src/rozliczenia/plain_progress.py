"""Line-oriented rendering of shared settlement progress snapshots."""

from __future__ import annotations

from typing import Callable

from .progress import ProgressNotice, ProgressNoticeKind, ProgressSnapshot
from .progress_presentation import counter_line, operation_status_presentation, progress_line


class PlainProgressAdapter:
    """Render safe progress snapshots as ordinary terminal lines."""

    def __init__(self, line: Callable[[str], None]):
        self._line = line

    def start(self, snapshot: ProgressSnapshot) -> None:
        self._line(f"Rozliczenia | okres: {snapshot.period} | tryb: {snapshot.mode}")
        self._line("Status: uruchomiono")
        self._line("Ostatnie operacje:")

    def update(self, snapshot: ProgressSnapshot, notice: ProgressNotice) -> None:
        if notice.kind is ProgressNoticeKind.PHASE_STARTED:
            phase = snapshot.current_phase or "oczekuje"
            self._line(f"Etap: {phase}")
        elif notice.kind is ProgressNoticeKind.PLAN_READY:
            self._line(f"Szablony pracownika: 0/{snapshot.template_total}")
        elif notice.kind is ProgressNoticeKind.WORKER_STARTED:
            worker_name = snapshot.current_worker or "brak"
            phase = snapshot.current_phase or "oczekuje"
            self._line(f"WYKONAWCA: {worker_name} | etap: {phase}")
        elif notice.kind is ProgressNoticeKind.WORKER_ENDED:
            operation = snapshot.recent_operations[-1]
            self._line(f"Postęp szablonów: {progress_line(snapshot)}")
            self._line(f"Liczniki: {counter_line(snapshot)}")
            status_label, _ = operation_status_presentation(operation.status)
            self._line(
                f"Ostatnia operacja: {operation.worker_name} | {operation.status} | "
                f"status: {status_label} | "
                f"wiersze: {operation.rows} | czas: {operation.worker_elapsed_ms or 0} ms"
            )
        elif notice.kind is ProgressNoticeKind.FAILED:
            phase = snapshot.current_phase or "oczekuje"
            if snapshot.current_worker:
                self._line(f"Etap przerwany: {phase} | WYKONAWCA: {snapshot.current_worker}")
            else:
                self._line(f"Etap przerwany: {phase}")

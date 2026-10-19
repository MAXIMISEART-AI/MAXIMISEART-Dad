"""Pure reduction of safe settlement events for terminal adapters."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from types import MappingProxyType
from typing import Mapping, TypeVar

from .domain import (
    PHASES,
    IssueCountReady,
    PhaseEnded,
    PhaseFailed,
    PhaseStarted,
    PlanReady,
    ProgressEvent,
    ProgressPhase,
    WorkerEnded,
    WorkerFailed,
    WorkerStarted,
)

KeyT = TypeVar("KeyT")
ValueT = TypeVar("ValueT")


class PhaseState(StrEnum):
    """Presentation-neutral state of a settlement phase."""

    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


@dataclass(frozen=True)
class OperationSnapshot:
    """Safe immutable facts for one completed Szablon pracownika operation."""

    worker_name: str
    status: str
    rows: int
    worker_elapsed_ms: int | None


@dataclass(frozen=True)
class ProgressSnapshot:
    """Immutable process facts shared by every terminal presentation adapter."""

    mode: str
    period: str
    phase_states: Mapping[ProgressPhase, PhaseState]
    phase_durations_ms: Mapping[ProgressPhase, int]
    template_total: int
    templates_completed: int
    rows: int
    operation_counts: Mapping[str, int]
    current_worker: str | None
    current_phase: ProgressPhase | None
    recent_operations: tuple[OperationSnapshot, ...]
    total_elapsed_ms: int
    issue_count: int

    def metric_counters(self) -> dict[str, int]:
        return {
            "templates_total": self.template_total,
            "templates_completed": self.templates_completed,
            "rows": self.rows,
            "written": self.operation_counts.get("ZAPISANO", 0),
            "empty": self.operation_counts.get("PUSTY_SZABLON", 0),
            "planned": self.operation_counts.get("PLAN", 0),
        }


@dataclass(frozen=True)
class ProgressUpdate:
    """Result of reducing one event, ready for an adapter to render."""

    snapshot: ProgressSnapshot
    event: ProgressEvent


def _immutable_mapping(values: Mapping[KeyT, ValueT]) -> Mapping[KeyT, ValueT]:
    return MappingProxyType(dict(values))


class ProgressProjection:
    """Single interpreter of ProgressEvent values for all terminal adapters.

    Reduces events without re-checking their order: ``PhaseRunner`` is the only emitter and checks it (ADR 0002).
    """

    def __init__(self, mode: str, period: str):
        self._mode = mode
        self._period = period
        self._phase_states = {ProgressPhase(phase): PhaseState.PENDING for phase in PHASES}
        self._phase_durations_ms = {ProgressPhase(phase): 0 for phase in PHASES}
        self._template_total = 0
        self._templates_completed = 0
        self._rows = 0
        self._operation_counts: dict[str, int] = {}
        self._current_worker: str | None = None
        self._current_phase: ProgressPhase | None = None
        self._recent_operations: list[OperationSnapshot] = []
        self._total_elapsed_ms = 0
        self._issue_count = 0
        self._snapshot = self._make_snapshot()

    @property
    def snapshot(self) -> ProgressSnapshot:
        return self._snapshot

    def update(self, event: ProgressEvent) -> ProgressUpdate:
        """Reduce one event and return an immutable snapshot together with that event."""

        self._total_elapsed_ms = event.elapsed_ms
        match event:
            case PhaseStarted(phase=phase):
                self._phase_states[phase] = PhaseState.RUNNING
                self._current_phase = phase
            case PhaseEnded(phase=phase, phase_elapsed_ms=phase_elapsed_ms):
                self._phase_states[phase] = PhaseState.COMPLETED
                self._phase_durations_ms[phase] = phase_elapsed_ms
                self._current_phase = None
            case IssueCountReady(issue_count=issue_count):
                self._issue_count = issue_count
            case PlanReady(template_total=template_total, issue_count=issue_count):
                self._template_total = template_total
                self._issue_count = issue_count
            case WorkerStarted(worker_name=worker_name):
                self._current_worker = worker_name
                self._current_phase = event.phase
            case WorkerEnded():
                self._templates_completed = event.template_index
                self._rows += event.rows
                self._issue_count = event.issue_count
                self._operation_counts[event.status] = self._operation_counts.get(event.status, 0) + 1
                self._recent_operations.append(
                    OperationSnapshot(
                        worker_name=event.worker_name,
                        status=event.status,
                        rows=event.rows,
                        worker_elapsed_ms=event.worker_elapsed_ms,
                    )
                )
                del self._recent_operations[:-5]
                self._current_worker = None
                self._current_phase = event.phase
            case PhaseFailed(phase=phase, phase_elapsed_ms=phase_elapsed_ms):
                self._phase_states[phase] = PhaseState.FAILED
                self._phase_durations_ms[phase] = phase_elapsed_ms
            case WorkerFailed():
                self._phase_states[event.phase] = PhaseState.FAILED
                self._phase_durations_ms[event.phase] = event.phase_elapsed_ms
                self._current_worker = event.worker_name
                self._current_phase = event.phase
        self._snapshot = self._make_snapshot()
        return ProgressUpdate(self._snapshot, event)

    def _make_snapshot(self) -> ProgressSnapshot:
        return ProgressSnapshot(
            mode=self._mode,
            period=self._period,
            phase_states=_immutable_mapping(self._phase_states),
            phase_durations_ms=_immutable_mapping(self._phase_durations_ms),
            template_total=self._template_total,
            templates_completed=self._templates_completed,
            rows=self._rows,
            operation_counts=_immutable_mapping(self._operation_counts),
            current_worker=self._current_worker,
            current_phase=self._current_phase,
            recent_operations=tuple(self._recent_operations),
            total_elapsed_ms=self._total_elapsed_ms,
            issue_count=self._issue_count,
        )

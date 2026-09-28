"""Pure reduction of safe settlement events for terminal adapters."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from types import MappingProxyType
from typing import Mapping

from .domain import (
    PHASES,
    ProgressEvent,
    ProgressPhase,
    ProgressProtocolError,
    ProgressState,
)


class PhaseState(StrEnum):
    """Presentation-neutral state of a settlement phase."""

    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


class ProgressNoticeKind(StrEnum):
    """Safe change notifications consumed by terminal adapters."""

    PHASE_STARTED = "PHASE_STARTED"
    PHASE_ENDED = "PHASE_ENDED"
    ISSUE_COUNT = "ISSUE_COUNT"
    PLAN_READY = "PLAN_READY"
    WORKER_STARTED = "WORKER_STARTED"
    WORKER_ENDED = "WORKER_ENDED"
    FAILED = "FAILED"


@dataclass(frozen=True)
class ProgressNotice:
    """Neutral, safe description of the latest accepted progress change."""

    kind: ProgressNoticeKind
    phase: ProgressPhase
    worker_name: str | None = None
    status: str | None = None
    rows: int = 0
    worker_elapsed_ms: int | None = None


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
            "skipped": sum(
                self.operation_counts.get(status, 0)
                for status in ("ZABLOKOWANY", "ZLY_SZABLON", "POMINIĘTO")
            ),
        }


@dataclass(frozen=True)
class ProgressUpdate:
    """Result of reducing one event, ready for an adapter to render."""

    snapshot: ProgressSnapshot
    notice: ProgressNotice


def _immutable_mapping(values: Mapping) -> Mapping:
    return MappingProxyType(dict(values))


class ProgressProjection:
    """Single interpreter of ProgressEvent values for all terminal adapters."""

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
        """Reduce one event and return only an immutable snapshot plus notice."""

        if not isinstance(event, ProgressEvent):
            raise ProgressProtocolError("Obserwator otrzymał obiekt inny niż ProgressEvent.")
        self._reduce(event)
        self._snapshot = self._make_snapshot()
        return ProgressUpdate(self._snapshot, self._notice(event))

    def _reduce(self, event: ProgressEvent) -> None:
        phase = ProgressPhase(event.phase)
        state = ProgressState(event.state)
        if event.elapsed_ms is not None:
            self._total_elapsed_ms = max(self._total_elapsed_ms, event.elapsed_ms)

        if state is ProgressState.START:
            self._expect_phase(phase, PhaseState.PENDING)
            self._phase_states[phase] = PhaseState.RUNNING
            self._current_phase = phase
        elif state is ProgressState.END:
            self._expect_phase(phase, PhaseState.RUNNING)
            self._phase_states[phase] = PhaseState.COMPLETED
            if event.phase_elapsed_ms is not None:
                self._phase_durations_ms[phase] = event.phase_elapsed_ms
            if phase is ProgressPhase.SAVING:
                self._current_worker = None
                self._current_phase = None
        elif state is ProgressState.ISSUE_COUNT:
            self._expect_phase(phase, (PhaseState.RUNNING, PhaseState.COMPLETED))
            self._issue_count = event.issue_count
        elif state is ProgressState.PLAN_READY:
            self._expect_phase(phase, (PhaseState.RUNNING, PhaseState.COMPLETED))
            self._template_total = event.template_total
            self._issue_count = event.issue_count
        elif state is ProgressState.WORKER_START:
            self._expect_phase(phase, PhaseState.RUNNING)
            if self._current_worker is not None:
                raise ProgressProtocolError("Nie można rozpocząć drugiego wykonawcy przed zakończeniem pierwszego.")
            self._template_total = event.template_total
            self._current_worker = event.worker_name
            self._current_phase = phase
        elif state is ProgressState.WORKER_END:
            self._expect_phase(phase, PhaseState.RUNNING)
            if self._current_worker != event.worker_name:
                raise ProgressProtocolError("WORKER_END nie pasuje do bieżącego wykonawcy.")
            self._templates_completed = event.template_index
            self._rows += event.rows
            self._issue_count = event.issue_count
            assert event.worker_name is not None
            assert event.status is not None
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
            self._current_phase = None
        elif state is ProgressState.FAILED:
            self._expect_phase(phase, PhaseState.RUNNING)
            self._phase_states[phase] = PhaseState.FAILED
            if event.phase_elapsed_ms is not None:
                self._phase_durations_ms[phase] = event.phase_elapsed_ms
            if event.worker_name is not None:
                self._current_worker = event.worker_name
                self._current_phase = phase
            elif self._current_phase is None:
                self._current_phase = phase

    def _expect_phase(self, phase: ProgressPhase, expected: PhaseState | tuple[PhaseState, ...]) -> None:
        expected_states = (expected,) if isinstance(expected, PhaseState) else expected
        if self._phase_states[phase] not in expected_states:
            expected_label = "/".join(state.value for state in expected_states)
            raise ProgressProtocolError(
                f"Faza {phase.value} ma stan {self._phase_states[phase].value}, oczekiwano {expected_label}."
            )

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

    @staticmethod
    def _notice(event: ProgressEvent) -> ProgressNotice:
        kind_by_state = {
            ProgressState.START: ProgressNoticeKind.PHASE_STARTED,
            ProgressState.END: ProgressNoticeKind.PHASE_ENDED,
            ProgressState.ISSUE_COUNT: ProgressNoticeKind.ISSUE_COUNT,
            ProgressState.PLAN_READY: ProgressNoticeKind.PLAN_READY,
            ProgressState.WORKER_START: ProgressNoticeKind.WORKER_STARTED,
            ProgressState.WORKER_END: ProgressNoticeKind.WORKER_ENDED,
            ProgressState.FAILED: ProgressNoticeKind.FAILED,
        }
        return ProgressNotice(
            kind=kind_by_state[ProgressState(event.state)],
            phase=ProgressPhase(event.phase),
            worker_name=event.worker_name,
            status=event.status,
            rows=event.rows,
            worker_elapsed_ms=event.worker_elapsed_ms,
        )

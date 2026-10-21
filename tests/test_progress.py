from __future__ import annotations


import pytest

from rozliczenia.domain import (
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
    WorkerStatus,
)
from rozliczenia.progress import (
    PhaseState,
    ProgressProjection,
)


def until_saving(template_total: int, *, issue_count: int = 0) -> list[ProgressEvent]:
    """Zdarzenia przebiegu od Sprawdzania do rozpoczęcia Zapisywania, z czasem rosnącym o 1 ms."""

    events: list[ProgressEvent] = []
    for phase in (ProgressPhase.CHECKING, ProgressPhase.READING, ProgressPhase.PLANNING):
        events.append(PhaseStarted(phase, elapsed_ms=len(events)))
        events.append(PhaseEnded(phase, elapsed_ms=len(events), phase_elapsed_ms=1))
        if phase is ProgressPhase.READING:
            events.append(IssueCountReady(elapsed_ms=len(events), issue_count=issue_count))
    events.append(PlanReady(elapsed_ms=len(events), template_total=template_total, issue_count=issue_count))
    events.append(PhaseStarted(ProgressPhase.SAVING, elapsed_ms=len(events)))
    return events


def project(events: list[ProgressEvent]) -> ProgressProjection:
    projection = ProgressProjection("RUN", "08_14_09_2026")
    for event in events:
        projection.update(event)
    return projection


def ended(worker_name: str, index: int, total: int, status: WorkerStatus = "ZAPISANO", rows: int = 1) -> WorkerEnded:
    return WorkerEnded(
        worker_name,
        template_index=index,
        template_total=total,
        status=status,
        rows=rows,
        elapsed_ms=20 + index,
        worker_elapsed_ms=4,
        issue_count=0,
    )


def test_projection_reduces_failed_przetworzenie_szablonu_pracownika_without_counting_it_as_completed() -> None:
    projection = project(
        [
            *until_saving(2),
            WorkerStarted("Adrian Testowy", template_index=1, template_total=2, elapsed_ms=10),
            ended("Adrian Testowy", 1, 2, rows=2),
            WorkerStarted("Darek Fikcyjny", template_index=2, template_total=2, elapsed_ms=12),
        ]
    )

    failed = WorkerFailed(
        "Darek Fikcyjny", template_index=2, template_total=2, elapsed_ms=25, phase_elapsed_ms=5, worker_elapsed_ms=3
    )
    update = projection.update(failed)

    snapshot = update.snapshot
    assert update.event is failed
    assert snapshot.phase_states[ProgressPhase.SAVING] is PhaseState.FAILED
    assert snapshot.phase_durations_ms[ProgressPhase.SAVING] == 5
    assert snapshot.current_worker == "Darek Fikcyjny"
    assert snapshot.templates_completed == 1
    assert snapshot.rows == 2
    assert snapshot.operation_counts["ZAPISANO"] == 1
    with pytest.raises(TypeError):
        snapshot.phase_states[ProgressPhase.SAVING] = PhaseState.COMPLETED  # type: ignore[index]


def test_projection_reduces_complete_przebieg_rozliczen_to_one_snapshot() -> None:
    projection = project(
        [
            *until_saving(2, issue_count=1),
            WorkerStarted("Adrian Testowy", template_index=1, template_total=2, elapsed_ms=9),
            WorkerEnded(
                "Adrian Testowy",
                template_index=1,
                template_total=2,
                status="ZAPISANO",
                rows=2,
                elapsed_ms=12,
                worker_elapsed_ms=3,
                issue_count=1,
            ),
            WorkerStarted("Darek Fikcyjny", template_index=2, template_total=2, elapsed_ms=13),
            WorkerEnded(
                "Darek Fikcyjny",
                template_index=2,
                template_total=2,
                status="PUSTY_SZABLON",
                rows=0,
                elapsed_ms=14,
                worker_elapsed_ms=1,
                issue_count=1,
            ),
        ]
    )

    update = projection.update(PhaseEnded(ProgressPhase.SAVING, elapsed_ms=16, phase_elapsed_ms=7, template_total=2))

    snapshot = update.snapshot
    assert all(state is PhaseState.COMPLETED for state in snapshot.phase_states.values())
    assert snapshot.template_total == 2
    assert snapshot.templates_completed == 2
    assert snapshot.rows == 2
    assert snapshot.operation_counts == {"ZAPISANO": 1, "PUSTY_SZABLON": 1}
    assert snapshot.current_worker is None
    assert snapshot.current_phase is None
    assert snapshot.recent_operations[-1].worker_name == "Darek Fikcyjny"
    assert snapshot.phase_durations_ms[ProgressPhase.SAVING] == 7
    assert snapshot.total_elapsed_ms == 16
    assert snapshot.issue_count == 1


def test_projection_marks_failed_faza_przebiegu() -> None:
    projection = project([PhaseStarted(ProgressPhase.CHECKING, elapsed_ms=1)])

    update = projection.update(PhaseFailed(ProgressPhase.CHECKING, elapsed_ms=3, phase_elapsed_ms=2))

    assert update.snapshot.phase_states[ProgressPhase.CHECKING] is PhaseState.FAILED
    assert update.snapshot.current_phase is ProgressPhase.CHECKING
    assert update.snapshot.phase_durations_ms[ProgressPhase.CHECKING] == 2

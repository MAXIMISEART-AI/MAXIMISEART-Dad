from __future__ import annotations

from io import StringIO
from types import MappingProxyType

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
from rozliczenia.plain_progress import PlainProgressAdapter
from rozliczenia.progress import (
    OperationSnapshot,
    PhaseState,
    ProgressProjection,
    ProgressSnapshot,
)
from rozliczenia.rich_progress import RichProgressAdapter


def render_with_rich(snapshot: ProgressSnapshot, event: ProgressEvent | None = None) -> str:
    rich_console = pytest.importorskip("rich.console")
    output = StringIO()
    rich_console.Console(file=output, color_system=None).print(RichProgressAdapter().render(snapshot, event))
    return output.getvalue()


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
            WorkerStarted("Adrian Maciejewski", template_index=1, template_total=2, elapsed_ms=10),
            ended("Adrian Maciejewski", 1, 2, rows=2),
            WorkerStarted("Darek Nowak", template_index=2, template_total=2, elapsed_ms=12),
        ]
    )

    failed = WorkerFailed(
        "Darek Nowak", template_index=2, template_total=2, elapsed_ms=25, phase_elapsed_ms=5, worker_elapsed_ms=3
    )
    update = projection.update(failed)

    snapshot = update.snapshot
    assert update.event is failed
    assert snapshot.phase_states[ProgressPhase.SAVING] is PhaseState.FAILED
    assert snapshot.phase_durations_ms[ProgressPhase.SAVING] == 5
    assert snapshot.current_worker == "Darek Nowak"
    assert snapshot.templates_completed == 1
    assert snapshot.rows == 2
    assert snapshot.operation_counts["ZAPISANO"] == 1
    with pytest.raises(TypeError):
        snapshot.phase_states[ProgressPhase.SAVING] = PhaseState.COMPLETED  # type: ignore[index]


def test_projection_reduces_complete_przebieg_rozliczen_to_one_snapshot() -> None:
    projection = project(
        [
            *until_saving(2, issue_count=1),
            WorkerStarted("Adrian Maciejewski", template_index=1, template_total=2, elapsed_ms=9),
            WorkerEnded(
                "Adrian Maciejewski",
                template_index=1,
                template_total=2,
                status="ZAPISANO",
                rows=2,
                elapsed_ms=12,
                worker_elapsed_ms=3,
                issue_count=1,
            ),
            WorkerStarted("Darek Nowak", template_index=2, template_total=2, elapsed_ms=13),
            WorkerEnded(
                "Darek Nowak",
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
    assert snapshot.recent_operations[-1].worker_name == "Darek Nowak"
    assert snapshot.phase_durations_ms[ProgressPhase.SAVING] == 7
    assert snapshot.total_elapsed_ms == 16
    assert snapshot.issue_count == 1


def test_projection_marks_failed_faza_przebiegu() -> None:
    projection = project([PhaseStarted(ProgressPhase.CHECKING, elapsed_ms=1)])

    update = projection.update(PhaseFailed(ProgressPhase.CHECKING, elapsed_ms=3, phase_elapsed_ms=2))

    assert update.snapshot.phase_states[ProgressPhase.CHECKING] is PhaseState.FAILED
    assert update.snapshot.current_phase is ProgressPhase.CHECKING
    assert update.snapshot.phase_durations_ms[ProgressPhase.CHECKING] == 2

    plain_lines: list[str] = []
    PlainProgressAdapter(plain_lines.append).update(update.snapshot, update.event)
    rich_output = render_with_rich(update.snapshot, update.event)

    assert "Etap przerwany: Sprawdzanie" in plain_lines
    assert "[przerwany]" in rich_output
    assert "Sprawdzanie" in rich_output
    assert "2 ms" in rich_output


def test_plain_and_rich_adapters_render_the_same_immutable_snapshot() -> None:
    projection = project([*until_saving(1), WorkerStarted("Darek Nowak", template_index=1, template_total=1, elapsed_ms=10)])
    update = projection.update(ended("Darek Nowak", 1, 1))

    plain_lines: list[str] = []
    PlainProgressAdapter(plain_lines.append).update(update.snapshot, update.event)
    rich_output = render_with_rich(update.snapshot, update.event)

    assert "Postęp szablonów: 1/1 (100%)" in plain_lines
    assert any("Darek Nowak | ZAPISANO" in line for line in plain_lines)
    assert "Darek Nowak" in rich_output
    assert "OK: ZAPISANO" in rich_output

    failure_projection = project(
        [*until_saving(1), WorkerStarted("Darek Nowak", template_index=1, template_total=1, elapsed_ms=10)]
    )
    failure_update = failure_projection.update(
        WorkerFailed("Darek Nowak", template_index=1, template_total=1, elapsed_ms=11, phase_elapsed_ms=1, worker_elapsed_ms=1)
    )
    failure_lines: list[str] = []
    PlainProgressAdapter(failure_lines.append).update(failure_update.snapshot, failure_update.event)
    failure_output = render_with_rich(failure_update.snapshot, failure_update.event)

    assert (
        "Etap przerwany: Zapisywanie | WYKONAWCA: Darek Nowak | Szablon pracownika: 1/1"
        in failure_lines
    )
    assert "przerwany" in failure_output
    assert "Darek Nowak" in failure_output
    assert "Przerwano przy szablonie pracownika: 1/1" in failure_output


def test_rich_adapter_renders_a_progress_snapshot_without_projection_state() -> None:
    snapshot = ProgressSnapshot(
        mode="RUN",
        period="08_14_09_2026",
        phase_states=MappingProxyType(
            {
                ProgressPhase.CHECKING: PhaseState.COMPLETED,
                ProgressPhase.READING: PhaseState.COMPLETED,
                ProgressPhase.PLANNING: PhaseState.COMPLETED,
                ProgressPhase.SAVING: PhaseState.RUNNING,
            }
        ),
        phase_durations_ms=MappingProxyType(
            {
                ProgressPhase.CHECKING: 1,
                ProgressPhase.READING: 2,
                ProgressPhase.PLANNING: 3,
                ProgressPhase.SAVING: 0,
            }
        ),
        template_total=2,
        templates_completed=1,
        rows=3,
        operation_counts=MappingProxyType({"ZAPISANO": 1}),
        current_worker="Darek Nowak",
        current_phase=ProgressPhase.SAVING,
        recent_operations=(OperationSnapshot("Adrian Maciejewski", "ZAPISANO", 3, 4),),
        total_elapsed_ms=12,
        issue_count=1,
    )
    event = WorkerEnded(
        "Adrian Maciejewski",
        template_index=1,
        template_total=2,
        status="ZAPISANO",
        rows=3,
        elapsed_ms=12,
        worker_elapsed_ms=4,
        issue_count=1,
    )
    rendered = render_with_rich(snapshot, event)
    assert "Sprawdzanie" in rendered
    assert "[gotowe]" in rendered
    assert "1 ms" in rendered
    assert "2 ms" in rendered
    assert "3 ms" in rendered
    assert "Postęp szablonów: 1/2 (50%)" in rendered
    assert "Liczniki: zapisano: 1 | puste: 0 | planowane: 0" in rendered
    assert "Bieżący WYKONAWCA: Darek Nowak" in rendered
    assert "Adrian Maciejewski" in rendered
    assert "3 wierszy, czas: 4 ms" in rendered
    assert "Wiersze danych: 3 | Czas: 12 ms" in rendered

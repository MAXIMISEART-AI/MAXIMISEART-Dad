from __future__ import annotations

from io import StringIO
from types import MappingProxyType
from collections.abc import Callable
from typing import cast

import pytest

from rozliczenia.domain import (
    ProgressEvent,
    ProgressEventFactory,
    ProgressPhase,
    ProgressProtocolError,
    ProgressState,
)
from rozliczenia.plain_progress import PlainProgressAdapter
from rozliczenia.progress import (
    OperationSnapshot,
    PhaseState,
    ProgressNotice,
    ProgressNoticeKind,
    ProgressProjection,
    ProgressSnapshot,
)
from rozliczenia.rich_progress import RichProgressAdapter


def render_with_rich(snapshot: ProgressSnapshot, notice: ProgressNotice | None = None) -> str:
    rich_console = pytest.importorskip("rich.console")
    output = StringIO()
    rich_console.Console(file=output, color_system=None).print(RichProgressAdapter().render(snapshot, notice))
    return output.getvalue()


def test_progress_event_keeps_string_compatible_typed_values() -> None:
    event = ProgressEvent(
        cast(ProgressPhase, "Sprawdzanie"),
        cast(ProgressState, "START"),
        elapsed_ms=4,
    )

    assert event.phase is ProgressPhase.CHECKING
    assert event.phase.value == "Sprawdzanie"
    assert event.state is ProgressState.START
    assert event.state.value == "START"
    assert ProgressEventFactory.phase_started("Sprawdzanie") == ProgressEvent(
        ProgressPhase.CHECKING,
        ProgressState.START,
    )


def test_invalid_progress_event_combination_is_rejected_at_construction() -> None:
    invalid_events: tuple[Callable[[], ProgressEvent], ...] = (
        lambda: ProgressEvent(ProgressPhase.CHECKING, ProgressState.START, elapsed_ms=-1),
        lambda: ProgressEvent(ProgressPhase.CHECKING, ProgressState.START, worker_name="Adrian"),
        lambda: ProgressEvent(ProgressPhase.READING, ProgressState.ISSUE_COUNT, worker_name="Adrian", issue_count=1),
        lambda: ProgressEvent(ProgressPhase.READING, ProgressState.ISSUE_COUNT, phase_elapsed_ms=1),
        lambda: ProgressEvent(ProgressPhase.PLANNING, ProgressState.PLAN_READY, status="ZAPISANO", template_total=1),
        lambda: ProgressEvent(
            ProgressPhase.PLANNING,
            ProgressState.WORKER_START,
            worker_name="Adrian",
            template_index=1,
            template_total=1,
        ),
        lambda: ProgressEvent(ProgressPhase.CHECKING, ProgressState.FAILED, worker_elapsed_ms=1),
        lambda: ProgressEvent(ProgressPhase.CHECKING, ProgressState.END, elapsed_ms=1, phase_elapsed_ms=2),
        lambda: ProgressEvent(
            ProgressPhase.SAVING,
            ProgressState.WORKER_END,
            worker_name="Adrian",
            template_index=1,
            template_total=1,
            status="ZAPISANO",
            rows=1,
            elapsed_ms=1,
            worker_elapsed_ms=2,
        ),
    )

    for create_event in invalid_events:
        with pytest.raises(ProgressProtocolError):
            create_event()


def test_projection_reduces_failed_przetworzenie_szablonu_pracownika_without_counting_it_as_completed() -> None:
    projection = ProgressProjection("RUN", "08_14_09_2026")
    events = (
        ProgressEventFactory.phase_started("Sprawdzanie"),
        ProgressEventFactory.phase_ended("Sprawdzanie"),
        ProgressEventFactory.phase_started("Odczyt danych"),
        ProgressEventFactory.phase_ended("Odczyt danych"),
        ProgressEventFactory.issue_count(),
        ProgressEventFactory.phase_started("Planowanie"),
        ProgressEventFactory.phase_ended("Planowanie", phase_elapsed_ms=2),
        ProgressEventFactory.plan_ready(template_total=2, issue_count=0),
        ProgressEventFactory.phase_started("Zapisywanie"),
        ProgressEventFactory.worker_started("Adrian Maciejewski", template_index=1, template_total=2),
        ProgressEventFactory.worker_ended(
            "Adrian Maciejewski",
            template_index=1,
            template_total=2,
            status="ZAPISANO",
            rows=2,
        ),
        ProgressEventFactory.worker_started("Darek Nowak", template_index=2, template_total=2),
    )
    for event in events:
        projection.update(event)

    update = projection.update(
        ProgressEventFactory.worker_failed(
            "Darek Nowak",
            template_index=2,
            template_total=2,
            elapsed_ms=15,
            phase_elapsed_ms=5,
            worker_elapsed_ms=3,
        )
    )

    snapshot = update.snapshot
    assert update.notice.kind is ProgressNoticeKind.FAILED
    assert update.notice.template_index == 2
    assert update.notice.template_total == 2
    assert snapshot.phase_states[ProgressPhase.SAVING] is PhaseState.FAILED
    assert snapshot.phase_durations_ms[ProgressPhase.SAVING] == 5
    assert snapshot.current_worker == "Darek Nowak"
    assert snapshot.templates_completed == 1
    assert snapshot.rows == 2
    assert snapshot.operation_counts["ZAPISANO"] == 1
    with pytest.raises(TypeError):
        snapshot.phase_states[ProgressPhase.SAVING] = PhaseState.COMPLETED  # type: ignore[index]


def test_projection_reduces_complete_przebieg_rozliczen_to_one_snapshot() -> None:
    projection = ProgressProjection("RUN", "08_14_09_2026")
    events = (
        ProgressEventFactory.phase_started(ProgressPhase.CHECKING, elapsed_ms=1),
        ProgressEventFactory.phase_ended(
            ProgressPhase.CHECKING,
            elapsed_ms=2,
            phase_elapsed_ms=1,
        ),
        ProgressEventFactory.phase_started(ProgressPhase.READING, elapsed_ms=3),
        ProgressEventFactory.phase_ended(
            ProgressPhase.READING,
            elapsed_ms=5,
            phase_elapsed_ms=2,
        ),
        ProgressEventFactory.issue_count(elapsed_ms=5, issue_count=1),
        ProgressEventFactory.phase_started(ProgressPhase.PLANNING, elapsed_ms=6),
        ProgressEventFactory.phase_ended(
            ProgressPhase.PLANNING,
            elapsed_ms=8,
            phase_elapsed_ms=2,
        ),
        ProgressEventFactory.plan_ready(elapsed_ms=8, template_total=2, issue_count=1),
        ProgressEventFactory.phase_started(ProgressPhase.SAVING, elapsed_ms=9),
        ProgressEventFactory.worker_started(
            "Adrian Maciejewski",
            template_index=1,
            template_total=2,
            elapsed_ms=9,
        ),
        ProgressEventFactory.worker_ended(
            "Adrian Maciejewski",
            template_index=1,
            template_total=2,
            status="ZAPISANO",
            rows=2,
            elapsed_ms=12,
            worker_elapsed_ms=3,
            issue_count=1,
        ),
        ProgressEventFactory.worker_started(
            "Darek Nowak",
            template_index=2,
            template_total=2,
            elapsed_ms=13,
        ),
        ProgressEventFactory.worker_ended(
            "Darek Nowak",
            template_index=2,
            template_total=2,
            status="PUSTY_SZABLON",
            rows=0,
            elapsed_ms=14,
            worker_elapsed_ms=1,
            issue_count=1,
        ),
    )

    for event in events:
        projection.update(event)
    update = projection.update(
        ProgressEventFactory.phase_ended(
            ProgressPhase.SAVING,
            elapsed_ms=16,
            phase_elapsed_ms=7,
            template_index=2,
            template_total=2,
        )
    )

    snapshot = update.snapshot
    assert update.notice.kind is ProgressNoticeKind.PHASE_ENDED
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


def test_projection_marks_failed_faza_przebiegu_without_accepting_later_events() -> None:
    projection = ProgressProjection("RUN", "08_14_09_2026")
    projection.update(ProgressEventFactory.phase_started("Sprawdzanie"))

    update = projection.update(
        ProgressEventFactory.phase_failed("Sprawdzanie", elapsed_ms=3, phase_elapsed_ms=2)
    )

    assert update.notice.kind is ProgressNoticeKind.FAILED
    assert update.snapshot.phase_states[ProgressPhase.CHECKING] is PhaseState.FAILED
    assert update.snapshot.current_phase is ProgressPhase.CHECKING
    assert update.snapshot.phase_durations_ms[ProgressPhase.CHECKING] == 2

    plain_lines: list[str] = []
    PlainProgressAdapter(plain_lines.append).update(update.snapshot, update.notice)
    rich_output = render_with_rich(update.snapshot, update.notice)

    assert "Etap przerwany: Sprawdzanie" in plain_lines
    assert "[przerwany]" in rich_output
    assert "Sprawdzanie" in rich_output
    assert "2 ms" in rich_output
    with pytest.raises(ProgressProtocolError):
        projection.update(ProgressEventFactory.phase_ended("Sprawdzanie"))


def test_projection_rejects_out_of_order_event_without_changing_snapshot() -> None:
    projection = ProgressProjection("RUN", "08_14_09_2026")
    initial = projection.snapshot

    with pytest.raises(ProgressProtocolError):
        projection.update(ProgressEventFactory.phase_started(ProgressPhase.PLANNING))

    assert projection.snapshot == initial


def test_projection_rejects_mismatched_worker_event_without_changing_snapshot() -> None:
    projection = ProgressProjection("RUN", "08_14_09_2026")
    for event in (
        ProgressEventFactory.phase_started("Sprawdzanie"),
        ProgressEventFactory.phase_ended("Sprawdzanie"),
        ProgressEventFactory.phase_started("Odczyt danych"),
        ProgressEventFactory.phase_ended("Odczyt danych"),
        ProgressEventFactory.issue_count(),
        ProgressEventFactory.phase_started("Planowanie"),
        ProgressEventFactory.phase_ended("Planowanie"),
        ProgressEventFactory.plan_ready(template_total=2),
        ProgressEventFactory.phase_started("Zapisywanie"),
        ProgressEventFactory.worker_started("Adrian Maciejewski", template_index=1, template_total=2),
    ):
        projection.update(event)
    before = projection.snapshot

    with pytest.raises(ProgressProtocolError):
        projection.update(
            ProgressEventFactory.worker_ended(
                "Adrian Maciejewski",
                template_index=2,
                template_total=2,
                status="ZAPISANO",
                rows=1,
            )
        )

    assert projection.snapshot == before


def test_projection_rejects_elapsed_time_regression_without_changing_snapshot() -> None:
    projection = ProgressProjection("RUN", "08_14_09_2026")
    projection.update(ProgressEventFactory.phase_started("Sprawdzanie", elapsed_ms=5))
    before = projection.snapshot

    with pytest.raises(ProgressProtocolError):
        projection.update(ProgressEventFactory.phase_ended("Sprawdzanie", elapsed_ms=4))

    assert projection.snapshot == before


def test_plain_and_rich_adapters_render_the_same_immutable_snapshot() -> None:
    projection = ProgressProjection("RUN", "08_14_09_2026")
    for event in (
        ProgressEventFactory.phase_started("Sprawdzanie"),
        ProgressEventFactory.phase_ended("Sprawdzanie"),
        ProgressEventFactory.phase_started("Odczyt danych"),
        ProgressEventFactory.phase_ended("Odczyt danych"),
        ProgressEventFactory.issue_count(),
        ProgressEventFactory.phase_started("Planowanie"),
        ProgressEventFactory.phase_ended("Planowanie"),
        ProgressEventFactory.plan_ready(template_total=1),
        ProgressEventFactory.phase_started("Zapisywanie"),
        ProgressEventFactory.worker_started("Darek Nowak", template_index=1, template_total=1),
    ):
        projection.update(event)
    update = projection.update(
        ProgressEventFactory.worker_ended(
            "Darek Nowak",
            template_index=1,
            template_total=1,
            status="ZAPISANO",
            rows=1,
            worker_elapsed_ms=4,
        )
    )

    plain_lines: list[str] = []
    PlainProgressAdapter(plain_lines.append).update(update.snapshot, update.notice)
    rich_output = render_with_rich(update.snapshot, update.notice)

    assert "Postęp szablonów: 1/1 (100%)" in plain_lines
    assert any("Darek Nowak | ZAPISANO" in line for line in plain_lines)
    assert "Darek Nowak" in rich_output
    assert "OK: ZAPISANO" in rich_output

    failure_projection = ProgressProjection("RUN", "08_14_09_2026")
    for event in (
        ProgressEventFactory.phase_started("Sprawdzanie"),
        ProgressEventFactory.phase_ended("Sprawdzanie"),
        ProgressEventFactory.phase_started("Odczyt danych"),
        ProgressEventFactory.phase_ended("Odczyt danych"),
        ProgressEventFactory.issue_count(),
        ProgressEventFactory.phase_started("Planowanie"),
        ProgressEventFactory.phase_ended("Planowanie"),
        ProgressEventFactory.plan_ready(template_total=1),
        ProgressEventFactory.phase_started("Zapisywanie"),
        ProgressEventFactory.worker_started("Darek Nowak", template_index=1, template_total=1),
    ):
        failure_projection.update(event)
    failure_update = failure_projection.update(
        ProgressEventFactory.worker_failed("Darek Nowak", template_index=1, template_total=1)
    )
    failure_lines: list[str] = []
    PlainProgressAdapter(failure_lines.append).update(failure_update.snapshot, failure_update.notice)
    failure_output = render_with_rich(failure_update.snapshot, failure_update.notice)

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
    notice = ProgressNotice(
        kind=ProgressNoticeKind.WORKER_ENDED,
        phase=ProgressPhase.SAVING,
        worker_name="Adrian Maciejewski",
        status="ZAPISANO",
        rows=3,
        worker_elapsed_ms=4,
    )
    rendered = render_with_rich(snapshot, notice)
    assert "Sprawdzanie" in rendered
    assert "[gotowe]" in rendered
    assert "1 ms" in rendered
    assert "2 ms" in rendered
    assert "3 ms" in rendered
    assert "Postęp szablonów: 1/2 (50%)" in rendered
    assert "Liczniki: zapisano: 1 | puste: 0 | planowane: 0 | pominięte: 0" in rendered
    assert "Bieżący WYKONAWCA: Darek Nowak" in rendered
    assert "Adrian Maciejewski" in rendered
    assert "3 wierszy, czas: 4 ms" in rendered
    assert "Wiersze danych: 3 | Czas: 12 ms" in rendered

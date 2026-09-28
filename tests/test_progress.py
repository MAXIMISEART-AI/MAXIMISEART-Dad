from __future__ import annotations

from io import StringIO

import pytest
from rich.console import Console

from rozliczenia.cli import PlainProgressAdapter, RichProgressAdapter
from rozliczenia.domain import (
    ProgressEvent,
    ProgressEventFactory,
    ProgressPhase,
    ProgressProtocolError,
    ProgressState,
)
from rozliczenia.progress import PhaseState, ProgressNoticeKind, ProgressProjection


def test_progress_event_keeps_string_compatible_typed_values() -> None:
    event = ProgressEvent("Sprawdzanie", "START", elapsed_ms=4)

    assert event.phase is ProgressPhase.CHECKING
    assert event.phase == "Sprawdzanie"
    assert event.state is ProgressState.START
    assert event.state == "START"
    assert ProgressEventFactory.phase_started("Sprawdzanie") == ProgressEvent("Sprawdzanie", "START")


def test_invalid_progress_event_combination_is_rejected_at_construction() -> None:
    invalid_events = (
        lambda: ProgressEvent("Sprawdzanie", "START", elapsed_ms=-1),
        lambda: ProgressEvent("Sprawdzanie", "START", worker_name="Adrian"),
        lambda: ProgressEvent("Odczyt danych", "ISSUE_COUNT", worker_name="Adrian", issue_count=1),
        lambda: ProgressEvent("Odczyt danych", "ISSUE_COUNT", phase_elapsed_ms=1),
        lambda: ProgressEvent("Planowanie", "PLAN_READY", status="ZAPISANO", template_total=1),
        lambda: ProgressEvent(
            "Planowanie", "WORKER_START", worker_name="Adrian", template_index=1, template_total=1
        ),
        lambda: ProgressEvent("Sprawdzanie", "FAILED", worker_elapsed_ms=1),
    )

    for create_event in invalid_events:
        with pytest.raises(ProgressProtocolError):
            create_event()


def test_projection_reduces_failed_przetworzenie_szablonu_pracownika_without_counting_it_as_completed() -> None:
    projection = ProgressProjection("RUN", "08_14_09_2026")
    events = (
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
            worker_elapsed_ms=3,
        )
    )

    snapshot = update.snapshot
    assert update.notice.kind is ProgressNoticeKind.FAILED
    assert snapshot.phase_states[ProgressPhase.SAVING] is PhaseState.FAILED
    assert snapshot.current_worker == "Darek Nowak"
    assert snapshot.templates_completed == 1
    assert snapshot.rows == 2
    assert snapshot.operation_counts["ZAPISANO"] == 1
    with pytest.raises(TypeError):
        snapshot.phase_states[ProgressPhase.SAVING] = PhaseState.COMPLETED  # type: ignore[index]


def test_plain_and_rich_adapters_render_the_same_immutable_snapshot() -> None:
    projection = ProgressProjection("RUN", "08_14_09_2026")
    for event in (
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
    rich_output = StringIO()
    Console(file=rich_output, color_system=None).print(RichProgressAdapter().render(update.snapshot, update.notice))

    assert "Postęp szablonów: 1/1 (100%)" in plain_lines
    assert any("Darek Nowak | ZAPISANO" in line for line in plain_lines)
    assert "Darek Nowak" in rich_output.getvalue()
    assert "OK: ZAPISANO" in rich_output.getvalue()

    failure_projection = ProgressProjection("RUN", "08_14_09_2026")
    for event in (
        ProgressEventFactory.phase_started("Zapisywanie"),
        ProgressEventFactory.worker_started("Darek Nowak", template_index=1, template_total=1),
    ):
        failure_projection.update(event)
    failure_update = failure_projection.update(
        ProgressEventFactory.worker_failed("Darek Nowak", template_index=1, template_total=1)
    )
    failure_lines: list[str] = []
    PlainProgressAdapter(failure_lines.append).update(failure_update.snapshot, failure_update.notice)
    failure_output = StringIO()
    Console(file=failure_output, color_system=None).print(
        RichProgressAdapter().render(failure_update.snapshot, failure_update.notice)
    )

    assert "Etap przerwany: Zapisywanie | WYKONAWCA: Darek Nowak" in failure_lines
    assert "przerwany" in failure_output.getvalue()
    assert "Darek Nowak" in failure_output.getvalue()

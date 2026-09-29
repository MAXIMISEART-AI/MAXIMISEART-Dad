from __future__ import annotations

from rozliczenia.domain import ProgressEventFactory, ProgressPhase
from rozliczenia.progress import ProgressProjection
from rozliczenia.plain_progress import PlainProgressAdapter


def projection_ready_for_workers(*, template_total: int) -> ProgressProjection:
    projection = ProgressProjection("RUN", "08_14_09_2026")
    for event in (
        ProgressEventFactory.phase_started(ProgressPhase.CHECKING),
        ProgressEventFactory.phase_ended(ProgressPhase.CHECKING),
        ProgressEventFactory.phase_started(ProgressPhase.READING),
        ProgressEventFactory.phase_ended(ProgressPhase.READING),
        ProgressEventFactory.issue_count(),
        ProgressEventFactory.phase_started(ProgressPhase.PLANNING),
        ProgressEventFactory.phase_ended(ProgressPhase.PLANNING),
        ProgressEventFactory.plan_ready(template_total=template_total),
        ProgressEventFactory.phase_started(ProgressPhase.SAVING),
    ):
        projection.update(event)
    return projection


def test_plain_adapter_start_renders_mode_and_period_from_snapshot() -> None:
    lines: list[str] = []

    PlainProgressAdapter(lines.append).start(ProgressProjection("RUN", "08_14_09_2026").snapshot)

    assert lines == [
        "Rozliczenia | okres: 08_14_09_2026 | tryb: RUN",
        "Status: uruchomiono",
        "Ostatnie operacje:",
    ]


def test_plain_adapter_renders_worker_end_details_from_projected_snapshot() -> None:
    lines: list[str] = []
    projection = projection_ready_for_workers(template_total=3)
    for event in (
        ProgressEventFactory.worker_started("Saved worker", template_index=1, template_total=3),
        ProgressEventFactory.worker_ended(
            "Saved worker",
            template_index=1,
            template_total=3,
            status="ZAPISANO",
            rows=5,
            worker_elapsed_ms=16,
        ),
        ProgressEventFactory.worker_started("Snapshot worker", template_index=2, template_total=3),
    ):
        projection.update(event)
    update = projection.update(
        ProgressEventFactory.worker_ended(
            "Snapshot worker",
            template_index=2,
            template_total=3,
            status="PUSTY_SZABLON",
            rows=0,
            worker_elapsed_ms=42,
        )
    )

    PlainProgressAdapter(lines.append).update(update.snapshot, update.notice)

    assert lines == [
        "Postęp szablonów: 2/3 (67%)",
        "Liczniki: zapisano: 1 | puste: 1 | planowane: 0 | pominięte: 0",
        "Ostatnia operacja: Snapshot worker | PUSTY_SZABLON | status: OK | wiersze: 0 | czas: 42 ms",
    ]


def test_plain_adapter_renders_current_worker_and_phase_from_snapshot() -> None:
    lines: list[str] = []
    projection = projection_ready_for_workers(template_total=1)
    started = projection.update(
        ProgressEventFactory.worker_started("Snapshot worker", template_index=1, template_total=1)
    )
    failed = projection.update(
        ProgressEventFactory.worker_failed("Snapshot worker", template_index=1, template_total=1)
    )
    adapter = PlainProgressAdapter(lines.append)

    adapter.update(started.snapshot, started.notice)
    adapter.update(failed.snapshot, failed.notice)

    assert lines == [
        "WYKONAWCA: Snapshot worker | etap: Zapisywanie",
        "Etap przerwany: Zapisywanie | WYKONAWCA: Snapshot worker | Szablon pracownika: 1/1",
    ]

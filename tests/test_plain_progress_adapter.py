from __future__ import annotations

from types import MappingProxyType

from rozliczenia.domain import ProgressPhase
from rozliczenia.progress import (
    OperationSnapshot,
    PhaseState,
    ProgressNotice,
    ProgressNoticeKind,
    ProgressSnapshot,
)
from rozliczenia.plain_progress import PlainProgressAdapter


def progress_snapshot(
    *,
    current_worker: str | None = None,
    current_phase: ProgressPhase | None = None,
) -> ProgressSnapshot:
    return ProgressSnapshot(
        mode="RUN",
        period="08_14_09_2026",
        phase_states=MappingProxyType({phase: PhaseState.PENDING for phase in ProgressPhase}),
        phase_durations_ms=MappingProxyType({phase: 0 for phase in ProgressPhase}),
        template_total=3,
        templates_completed=2,
        rows=5,
        operation_counts=MappingProxyType(
            {
                "ZAPISANO": 1,
                "PUSTY_SZABLON": 1,
                "PLAN": 1,
                "ZABLOKOWANY": 1,
                "POMINIĘTO": 1,
            }
        ),
        current_worker=current_worker,
        current_phase=current_phase,
        recent_operations=(
            OperationSnapshot("Snapshot worker", "PUSTY_SZABLON", 5, 42),
        ),
        total_elapsed_ms=123,
        issue_count=0,
    )


def test_plain_adapter_start_renders_mode_and_period_from_snapshot() -> None:
    lines: list[str] = []

    PlainProgressAdapter(lines.append).start(progress_snapshot())

    assert lines == [
        "Rozliczenia | okres: 08_14_09_2026 | tryb: RUN",
        "Status: uruchomiono",
        "Ostatnie operacje:",
    ]


def test_plain_adapter_renders_worker_end_details_from_projected_snapshot() -> None:
    lines: list[str] = []
    notice = ProgressNotice(
        kind=ProgressNoticeKind.WORKER_ENDED,
        phase=ProgressPhase.SAVING,
        worker_name="Notice worker",
        status="POMINIĘTO",
        rows=999,
        worker_elapsed_ms=999,
    )

    PlainProgressAdapter(lines.append).update(progress_snapshot(), notice)

    assert lines == [
        "Postęp szablonów: 2/3 (67%)",
        "Liczniki: zapisano: 1 | puste: 1 | planowane: 1 | pominięte: 2",
        "Ostatnia operacja: Snapshot worker | PUSTY_SZABLON | status: OK | wiersze: 5 | czas: 42 ms",
    ]


def test_plain_adapter_renders_current_worker_and_phase_from_snapshot() -> None:
    lines: list[str] = []
    snapshot = progress_snapshot(
        current_worker="Snapshot worker",
        current_phase=ProgressPhase.SAVING,
    )
    adapter = PlainProgressAdapter(lines.append)

    adapter.update(
        snapshot,
        ProgressNotice(
            kind=ProgressNoticeKind.WORKER_STARTED,
            phase=ProgressPhase.CHECKING,
            worker_name="Notice worker",
        ),
    )
    adapter.update(
        snapshot,
        ProgressNotice(
            kind=ProgressNoticeKind.FAILED,
            phase=ProgressPhase.CHECKING,
            worker_name="Notice worker",
        ),
    )

    assert lines == [
        "WYKONAWCA: Snapshot worker | etap: Zapisywanie",
        "Etap przerwany: Zapisywanie | WYKONAWCA: Snapshot worker",
    ]

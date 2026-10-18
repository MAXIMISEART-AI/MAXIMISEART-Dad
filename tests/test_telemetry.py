"""Rekord metryk Uruchomienia procesu budowany obok swojej walidacji."""

from __future__ import annotations

from pathlib import Path

from rozliczenia.domain import ProgressPhase
from rozliczenia.telemetry import MetricsStore, metric_record

COUNTERS = frozenset({"period_orders", "warnings"})


def test_stopped_uruchomienie_procesu_is_an_incomplete_record_with_every_phase(tmp_path: Path) -> None:
    record = metric_record(
        mode="RUN",
        period="zly okres",
        started_at="2026-09-28T10:00:00+00:00",
        total_duration_ms=12,
        phase_durations_ms={ProgressPhase.CHECKING: 7},
        result="BLAD_KRYTYCZNY",
        counters={"period_orders": 0, "warnings": 0},
    )

    assert record == {
        "schema_version": 1,
        "started_at": "2026-09-28T10:00:00+00:00",
        "mode": "RUN",
        "period": "nieznany",
        "completed": False,
        "result": "BLAD_KRYTYCZNY",
        "total_duration_ms": 12,
        "phase_durations_ms": {"Sprawdzanie": 7, "Odczyt danych": 0, "Planowanie": 0, "Zapisywanie": 0},
        "counters": {"period_orders": 0, "warnings": 0},
    }
    store = MetricsStore(tmp_path / "metrics.jsonl", COUNTERS)
    store.append(record)
    assert store.read() == [record]


def test_finished_uruchomienie_procesu_is_a_completed_record_of_its_period() -> None:
    record = metric_record(
        mode="DRY-RUN",
        period="08_14_09_2026",
        started_at="2026-09-28T10:00:00+00:00",
        total_duration_ms=40,
        phase_durations_ms={phase: 10 for phase in ProgressPhase},
        result="WYMAGA_SPRAWDZENIA",
        counters={"period_orders": 4, "warnings": 1},
    )

    assert (record["period"], record["completed"], record["result"]) == (
        "08_14_09_2026",
        True,
        "WYMAGA_SPRAWDZENIA",
    )

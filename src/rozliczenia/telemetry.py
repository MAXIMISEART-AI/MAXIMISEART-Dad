"""Lokalny, bezpieczny zapis i odczyt metryk uruchomień."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .domain import PHASES


METRICS_SCHEMA_VERSION = 1
MINIMUM_STATISTIC_SAMPLES = 5


class MetricsStore:
    """Dopisuje rekordy JSONL bez przechowywania danych skoroszytów."""

    def __init__(self, path: Path):
        self.path = path.expanduser()

    def append(self, record: dict[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as stream:
            json.dump(record, stream, ensure_ascii=False, separators=(",", ":"))
            stream.write("\n")

    def read(self) -> list[dict[str, Any]]:
        if not self.path.exists():
            return []
        records: list[dict[str, Any]] = []
        with self.path.open("r", encoding="utf-8") as stream:
            for line in stream:
                try:
                    record = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if isinstance(record, dict) and record.get("schema_version") == METRICS_SCHEMA_VERSION:
                    records.append(record)
        return records


def percentile(values: list[float], proportion: float) -> float:
    """Zwraca interpolowany percentyl dla niepustej, posortowanej próby."""

    ordered = sorted(values)
    position = (len(ordered) - 1) * proportion
    lower = int(position)
    upper = min(lower + 1, len(ordered) - 1)
    fraction = position - lower
    return ordered[lower] + (ordered[upper] - ordered[lower]) * fraction


def comparable_records(records: list[dict[str, Any]], mode: str) -> list[dict[str, Any]]:
    return [
        record
        for record in records
        if record.get("mode") == mode and record.get("completed") is True
    ]


def statistics_for(records: list[dict[str, Any]], mode: str) -> dict[str, tuple[int, int]] | None:
    comparable = comparable_records(records, mode)
    if len(comparable) < MINIMUM_STATISTIC_SAMPLES:
        return None

    durations: dict[str, list[float]] = {"total": []}
    for phase in PHASES:
        durations[phase] = []
    for record in comparable:
        durations["total"].append(float(record.get("total_duration_ms", 0)))
        phase_values = record.get("phase_durations_ms", {})
        if not isinstance(phase_values, dict):
            phase_values = {}
        for phase in durations:
            if phase != "total":
                durations[phase].append(float(phase_values.get(phase, 0)))

    return {
        name: (round(percentile(values, 0.50)), round(percentile(values, 0.95)))
        for name, values in durations.items()
    }

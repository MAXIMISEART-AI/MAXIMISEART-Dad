"""Lokalny, bezpieczny zapis i odczyt metryk uruchomień."""

from __future__ import annotations

from datetime import datetime
import json
from pathlib import Path
import re
from typing import Any

from .domain import PHASES


METRICS_SCHEMA_VERSION = 1
MINIMUM_STATISTIC_SAMPLES = 5
METRIC_MODES = frozenset({"RUN", "DRY-RUN"})
METRIC_RESULTS = frozenset({"OK", "WYMAGA_SPRAWDZENIA", "BLAD_KRYTYCZNY"})
COUNTER_NAMES = frozenset(
    {"templates_total", "templates_completed", "rows", "written", "empty", "planned", "skipped", "issues"}
)
PERIOD_PATTERN = re.compile(r"^(?:\d{2}_\d{2}_\d{2}_\d{4}|nieznany)$")
RECORD_FIELDS = frozenset(
    {
        "schema_version",
        "started_at",
        "mode",
        "period",
        "completed",
        "result",
        "total_duration_ms",
        "phase_durations_ms",
        "counters",
    }
)


def _is_nonnegative_int(value: object) -> bool:
    return type(value) is int and value >= 0


def _is_valid_record(record: object) -> bool:
    if not isinstance(record, dict) or set(record) != RECORD_FIELDS:
        return False
    if type(record["schema_version"]) is not int or record["schema_version"] != METRICS_SCHEMA_VERSION:
        return False
    started_at = record["started_at"]
    if not isinstance(started_at, str):
        return False
    try:
        timestamp = datetime.fromisoformat(started_at)
    except ValueError:
        return False
    if timestamp.tzinfo is None:
        return False
    mode = record["mode"]
    result = record["result"]
    if not isinstance(mode, str) or mode not in METRIC_MODES:
        return False
    if not PERIOD_PATTERN.fullmatch(str(record["period"])):
        return False
    if not isinstance(result, str) or result not in METRIC_RESULTS:
        return False
    if type(record["completed"]) is not bool:
        return False
    if not _is_nonnegative_int(record["total_duration_ms"]):
        return False

    phase_durations = record["phase_durations_ms"]
    if not isinstance(phase_durations, dict) or set(phase_durations) != set(PHASES):
        return False
    if not all(_is_nonnegative_int(value) for value in phase_durations.values()):
        return False

    counters = record["counters"]
    if not isinstance(counters, dict) or set(counters) != COUNTER_NAMES:
        return False
    return all(_is_nonnegative_int(value) for value in counters.values())


class MetricsStore:
    """Dopisuje rekordy JSONL bez przechowywania danych skoroszytów."""

    def __init__(self, path: Path):
        self.path = path.expanduser()

    def append(self, record: dict[str, Any]) -> None:
        if not _is_valid_record(record):
            raise ValueError("Niepoprawny rekord metryk.")
        serialized = json.dumps(record, ensure_ascii=False, separators=(",", ":"), allow_nan=False)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as stream:
            stream.write(f"{serialized}\n")

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
                if _is_valid_record(record):
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
        if _is_valid_record(record) and record["mode"] == mode and record["completed"] is True
    ]


def statistics_for(records: list[dict[str, Any]], mode: str) -> dict[str, tuple[int, int]] | None:
    comparable = comparable_records(records, mode)
    if len(comparable) < MINIMUM_STATISTIC_SAMPLES:
        return None

    durations: dict[str, list[float]] = {"total": []}
    for phase in PHASES:
        durations[phase] = []
    for record in comparable:
        durations["total"].append(float(record["total_duration_ms"]))
        phase_values = record.get("phase_durations_ms", {})
        for phase in durations:
            if phase != "total":
                durations[phase].append(float(phase_values[phase]))

    return {
        name: (round(percentile(values, 0.50)), round(percentile(values, 0.95)))
        for name, values in durations.items()
    }

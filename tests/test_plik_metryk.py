"""Plik metryk (``MetricsStore``): jedyne miejsce zapisu rekordu Uruchomienia procesu na dysk."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from rozliczenia import preparation_process, settlement_process
from rozliczenia.telemetry import COUNTER_NAMES, MetricsStore, metric_record
from tests.fixtures.preparation import PERIOD


def completed_record() -> dict[str, Any]:
    return metric_record(
        mode="RUN",
        period=PERIOD,
        started_at="2026-09-15T08:00:00+00:00",
        total_duration_ms=1000,
        phase_durations_ms={},
        result="OK",
        counters=dict.fromkeys(COUNTER_NAMES, 1),
    )


def test_plik_metryk_odrzuca_rekord_ze_sciezka(tmp_path: Path) -> None:
    metrics_path = tmp_path / "metrics.jsonl"
    record = completed_record()
    MetricsStore(metrics_path).append(record)

    with pytest.raises(ValueError):
        MetricsStore(metrics_path).append({**record, "source_path": str(tmp_path / PERIOD)})

    assert MetricsStore(metrics_path).read() == [record]
    assert metrics_path.read_text(encoding="utf-8").count("\n") == 1


@pytest.mark.parametrize(
    "torn",
    [b'{"schema_version":1', b'{"schema_version":1\n', b"\xff\n"],
    ids=["bez-konca-linii", "z-koncem-linii", "nie-utf8"],
)
def test_plik_metryk_naprawia_ucieta_ostatnia_linie(tmp_path: Path, torn: bytes) -> None:
    metrics_path = tmp_path / "metrics.jsonl"
    record = completed_record()
    MetricsStore(metrics_path).append(record)
    with metrics_path.open("ab") as stream:
        stream.write(torn)

    MetricsStore(metrics_path).append(record)

    assert [json.loads(line) for line in metrics_path.read_text(encoding="utf-8").splitlines()] == [record, record]
    assert metrics_path.read_bytes().endswith(b"\n")


@pytest.mark.parametrize("line_end", [b"\n", b""], ids=["z-koncem-linii", "bez-konca-linii"])
def test_plik_metryk_zachowuje_pelny_rekord_innej_wersji_narzedzia(tmp_path: Path, line_end: bytes) -> None:
    metrics_path = tmp_path / "metrics.jsonl"
    record = completed_record()
    other_version = {**record, "counters": {**record["counters"], "nowy_licznik": 3}}
    MetricsStore(metrics_path).append(record)
    with metrics_path.open("ab") as stream:
        stream.write(json.dumps(other_version).encode("utf-8") + line_end)

    MetricsStore(metrics_path).append(record)

    assert [json.loads(line) for line in metrics_path.read_text(encoding="utf-8").splitlines()] == [
        record,
        other_version,
        record,
    ]
    assert MetricsStore(metrics_path).read() == [record, record]


def test_przygotowanie_ma_wlasna_historie_metryk_obok_przebiegu_rozliczen() -> None:
    preparation = preparation_process.PROCESS.metrics_path()

    assert preparation.parent == settlement_process.PROCESS.metrics_path().parent
    assert preparation.name == ".przygotowanie-pliku-zbiorczego-metrics.jsonl"

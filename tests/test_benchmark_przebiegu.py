"""Test dymny benchmarku Przebiegu rozliczeń przez jego CLI, na małym scenariuszu z syntetycznymi Wzorcami."""

from __future__ import annotations

import json
from pathlib import Path

from rozliczenia.worker_config import load_worker_mapping
from tests.fixtures.benchmark import identifying_values, protected_repository_files, run_benchmark, write_templates
from tests.fixtures.settlement import write_mapping

RECORD_FIELDS = {
    "started_at",
    "git_sha",
    "dirty",
    "machine",
    "scenario",
    "runs",
    "wall_ms",
    "czas_uruchomienia_ms",
    "phase_durations_ms",
    "counters",
    "oracle",
}
PHASES = {"Sprawdzanie", "Odczyt danych", "Planowanie", "Zapisywanie"}
SPREAD = {"mediana", "min", "max"}
COMMENT_SECTIONS = ("Hipoteza", "Zmiana", "Pomiar", "Bramka poprawności", "Decyzja", "Następny krok")


def test_benchmark_mierzy_przebieg_rozliczen_na_lustrze_i_opisuje_pomiar_bez_danych_wykonawcow(
    tmp_path: Path,
) -> None:
    config = write_mapping(tmp_path / "worker_mapping.yaml")
    journal = tmp_path / "dziennik.jsonl"
    mirror = tmp_path / "lustro"
    arguments = [
        "measure",
        "--scenario",
        "maly-tydzien",
        "--templates-dir",
        str(write_templates(tmp_path / "wzorce")),
        "--config",
        str(config),
        "--mirror-dir",
        str(mirror),
        "--journal",
        str(journal),
        "--machine",
        "test",
    ]
    repository_before = protected_repository_files()

    first = run_benchmark(*arguments)
    (collective_file,) = mirror.rglob("Rozliczenie * - zbiorcze.xlsx")
    built_at = collective_file.stat().st_mtime_ns
    second = run_benchmark(*arguments)

    assert (first.returncode, second.returncode) == (0, 0), first.stderr + second.stderr
    assert collective_file.stat().st_mtime_ns == built_at  # drugi pomiar używa istniejącego lustra
    assert "Załączniki" in collective_file.parts
    assert collective_file.parent.parent.name == "INEA"
    assert protected_repository_files() == repository_before

    records = [json.loads(line) for line in journal.read_text(encoding="utf-8").splitlines()]
    assert len(records) == 2
    for record in records:
        assert set(record) == RECORD_FIELDS
        assert (record["scenario"], record["machine"], record["runs"]) == ("maly-tydzien", "test", 3)
        assert record["oracle"] is None
        assert len(record["git_sha"]) == 40
        assert isinstance(record["dirty"], bool)
        for spread in (record["wall_ms"], record["czas_uruchomienia_ms"], *record["phase_durations_ms"].values()):
            assert set(spread) == SPREAD
            assert spread["min"] <= spread["mediana"] <= spread["max"]
        assert set(record["phase_durations_ms"]) == PHASES
        assert record["czas_uruchomienia_ms"]["max"] <= record["wall_ms"]["max"]
        assert record["counters"] | {"templates_total": 3, "empty": 1, "rows": 6, "issues": 0} == record["counters"]

    comment = run_benchmark("comment", "--journal", str(journal))
    assert comment.returncode == 0, comment.stderr
    headings = [line for line in comment.stdout.splitlines() if line.startswith("## ")]
    assert headings == [f"## {heading}" for heading in COMMENT_SECTIONS]
    assert "### maly-tydzien" in comment.stdout
    for record in records:
        wall = record["wall_ms"]
        assert f"{wall['mediana']} ({wall['min']}–{wall['max']})" in comment.stdout
        assert record["started_at"] in comment.stdout

    published = "".join(
        [
            *(result.stdout + result.stderr for result in (first, second, comment)),
            journal.read_text(encoding="utf-8"),
        ]
    )
    secrets = identifying_values(collective_file)
    assert len(secrets) == 4 * 6
    secrets |= {*load_worker_mapping(config), *load_worker_mapping(config).values()}
    assert {secret for secret in secrets if secret in published} == set()

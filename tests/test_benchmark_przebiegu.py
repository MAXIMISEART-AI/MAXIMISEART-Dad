"""Test dymny benchmarku Przebiegu rozliczeń przez jego CLI, na małym scenariuszu z syntetycznymi Wzorcami."""

from __future__ import annotations

import json
from pathlib import Path

from rozliczenia.worker_config import load_worker_mapping
from tests.fixtures.benchmark import (
    data_row_entries,
    frozen_reference,
    identifying_values,
    protected_repository_files,
    run_benchmark,
    write_templates,
)
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
ORACLE_CATEGORIES = (
    "pliki",
    "wartosci",
    "formuly",
    "style",
    "scalenia",
    "wymiary",
    "nazwy_zdefiniowane",
    "external_links",
    "flagi_przeliczania",
    "liczniki",
    "komunikaty",
)


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
    entries = data_row_entries(collective_file)
    assert len(entries) == 6
    for quantities_and_charges in entries:  # tata wpisał ilości w N:AP przed Przebiegiem rozliczeń
        assert any(isinstance(value, int) and value > 0 for value in quantities_and_charges[:29])
    assert any(value is not None for row in entries for value in row[29:])

    records = [json.loads(line) for line in journal.read_text(encoding="utf-8").splitlines()]
    assert len(records) == 2
    for record in records:
        assert set(record) == RECORD_FIELDS
        assert (record["scenario"], record["machine"], record["runs"]) == ("maly-tydzien", "test", 3)
        assert record["oracle"] is None  # bez zamrożonego wyniku referencyjnego bramka nie jest sprawdzana
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


def test_benchmark_porownuje_pomiar_z_wynikiem_referencyjnym_zamrozonym_z_commita(tmp_path: Path) -> None:
    config = write_mapping(tmp_path / "worker_mapping.yaml")
    journal = tmp_path / "dziennik.jsonl"
    references = tmp_path / "referencje"
    common = [
        "--scenario",
        "maly-tydzien",
        "--templates-dir",
        str(write_templates(tmp_path / "wzorce")),
        "--config",
        str(config),
        "--mirror-dir",
        str(tmp_path / "lustro"),
        "--reference-dir",
        str(references),
    ]
    measure = ["measure", *common, "--journal", str(journal), "--machine", "test"]

    frozen = run_benchmark("freeze", *common, "--commit", "HEAD")
    assert frozen.returncode == 0, frozen.stdout + frozen.stderr
    reference_folder = frozen_reference(references)
    commit = reference_folder.parent.name
    assert len(commit) == 40
    assert len(list(reference_folder.glob("*.xlsx"))) == 3

    consistent = run_benchmark(*measure)
    for removed in sorted(reference_folder.glob("*.xlsx"))[:1]:
        removed.unlink()
    inconsistent = run_benchmark(*measure)
    comment = run_benchmark("comment", "--journal", str(journal))

    assert (consistent.returncode, inconsistent.returncode, comment.returncode) == (0, 0, 0), (
        consistent.stderr + inconsistent.stderr + comment.stderr
    )
    first, second = (json.loads(line)["oracle"] for line in journal.read_text(encoding="utf-8").splitlines())
    assert first == {"wynik": "zgodny", "referencja": commit, "roznice": dict.fromkeys(ORACLE_CATEGORIES, 0)}
    assert second == {
        "wynik": "niezgodny",
        "referencja": commit,
        "roznice": dict.fromkeys(ORACLE_CATEGORIES, 0) | {"pliki": 1},
    }
    gate = comment.stdout.split("## Bramka poprawności", 1)[1].split("## Decyzja", 1)[0]
    assert "**niezgodny**" in gate
    assert f"`{commit[:7]}`" in gate
    assert "| pliki | 1 |" in gate
    assert "| komunikaty | 0 |" in gate

    published = "".join(result.stdout + result.stderr for result in (frozen, consistent, inconsistent, comment))
    secrets = {*load_worker_mapping(config), *load_worker_mapping(config).values()}
    assert {secret for secret in secrets if secret in published} == set()

"""Skrypt dla maszyn ``tools/uruchom_proces.py`` jako osobny proces Pythona: kod wyjścia, wynik JSON i pliki."""

from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
from typing import Any

from rozliczenia.preparation_process import PROCESS as PREPARATION
from rozliczenia.telemetry import COUNTER_NAMES, MetricsStore

from tests.fixtures.preparation import (
    COLLECTIVE_FILE_NAME,
    INTERNAL_SETTLEMENT_NAME,
    PreparationFixture,
    incomplete_period_fixture,
    make_preparation_fixture,
)
from tests.fixtures.settlement import PERIOD, SOURCE_NAME, make_fixture, make_preview_fixture

SCRIPT = Path(__file__).resolve().parents[1] / "tools" / "uruchom_proces.py"
WORKER_SETTLEMENTS = f"Rozliczenie pracowników {PERIOD}"


def _completed(*arguments: str | Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(SCRIPT), *map(str, arguments)],
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        encoding="utf-8",
        env={**os.environ, "PYTHONIOENCODING": "utf-8"},
        timeout=100,
        check=False,
    )


def _run(*arguments: str | Path) -> tuple[int, dict[str, Any]]:
    completed = _completed(*arguments)
    assert completed.stderr == ""
    assert "Traceback" not in completed.stdout
    return completed.returncode, json.loads(completed.stdout)


def _settlement(tmp_path: Path, source: Path, config: Path, *extra: str) -> tuple[int, dict[str, Any]]:
    return _run(
        "settlement",
        "--source",
        source,
        "--config",
        config,
        "--worker-template",
        tmp_path / "Wzorzec rozliczenia pracownika.xlsx",
        "--metrics",
        tmp_path / "metrics.jsonl",
        *extra,
    )


def _preparation(fixture: PreparationFixture, *extra: str) -> tuple[int, dict[str, Any]]:
    return _run(
        "preparation",
        "--register",
        fixture.register_path,
        "--periods-directory",
        fixture.periods_directory,
        "--period",
        PERIOD,
        "--config",
        fixture.config_path,
        "--internal-template",
        fixture.internal_template_path,
        "--collective-template",
        fixture.collective_template_path,
        "--metrics",
        fixture.register_path.parent / "metrics.jsonl",
        *extra,
    )


def test_przebieg_rozliczen_ok_konczy_kodem_0_z_podsumowaniem_karty_uruchomienia(tmp_path: Path) -> None:
    source, target, config = make_fixture(tmp_path)

    exit_code, result = _settlement(tmp_path, source, config)

    assert (exit_code, result["result"], result["stop"]) == (0, "OK", None)
    assert [(figure["label"], figure["value"]) for figure in result["summary"]["figures"]] == [
        ("Zapisane szablony", 2),
        ("Puste szablony", 1),
    ]
    assert result["summary"]["file_plan"] == [
        {"file": f"Rozliczenie {PERIOD} - Adrian Testowy.xlsx", "rows": 2},
        {"file": f"Rozliczenie {PERIOD} - Darek Fikcyjny.xlsx", "rows": 1},
        {"file": f"Rozliczenie {PERIOD} - Kamil Syntetyczny.xlsx", "rows": 0},
    ]
    assert sorted(path.name for path in target.iterdir()) == [file["file"] for file in result["summary"]["file_plan"]]
    assert sorted(path.name for path in source.parent.iterdir()) == [SOURCE_NAME, WORKER_SETTLEMENTS]
    assert result["warnings"] == []
    progress = result["progress"]
    assert [(phase["phase"], phase["state"]) for phase in progress["phases"]] == [
        ("Sprawdzanie", "completed"),
        ("Odczyt danych", "completed"),
        ("Planowanie", "completed"),
        ("Zapisywanie", "completed"),
    ]
    assert (progress["template_total"], progress["templates_completed"]) == (3, 3)
    [record] = MetricsStore(tmp_path / "metrics.jsonl", COUNTER_NAMES).read()
    assert (record["mode"], record["result"], record["total_duration_ms"]) == ("RUN", "OK", result["total_duration_ms"])
    assert (result["metrics_saved"], result["notices"]) == (True, [])
    assert str(tmp_path) not in json.dumps(result)


def test_podglad_z_nieznanym_wykonawca_wymaga_sprawdzenia_kodem_2_z_kodem_ostrzezenia(tmp_path: Path) -> None:
    source, _target, config = make_preview_fixture(tmp_path)

    exit_code, result = _settlement(tmp_path, source, config, "--dry-run")

    assert (exit_code, result["result"], result["stop"]) == (2, "WYMAGA_SPRAWDZENIA", None)
    assert [warning["code"] for warning in result["warnings"]] == ["BRAK_MAPOWANIA"]
    assert set(result["warnings"][0]) == {"code", "what", "where", "action"}
    assert [(figure["label"], figure["value"]) for figure in result["summary"]["figures"]] == [
        ("Wiersze danych", 3),
        ("Planowane szablony", 2),
        ("Puste szablony", 1),
    ]
    assert sorted(path.name for path in source.parent.iterdir()) == [SOURCE_NAME]
    [record] = MetricsStore(tmp_path / "metrics.jsonl", COUNTER_NAMES).read()
    assert (record["mode"], record["result"]) == ("DRY-RUN", "WYMAGA_SPRAWDZENIA")


def test_zatrzymanie_w_sprawdzaniu_konczy_kodem_1_z_kodem_komunikatu_i_bez_plikow(tmp_path: Path) -> None:
    source, _target, config = make_fixture(tmp_path)
    source.unlink()

    exit_code, result = _settlement(tmp_path, source, config)

    assert (exit_code, result["result"], result["summary"], result["warnings"]) == (1, "BLAD_KRYTYCZNY", None, [])
    assert result["stop"]["kind"] == "stop"
    assert result["stop"]["message"]["code"] == "BRAK_PLIKU_ZBIORCZEGO"
    assert set(result["stop"]["message"]) == {"code", "what", "where", "action"}
    first, *rest = result["progress"]["phases"]
    assert (first["phase"], first["state"]) == ("Sprawdzanie", "failed")
    assert {phase["state"] for phase in rest} == {"pending"}
    assert list(source.parent.iterdir()) == []
    [record] = MetricsStore(tmp_path / "metrics.jsonl", COUNTER_NAMES).read()
    assert (record["result"], set(record["counters"].values())) == ("BLAD_KRYTYCZNY", {0})
    assert str(tmp_path) not in json.dumps(result)


def test_decyzja_o_niepelnym_okresie_jest_odrzucana_bez_czekania_i_bez_plikow_okresu(tmp_path: Path) -> None:
    fixture = incomplete_period_fixture(tmp_path)

    exit_code, result = _preparation(fixture)

    assert (exit_code, result["result"], result["summary"]) == (1, "BLAD_KRYTYCZNY", None)
    assert (result["stop"]["kind"], result["stop"]["message"]["code"]) == ("stop", "PRZERWANO_NIEPELNY_OKRES")
    assert not fixture.period_directory.exists()
    [record] = MetricsStore(fixture.register_path.parent / "metrics.jsonl", PREPARATION.counter_names).read()
    assert (record["mode"], record["period"], record["result"]) == ("RUN", PERIOD, "BLAD_KRYTYCZNY")
    assert str(tmp_path) not in json.dumps(result)


def test_podglad_przygotowania_pliku_zbiorczego_pokazuje_plan_bez_plikow_okresu(tmp_path: Path) -> None:
    fixture = make_preparation_fixture(tmp_path)

    exit_code, result = _preparation(fixture, "--dry-run")

    assert (exit_code, result["result"], result["stop"], result["warnings"]) == (0, "OK", None, [])
    figures = {figure["label"]: figure["value"] for figure in result["summary"]["figures"]}
    assert (figures["Zlecenia okresu"], figures["Zlecenia skuteczne"]) == (4, 3)
    assert result["summary"]["files"] == [
        {"name": INTERNAL_SETTLEMENT_NAME, "kind": "internal_settlement"},
        {"name": COLLECTIVE_FILE_NAME, "kind": "collective_file"},
    ]
    assert list(fixture.periods_directory.iterdir()) == []
    assert result["metrics_saved"] is True


def test_bledne_argumenty_koncza_sie_kodem_1_bez_wyniku_json(tmp_path: Path) -> None:
    completed = _completed("settlement", "--metrics", tmp_path / "metrics.jsonl")

    assert (completed.returncode, completed.stdout) == (1, "")
    assert "--source" in completed.stderr
    assert not (tmp_path / "metrics.jsonl").exists()

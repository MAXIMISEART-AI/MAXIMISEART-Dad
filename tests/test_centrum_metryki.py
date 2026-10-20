"""Metryki i historia Uruchomień procesu w Centrum rozliczeń, przez HTTP API jak w przeglądarce."""

from __future__ import annotations

import json
from io import StringIO
from pathlib import Path
from typing import Any

from rozliczenia import preparation_cli
from tests.fixtures.centrum import Centrum, centrum

PREPARATION_COUNTERS = {"period_orders": 3, "successful_orders": 2, "skipped_empty_rows": 1, "warnings": 0}
SETTLEMENT_COUNTERS = {
    "templates_total": 2,
    "templates_completed": 2,
    "rows": 4,
    "written": 2,
    "empty": 0,
    "planned": 2,
    "skipped": 0,
    "issues": 0,
}


def record(
    started_at: str,
    *,
    counters: dict[str, int],
    mode: str = "RUN",
    period: str = "08_14_09_2026",
    result: str = "OK",
    total: int = 1000,
    phases: tuple[int, int, int, int] = (100, 200, 300, 400),
) -> dict[str, object]:
    """Rekord w schemacie plików metryk CLI (``schema_version`` 1)."""

    return {
        "schema_version": 1,
        "started_at": started_at,
        "mode": mode,
        "period": period,
        "completed": result != "BLAD_KRYTYCZNY",
        "result": result,
        "total_duration_ms": total,
        "phase_durations_ms": dict(zip(("Sprawdzanie", "Odczyt danych", "Planowanie", "Zapisywanie"), phases)),
        "counters": counters if result != "BLAD_KRYTYCZNY" else dict.fromkeys(counters, 0),
    }


def preparation(started_at: str, **fields: Any) -> dict[str, object]:
    return record(started_at, counters=PREPARATION_COUNTERS, **fields)


def settlement(started_at: str, **fields: Any) -> dict[str, object]:
    return record(started_at, counters=SETTLEMENT_COUNTERS, **fields)


def write_lines(path: Path, *lines: dict[str, object] | str) -> None:
    with path.open("a", encoding="utf-8") as file:
        for line in lines:
            file.write((line if isinstance(line, str) else json.dumps(line, ensure_ascii=False)) + "\n")


def metrics(app: Centrum) -> dict[str, object]:
    response = app.client.get("/api/metrics")
    assert response.status_code == 200
    body = response.json()
    assert isinstance(body, dict)
    return body


def test_bez_plikow_metryk_historia_uruchomien_procesu_jest_pusta(tmp_path: Path) -> None:
    body = metrics(centrum(tmp_path))

    assert body["runs"] == []
    assert body["phases"] == ["Sprawdzanie", "Odczyt danych", "Planowanie", "Zapisywanie"]
    assert body["minimum_completed_runs"] == 5


def test_historia_obejmuje_uruchomienia_procesu_obu_procesow_od_najnowszego(tmp_path: Path) -> None:
    app = centrum(tmp_path)
    write_lines(
        app.metrics.preparation,
        preparation("2026-10-06T06:21:00+00:00", period="29_05_10_2026", total=11_200),
        preparation("2026-10-06T06:12:00+00:00", mode="DRY-RUN", period="29_05_10_2026", total=8_100),
    )
    write_lines(
        app.metrics.settlement,
        settlement("2026-10-01T17:46:00+02:00", period="22_28_09_2026", result="WYMAGA_SPRAWDZENIA", total=12_700),
    )

    runs = metrics(app)["runs"]

    assert runs == [
        {
            "process": "preparation",
            "process_label": "Przygotowanie pliku zbiorczego",
            "started_at": "2026-10-06T06:21:00Z",
            "mode": "RUN",
            "period": "29_05_10_2026",
            "result": "OK",
            "total_duration_ms": 11_200,
            "phase_durations": [
                {"phase": "Sprawdzanie", "duration_ms": 100},
                {"phase": "Odczyt danych", "duration_ms": 200},
                {"phase": "Planowanie", "duration_ms": 300},
                {"phase": "Zapisywanie", "duration_ms": 400},
            ],
            "origin": "cmd",
        },
        {
            "process": "preparation",
            "process_label": "Przygotowanie pliku zbiorczego",
            "started_at": "2026-10-06T06:12:00Z",
            "mode": "DRY-RUN",
            "period": "29_05_10_2026",
            "result": "OK",
            "total_duration_ms": 8_100,
            "phase_durations": [
                {"phase": "Sprawdzanie", "duration_ms": 100},
                {"phase": "Odczyt danych", "duration_ms": 200},
                {"phase": "Planowanie", "duration_ms": 300},
                {"phase": "Zapisywanie", "duration_ms": 400},
            ],
            "origin": "cmd",
        },
        {
            "process": "settlement",
            "process_label": "Przebieg rozliczeń",
            "started_at": "2026-10-01T15:46:00Z",
            "mode": "RUN",
            "period": "22_28_09_2026",
            "result": "WYMAGA_SPRAWDZENIA",
            "total_duration_ms": 12_700,
            "phase_durations": [
                {"phase": "Sprawdzanie", "duration_ms": 100},
                {"phase": "Odczyt danych", "duration_ms": 200},
                {"phase": "Planowanie", "duration_ms": 300},
                {"phase": "Zapisywanie", "duration_ms": 400},
            ],
            "origin": "cmd",
        },
    ]


def statistics(body: dict[str, object], process: str, mode: str) -> dict[str, object]:
    entries = body["statistics"]
    assert isinstance(entries, list)
    [entry] = [entry for entry in entries if (entry["process"], entry["mode"]) == (process, mode)]
    assert isinstance(entry, dict)
    return entry


def runs_of(body: dict[str, object]) -> list[dict[str, Any]]:
    runs = body["runs"]
    assert isinstance(runs, list)
    return runs


def test_p50_i_p95_dopiero_od_pieciu_ukonczonych_obserwacji_tego_samego_trybu(tmp_path: Path) -> None:
    app = centrum(tmp_path)
    write_lines(
        app.metrics.preparation,
        *(
            preparation(f"2026-09-0{day}T08:00:00+00:00", total=total, phases=(total // 10, total // 5, 0, 0))
            for day, total in zip(range(1, 6), (5000, 1000, 4000, 2000, 3000))
        ),
        *(preparation(f"2026-09-1{day}T08:00:00+00:00", mode="DRY-RUN") for day in range(4)),
        preparation("2026-09-20T08:00:00+00:00", mode="DRY-RUN", result="BLAD_KRYTYCZNY"),
    )

    body = metrics(app)

    assert statistics(body, "preparation", "RUN") == {
        "process": "preparation",
        "mode": "RUN",
        "completed_runs": 5,
        "percentiles": {
            "p50_ms": 3000,
            "p95_ms": 4800,
            "phases": [
                {"phase": "Sprawdzanie", "p50_ms": 300, "p95_ms": 480},
                {"phase": "Odczyt danych", "p50_ms": 600, "p95_ms": 960},
                {"phase": "Planowanie", "p50_ms": 0, "p95_ms": 0},
                {"phase": "Zapisywanie", "p50_ms": 0, "p95_ms": 0},
            ],
        },
        "results": {"ok": 5, "needs_review": 0, "critical": 0},
    }
    # Cztery ukończone DRY-RUN i jedno przerwane to za mało: przerwane nie jest ukończoną obserwacją.
    dry_run = statistics(body, "preparation", "DRY-RUN")
    assert (dry_run["completed_runs"], dry_run["percentiles"]) == (4, None)
    assert dry_run["results"] == {"ok": 4, "needs_review": 0, "critical": 1}
    assert statistics(body, "settlement", "RUN")["percentiles"] is None


def test_wymaga_sprawdzenia_jest_ukonczona_obserwacja_i_osobnym_wynikiem(tmp_path: Path) -> None:
    app = centrum(tmp_path)
    write_lines(
        app.metrics.settlement,
        *(settlement(f"2026-09-0{day}T08:00:00+00:00") for day in range(1, 4)),
        *(settlement(f"2026-09-1{day}T08:00:00+00:00", result="WYMAGA_SPRAWDZENIA") for day in range(2)),
        settlement("2026-09-20T08:00:00+00:00", result="BLAD_KRYTYCZNY"),
    )

    run = statistics(metrics(app), "settlement", "RUN")

    assert run["completed_runs"] == 5
    assert run["results"] == {"ok": 3, "needs_review": 2, "critical": 1}
    assert run["percentiles"] is not None


def test_przerwane_uruchomienie_procesu_ma_czasy_etapow_do_momentu_przerwania(tmp_path: Path) -> None:
    app = centrum(tmp_path)
    write_lines(
        app.metrics.preparation,
        preparation(
            "2026-08-25T06:15:00+00:00",
            period="18_24_08_2026",
            result="BLAD_KRYTYCZNY",
            total=1700,
            phases=(400, 1300, 0, 0),
        ),
    )

    [run] = runs_of(metrics(app))

    assert run["result"] == "BLAD_KRYTYCZNY"
    assert run["total_duration_ms"] == 1700
    assert run["phase_durations"] == [
        {"phase": "Sprawdzanie", "duration_ms": 400},
        {"phase": "Odczyt danych", "duration_ms": 1300},
        {"phase": "Planowanie", "duration_ms": 0},
        {"phase": "Zapisywanie", "duration_ms": 0},
    ]


def test_niepoprawne_rekordy_metryk_sa_pomijane(tmp_path: Path) -> None:
    app = centrum(tmp_path)
    write_lines(
        app.metrics.preparation,
        preparation("2026-09-01T08:00:00+00:00", period="01_07_09_2026"),
        "{nie json",
        preparation("2026-09-02T08:00:00"),  # czas bez strefy
        preparation("2026-09-03T08:00:00+00:00", total=True),
        {**preparation("2026-09-04T08:00:00+00:00"), "schema_version": 2},
        settlement("2026-09-05T08:00:00+00:00"),  # liczniki Przebiegu rozliczeń w pliku Przygotowania
        '{"schema_version":1,"started_at":"2026-09-06T08:00:00+00:00","mode":"RUN"',
    )
    write_lines(app.metrics.settlement, preparation("2026-09-07T08:00:00+00:00"))

    runs = runs_of(metrics(app))

    assert [(run["process"], run["period"]) for run in runs] == [("preparation", "01_07_09_2026")]


def test_rozklad_wynikow_z_ostatnich_osmiu_tygodni_obejmuje_oba_procesy(tmp_path: Path) -> None:
    app = centrum(tmp_path)  # dziś poniedziałek 19.10.2026
    write_lines(
        app.metrics.preparation,
        preparation("2026-08-23T12:00:00+00:00"),  # przed ostatnimi ośmioma tygodniami
        preparation("2026-08-25T12:00:00+00:00"),
        preparation("2026-10-06T12:00:00+00:00", result="BLAD_KRYTYCZNY"),
    )
    write_lines(app.metrics.settlement, settlement("2026-10-01T12:00:00+00:00", result="WYMAGA_SPRAWDZENIA"))

    recent = metrics(app)["recent"]

    assert recent == {"weeks": 8, "results": {"ok": 1, "needs_review": 1, "critical": 1}}


def test_rekord_zapisany_przez_cli_pojawia_sie_bez_restartu_centrum(tmp_path: Path) -> None:
    app = centrum(tmp_path)
    assert metrics(app)["runs"] == []
    missing_register = tmp_path / "brak.xlsx"

    exit_code = preparation_cli.main(
        ["--register", str(missing_register), "--periods-directory", str(tmp_path), "--period", "08_14_09_2026",
         "--dry-run", "--metrics", str(app.metrics.preparation)],
        output=StringIO(),
    )

    assert exit_code == 1
    [run] = runs_of(metrics(app))
    assert (run["process"], run["mode"], run["period"], run["result"], run["origin"]) == (
        "preparation",
        "DRY-RUN",
        "08_14_09_2026",
        "BLAD_KRYTYCZNY",
        "cmd",
    )


def test_odczyt_metryk_niczego_nie_zmienia_w_plikach_metryk(tmp_path: Path) -> None:
    app = centrum(tmp_path)
    write_lines(app.metrics.settlement, settlement("2026-09-01T08:00:00+00:00"), "{urwany")
    before = app.metrics.settlement.read_bytes()

    metrics(app)

    assert app.metrics.settlement.read_bytes() == before
    assert not app.metrics.preparation.exists()


def test_nieczytelny_plik_metryk_daje_bezpieczny_komunikat(tmp_path: Path) -> None:
    app = centrum(tmp_path)
    app.metrics.preparation.mkdir()

    response = app.client.get("/api/metrics")

    assert response.status_code == 500
    assert response.json() == {"message": "Nie udało się odczytać plików metryk. Odśwież kartę."}

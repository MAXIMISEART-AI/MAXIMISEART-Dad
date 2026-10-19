"""Widok Uruchomienia w Centrum rozliczeń: co karta Uruchomienia pokazuje ze snapshotu postępu i podsumowania procesu.

Liczby i etykiety w kolejności, w jakiej widzi je tata. Snapshot pochodzi z projekcji postępu (ADR 0002),
podsumowanie z silnika; widok niczego nie interpretuje ponad wybór i nazwanie faktów.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import date
from pathlib import Path
from typing import Any

from rozliczenia.centrum import run_view
from rozliczenia.collective_preparation import PreparationSummary
from rozliczenia.domain import ProgressPhase, SettlementSummary, WorkerResult
from rozliczenia.progress import PhaseState, ProgressProjection, ProgressSnapshot

PERIOD = "08_14_09_2026"
WORKER_SETTLEMENTS = Path("INEA") / PERIOD / f"Rozliczenie pracowników {PERIOD}"


def snapshot(**facts: Any) -> ProgressSnapshot:
    return replace(ProgressProjection("RUN", PERIOD).snapshot, **facts)


def figures(shown: Any) -> list[tuple[str, int, str]]:
    return [(figure.label, figure.value, figure.unit) for figure in shown.figures]


def test_przebieg_rozliczen_na_zywo_pokazuje_wiersze_szablony_i_problemy() -> None:
    progress = run_view.SETTLEMENT.progress(
        snapshot(rows=7, operation_counts={"ZAPISANO": 2, "PUSTY_SZABLON": 1, "ZABLOKOWANY": 1}, issue_count=3),
        dry_run=False,
    )

    assert figures(progress) == [
        ("Wiersze danych", 7, "count"),
        ("Zapisane szablony", 2, "count"),
        ("Puste szablony", 1, "count"),
        ("Pominięte szablony", 1, "count"),
        ("Problemy", 3, "count"),
    ]


def test_podglad_przebiegu_rozliczen_na_zywo_liczy_planowane_szablony() -> None:
    progress = run_view.SETTLEMENT.progress(
        snapshot(rows=3, operation_counts={"PLAN": 2, "PUSTY_SZABLON": 1}), dry_run=True
    )

    assert figures(progress) == [
        ("Wiersze danych", 3, "count"),
        ("Planowane szablony", 2, "count"),
        ("Puste szablony", 1, "count"),
        ("Pominięte szablony", 0, "count"),
        ("Problemy", 0, "count"),
    ]


def test_przygotowanie_pliku_zbiorczego_na_zywo_pokazuje_ostrzezenia_i_czas_uruchomienia() -> None:
    for dry_run in (True, False):
        progress = run_view.PREPARATION.progress(snapshot(issue_count=1, total_elapsed_ms=10900), dry_run=dry_run)

        assert figures(progress) == [("Ostrzeżenia", 1, "count"), ("Czas uruchomienia", 10900, "ms")]


def test_na_zywo_widac_etapy_i_szablony_pracownikow_z_biezacym_wykonawca() -> None:
    progress = run_view.SETTLEMENT.progress(
        snapshot(
            phase_states={
                ProgressPhase.CHECKING: PhaseState.COMPLETED,
                ProgressPhase.READING: PhaseState.COMPLETED,
                ProgressPhase.PLANNING: PhaseState.FAILED,
                ProgressPhase.SAVING: PhaseState.PENDING,
            },
            phase_durations_ms={ProgressPhase.CHECKING: 120, ProgressPhase.READING: 340, ProgressPhase.PLANNING: 50},
            template_total=3,
            templates_completed=1,
            current_worker="Darek Nowak",
        ),
        dry_run=False,
    )

    assert [phase.model_dump() for phase in progress.phases] == [
        {"phase": "Sprawdzanie", "state": "completed", "duration_ms": 120},
        {"phase": "Odczyt danych", "state": "completed", "duration_ms": 340},
        {"phase": "Planowanie", "state": "failed", "duration_ms": 50},
        {"phase": "Zapisywanie", "state": "pending", "duration_ms": 0},
    ]
    assert (progress.template_total, progress.templates_completed, progress.current_worker) == (3, 1, "Darek Nowak")


def settlement_summary(*results: tuple[str, int, str]) -> SettlementSummary:
    return SettlementSummary(
        period=PERIOD,
        source_file=Path("INEA") / PERIOD / f"Rozliczenie {PERIOD} - zbiorcze.xlsx",
        target_directory=WORKER_SETTLEMENTS,
        results=[
            WorkerResult(name, WORKER_SETTLEMENTS / f"Rozliczenie {PERIOD} - {name}.xlsx", rows, status)
            for name, rows, status in results
        ],
    )


def test_wynik_podgladu_przebiegu_rozliczen_pokazuje_plan_plikow_kazdego_wykonawcy() -> None:
    summary = run_view.SETTLEMENT.summary(
        settlement_summary(("Adrian Maciejewski", 2, "PLAN"), ("Darek Nowak", 1, "PLAN"), ("Kamil Frontczak", 0, "PUSTY_SZABLON")),
        dry_run=True,
    )

    assert summary.model_dump() == {
        "figures": [
            {"label": "Wiersze danych", "value": 3, "unit": "count"},
            {"label": "Planowane szablony", "value": 2, "unit": "count"},
            {"label": "Puste szablony", "value": 1, "unit": "count"},
        ],
        "counts": None,
        "files": [],
        "file_plan": [
            {"file": f"Rozliczenie {PERIOD} - Adrian Maciejewski.xlsx", "rows": 2},
            {"file": f"Rozliczenie {PERIOD} - Darek Nowak.xlsx", "rows": 1},
            {"file": f"Rozliczenie {PERIOD} - Kamil Frontczak.xlsx", "rows": 0},
        ],
    }


def test_wynik_zapisu_przebiegu_rozliczen_liczy_zapisane_puste_i_pominiete_szablony() -> None:
    summary = run_view.SETTLEMENT.summary(
        settlement_summary(
            ("Adrian Maciejewski", 2, "ZAPISANO"),
            ("Darek Nowak", 1, "ZAPISANO"),
            ("Kamil Frontczak", 0, "PUSTY_SZABLON"),
            ("Ola Lis", 4, "ZLY_SZABLON"),
        ),
        dry_run=False,
    )

    assert figures(summary) == [
        ("Zapisane szablony", 2, "count"),
        ("Puste szablony", 1, "count"),
        ("Pominięte szablony", 1, "count"),
    ]
    assert [(file.file, file.rows) for file in summary.file_plan or []][-1] == (
        f"Rozliczenie {PERIOD} - Ola Lis.xlsx",
        4,
    )


def preparation_summary() -> PreparationSummary:
    period_directory = Path("INEA") / PERIOD
    return PreparationSummary(
        period=PERIOD,
        period_directory=period_directory,
        internal_settlement_file=period_directory / f"Rozliczenie wewnętrzne {PERIOD}.xlsx",
        collective_file=period_directory / f"Rozliczenie {PERIOD} - zbiorcze.xlsx",
        period_order_count=4,
        successful_order_count=3,
        skipped_empty_rows=5,
        orders_per_day={
            date(2026, 9, 8): 1,
            date(2026, 9, 9): 1,
            date(2026, 9, 10): 0,
            date(2026, 9, 11): 0,
            date(2026, 9, 12): 1,
            date(2026, 9, 13): 0,
            date(2026, 9, 14): 1,
        },
    )


def test_wynik_przygotowania_pliku_zbiorczego_pokazuje_zlecenia_na_dzien_i_oba_pliki_okresu() -> None:
    for dry_run in (True, False):
        summary = run_view.PREPARATION.summary(preparation_summary(), dry_run=dry_run)

        assert summary.model_dump() == {
            "figures": [
                {"label": "Zlecenia okresu", "value": 4, "unit": "count"},
                {"label": "Zlecenia skuteczne", "value": 3, "unit": "count"},
                {"label": "Pominięte puste wiersze", "value": 5, "unit": "count"},
            ],
            "counts": {
                "title": "Zlecenia na dzień",
                "counts": [
                    {"label": "wt 08.09.2026", "count": 1},
                    {"label": "śr 09.09.2026", "count": 1},
                    {"label": "czw 10.09.2026", "count": 0},
                    {"label": "pt 11.09.2026", "count": 0},
                    {"label": "sob 12.09.2026", "count": 1},
                    {"label": "niedz 13.09.2026", "count": 0},
                    {"label": "pon 14.09.2026", "count": 1},
                ],
            },
            "files": [
                {"name": f"Rozliczenie wewnętrzne {PERIOD}.xlsx", "kind": "internal_settlement"},
                {"name": f"Rozliczenie {PERIOD} - zbiorcze.xlsx", "kind": "collective_file"},
            ],
            "file_plan": None,
        }

"""Metryki: historia Uruchomień procesu obu procesów z plików metryk, z P50/P95 i rozkładem wyników.

Pliki są czytane przy każdym odczycie, więc rekord dopisany spoza Centrum, np.
przez skrypt dla maszyn, widać bez restartu serwera. Walidację rekordów, pomijanie
niepoprawnych i reguły P50/P95 daje ``telemetry``; Centrum ich nie powtarza.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Final

from fastapi import APIRouter

from rozliczenia import preparation_process, settlement_process
from rozliczenia.centrum import contract
from rozliczenia.centrum.run_origins import CentrumRuns
from rozliczenia.domain import PHASES
from rozliczenia.process_run import Process
from rozliczenia.telemetry import MINIMUM_STATISTIC_SAMPLES, MetricsStore, comparable_records, statistics_for

# Procesy Centrum rozliczeń pod kluczami kontraktu.
PROCESSES: Final[dict[contract.ProcessKey, Process[Any, Any]]] = {
    "preparation": preparation_process.PROCESS,
    "settlement": settlement_process.PROCESS,
}
_MODES: Final[tuple[contract.RunMode, ...]] = ("RUN", "DRY-RUN")
_RECENT_WEEKS = 8


@dataclass(frozen=True)
class MetricsFiles:
    """Pliki metryk obu procesów."""

    preparation: Path
    settlement: Path

    @classmethod
    def default(cls) -> MetricsFiles:
        return cls(**{key: process.metrics_path() for key, process in PROCESSES.items()})

    def stores(self) -> dict[contract.ProcessKey, MetricsStore]:
        paths: dict[contract.ProcessKey, Path] = {"preparation": self.preparation, "settlement": self.settlement}
        return {key: MetricsStore(paths[key], process.counter_names) for key, process in PROCESSES.items()}


def read_metrics(
    files: MetricsFiles, today: date, centrum_started: frozenset[tuple[str, str]] = frozenset()
) -> contract.Metrics:
    """``centrum_started``: pary (proces, ``started_at``) Uruchomień z Centrum (``run_origins``)."""

    stores = files.stores()
    records = {process: store.read() for process, store in stores.items()}
    runs = sorted(
        (
            _run(process, record, centrum_started)
            for process, process_records in records.items()
            for record in process_records
        ),
        key=lambda run: run.started_at,
        reverse=True,
    )
    since = today - timedelta(weeks=_RECENT_WEEKS)
    return contract.Metrics(
        phases=list(PHASES),
        minimum_completed_runs=MINIMUM_STATISTIC_SAMPLES,
        runs=runs,
        statistics=[
            _statistics(process, mode, stores[process].counter_names, records[process], runs)
            for process in stores
            for mode in _MODES
        ],
        recent=contract.RecentResults(
            weeks=_RECENT_WEEKS,
            results=_results(run for run in runs if run.started_at.astimezone().date() >= since),
        ),
    )


def _run(
    process: contract.ProcessKey, record: dict[str, Any], centrum_started: frozenset[tuple[str, str]]
) -> contract.ProcessRun:
    return contract.ProcessRun(
        process=process,
        process_label=PROCESSES[process].name,
        started_at=datetime.fromisoformat(record["started_at"]).astimezone(timezone.utc),
        mode=record["mode"],
        period=record["period"],
        result=record["result"],
        total_duration_ms=record["total_duration_ms"],
        phase_durations=[
            contract.PhaseDuration(phase=phase, duration_ms=record["phase_durations_ms"][phase]) for phase in PHASES
        ],
        # Rekord metryk nie mówi, skąd wystartował (schemat bez zmian); Centrum pamięta swoje Uruchomienia samo.
        origin="centrum" if (process, record["started_at"]) in centrum_started else "cmd",
        # Rekord wersji 1 nie ma ``stop``: rodzaju jego Zatrzymania nie zgadujemy.
        stop_kind=stop["kind"] if (stop := record.get("stop")) else None,
    )


def _statistics(
    process: contract.ProcessKey,
    mode: contract.RunMode,
    counter_names: frozenset[str],
    records: list[dict[str, Any]],
    runs: list[contract.ProcessRun],
) -> contract.ModeStatistics:
    statistics = statistics_for(records, mode, counter_names)
    return contract.ModeStatistics(
        process=process,
        mode=mode,
        completed_runs=len(comparable_records(records, mode, counter_names)),
        percentiles=None
        if statistics is None
        else contract.Percentiles(
            p50_ms=statistics["total"][0],
            p95_ms=statistics["total"][1],
            phases=[
                contract.PhasePercentiles(phase=phase, p50_ms=statistics[phase][0], p95_ms=statistics[phase][1])
                for phase in PHASES
            ],
        ),
        results=_results(run for run in runs if run.process == process and run.mode == mode),
    )


def _results(runs: Iterable[contract.ProcessRun]) -> contract.ResultCounts:
    """Przerwane bez rodzaju (stary rekord) liczą się jako zatrzymane, nie jako błąd."""

    counted = list(runs)
    results = [run.result for run in counted]
    failed = sum(run.stop_kind == "for_maks" for run in counted)
    return contract.ResultCounts(
        ok=results.count("OK"),
        needs_review=results.count("WYMAGA_SPRAWDZENIA"),
        stopped=results.count("BLAD_KRYTYCZNY") - failed,
        failed=failed,
    )


def previewed_periods(store: MetricsStore) -> frozenset[str]:
    """Okresy, dla których historia metryk ma udany podgląd bez zapisu (DRY-RUN z wynikiem OK).

    Nieczytelny plik metryk oznacza „nie było podglądu”.
    """

    try:
        records = store.read()
    except OSError:
        return frozenset()
    return frozenset(record["period"] for record in records if (record["mode"], record["result"]) == ("DRY-RUN", "OK"))


def metrics_router(files: MetricsFiles, today: Callable[[], date], centrum_runs: CentrumRuns) -> APIRouter:
    router = APIRouter(prefix="/api/metrics", tags=["metryki"])

    @router.get("", operation_id="getMetrics", responses={500: {"model": contract.Problem}})
    def metrics() -> contract.Metrics:
        try:
            return read_metrics(files, today(), centrum_runs.started())
        except OSError:
            raise contract.Refusal(500, "Nie udało się odczytać plików metryk. Odśwież kartę.") from None

    return router

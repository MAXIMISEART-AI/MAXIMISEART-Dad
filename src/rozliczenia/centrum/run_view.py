"""Widok Uruchomienia: to, co karta Uruchomienia pokazuje ze snapshotu postępu i z podsumowania procesu.

Jedyne miejsce prezentacji procesów w Centrum rozliczeń: deklaracja procesu (przypomnienie przed
uruchomieniem, Gotowość, podpowiedź podglądu), etykiety i kolejność liczb na żywo, liczb wyniku
i szczegóły wyniku. Projekcja postępu pozostaje jedynym interpretatorem Zdarzeń przebiegu
(ADR 0002); widok tylko wybiera i nazywa jej fakty, a przeglądarka renderuje go bez rozróżniania
procesów (ADR 0004). Kontrakt niesie wyłącznie to, co karta pokazuje.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Final, Generic, TypeVar

from rozliczenia import preparation_cli
from rozliczenia.centrum import contract
from rozliczenia.collective_preparation import PreparationSummary
from rozliczenia.domain import SettlementSummary
from rozliczenia.progress import ProgressSnapshot

SummaryT = TypeVar("SummaryT")


@dataclass(frozen=True)
class ProcessView(Generic[SummaryT]):
    """Widok Uruchomienia jednego procesu: deklaracja procesu, liczby na żywo i wynik w kształcie kontraktu.

    Deklaracja procesu: ``reminder`` to przypomnienie przed uruchomieniem, ``confirms_readiness``
    mówi, czy „Uruchom” potwierdza Gotowość Pliku zbiorczego, a ``preview_hint`` to podpowiedź
    „Podgląd bez zapisu”.
    """

    reminder: str
    confirms_readiness: bool
    preview_hint: str
    _figures: Callable[[ProgressSnapshot, bool], list[contract.Figure]]
    _summary: Callable[[SummaryT, bool], contract.RunSummary]

    def progress(self, snapshot: ProgressSnapshot, *, dry_run: bool) -> contract.Progress:
        """Etapy, postęp Szablonów pracowników i liczby na żywo z jednego snapshotu projekcji."""

        return contract.Progress(
            phases=[
                contract.PhaseProgress(
                    phase=phase.value, state=state.value, duration_ms=snapshot.phase_durations_ms.get(phase, 0)
                )
                for phase, state in snapshot.phase_states.items()
            ],
            template_total=snapshot.template_total,
            templates_completed=snapshot.templates_completed,
            current_worker=snapshot.current_worker,
            figures=self._figures(snapshot, dry_run),
        )

    def summary(self, summary: SummaryT, *, dry_run: bool) -> contract.RunSummary:
        """Liczby i szczegóły wyniku podglądu bez zapisu albo zapisu."""

        return self._summary(summary, dry_run)


def _count(label: str, value: int) -> contract.Figure:
    return contract.Figure(label=label, value=value, unit="count")


def _settlement_figures(snapshot: ProgressSnapshot, dry_run: bool) -> list[contract.Figure]:
    counters = snapshot.metric_counters()
    return [
        _count("Wiersze danych", snapshot.rows),
        _count("Planowane szablony", counters["planned"]) if dry_run else _count("Zapisane szablony", counters["written"]),
        _count("Puste szablony", counters["empty"]),
        _count("Pominięte szablony", counters["skipped"]),
        _count("Problemy", snapshot.issue_count),
    ]


def _settlement_summary(summary: SettlementSummary, dry_run: bool) -> contract.RunSummary:
    figures = (
        [
            _count("Wiersze danych", summary.total_rows),
            _count("Planowane szablony", summary.planned_count),
            _count("Puste szablony", summary.empty_count),
        ]
        if dry_run
        else [
            _count("Zapisane szablony", summary.written_count),
            _count("Puste szablony", summary.empty_count),
            _count("Pominięte szablony", summary.skipped_count),
        ]
    )
    return contract.RunSummary(
        figures=figures,
        counts=None,
        files=[],
        file_plan=[contract.WorkerFile(file=result.output_file.name, rows=result.rows) for result in summary.results],
    )


def _preparation_figures(snapshot: ProgressSnapshot, _dry_run: bool) -> list[contract.Figure]:
    return [
        _count("Ostrzeżenia", snapshot.issue_count),
        contract.Figure(label="Czas uruchomienia", value=snapshot.total_elapsed_ms, unit="ms"),
    ]


def _preparation_summary(summary: PreparationSummary, _dry_run: bool) -> contract.RunSummary:
    return contract.RunSummary(
        figures=[
            _count("Zlecenia okresu", summary.period_order_count),
            _count("Zlecenia skuteczne", summary.successful_order_count),
            _count("Pominięte puste wiersze", summary.skipped_empty_rows),
        ],
        counts=contract.CountGroup(
            title="Zlecenia na dzień",
            counts=[
                contract.Count(label=label, count=count) for label, count in preparation_cli.orders_per_day(summary)
            ],
        ),
        files=[
            contract.PeriodFile(name=summary.internal_settlement_file.name, kind="internal_settlement"),
            contract.PeriodFile(name=summary.collective_file.name, kind="collective_file"),
        ],
        file_plan=None,
    )


SETTLEMENT: Final[ProcessView[SettlementSummary]] = ProcessView(
    reminder="Zapisz i zamknij Plik zbiorczy w Excelu",
    confirms_readiness=True,
    preview_hint="Nic nie zostanie zapisane. Zobaczysz plan plików każdego Wykonawcy.",
    _figures=_settlement_figures,
    _summary=_settlement_summary,
)
PREPARATION: Final[ProcessView[PreparationSummary]] = ProcessView(
    reminder="Zapisz i zamknij Rejestr zleceń w Excelu",
    confirms_readiness=False,
    preview_hint="Nic nie zostanie zapisane. Zobaczysz plan i nazwy obu plików.",
    _figures=_preparation_figures,
    _summary=_preparation_summary,
)

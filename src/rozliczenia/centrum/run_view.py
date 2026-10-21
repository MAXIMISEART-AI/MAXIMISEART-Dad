"""Widok Uruchomienia: to, co karta Uruchomienia pokazuje ze snapshotu postępu i z podsumowania procesu.

Jedyne miejsce prezentacji procesów w Centrum rozliczeń. Projekcja postępu pozostaje jedynym
interpretatorem Zdarzeń przebiegu (ADR 0002); widok tylko wybiera i nazywa jej fakty, a przeglądarka
renderuje go bez rozróżniania procesów (ADR 0004). Kontrakt niesie wyłącznie to, co karta pokazuje.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Final, Generic, TypeVar

from rozliczenia import settlement_messages
from rozliczenia.centrum import contract
from rozliczenia.collective_preparation import PreparationSummary
from rozliczenia.domain import SettlementSummary
from rozliczenia.message import Message
from rozliczenia.preparation_process import PreparationInputs
from rozliczenia.process_run import ProcessInputs
from rozliczenia.progress import ProgressSnapshot
from rozliczenia.settlement_process import SettlementInputs

InputsT = TypeVar("InputsT", bound=ProcessInputs)
SummaryT = TypeVar("SummaryT")


@dataclass(frozen=True)
class ProcessView(Generic[InputsT, SummaryT]):
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
    _warnings: Callable[[InputsT, SummaryT], Sequence[Message]]

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

    def warnings(self, inputs: InputsT, summary: SummaryT) -> list[Message]:
        """Ostrzeżenia zakończonego procesu."""

        return list(self._warnings(inputs, summary))


def _count(label: str, value: int) -> contract.Figure:
    return contract.Figure(label=label, value=value, unit="count")


# Etykiety Przebiegu rozliczeń wspólne dla liczb na żywo i wyniku.
_ROWS: Final = "Wiersze danych"
_PLANNED: Final = "Planowane szablony"
_WRITTEN: Final = "Zapisane szablony"
_EMPTY: Final = "Puste szablony"


def _settlement_figures(snapshot: ProgressSnapshot, dry_run: bool) -> list[contract.Figure]:
    counters = snapshot.metric_counters()
    return [
        _count(_ROWS, snapshot.rows),
        _count(_PLANNED, counters["planned"]) if dry_run else _count(_WRITTEN, counters["written"]),
        _count(_EMPTY, counters["empty"]),
        _count("Problemy", snapshot.issue_count),
    ]


def _settlement_summary(summary: SettlementSummary, dry_run: bool) -> contract.RunSummary:
    figures = (
        [
            _count(_ROWS, summary.total_rows),
            _count(_PLANNED, summary.planned_count),
            _count(_EMPTY, summary.empty_count),
        ]
        if dry_run
        else [
            _count(_WRITTEN, summary.written_count),
            _count(_EMPTY, summary.empty_count),
        ]
    )
    return contract.RunSummary(
        figures=figures,
        counts=None,
        files=[],
        file_plan=[contract.WorkerFile(file=result.output_file.name, rows=result.rows) for result in summary.results],
    )


def _settlement_warnings(inputs: SettlementInputs, summary: SettlementSummary) -> list[Message]:
    return [settlement_messages.issue_message(issue, inputs.source) for issue in summary.issues]


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
                contract.Count(label=label, count=count) for label, count in summary.labeled_orders_per_day()
            ],
        ),
        files=[
            contract.PeriodFile(name=summary.internal_settlement_file.name, kind="internal_settlement"),
            contract.PeriodFile(name=summary.collective_file.name, kind="collective_file"),
        ],
        file_plan=None,
    )


SETTLEMENT: Final[ProcessView[SettlementInputs, SettlementSummary]] = ProcessView(
    reminder="Zapisz i zamknij Plik zbiorczy w Excelu",
    confirms_readiness=True,
    preview_hint="Nic nie zostanie zapisane. Zobaczysz plan plików każdego Wykonawcy.",
    _figures=_settlement_figures,
    _summary=_settlement_summary,
    _warnings=_settlement_warnings,
)
PREPARATION: Final[ProcessView[PreparationInputs, PreparationSummary]] = ProcessView(
    reminder="Zapisz i zamknij Rejestr zleceń w Excelu",
    confirms_readiness=False,
    preview_hint="Nic nie zostanie zapisane. Zobaczysz plan i nazwy obu plików.",
    _figures=_preparation_figures,
    _summary=_preparation_summary,
    _warnings=lambda _inputs, summary: summary.warnings,
)

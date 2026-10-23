"""Procesy Centrum rozliczeń: rdzeń każdego procesu (seam ``Process``) z jego plikiem metryk.

Uruchomienia i Metryki biorą rdzeń procesu i jego plik metryk (``Process.metrics_path``) tylko stąd.
"""

from __future__ import annotations

from dataclasses import dataclass

from rozliczenia import preparation_process, settlement_process
from rozliczenia.collective_preparation import PreparationSummary
from rozliczenia.domain import SettlementSummary
from rozliczenia.preparation_process import PreparationInputs
from rozliczenia.process_run import Process
from rozliczenia.settlement_process import SettlementInputs


@dataclass(frozen=True)
class Processes:
    """Rdzenie obu procesów; pola zamiast słownika, bo wpis procesu buduje wejście konkretnego typu."""

    preparation: Process[PreparationInputs, PreparationSummary]
    settlement: Process[SettlementInputs, SettlementSummary]

    @classmethod
    def default(cls) -> Processes:
        return cls(preparation_process.PROCESS, settlement_process.PROCESS)

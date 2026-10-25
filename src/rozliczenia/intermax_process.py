"""Uporządkowanie INTERMAX dla Uruchomienia procesu: wejście procesu, wywołanie silnika i fakty zakończenia.

Opis procesu (``PROCESS``) jest wspólny dla każdego rozmówcy, więc liczby, Komunikaty i rekord metryk są te same.
Proces nie należy do okresu; jego Uruchomienie ma okres dzisiejszej daty z zegara procesu (ADR 0019).
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from . import TOOL_ROOT, intermax_copies, intermax_ordering
from . import intermax_messages as messages
from .decision import Conversation
from .domain import ProgressObserver
from .intermax_ordering import OrderingSummary
from .process_run import Finished, Process
from .settlement_period import period_of

_COUNTERS = frozenset({"orders", "workers"})


def default_metrics_path() -> Path:
    """Osobna lokalna historia metryk, obok historii pozostałych procesów."""

    return TOOL_ROOT / ".uporzadkowanie-intermax-metrics.jsonl"


def _local_now() -> datetime:
    return datetime.now().astimezone()


def _store(path: Path, content: bytes) -> None:
    path.write_bytes(content)


@dataclass(frozen=True)
class OrderingInputs:
    """Wejście procesu Uporządkowania INTERMAX: INTERMAX z Ustawień taty, folder Kopii i zegar procesu.

    ``store`` zapisuje bajty pliku tymczasowego przed jego sprawdzeniem; test podstawia zapis, który się psuje.
    """

    register_path: Path
    copies_directory: Path = field(default_factory=intermax_copies.default_directory)
    now: Callable[[], datetime] = _local_now
    store: Callable[[Path, bytes], None] = _store

    @property
    def dry_run(self) -> bool:
        """Uporządkowanie INTERMAX nie ma podglądu bez zapisu."""

        return False

    @property
    def period(self) -> str:
        return period_of(self.now().date()).token


def _execute(inputs: OrderingInputs, observer: ProgressObserver, _conversation: Conversation) -> OrderingSummary:
    return intermax_ordering.order_register(
        inputs.register_path, inputs.copies_directory, now=inputs.now, store=inputs.store, observer=observer
    )


def _finished(_inputs: OrderingInputs, summary: OrderingSummary) -> Finished:
    return Finished(
        result="OK",
        counters={"orders": summary.order_count, "workers": summary.worker_count},
        phase_durations_ms=summary.phase_durations_ms,
    )


PROCESS: Process[OrderingInputs, OrderingSummary] = Process(
    name="Uporządkowanie INTERMAX",
    counter_names=_COUNTERS,
    metrics_path=default_metrics_path,
    metrics_failure_tail="Uporządkowanie INTERMAX zakończyło się niezależnie.",
    execute=_execute,
    finished=_finished,
    unexpected_failure=messages.unexpected_failure(),
    plan_not_shown=messages.plan_not_shown(),
    summary_not_shown=messages.summary_not_shown(),
)

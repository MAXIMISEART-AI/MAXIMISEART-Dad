"""Sztuczny proces w pamięci: trzeci adapter seamu ``Process`` obok obu procesów taty."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
import json
from pathlib import Path
from typing import Any, NoReturn

from rozliczenia.decision import Conversation, Decision
from rozliczenia.domain import ProgressObserver, ProgressPhase
from rozliczenia.message import Message, StopError
from rozliczenia.phase_runner import PhaseRunner
from rozliczenia.process_run import Finished, Process

PERIOD = "08_14_09_2026"
COUNTERS = frozenset({"items"})
DETACHED_OBSERVER_NOTICE = "Podgląd postępu przestał się aktualizować; wynik nie zależy od tego."
METRICS_WARNING = "Ostrzeżenie: Nie zapisano metryk; Proces testowy zakończył się niezależnie."
SECRET = "sekret klienta SYN-001"
# Komunikaty zakończeń sztucznego procesu: każde zatrzymanie bez własnego Komunikatu procesu dostaje jeden z nich.
ENDINGS = {
    "unexpected_failure": Message("BLAD_NIEOCZEKIWANY", "Wystąpił nieoczekiwany błąd.", "Proces testowy", "Uruchom ponownie."),
    "plan_not_shown": Message("BLAD_PLANU", "Nie udało się pokazać planu.", "Proces testowy", "Zgłoś to."),
    "summary_not_shown": Message("BLAD_PODSUMOWANIA", "Nie udało się pokazać podsumowania.", "Proces testowy", "Zgłoś to."),
}

Durations = Mapping[ProgressPhase, int]


@dataclass(frozen=True)
class Inputs:
    period: str = PERIOD
    dry_run: bool = False


def stop_error(what: str, where: str = "Proces testowy", action: str = "Uruchom ponownie.") -> StopError:
    return StopError(Message(code="ZATRZYMANIE", what=what, where=where, action=action))


def all_phases(observer: ProgressObserver, before_save: Callable[[], None] = lambda: None) -> Durations:
    phases = PhaseRunner(observer)
    phases.check(lambda: None)
    phases.read(lambda: None)
    phases.plan(lambda: None)
    before_save()
    phases.save(lambda: None)
    return phases.durations_ms()


def execute(_inputs: Inputs, observer: ProgressObserver, _conversation: Conversation) -> Durations:
    return all_phases(observer)


def finished_with(result: str) -> Callable[[Durations], Finished]:
    def finished(durations: Durations) -> Finished:
        return Finished(
            result=result,  # type: ignore[arg-type]  # parametr testu: "OK" albo "WYMAGA_SPRAWDZENIA"
            counters={"items": 1},
            phase_durations_ms=durations,
        )

    return finished


def fail(*_args: object) -> NoReturn:
    raise RuntimeError(SECRET)


def fake_process(**overrides: Any) -> Process[Inputs, Durations]:
    fields: dict[str, Any] = {
        "name": "Proces testowy",
        "counter_names": COUNTERS,
        "metrics_path": lambda: Path("nieuzywany-plik-metryk.jsonl"),
        "metrics_failure_tail": "Proces testowy zakończył się niezależnie.",
        "execute": execute,
        "finished": finished_with("OK"),
        **ENDINGS,
    }
    fields.update(overrides)
    return Process(**fields)


def records(metrics_path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in metrics_path.read_text(encoding="utf-8").splitlines()]


QUESTION = Decision(
    title="Ostrzeżenie: pytanie",
    message=Message("PYTANIE", "Dane mogą być niepełne.", "Proces testowy", "Sprawdź liczby."),
    counts_title="Elementy",
    counts=[("pierwszy", 1)],
    question="Kontynuować?",
)


def asking_between_planning_and_saving(
    _inputs: Inputs, observer: ProgressObserver, conversation: Conversation
) -> Durations:
    def ask() -> None:
        if not conversation.confirm(QUESTION):
            raise stop_error("Przerwano zgodnie z odpowiedzią.")

    return all_phases(observer, before_save=ask)

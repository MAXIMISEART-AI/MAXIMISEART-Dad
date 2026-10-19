"""Kontrakt serwer ↔ przeglądarka: modele odpowiedzi i żądań Centrum rozliczeń.

Z tych modeli powstaje OpenAPI, a z niego schematy zod i typy w
``frontend/src/api/generated`` (``npm run contract`` w ``frontend/``).
"""

from __future__ import annotations

from datetime import date
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field


class _Model(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class Problem(_Model):
    """Odmowa wykonania żądania z bezpiecznym komunikatem dla taty, bez tekstu wyjątku."""

    message: str


class Refusal(Exception):
    """Serwer odmawia żądania; ``create_app`` zamienia odmowę na odpowiedź ``Problem``."""

    def __init__(self, status_code: int, message: str) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.message = message


class Health(_Model):
    service: Literal["centrum-rozliczen"]
    version: str


class NotSetPath(_Model):
    """Ścieżka jeszcze niewskazana albo plik ustawień nieczytelny."""

    state: Literal["not_set"]


class MissingPath(_Model):
    """Zapamiętana ścieżka, pod którą nie ma już pliku albo folderu."""

    state: Literal["missing"]
    path: str
    name: str


class ReadyPath(_Model):
    state: Literal["ready"]
    path: str
    name: str


PathSetting = Annotated[NotSetPath | MissingPath | ReadyPath, Field(discriminator="state")]
Theme = Literal["dark", "light"]


class Settings(_Model):
    order_register: PathSetting
    periods_directory: PathSetting
    theme: Theme


class Choice(_Model):
    """Wynik natywnego okna wyboru: ``chosen`` zapisuje ścieżkę, ``cancelled`` niczego nie zmienia."""

    outcome: Literal["chosen", "cancelled"]
    settings: Settings


class ThemeChange(_Model):
    theme: Theme


PeriodStatus = Literal["no_period_files", "collective_file_prepared", "worker_settlements_ready"]


class NextStep(_Model):
    """Podpowiedź następnego kroku okresu; ``none``, gdy okres jest zamknięty."""

    action: Literal["prepare_collective_file", "create_worker_settlements", "none"]
    label: str
    hint: str


class PeriodRow(_Model):
    """Jeden okres Tablicy okresów, wyliczony z plików przy każdym odczycie."""

    token: str
    tuesday: date
    monday: date
    status: PeriodStatus
    status_label: str
    period_folder_exists: bool
    internal_settlement_exists: bool
    collective_file_exists: bool
    worker_settlements_folder_exists: bool
    worker_settlement_count: int
    last_complete: bool
    next_step: NextStep


class BoardNotSet(_Model):
    state: Literal["not_set"]


class BoardMissing(_Model):
    state: Literal["missing"]
    name: str


class BoardReady(_Model):
    state: Literal["ready"]
    periods: list[PeriodRow]


PeriodBoard = Annotated[BoardNotSet | BoardMissing | BoardReady, Field(discriminator="state")]

OpenTarget = Literal["internal_settlement", "collective_file", "period_folder", "worker_settlements_folder"]


class OpenRequest(_Model):
    """Co otworzyć w okresie; ścieżkę wylicza serwer z folderu okresów, nigdy z żądania."""

    target: OpenTarget


class Opened(_Model):
    name: str


# Uruchomienia procesu. Każdy proces ma klucz; Przebieg rozliczeń dopisze swój (#99).
ProcessKey = Literal["preparation"]
PhaseName = Literal["Sprawdzanie", "Odczyt danych", "Planowanie", "Zapisywanie"]


class PeriodChoice(_Model):
    """Okres do wyboru przy starcie, ze Statusem okresu wyliczonym z plików."""

    token: str
    tuesday: date
    monday: date
    status_label: str
    last_complete: bool


class ProcessSetup(_Model):
    """Co tata wybiera przed Uruchomieniem procesu; ``blocker`` mówi, czego jeszcze brakuje w ustawieniach."""

    process: ProcessKey
    title: str
    creates: str
    reminder: str
    periods: list[PeriodChoice]
    preselected_period: str
    blocker: str | None


class RunSetup(_Model):
    processes: list[ProcessSetup]


class RunRequest(_Model):
    """Start Uruchomienia procesu; pliki wejściowe wylicza serwer z ustawień i okresu."""

    process: ProcessKey
    period: str
    dry_run: bool


class PhaseProgress(_Model):
    phase: PhaseName
    state: Literal["pending", "running", "completed", "failed"]
    duration_ms: int


class OperationProgress(_Model):
    worker_name: str
    status: str
    rows: int
    worker_elapsed_ms: int | None


class Progress(_Model):
    """Snapshot jedynej projekcji postępu (ADR 0002) w kształcie dla przeglądarki; nic nie jest tu wyliczane."""

    mode: Literal["RUN", "DRY-RUN"]
    period: str
    phases: list[PhaseProgress]
    current_phase: PhaseName | None
    template_total: int
    templates_completed: int
    current_worker: str | None
    rows: int
    operation_counts: dict[str, int]
    recent_operations: list[OperationProgress]
    total_elapsed_ms: int
    issue_count: int


class ProgressNotice(_Model):
    """Neutralne powiadomienie o ostatniej zmianie postępu."""

    kind: Literal[
        "PHASE_STARTED", "PHASE_ENDED", "ISSUE_COUNT", "PLAN_READY", "WORKER_STARTED", "WORKER_ENDED", "FAILED"
    ]
    phase: PhaseName
    worker_name: str | None
    status: str | None
    rows: int
    worker_elapsed_ms: int | None
    template_index: int
    template_total: int


class RunInfo(_Model):
    id: str
    process: ProcessKey
    title: str
    period: str
    dry_run: bool


class Message(_Model):
    """Komunikat w trzech częściach (Co się stało, Gdzie, Co zrobić) z liniami terminala; jednoliniowy ma tylko ``what``."""

    what: str
    where: str | None
    action: str | None


class Count(_Model):
    label: str
    count: int


class CountGroup(_Model):
    title: str
    counts: list[Count]


class Decision(_Model):
    """Pytanie do taty z liniami procesu: tytuł, komunikat w trzech częściach i liczby (np. Zlecenia na dzień)."""

    question: str
    title: str | None
    message: Message | None
    count_groups: list[CountGroup]


class PreparationSummary(_Model):
    """Podsumowanie albo plan (DRY-RUN) Przygotowania pliku zbiorczego, bez danych klientów."""

    period: str
    period_order_count: int
    successful_order_count: int
    skipped_empty_rows: int
    orders_per_day: list[Count]
    internal_settlement_file: str
    collective_file: str


class RunResult(_Model):
    """Wynik Uruchomienia procesu: te same linie co w terminalu, rozdzielone na zatrzymania, ostrzeżenia i resztę.

    ``ending`` mówi, jak się skończyło: ``finished``, własne zatrzymanie procesu (``stop``), nieoczekiwany
    błąd (``unexpected``) albo błąd po zakończeniu silnika (``after_engine``). ``next_action`` to jedyna
    akcja, którą Centrum proponuje po wyniku.
    """

    result: Literal["OK", "WYMAGA_SPRAWDZENIA", "BLAD_KRYTYCZNY"]
    ending: Literal["finished", "stop", "unexpected", "after_engine"]
    next_action: Literal["run", "rerun", "open_period_folder"]
    status_line: str
    total_duration_ms: int
    stops: list[Message]
    warnings: list[Message]
    notices: list[str]
    summary: PreparationSummary | None
    lines: list[str]


class RunIdle(_Model):
    """Od startu serwera nie było żadnego Uruchomienia procesu."""

    state: Literal["idle"]


class RunRunning(_Model):
    state: Literal["running"]
    run: RunInfo
    progress: Progress
    notice: ProgressNotice | None
    progress_stale: bool


class RunAwaitingDecision(_Model):
    """Uruchomienie czeka na decyzję taty; czas czekania nie wlicza się do czasu ani do metryk."""

    state: Literal["awaiting_decision"]
    run: RunInfo
    progress: Progress
    decision: Decision


class RunFinished(_Model):
    state: Literal["finished"]
    run: RunInfo
    progress: Progress
    progress_stale: bool
    result: RunResult


RunView = Annotated[RunIdle | RunRunning | RunAwaitingDecision | RunFinished, Field(discriminator="state")]


class RunEvent(_Model):
    """Jedno zdarzenie strumienia SSE: kolejny numer i pełny widok bieżącego Uruchomienia procesu."""

    sequence: int
    view: RunView


class DecisionAnswer(_Model):
    answer: Literal["continue", "abort"]

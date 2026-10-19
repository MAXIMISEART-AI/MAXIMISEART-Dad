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


class Closing(_Model):
    """Centrum przyjęło prośbę o zamknięcie i kończy pracę po tej odpowiedzi."""

    state: Literal["closing"]


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

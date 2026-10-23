"""Centrum rozliczeń w testach: aplikacja na syntetycznym folderze okresów i skryptowany komputer taty."""

from __future__ import annotations

import json
import threading
from collections.abc import Iterator, Sequence
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient

from rozliczenia.centrum.app import create_app
from rozliczenia.centrum.cloud_files import CloudFiles
from rozliczenia.centrum.log import CentrumLog
from rozliczenia.centrum.metrics import MetricsFiles
from rozliczenia.centrum.report_box import (
    FindOutcome,
    Refused,
    Report,
    SendOutcome,
    Sent,
    StatesOutcome,
    Unreachable,
)
from rozliczenia.centrum.shutdown import Shutdown
from rozliczenia.centrum.tool_freshness import GitHubReleases, ToolFreshness

ROOT = Path(__file__).resolve().parents[2]


CENTRUM = "http://127.0.0.1:47811"
# Syntetyczny commit narzędzia; testy nigdy nie czytają prawdziwego `main` z GitHuba.
TOOL_COMMIT = "3c1d0a9e5b7f4c2d8e6a1b0f9c8d7e6a5b4c3d2e"
# GitHub odpowiedział, ale nie ma żadnego Wydania na `main`.
NO_RELEASE = "brak-wydania"
# Atrybuty plików Windows: zwykły plik i plik OneDrive „tylko online” (FILE_ATTRIBUTE_RECALL_ON_DATA_ACCESS).
NORMAL_FILE = 0x80
ONLINE_ONLY_FILE = 0x400000


@dataclass
class FakePlatform:
    """Akcje systemowe komputera taty zastąpione zapisem wywołań i przygotowanymi odpowiedziami."""

    chosen_files: list[Path | None] = field(default_factory=list)
    chosen_folders: list[Path | None] = field(default_factory=list)
    opened: list[Path] = field(default_factory=list)
    dialog_titles: list[str] = field(default_factory=list)
    failure: Exception | None = None  # awaria systemu przy otwieraniu, np. zablokowany Excel

    def open_path(self, path: Path) -> None:
        if self.failure is not None:
            raise self.failure
        self.opened.append(path)

    def choose_file(self, title: str, filetypes: Sequence[tuple[str, str]]) -> Path | None:
        self.dialog_titles.append(title)
        return self.chosen_files.pop(0)

    def choose_folder(self, title: str) -> Path | None:
        self.dialog_titles.append(title)
        return self.chosen_folders.pop(0)


@dataclass
class FakeReportBox:
    """Skrzynka Zgłoszeń zastąpiona zapisem wysłanych Zgłoszeń i przygotowanymi wynikami wysyłki.

    Bez przygotowanego wyniku każde Zgłoszenie dostaje kolejny numer issue i jest
    otwarte (``open``: odcisk problemu → numer), dopóki Maks nie zamknie jego
    numeru (``close``). ``search_failure`` to odmowa albo brak połączenia przy
    każdym pytaniu o otwarte Zgłoszenie, ``states_failure`` to porażka każdego
    zapytania o stan, a ``asked`` to numery z każdego zapytania o stan.
    ``search_hold`` to skrzynka, która na pytanie o otwarte Zgłoszenie odpowiada
    dopiero, gdy test ją puści (``set``), jak GitHub bez sieci; ``searching``
    mówi, że takie pytanie już trwa.
    """

    outcomes: list[SendOutcome] = field(default_factory=list)
    sent: list[Report] = field(default_factory=list)
    keys: list[str] = field(default_factory=list)
    open: dict[str, int] = field(default_factory=dict)
    closed: set[int] = field(default_factory=set)
    search_failure: Refused | Unreachable | None = None
    states_failure: Refused | Unreachable | None = None
    asked: list[list[int]] = field(default_factory=list)
    search_hold: threading.Event | None = None
    searching: threading.Event = field(default_factory=threading.Event)

    def send(self, report: Report, *, key: str) -> SendOutcome:
        self.keys.append(key)
        outcome = self.outcomes.pop(0) if self.outcomes else Sent(number=len(self.sent) + 1)
        if isinstance(outcome, Sent):
            self.sent.append(report)
            self.open[report.fingerprint] = outcome.number
        return outcome

    def find_open(self, fingerprint: str, *, key: str) -> FindOutcome:
        self.searching.set()
        if self.search_hold is not None:
            self.search_hold.wait()
        if self.search_failure is not None:
            return self.search_failure
        number = self.open.get(fingerprint)
        return None if number is None or number in self.closed else number

    def close(self, number: int) -> None:
        self.closed.add(number)

    def states(self, numbers: Sequence[int], *, key: str) -> StatesOutcome:
        assert key, "skrzynka pytana bez klucza"
        self.asked.append(list(numbers))
        if self.states_failure is not None:
            return self.states_failure
        return {number: "closed" if number in self.closed else "open" for number in numbers}


@dataclass
class FakeClock:
    """Zegar monotoniczny Centrum w sekundach, przesuwany przez test."""

    seconds: float = 0.0

    def __call__(self) -> float:
        return self.seconds

    def advance(self, *, minutes: float) -> None:
        self.seconds += minutes * 60


@dataclass
class FakeGitHub:
    """Commit narzędzia u taty, dzień, od którego narzędzie jest na nim, i commit najnowszego Wydania na GitHubie.

    ``release=None`` to brak sieci, ``NO_RELEASE`` to GitHub bez żadnego Wydania; ``asked`` liczy pytania o Wydania.
    Commit narzędzia zawiera tylko taki sam commit Wydania.
    """

    tool_commit: str | None = TOOL_COMMIT
    since: date | None = None
    release: str | None = TOOL_COMMIT
    asked: int = 0

    def freshness(self) -> ToolFreshness:
        return ToolFreshness(local=lambda: self.tool_commit, since=lambda: self.since, release=self._release)

    def _release(self) -> GitHubReleases | None:
        self.asked += 1
        if self.release is None:
            return None
        return GitHubReleases(None if self.release == NO_RELEASE else self.release)


@dataclass
class FakeOneDrive:
    """Atrybuty plików jak w Windows: pliki z ``online_only`` są tylko w OneDrive w chmurze."""

    online_only: set[Path] = field(default_factory=set)

    def attributes(self, path: Path) -> int:
        return ONLINE_ONLY_FILE if path in self.online_only else NORMAL_FILE

    def cloud_files(self) -> CloudFiles:
        return CloudFiles(read_attributes=self.attributes)


@dataclass
class Centrum:
    client: TestClient
    platform: FakePlatform
    settings_path: Path
    metrics: MetricsFiles
    log_path: Path
    report_box: FakeReportBox


def centrum(tmp_path: Path, *, today: date = date(2026, 10, 19)) -> Centrum:
    platform = FakePlatform()
    report_box = FakeReportBox()
    settings_path = tmp_path / "config" / "centrum-ustawienia.yaml"
    # Pliki metryk obu procesów w katalogu testu, nigdy historia z katalogu narzędzia.
    metrics = MetricsFiles(preparation=tmp_path / "przygotowanie-metrics.jsonl", settlement=tmp_path / "metrics.jsonl")
    log_path = tmp_path / "logs" / "centrum-rozliczen.log"
    log = CentrumLog(log_path)
    app = create_app(
        settings_path=settings_path,
        platform=platform,
        log=log,
        shutdown=Shutdown(log),
        today=lambda: today,
        metrics_files=metrics,
        tool_freshness=FakeGitHub().freshness(),
        cloud_files=FakeOneDrive().cloud_files(),
        report_box=report_box,
    )
    client = TestClient(app, base_url=CENTRUM, headers={"Origin": CENTRUM})
    return Centrum(client, platform, settings_path, metrics, log_path, report_box)


def view_timing(**changes: object) -> dict[str, object]:
    """Pomiar zimnego startu Metryk, jaki przeglądarka wysyła po gotowym widoku; ``changes`` podmienia pola."""

    timing: dict[str, object] = {
        "kind": "cold_start",
        "page": "metryki",
        "ready_ms": 415,
        "fcp_ms": 210,
        "skeleton_ms": 120,
        "requests": [
            {"operation": "getSettings", "browser_ms": 12, "server_ms": 3},
            {"operation": "getMetrics", "browser_ms": 48, "server_ms": None},
        ],
    }
    return timing | changes


def run_events(client: TestClient) -> Iterator[dict[str, Any]]:
    """Zdarzenia strumienia SSE Uruchomień procesu, każde jako sparsowany JSON z linii ``data:``."""

    with client.stream("GET", "/api/runs/events") as response:
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/event-stream")
        for line in response.iter_lines():
            if line.startswith("data: "):
                yield json.loads(line.removeprefix("data: "))


def views_until(client: TestClient, *states: str) -> list[dict[str, Any]]:
    """Widoki bieżącego Uruchomienia ze strumienia, aż do pierwszego w jednym ze stanów ``states``."""

    views = []
    for event in run_events(client):
        views.append(event["view"])
        if event["view"]["state"] in states:
            return views
    raise AssertionError("Strumień skończył się przed oczekiwanym stanem.")


def finished_view(client: TestClient) -> dict[str, Any]:
    return views_until(client, "finished")[-1]


def phase_states(view: dict[str, Any]) -> dict[str, str]:
    return {phase["phase"]: phase["state"] for phase in view["progress"]["phases"]}

"""Centrum rozliczeń w testach: aplikacja na syntetycznym folderze okresów i skryptowany komputer taty."""

from __future__ import annotations

import json
import tomllib
from collections.abc import Iterator, Sequence
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient

from rozliczenia.centrum.app import create_app
from rozliczenia.centrum.log import CentrumLog
from rozliczenia.centrum.metrics import MetricsFiles
from rozliczenia.centrum.report_box import Report, SendOutcome, Sent
from rozliczenia.centrum.shutdown import Shutdown

ROOT = Path(__file__).resolve().parents[2]


CENTRUM = "http://127.0.0.1:47811"


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

    Bez przygotowanego wyniku każde Zgłoszenie dostaje kolejny numer issue.
    """

    outcomes: list[SendOutcome] = field(default_factory=list)
    sent: list[Report] = field(default_factory=list)
    keys: list[str] = field(default_factory=list)

    def send(self, report: Report, *, key: str) -> SendOutcome:
        self.keys.append(key)
        outcome = self.outcomes.pop(0) if self.outcomes else Sent(number=len(self.sent) + 1)
        if isinstance(outcome, Sent):
            self.sent.append(report)
        return outcome


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
        report_box=report_box,
    )
    client = TestClient(app, base_url=CENTRUM, headers={"Origin": CENTRUM})
    return Centrum(client, platform, settings_path, metrics, log_path, report_box)


def project_version() -> str:
    with (ROOT / "pyproject.toml").open("rb") as file:
        version = tomllib.load(file)["project"]["version"]
    assert isinstance(version, str)
    return version


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

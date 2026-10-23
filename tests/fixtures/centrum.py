"""Centrum rozliczeń w testach: aplikacja na syntetycznym folderze okresów i skryptowany komputer taty."""

from __future__ import annotations

import json
import threading
from collections.abc import Callable, Iterator, Sequence
from dataclasses import dataclass, field, replace
from datetime import date
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient

from rozliczenia import preparation_process, settlement_process
from rozliczenia.centrum.app import create_app
from rozliczenia.centrum.cloud_files import CloudFiles
from rozliczenia.centrum.log import CentrumLog
from rozliczenia.centrum.processes import Processes
from rozliczenia.centrum.report_box import (
    REPORT_LABEL,
    REPOSITORY,
    CommentOutcome,
    Commented,
    Issue,
    IssuesOutcome,
    Label,
    Refused,
    SendOutcome,
    Sent,
    StatesOutcome,
    Unreachable,
)
from rozliczenia.centrum.shutdown import Shutdown
from rozliczenia.centrum.tool_freshness import ToolFreshness

ROOT = Path(__file__).resolve().parents[2]


CENTRUM = "http://127.0.0.1:47811"
# Syntetyczny commit narzędzia; testy nigdy nie czytają prawdziwego `main` z GitHuba.
TOOL_COMMIT = "3c1d0a9e5b7f4c2d8e6a1b0f9c8d7e6a5b4c3d2e"
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
class FakeIssue:
    """Issue fałszywej skrzynki: etykieta, tytuł i treść, jak je założyło Centrum."""

    number: int
    label: Label
    title: str
    body: str
    comments: list[str] = field(default_factory=list)


@dataclass
class FakeReportBox:
    """Skrzynka Zgłoszeń zastąpiona zapisem założonych issue i przygotowanymi wynikami.

    Bez przygotowanego wyniku (``outcomes``, po jednym na każde zakładane issue) każde
    issue dostaje kolejny numer i jest otwarte, dopóki Maks nie zamknie jego numeru
    (``close``); komentarz do issue, którego nie ma, to odmowa jak 404 GitHuba. ``sent`` to Zgłoszenia (etykieta ``zgloszenie``), a ``issues_with``
    issue innej etykiety. ``search_failure`` to odmowa albo brak połączenia przy
    każdym pytaniu o issue z etykietą, ``states_failure`` to porażka każdego
    zapytania o stan, a ``asked`` to numery z każdego zapytania o stan.
    ``search_hold`` to skrzynka, która na pytanie o issue z etykietą odpowiada
    dopiero, gdy test ją puści (``set``), jak GitHub bez sieci; ``searching``
    mówi, że takie pytanie już trwa. ``open_hold`` i ``opening`` robią to samo
    z zakładaniem issue, a ``comment_outcomes`` to przygotowane wyniki komentarzy.
    ``wait_until`` czeka na wysyłkę w tle.
    """

    outcomes: list[SendOutcome] = field(default_factory=list)
    issues: list[FakeIssue] = field(default_factory=list)
    keys: list[str] = field(default_factory=list)
    closed: set[int] = field(default_factory=set)
    search_failure: Refused | Unreachable | None = None
    states_failure: Refused | Unreachable | None = None
    asked: list[list[int]] = field(default_factory=list)
    search_hold: threading.Event | None = None
    searching: threading.Event = field(default_factory=threading.Event)
    open_hold: threading.Event | None = None
    opening: threading.Event = field(default_factory=threading.Event)
    comment_outcomes: list[CommentOutcome] = field(default_factory=list)
    _changed: threading.Condition = field(default_factory=threading.Condition)

    def wait_until(self, condition: Callable[[FakeReportBox], bool], seconds: float = 30) -> bool:
        """Czeka, aż skrzynka dostanie to, czego test oczekuje (wysyłka w tle); ``False`` po ``seconds``."""

        with self._changed:
            return self._changed.wait_for(lambda: condition(self), seconds)

    @property
    def sent(self) -> list[FakeIssue]:
        return self.issues_with(REPORT_LABEL)

    def issues_with(self, label: Label) -> list[FakeIssue]:
        with self._changed:
            return [issue for issue in self.issues if issue.label == label]

    def open_issue(self, label: Label, title: str, body: str, *, key: str) -> SendOutcome:
        self.opening.set()
        if self.open_hold is not None:
            self.open_hold.wait()
        with self._changed:
            self.keys.append(key)
            outcome = self.outcomes.pop(0) if self.outcomes else Sent(number=len(self.issues) + 1)
            if isinstance(outcome, Sent):
                self.issues.append(FakeIssue(outcome.number, label, title, body))
            self._changed.notify_all()
        return outcome

    def comment(self, number: int, body: str, *, key: str) -> CommentOutcome:
        with self._changed:
            self.keys.append(key)
            self._changed.notify_all()
            if self.comment_outcomes:
                return self.comment_outcomes.pop(0)
            issue = next((issue for issue in self.issues if issue.number == number), None)
            if issue is None:
                return Refused()
            issue.comments.append(body)
            comment_id = sum(len(issue.comments) for issue in self.issues)
        return Commented(comment_id, f"https://github.com/{REPOSITORY}/issues/{number}#issuecomment-{comment_id}")

    def labelled_issues(self, label: Label, *, include_closed: bool, key: str) -> IssuesOutcome:
        self.searching.set()
        if self.search_hold is not None:
            self.search_hold.wait()
        if self.search_failure is not None:
            return self.search_failure
        return tuple(
            Issue(issue.number, issue.body)
            for issue in self.issues_with(label)
            if include_closed or issue.number not in self.closed
        )

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
    """Commit narzędzia u taty, dzień, od którego narzędzie jest na nim, i commit `main` na GitHubie.

    ``main=None`` to brak sieci; ``asked`` liczy pytania o `main`.
    """

    tool_commit: str | None = TOOL_COMMIT
    since: date | None = None
    main: str | None = TOOL_COMMIT
    asked: int = 0

    def freshness(self) -> ToolFreshness:
        return ToolFreshness(local=lambda: self.tool_commit, since=lambda: self.since, main=self._main)

    def _main(self) -> str | None:
        self.asked += 1
        return self.main


@dataclass
class FakeOneDrive:
    """Atrybuty plików jak w Windows: pliki z ``online_only`` są tylko w OneDrive w chmurze."""

    online_only: set[Path] = field(default_factory=set)

    def attributes(self, path: Path) -> int:
        return ONLINE_ONLY_FILE if path in self.online_only else NORMAL_FILE

    def cloud_files(self) -> CloudFiles:
        return CloudFiles(read_attributes=self.attributes)


@dataclass(frozen=True)
class MetricsPaths:
    """Pliki metryk obu procesów w Centrum testu zamiast historii z katalogu narzędzia."""

    preparation: Path
    settlement: Path

    def processes(self) -> Processes:
        return Processes(
            preparation=replace(preparation_process.PROCESS, metrics_path=lambda: self.preparation),
            settlement=replace(settlement_process.PROCESS, metrics_path=lambda: self.settlement),
        )


@dataclass
class Centrum:
    client: TestClient
    platform: FakePlatform
    settings_path: Path
    metrics: MetricsPaths
    log_path: Path
    report_box: FakeReportBox


def centrum(tmp_path: Path, *, today: date = date(2026, 10, 19)) -> Centrum:
    platform = FakePlatform()
    report_box = FakeReportBox()
    settings_path = tmp_path / "config" / "centrum-ustawienia.yaml"
    metrics = MetricsPaths(preparation=tmp_path / "przygotowanie-metrics.jsonl", settlement=tmp_path / "metrics.jsonl")
    log_path = tmp_path / "logs" / "centrum-rozliczen.log"
    log = CentrumLog(log_path)
    app = create_app(
        settings_path=settings_path,
        platform=platform,
        log=log,
        shutdown=Shutdown(log),
        today=lambda: today,
        processes=metrics.processes(),
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

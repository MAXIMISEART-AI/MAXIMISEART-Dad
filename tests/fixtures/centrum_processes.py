"""Centrum rozliczeń w testach z procesem do uruchomienia: syntetyczne pliki Przygotowania i Przebiegu.

``restart()`` to nowa aplikacja Centrum na tych samych plikach i Ustawieniach
taty, jak po zamknięciu i ponownym otwarciu Centrum na komputerze taty.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date
import json
from pathlib import Path
import shutil
import threading
from typing import Any, NoReturn, Protocol

import pytest

from fastapi.testclient import TestClient

from rozliczenia.centrum import run_view
from rozliczenia.centrum.app import create_app
from rozliczenia.centrum.configuration import ConfigurationFiles
from rozliczenia.centrum.log import CentrumLog
from rozliczenia.centrum.metrics import MetricsFiles
from rozliczenia.centrum.restart_guardian import Restart
from rozliczenia.centrum.shutdown import Shutdown
from rozliczenia.centrum.tool_freshness import ToolFreshness
from rozliczenia.centrum.tool_update import ToolClone

from tests.fixtures.centrum import (
    CENTRUM,
    FakeClock,
    FakeGitHub,
    FakeOneDrive,
    FakePlatform,
    FakeReportBox,
    finished_view,
)
from tests.fixtures.preparation import PERIOD, PreparationFixture, RegisterRow, make_preparation_fixture
from tests.fixtures.settlement import SOURCE_NAME, write_mapping, write_source, write_template
from tests.fixtures.tool_clone import FakeInstaller, ToolRepository

# Środa po okresie 08_14_09_2026, więc to on jest ostatnim pełnym okresem.
TODAY = date(2026, 9, 16)
WORKER_SETTLEMENTS = f"Rozliczenie pracowników {PERIOD}"


@dataclass
class Surroundings:
    """GitHub, OneDrive, skrzynka Zgłoszeń i zegar widziane z komputera taty.

    ``onedrive=None`` to prawdziwy odczyt atrybutów tego systemu. ``tool`` to
    narzędzie jako prawdziwy klon z lokalnym „origin” zamiast GitHuba: wtedy
    commit narzędzia i najnowsze Wydanie pochodzą z tych repozytoriów, a Aktualizacja
    narzędzia przesuwa ten klon. ``update_hold`` zatrzymuje każdą Aktualizację
    narzędzia na jej początku, dopóki test jej nie puści (``set``), a
    ``installer`` instaluje biblioteki zamiast pip. Opiekun ponownego startu po udanej
    aktualizacji tylko zapisuje prośbę w ``restarts`` (i usuwa katalog
    tymczasowy aktualizacji, jak prawdziwy po starcie nowej wersji). Z
    ``guardian_failure`` opiekun nie wystartuje: wywołuje ją i rzuca ``OSError``.
    """

    github: FakeGitHub = field(default_factory=FakeGitHub)
    onedrive: FakeOneDrive | None = field(default_factory=FakeOneDrive)
    report_box: FakeReportBox = field(default_factory=FakeReportBox)
    clock: FakeClock = field(default_factory=FakeClock)
    tool: ToolRepository | None = None
    update_hold: threading.Event | None = None
    installer: FakeInstaller = field(default_factory=FakeInstaller)
    restarts: list[Restart] = field(default_factory=list)
    guardian_failure: Callable[[], None] | None = None

    def tool_freshness(self) -> ToolFreshness:
        tool = self.tool
        if tool is None:
            return self.github.freshness()
        return ToolFreshness.of_clone(tool.clone, tool.newest_release_commit)

    def tool_update(self) -> ToolClone | None:
        tool, hold = self.tool, self.update_hold
        if tool is None:
            return None

        def held_git() -> Path | None:
            if hold is not None:
                hold.wait()
            found = shutil.which("git")
            return None if found is None else Path(found)

        return ToolClone(
            tool.clone, origin=str(tool.origin), find_git=held_git, install=self.installer
        )

    def guardian(self, copy: Path, restart: Restart) -> None:
        assert (copy / "rozliczenia" / "centrum" / "restart_guardian.py").is_file()
        if self.guardian_failure is not None:
            self.guardian_failure()
            raise OSError("opiekun nie wystartował")
        self.restarts.append(restart)
        shutil.rmtree(restart.work)


def _client(
    tmp_path: Path,
    platform: FakePlatform,
    configuration: ConfigurationFiles,
    metrics: MetricsFiles,
    surroundings: Surroundings,
) -> TestClient:
    log = CentrumLog(tmp_path / "logs" / "centrum-rozliczen.log")
    onedrive = surroundings.onedrive
    app = create_app(
        settings_path=tmp_path / "config" / "centrum-ustawienia.yaml",
        platform=platform,
        log=log,
        shutdown=Shutdown(log),
        today=lambda: TODAY,
        configuration_files=configuration,
        metrics_files=metrics,
        tool_freshness=surroundings.tool_freshness(),
        cloud_files=None if onedrive is None else onedrive.cloud_files(),
        report_box=surroundings.report_box,
        clock=surroundings.clock,
        tool_update=surroundings.tool_update(),
        guardian=surroundings.guardian,
    )
    return TestClient(app, base_url=CENTRUM, headers={"Origin": CENTRUM})


@dataclass
class PreparingCentrum:
    client: TestClient
    fixture: PreparationFixture
    metrics_path: Path
    log_path: Path
    tmp_path: Path
    surroundings: Surroundings

    def start(self, *, dry_run: bool, period: str = PERIOD) -> Any:
        return self.client.post("/api/runs", json={"process": "preparation", "period": period, "dry_run": dry_run})

    def metric_records(self) -> list[dict[str, Any]]:
        text = self.metrics_path.read_text(encoding="utf-8")
        return [json.loads(line) for line in text.splitlines()]

    def restart(self) -> None:
        """Nowe Centrum na tych samych plikach i Ustawieniach taty."""

        self.client = _preparation_client(self.tmp_path, self.fixture, FakePlatform(), self.surroundings)


def _preparation_client(
    tmp_path: Path, fixture: PreparationFixture, platform: FakePlatform, surroundings: Surroundings
) -> TestClient:
    configuration = ConfigurationFiles(
        worker_config=fixture.config_path,
        internal_template=fixture.internal_template_path,
        collective_template=fixture.collective_template_path,
        worker_template=tmp_path / "config" / "Wzorzec rozliczenia pracownika.xlsx",
    )
    return _client(tmp_path, platform, configuration, _metrics(tmp_path), surroundings)


def _metrics(tmp_path: Path) -> MetricsFiles:
    return MetricsFiles(
        preparation=tmp_path / ".przygotowanie-pliku-zbiorczego-metrics.jsonl",
        settlement=tmp_path / ".rozliczenia-metrics.jsonl",
    )


def preparing_centrum(
    tmp_path: Path, rows: list[RegisterRow] | None = None, *, surroundings: Surroundings | None = None
) -> PreparingCentrum:
    """Centrum z zapamiętanym syntetycznym Rejestrem zleceń i folderem okresów oraz własnymi wzorcami i metrykami.

    Bez ``surroundings`` narzędzie jest aktualne, a każdy plik ma kopię na tym komputerze.
    """

    fixture = make_preparation_fixture(tmp_path, rows)
    platform = FakePlatform(chosen_files=[fixture.register_path], chosen_folders=[fixture.periods_directory])
    surroundings = surroundings or Surroundings()
    client = _preparation_client(tmp_path, fixture, platform, surroundings)
    client.post("/api/settings/register/choose")
    client.post("/api/settings/periods-directory/choose")
    return PreparingCentrum(
        client,
        fixture,
        _metrics(tmp_path).preparation,
        tmp_path / "logs" / "centrum-rozliczen.log",
        tmp_path,
        surroundings,
    )


@dataclass
class SettlingCentrum:
    client: TestClient
    periods_directory: Path
    metrics_path: Path
    log_path: Path
    period_parent: Path
    configuration: ConfigurationFiles
    tmp_path: Path
    surroundings: Surroundings

    @property
    def period_directory(self) -> Path:
        return self.period_parent / PERIOD

    @property
    def collective_file(self) -> Path:
        return self.period_directory / SOURCE_NAME

    @property
    def worker_settlements(self) -> Path:
        return self.period_directory / WORKER_SETTLEMENTS

    def start(self, *, dry_run: bool, period: str = PERIOD) -> Any:
        return self.client.post("/api/runs", json={"process": "settlement", "period": period, "dry_run": dry_run})

    def metric_records(self) -> list[dict[str, Any]]:
        text = self.metrics_path.read_text(encoding="utf-8")
        return [json.loads(line) for line in text.splitlines()]

    def restart(self) -> None:
        """Nowe Centrum na tych samych plikach i Ustawieniach taty."""

        self.client = _client(
            self.tmp_path, FakePlatform(), self.configuration, _metrics(self.tmp_path), self.surroundings
        )


def settling_centrum(
    tmp_path: Path, *, include_unmapped: bool = False, dad_layout: bool = False
) -> SettlingCentrum:
    """Centrum z zapamiętanym folderem okresów, w którym okres ma tylko syntetyczny Plik zbiorczy.

    ``dad_layout`` kładzie Folder okresu w ``Załączniki\\Rozliczenia 2026\\09_Wrzesień_2026\\INEA``.
    """

    periods_directory = tmp_path / ("Załączniki" if dad_layout else "INEA")
    parent = periods_directory / "Rozliczenia 2026" / "09_Wrzesień_2026" / "INEA" if dad_layout else periods_directory
    (parent / PERIOD).mkdir(parents=True)
    write_source(parent / PERIOD / SOURCE_NAME, include_unmapped=include_unmapped)
    config = tmp_path / "config"
    config.mkdir()
    worker_template = config / "Wzorzec rozliczenia pracownika.xlsx"
    write_template(worker_template)
    configuration = ConfigurationFiles(
        worker_config=write_mapping(config / "worker_mapping.yaml"),
        internal_template=config / "Wzorzec rozliczenia wewnętrznego.xlsx",
        collective_template=config / "Wzorzec pliku zbiorczego.xlsx",
        worker_template=worker_template,
    )
    metrics = _metrics(tmp_path)
    surroundings = Surroundings()
    client = _client(tmp_path, FakePlatform(chosen_folders=[periods_directory]), configuration, metrics, surroundings)
    client.post("/api/settings/periods-directory/choose")
    log_path = tmp_path / "logs" / "centrum-rozliczen.log"
    return SettlingCentrum(
        client, periods_directory, metrics.settlement, log_path, parent, configuration, tmp_path, surroundings
    )


class _Starting(Protocol):
    @property
    def client(self) -> TestClient: ...

    def start(self, *, dry_run: bool, period: str = PERIOD) -> Any: ...


def run_to_end(centrum: _Starting, *, dry_run: bool) -> dict[str, Any]:
    started = centrum.start(dry_run=dry_run)
    assert started.status_code == 200, started.json()
    return finished_view(centrum.client)


def stopped_for_maks(centrum: PreparingCentrum | SettlingCentrum, monkeypatch: pytest.MonkeyPatch) -> str:
    """Zatrzymanie „do Maksa” bez zmiany plików: podgląd, którego planu nie da się pokazać; zwraca id Uruchomienia."""

    def broken_summary(*args: object, **kwargs: object) -> NoReturn:
        raise ValueError("synthetic summary failure SYN-001")

    monkeypatch.setattr(run_view.ProcessView, "summary", broken_summary)
    view = run_to_end(centrum, dry_run=True)
    assert view["result"]["stop_kind"] == "for_maks"
    return str(view["run"]["id"])

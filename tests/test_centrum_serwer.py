"""Serwer Centrum rozliczeń: ``start`` i ``stop`` w dzienniku, póki Centrum trzyma port, i kolejka Skrzynki Zgłoszeń,
która przy zamknięciu kończy rozpoczętą wysyłkę, zanim Centrum zwolni port dla następnego."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
import threading

from fastapi import FastAPI
import pytest

from rozliczenia.centrum.app import create_app
from rozliczenia.centrum.launcher import listen_locally
from rozliczenia.centrum.log import CentrumLog
from rozliczenia.centrum.outbox import PeriodThread, Post
from rozliczenia.centrum.report_box import Unreachable
from rozliczenia.centrum.server import serve
from rozliczenia.centrum.shutdown import Shutdown

from tests.fixtures.centrum import (
    FakeGitHub,
    FakeOneDrive,
    FakePlatform,
    FakeReportBox,
    MetricsPaths,
    join_threads_since,
    new_line,
)
from tests.fixtures.clock import ManualClock
from tests.fixtures.potomne import wait_for

KONTROLA = Post.of(
    PeriodThread(
        "kontrola-ilosci", "- Kontrola ilości okresu: 08_14_09_2026", "new_issue", "Kontrola ilości 08_14_09_2026"
    ),
    period="08_14_09_2026",
    run_id="3f2a9c1b8e7d4f0a9b1c2d3e4f5a6b7c",
    blocks=["różnice\n"],
    frame=lambda _number, _count, text: text,
)
QUEUED = "20261023T101500000000Z-0001-kontrola-ilosci-3f2a9c1b.json"


def _port_free(port: int) -> bool:
    """Czy nowe Centrum mogłoby teraz zająć ``port``."""

    try:
        listen_locally(port).close()
    except OSError:
        return False
    return True


class _PortAtStop(CentrumLog):
    """Dziennik, który przy ``stop`` sprawdza, czy nowe Centrum mogłoby już zająć port."""

    port_free_at_stop: bool | None = None

    def stopped(self, *, port: int) -> None:
        self.port_free_at_stop = _port_free(port)
        super().stopped(port=port)


class _PortWhileClosing(CentrumLog):
    """Dziennik, który w następnym kroku pętli serwera po ``stop`` sprawdza port, a potem puszcza skrzynkę (``hold``).

    Uvicorn zamyka gniazdo zaraz po ``stop``, bez oddania pętli po drodze, więc ten krok przychodzi przed zamknięciem
    tylko wtedy, gdy zamykanie serwera najpierw na coś czeka.
    """

    port_free_while_closing: bool | None = None

    def __init__(self, path: Path, hold: threading.Event) -> None:
        super().__init__(path)
        self._hold = hold

    def stopped(self, *, port: int) -> None:
        super().stopped(port=port)
        asyncio.get_running_loop().call_soon(self._check, port)

    def _check(self, port: int) -> None:
        self.port_free_while_closing = _port_free(port)
        self._hold.set()


def _events(path: Path) -> list[str]:
    return [line.split(" ")[1] for line in path.read_text(encoding="utf-8").splitlines()] if path.exists() else []


def _centrum(tmp_path: Path, box: FakeReportBox, log: CentrumLog, clock: ManualClock) -> tuple[FastAPI, Shutdown]:
    """Centrum z kluczem do Zgłoszeń, w którego kolejce czeka Kontrola ilości z poprzedniej pracy Centrum."""

    config = tmp_path / "config"
    (config / "zgloszenia" / "kolejka").mkdir(parents=True)
    (config / "zgloszenia-klucz.txt").write_text("github_pat_SYNTETYCZNY_KLUCZ\n", encoding="utf-8")
    (config / "zgloszenia" / "kolejka" / QUEUED).write_text(KONTROLA.to_json(), encoding="utf-8")
    shutdown = Shutdown(log)
    metrics = MetricsPaths(
        preparation=tmp_path / "przygotowanie-metrics.jsonl",
        settlement=tmp_path / "metrics.jsonl",
        intermax=tmp_path / "intermax-metrics.jsonl",
    )
    app = create_app(
        settings_path=config / "centrum-ustawienia.yaml",
        platform=FakePlatform(),
        log=log,
        shutdown=shutdown,
        processes=metrics.processes(),
        tool_freshness=FakeGitHub().freshness(),
        cloud_files=FakeOneDrive().cloud_files(),
        report_box=box,
        clock=clock,
        pause=clock.pause,
    )
    return app, shutdown


def _serving(app: FastAPI, shutdown: Shutdown, log: CentrumLog) -> threading.Thread:
    """``serve`` na wolnym porcie w osobnym wątku, do zamknięcia przez ``shutdown``."""

    listener = listen_locally(0)
    kwargs = {"listener": listener, "on_ready": lambda _url: None, "shutdown": shutdown, "log": log}
    thread = threading.Thread(target=serve, args=(app,), kwargs=kwargs, name="centrum-test", daemon=True)
    thread.start()
    return thread


def _queued(tmp_path: Path) -> list[str]:
    return sorted(path.name for path in (tmp_path / "config" / "zgloszenia" / "kolejka").glob("*.json"))


def test_zamkniecie_po_starcie_zapisuje_stop_zanim_port_jest_wolny(tmp_path: Path) -> None:
    path = tmp_path / "centrum-rozliczen.log"
    log = _PortAtStop(path)
    shutdown = Shutdown(log)

    code = serve(FastAPI(), listener=listen_locally(0), on_ready=lambda _url: shutdown.request(), shutdown=shutdown, log=log)

    assert code == 0
    assert _events(path) == ["start", "zamkniecie", "stop"]
    assert log.port_free_at_stop is False


def test_nieudany_start_nie_zapisuje_ani_startu_ani_stopu(tmp_path: Path) -> None:
    @asynccontextmanager
    async def failing(_app: FastAPI) -> AsyncIterator[None]:
        raise RuntimeError("start się nie udał")
        yield

    path = tmp_path / "centrum-rozliczen.log"
    log = _PortAtStop(path)
    listener = listen_locally(0)
    port = listener.getsockname()[1]

    with pytest.raises(SystemExit):
        serve(FastAPI(lifespan=failing), listener=listener, on_ready=lambda _url: None, shutdown=Shutdown(log), log=log)

    assert _events(path) == []
    listen_locally(port).close()


def test_zamykane_centrum_zwalnia_port_dopiero_po_wysylce_ktora_kolejka_juz_zaczela(tmp_path: Path) -> None:
    # Port to jedyne, co dzieli stare i nowe Centrum: wolny w trakcie wysyłki pozwoliłby kolejce nowego założyć drugie
    # issue okresu obok kolejki starego.
    hold = threading.Event()
    box = FakeReportBox(open_hold=hold)
    log = _PortWhileClosing(tmp_path / "logs" / "centrum-rozliczen.log", hold)
    app, shutdown = _centrum(tmp_path, box, log, ManualClock())
    since = new_line()
    served = _serving(app, shutdown, log)

    try:
        assert box.opening.wait(30), "kolejka nie zaczęła wysyłki z poprzedniej pracy Centrum"
        shutdown.request()
        served.join(30)
    finally:
        hold.set()
        join_threads_since(since)

    assert log.port_free_while_closing is False
    assert [issue.label for issue in box.issues] == ["kontrola-ilosci"]
    assert _queued(tmp_path) == []


def test_kolejka_zamknietego_centrum_nie_wysyla_po_budzeniu(tmp_path: Path) -> None:
    box = FakeReportBox(search_failure=Unreachable())
    clock = ManualClock()
    log = CentrumLog(tmp_path / "logs" / "centrum-rozliczen.log")
    app, shutdown = _centrum(tmp_path, box, log, clock)
    since = new_line()
    served = _serving(app, shutdown, log)

    try:
        assert wait_for(lambda: clock.wakes == 1), "kolejka bez sieci nie nastawiła ponowienia"
    finally:
        shutdown.request()
        served.join(30)
    box.search_failure = None
    clock.advance(minutes=1)
    join_threads_since(since)

    assert [label for label, _closed in box.listed if label == "kontrola-ilosci"] == ["kontrola-ilosci"]
    assert box.issues == []
    assert _queued(tmp_path) == [QUEUED]

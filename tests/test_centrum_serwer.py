"""Serwer Centrum rozliczeń: ``start`` i ``stop`` w dzienniku, póki Centrum trzyma port."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
import pytest

from rozliczenia.centrum.launcher import listen_locally
from rozliczenia.centrum.log import CentrumLog
from rozliczenia.centrum.server import serve
from rozliczenia.centrum.shutdown import Shutdown


class _PortAtStop(CentrumLog):
    """Dziennik, który przy ``stop`` sprawdza, czy nowe Centrum mogłoby już zająć port."""

    port_free_at_stop: bool | None = None

    def stopped(self, *, port: int) -> None:
        try:
            listen_locally(port).close()
        except OSError:
            self.port_free_at_stop = False
        else:
            self.port_free_at_stop = True
        super().stopped(port=port)


def _events(path: Path) -> list[str]:
    return [line.split(" ")[1] for line in path.read_text(encoding="utf-8").splitlines()] if path.exists() else []


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

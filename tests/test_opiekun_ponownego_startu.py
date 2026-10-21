"""Opiekun ponownego startu jako prawdziwy proces: stare Centrum zwalnia port, a opiekun startuje nową wersję.

Klon narzędzia to prawdziwe Centrum rozliczeń w klonie Gita z lokalnym
„origin” zamiast GitHuba. Opiekun działa z kopii sprzed aktualizacji, tak jak
uruchamia go Centrum po udanej Aktualizacji narzędzia.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import time
import urllib.request

import pytest

# Prawdziwy ``launch`` z importu: strażnik z conftest podmienia go tylko dla Centrum w testach API.
from rozliczenia.centrum.restart_guardian import Restart, launch, prepare
from rozliczenia.centrum.tool_update import RESULT_FILE, ToolClone, UPDATED

from tests.fixtures.tool_clone import centrum_tool_repository


@pytest.fixture(autouse=True)
def git_bez_konfiguracji_komputera_testow(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", os.devnull)
    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")


def _free_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port: int = probe.getsockname()[1]
        return port


def _get(port: int, path: str) -> dict[str, object]:
    with urllib.request.urlopen(f"http://127.0.0.1:{port}{path}", timeout=1) as response:
        body = json.load(response)
        assert isinstance(body, dict)
        return body


def _health(port: int, *, commit: str | None = None, timeout_s: float = 60) -> dict[str, object]:
    """``health`` Centrum na porcie; z ``commit`` dopiero wtedy, gdy odpowiada Centrum w tym commicie."""

    deadline = time.monotonic() + timeout_s
    while True:
        try:
            health = _get(port, "/api/health")
            if commit is None or health["commit"] == commit:
                return health
        except OSError:
            pass
        assert time.monotonic() < deadline, "Centrum nie odpowiedziało na health."
        time.sleep(0.1)


def _close(port: int) -> None:
    origin = f"http://127.0.0.1:{port}"
    request = urllib.request.Request(f"{origin}/api/shutdown", method="POST", headers={"Origin": origin})
    with urllib.request.urlopen(request, timeout=10) as response:
        assert response.status == 202


def _close_if_running(port: int) -> None:
    try:
        _close(port)
    except OSError:
        return
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        try:
            _get(port, "/api/health")
        except OSError:
            return
        time.sleep(0.1)


def _log_lines(clone: Path) -> list[str]:
    return (clone / "logs" / "centrum-rozliczen.log").read_text(encoding="utf-8").splitlines()


def test_opiekun_czeka_na_zwolnienie_portu_i_startuje_nowa_wersje_z_nowym_identyfikatorem_startu(
    tmp_path: Path,
) -> None:
    repository = centrum_tool_repository(tmp_path / "repozytoria")
    clone = repository.clone
    before = repository.head()
    port = _free_port()
    old = subprocess.Popen(
        [sys.executable, str(clone / "run_centrum.py"), "--port", str(port), "--no-browser"],
        cwd=clone,
        env=os.environ | {"PYTHONUTF8": "1"},
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        old_health = _health(port)
        newest = repository.publish({"NOWA_WERSJA.txt": "druga wersja narzędzia\n"})
        (tmp_path / "pliki-taty").mkdir()
        assert ToolClone(clone, origin=str(repository.origin)).update(tmp_path / "pliki-taty").code == UPDATED
        work = tmp_path / "praca"
        work.mkdir()
        guardian = launch(
            prepare(work),
            Restart(
                port=port,
                before=before,
                after=newest,
                root=clone,
                result=clone / "config" / RESULT_FILE,
                installed=False,
                work=work,
            ),
        )
        _close(port)
        old_exit = old.wait(timeout=30)
        new_health = _health(port, commit=newest)
        guardian_exit = guardian.wait(timeout=30)
        view = _get(port, "/api/tool-update")
    finally:
        _close_if_running(port)
        old.kill()
        old.wait()

    assert old_exit == 0
    assert (old_health["commit"], new_health["commit"]) == (before, newest)
    assert new_health["instance"] != old_health["instance"]
    assert new_health["version"] == old_health["version"]
    assert guardian_exit == 0
    assert view == {"state": "updated", "commit": newest[:7]}
    assert not (clone / "config" / RESULT_FILE).exists()
    assert not work.exists()
    events = [line.split(" ", 2)[1] for line in _log_lines(clone)]
    # Stare Centrum zwalnia port, zanim zapisze „stop”, więc jego „stop” może przyjść po starcie nowego.
    assert [event for event in events if event != "stop"][:5] == [
        "start",
        "zamkniecie",
        "aktualizacja-koniec",
        "start",
        "zamkniecie",
    ]
    assert f"aktualizacja-koniec wynik=ok przed={before} po={newest} biblioteki=nie" in [
        line.split(" ", 1)[1] for line in _log_lines(clone)
    ]

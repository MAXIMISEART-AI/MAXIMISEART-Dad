"""Start Centrum rozliczeń jako prawdziwy proces w odizolowanym runtime na wolnym porcie."""

from __future__ import annotations

import json
import os
import shutil
import socket
import subprocess
import sys
import time
import urllib.request
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

import pytest

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
CENTRUM_LAUNCHER = "Centrum rozliczeń (konsola).cmd"


def _copy_centrum_runtime(destination: Path) -> Path:
    """Kopia narzędzia z launcherem Centrum, bez ustawień taty; zwraca katalog kopii."""

    destination.mkdir()
    for name in (CENTRUM_LAUNCHER, "run_centrum.py", "pyproject.toml"):
        shutil.copy2(REPOSITORY_ROOT / name, destination)
    shutil.copytree(REPOSITORY_ROOT / "src", destination / "src", ignore=shutil.ignore_patterns("__pycache__"))
    shutil.copytree(
        REPOSITORY_ROOT / "config", destination / "config", ignore=shutil.ignore_patterns("centrum-ustawienia.yaml")
    )
    return destination


def _free_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port: int = probe.getsockname()[1]
        return port


def _browser_recorder(directory: Path) -> tuple[Path, Path]:
    """Program podstawiony jako przeglądarka (zmienna ``BROWSER``), który zapisuje otwierany adres."""

    record = directory / "otwarte-adresy.txt"
    if os.name == "nt":
        recorder = directory / "przegladarka.cmd"
        recorder.write_text(f'@echo %~1>>"{record}"\r\n', encoding="utf-8")
    else:
        recorder = directory / "przegladarka.sh"
        recorder.write_text(f'#!/bin/sh\nprintf "%s\\n" "$1" >> "{record}"\n', encoding="utf-8")
        recorder.chmod(0o755)
    return recorder, record


def _health(port: int, *, timeout_s: float = 30) -> dict[str, object]:
    deadline = time.monotonic() + timeout_s
    while True:
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/health", timeout=1) as response:
                body = json.load(response)
                assert isinstance(body, dict)
                return body
        except OSError:
            if time.monotonic() > deadline:
                raise
            time.sleep(0.1)


def _wait_for_line(path: Path, *, timeout_s: float = 10) -> str:
    deadline = time.monotonic() + timeout_s
    while not path.exists() or not path.read_text(encoding="utf-8").strip():
        assert time.monotonic() < deadline, "Przeglądarka nie dostała adresu Centrum."
        time.sleep(0.1)
    return path.read_text(encoding="utf-8").strip()


@dataclass
class _Console:
    text: str = ""


@contextmanager
def _started(command: list[str] | str, runtime: Path, environment: dict[str, str]) -> Iterator[_Console]:
    """Uruchamia Centrum i po bloku zamyka dokładnie ten proces (z potomkami); konsola jest dostępna po bloku."""

    console = _Console()
    process = subprocess.Popen(
        command,
        cwd=runtime,
        env=environment,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    try:
        yield console
    finally:
        if os.name == "nt":
            subprocess.run(["taskkill", "/T", "/F", "/PID", str(process.pid)], capture_output=True, check=False)
        else:
            process.terminate()
        console.text, _ = process.communicate(timeout=30)


def _environment(browser: Path) -> dict[str, str]:
    environment = os.environ.copy()
    environment["PYTHONUTF8"] = "1"
    environment["BROWSER"] = str(browser)
    return environment


def test_centrum_startuje_na_localhost_i_otwiera_karte_w_przegladarce(tmp_path: Path) -> None:
    runtime = _copy_centrum_runtime(tmp_path / "narzedzie")
    browser, opened = _browser_recorder(tmp_path)
    port = _free_port()

    with _started(
        [sys.executable, str(runtime / "run_centrum.py"), "--port", str(port)], runtime, _environment(browser)
    ):
        health = _health(port)
        address = _wait_for_line(opened)

    assert health["service"] == "centrum-rozliczen"
    assert address == f"http://127.0.0.1:{port}/"
    assert not (runtime / "config" / "centrum-ustawienia.yaml").exists()


@pytest.mark.skipif(os.name != "nt", reason="The CMD launcher is Windows-only.")
def test_launcher_cmd_uruchamia_centrum_z_konsola_i_otwiera_przegladarke(tmp_path: Path) -> None:
    runtime = _copy_centrum_runtime(tmp_path / "narzedzie")
    browser, opened = _browser_recorder(tmp_path)
    port = _free_port()
    command_line = f'cmd.exe /d /c ""{runtime / CENTRUM_LAUNCHER}" --port {port}"'

    with _started(command_line, runtime, _environment(browser)) as console:
        health = _health(port)
        address = _wait_for_line(opened)

    assert health["service"] == "centrum-rozliczen"
    assert address == f"http://127.0.0.1:{port}/"
    assert f"Centrum rozliczeń działa: http://127.0.0.1:{port}/" in console.text

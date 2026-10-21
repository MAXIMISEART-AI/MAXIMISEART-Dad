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
import threading
import time
import urllib.request

import pytest

from rozliczenia.centrum import restart_guardian

# Prawdziwy ``launch`` z importu: strażnik z conftest podmienia go tylko dla Centrum w testach API.
from rozliczenia.centrum.restart_guardian import Restart, launch, main, prepare
from rozliczenia.centrum.tool_update import (
    NEW_VERSION_FAILED,
    RESULT_FILE,
    UNEXPECTED,
    UPDATED,
    ToolClone,
    UpdateResult,
    read_result,
)

from tests.fixtures.tool_clone import FIRST_VERSION, ToolRepository, centrum_tool_repository, tool_repository


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


def _guardian_in_background(restart: Restart, dialogs: list[tuple[str, str]]) -> tuple[threading.Thread, list[int]]:
    """Opiekun w wątku testu (prawdziwe procesy Centrum), z okienkiem podstawionym zapisem jego treści."""

    exits: list[int] = []

    def record(title: str, text: str) -> None:
        dialogs.append((title, text))

    def guard() -> None:
        exits.append(main(restart.arguments(), show_problem=record))

    thread = threading.Thread(target=guard, name="opiekun-w-tescie", daemon=True)
    thread.start()
    return thread, exits


def _broken_version(repository: ToolRepository, dialogs: Path) -> dict[str, str]:
    """Nowa wersja z błędem importu: brakuje jej biblioteki, a jak pod ``pythonw`` nie ma konsoli.

    Okienko błędu startu tej wersji zapisuje swoją treść do ``dialogs`` zamiast pokazywać się na ekranie.
    """

    app = (repository.publisher / "src/rozliczenia/centrum/app.py").read_text(encoding="utf-8")
    platform = (repository.publisher / "src/rozliczenia/centrum/platform.py").read_text(encoding="utf-8")
    windowless = (
        "\n\ndef has_console() -> bool:\n    return False\n\n\n"
        "def show_start_problem(title: str, text: str) -> None:\n"
        f"    with open({str(dialogs)!r}, 'a', encoding='utf-8') as shown:\n"
        "        shown.write(text + '\\n')\n"
    )
    return {
        "src/rozliczenia/centrum/app.py": app.replace(
            "from __future__ import annotations\n",
            "from __future__ import annotations\n\nimport biblioteka_ktorej_nie_ma  # noqa: F401\n",
            1,
        ),
        "src/rozliczenia/centrum/platform.py": platform + windowless,
    }


def test_nowa_wersja_ktora_nie_wystartuje_wraca_do_starego_commitu_a_stara_startuje_z_komunikatem(
    tmp_path: Path,
) -> None:
    repository = centrum_tool_repository(tmp_path / "repozytoria")
    clone = repository.clone
    before = repository.head()
    port = _free_port()
    new_version_dialogs = tmp_path / "okienka-nowej-wersji.txt"
    dialogs: list[tuple[str, str]] = []
    old = subprocess.Popen(
        [sys.executable, str(clone / "run_centrum.py"), "--port", str(port), "--no-browser"],
        cwd=clone,
        env=os.environ | {"PYTHONUTF8": "1"},
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        old_health = _health(port)
        newest = repository.publish(_broken_version(repository, new_version_dialogs))
        work = tmp_path / "praca"
        (work / "pliki-taty").mkdir(parents=True)
        assert ToolClone(clone, origin=str(repository.origin)).update(work / "pliki-taty").code == UPDATED
        restart = Restart(port, before, newest, clone, clone / "config" / RESULT_FILE, False, work)
        guardian, exits = _guardian_in_background(restart, dialogs)
        _close(port)
        old.wait(timeout=30)
        guardian.join(timeout=90)
        back_health = _health(port, commit=before)
        view = _get(port, "/api/tool-update")
    finally:
        _close_if_running(port)
        old.kill()
        old.wait()

    assert exits == [0]
    assert repository.head() == before
    assert repository.in_clone("status", "--porcelain", "--untracked-files=no") == ""
    assert back_health["instance"] != old_health["instance"]
    assert dialogs == []
    assert not new_version_dialogs.exists()
    assert (view["state"], view["message"], view["next_action"]) == (
        "failed",
        {
            "what": "Nowa wersja narzędzia nie wystartowała.",
            "where": "narzędzie na tym komputerze",
            "action": "Narzędzie działa dalej w poprzedniej wersji. Przekaż sprawę Maksowi: kliknij „Wyślij do Maksa”.",
        },
        "report",
    )
    assert not (clone / "config" / RESULT_FILE).exists()
    assert not work.exists()
    entries = [line.split(" ", 1)[1] for line in _log_lines(clone)]
    assert any(entry.startswith("blad-startu kod=BRAK_BIBLIOTEKI ") for entry in entries)
    assert [entry for entry in entries if entry.startswith("aktualizacja-koniec")] == [
        f"aktualizacja-koniec wynik=NOWA_WERSJA_NIE_WYSTARTOWALA przed={before} po={newest} biblioteki=nie"
    ]


def test_gdy_nie_startuje_zadna_wersja_opiekun_pokazuje_jedno_okienko_a_klon_stoi_na_starym_commicie(
    tmp_path: Path,
) -> None:
    not_starting = "raise SystemExit(1)\n"
    repository = tool_repository(tmp_path / "repozytoria", {**FIRST_VERSION, "run_centrum.py": not_starting})
    before = repository.head()
    dad_mapping = "schema_version: 1\nworkers:\n  wykonawca.a: Wykonawca Syntetyczny A\n"
    repository.write("config/worker_mapping.yaml", dad_mapping)
    newest = repository.publish(
        {".gitignore": "config/worker_mapping.yaml\n"}, untrack=("config/worker_mapping.yaml",)
    )
    work = tmp_path / "praca"
    (work / "pliki-taty").mkdir(parents=True)
    assert ToolClone(repository.clone, origin=str(repository.origin)).update(work / "pliki-taty").code == UPDATED
    result = repository.clone / "config" / RESULT_FILE
    dialogs: list[tuple[str, str]] = []

    guardian, exits = _guardian_in_background(
        Restart(_free_port(), before, newest, repository.clone, result, False, work), dialogs
    )
    guardian.join(timeout=90)

    assert exits == [1]
    assert dialogs == [
        (
            "Centrum rozliczeń",
            "Co się stało: Centrum rozliczeń nie wystartowało po aktualizacji narzędzia.\n"
            "Gdzie: narzędzie na tym komputerze\n"
            "Co zrobić: Przekaż ten komunikat Maksowi. "
            "Do tego czasu używaj launcherów Przygotuj plik zbiorczy.cmd i Utwórz rozliczenia.cmd.",
        )
    ]
    assert repository.head() == before
    assert repository.read("config/worker_mapping.yaml") == dad_mapping
    assert repository.in_clone("status", "--porcelain", "--untracked-files=no") == "M config/worker_mapping.yaml"
    assert read_result(result) == UpdateResult(NEW_VERSION_FAILED, before, newest, False)


def test_gdy_stare_centrum_nie_zwalnia_portu_opiekun_cofa_klon_i_startuje_stara_wersje_z_komunikatem(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(restart_guardian, "PORT_TIMEOUT_S", 5.0)
    repository = centrum_tool_repository(tmp_path / "repozytoria")
    clone = repository.clone
    before = repository.head()
    port = _free_port()
    dialogs: list[tuple[str, str]] = []
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
        work = tmp_path / "praca"
        (work / "pliki-taty").mkdir(parents=True)
        assert ToolClone(clone, origin=str(repository.origin)).update(work / "pliki-taty").code == UPDATED
        result = clone / "config" / RESULT_FILE
        guardian, exits = _guardian_in_background(
            Restart(port, before, newest, clone, result, False, work), dialogs
        )
        deadline = time.monotonic() + 30
        while (unchecked := read_result(result)) is None or unchecked.code == UPDATED:
            assert time.monotonic() < deadline, "Opiekun nie zapisał wyniku po czekaniu na port."
            time.sleep(0.02)
        _close(port)
        old.wait(timeout=30)
        guardian.join(timeout=90)
        back_health = _health(port, commit=before)
        view = _get(port, "/api/tool-update")
    finally:
        _close_if_running(port)
        old.kill()
        old.wait()

    assert unchecked == UpdateResult(UNEXPECTED, before, newest, False)
    assert exits == [0]
    assert dialogs == []
    assert repository.head() == before
    assert not (clone / "NOWA_WERSJA.txt").exists()
    assert back_health["instance"] != old_health["instance"]
    assert (view["state"], view["message"], view["next_action"]) == (
        "failed",
        {
            "what": "Nie udało się zaktualizować narzędzia z nieoczekiwanego powodu.",
            "where": "narzędzie na tym komputerze",
            "action": (
                "Narzędzie działa dalej w poprzedniej wersji. Kliknij „Zaktualizuj narzędzie” jeszcze raz. "
                "Jeśli komunikat wraca, kliknij „Wyślij do Maksa”."
            ),
        },
        "retry",
    )
    entries = [line.split(" ", 1)[1] for line in _log_lines(clone)]
    assert [entry for entry in entries if entry.startswith("aktualizacja-koniec")] == [
        f"aktualizacja-koniec wynik=NIEOCZEKIWANY_BLAD przed={before} po={newest} biblioteki=nie"
    ]


def test_gdy_port_nie_zwolni_sie_wcale_opiekun_cofa_klon_z_plikiem_taty_i_pokazuje_okienko(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(restart_guardian, "PORT_TIMEOUT_S", 0.5)
    repository = tool_repository(tmp_path / "repozytoria")
    before = repository.head()
    dad_mapping = "schema_version: 1\nworkers:\n  wykonawca.a: Wykonawca Syntetyczny A\n"
    repository.write("config/worker_mapping.yaml", dad_mapping)
    newest = repository.publish(
        {".gitignore": "config/worker_mapping.yaml\n"}, untrack=("config/worker_mapping.yaml",)
    )
    work = tmp_path / "praca"
    (work / "pliki-taty").mkdir(parents=True)
    assert ToolClone(repository.clone, origin=str(repository.origin)).update(work / "pliki-taty").code == UPDATED
    result = repository.clone / "config" / RESULT_FILE
    dialogs: list[tuple[str, str]] = []

    with socket.socket() as busy:
        busy.bind(("127.0.0.1", 0))
        busy.listen()
        guardian, exits = _guardian_in_background(
            Restart(busy.getsockname()[1], before, newest, repository.clone, result, False, work), dialogs
        )
        guardian.join(timeout=30)

    assert exits == [1]
    assert [text.splitlines()[0] for _, text in dialogs] == [
        "Co się stało: Centrum rozliczeń nie wystartowało po aktualizacji narzędzia."
    ]
    assert repository.head() == before
    assert repository.read("config/worker_mapping.yaml") == dad_mapping
    assert repository.in_clone("status", "--porcelain", "--untracked-files=no") == "M config/worker_mapping.yaml"
    assert read_result(result) == UpdateResult(UNEXPECTED, before, newest, False)
    assert not work.exists()

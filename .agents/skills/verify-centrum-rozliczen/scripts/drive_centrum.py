"""Drive a running Centrum rozliczeń in Chromium the way Dad does and record the proof.

Each feature step pairs a user action with the resulting screen, the server's
answer, and the side effect on disk (settings file, picker dialogs, opened
paths). Screenshots and ARIA snapshots go to ``<evidence>/screenshots`` and
``<evidence>/aria``; API answers to ``<evidence>/api``; the run's state files
to ``<evidence>/state``.
"""

from __future__ import annotations

import argparse
from collections.abc import Callable
import json
import os
from pathlib import Path
import shutil
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

from playwright.sync_api import Error as PlaywrightError
from playwright.sync_api import Locator, Page, expect, sync_playwright
import yaml

# start-i-zamykanie closes Centrum, so it stays last.
FEATURES = ("ustawienia", "tablica-okresow", "start-i-zamykanie")


class DriveFailure(Exception):
    pass


class Run:
    def __init__(self, root: Path, url: str, evidence: Path) -> None:
        self.root = root
        self.url = url
        self.evidence = evidence
        self.fixture = json.loads((root / "fixture.json").read_text(encoding="utf-8"))
        for name in ("screenshots", "aria", "api", "state"):
            (evidence / name).mkdir(parents=True, exist_ok=True)

    def step(self, feature: str, name: str) -> None:
        print(f"STEP {feature} | {name}", flush=True)

    def check(self, condition: bool, message: str) -> None:
        if not condition:
            raise DriveFailure(message)
        print(f"  ok: {message}", flush=True)

    def capture(self, page: Page, name: str, *, full_page: bool = True) -> None:
        """Screenshot and ARIA snapshot after every running transition has finished."""

        page.wait_for_function(
            "document.getAnimations().every((animation) => animation.playState !== 'running')"
        )
        page.screenshot(path=self.evidence / "screenshots" / f"{name}.png", full_page=full_page)
        snapshot = page.locator("body").aria_snapshot()
        (self.evidence / "aria" / f"{name}.txt").write_text(snapshot + "\n", encoding="utf-8")

    def api(self, path: str, name: str) -> dict[str, object]:
        with urllib.request.urlopen(self.url.rstrip("/") + path, timeout=10) as response:
            body = json.load(response)
        (self.evidence / "api" / f"{name}.json").write_text(
            json.dumps(body, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        assert isinstance(body, dict)
        return body

    def refused(self, request: urllib.request.Request, name: str) -> int:
        try:
            with urllib.request.urlopen(request, timeout=10) as response:
                status, body = int(response.status), response.read()
        except urllib.error.HTTPError as error:
            status, body = error.code, error.read()
        record = {"status": status, "body": json.loads(body or b"null")}
        (self.evidence / "api" / f"{name}.json").write_text(
            json.dumps(record, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        return status

    def answer_picker(self, path: str) -> None:
        (self.root / "picker" / "answer.txt").write_text(path, encoding="utf-8")

    def lines(self, name: str) -> list[dict[str, str]]:
        log = self.root / name
        if not log.exists():
            return []
        return [json.loads(line) for line in log.read_text(encoding="utf-8").splitlines() if line]

    def settings_text(self) -> str:
        settings = Path(self.fixture["settings"])
        return settings.read_text(encoding="utf-8") if settings.exists() else ""

    def remembered(self, key: str) -> object:
        """One value of the settings file as Centrum wrote it (``folder_okresow``, ``rejestr_zlecen``, ``motyw``)."""

        document = yaml.safe_load(self.settings_text()) or {}
        assert isinstance(document, dict)
        return document.get(key)

    def wait_for(self, condition: Callable[[], bool], message: str, timeout_s: float = 10) -> None:
        deadline = time.monotonic() + timeout_s
        while not condition():
            if time.monotonic() > deadline:
                raise DriveFailure(f"timed out: {message}")
            time.sleep(0.1)
        print(f"  ok: {message}", flush=True)


def _choose_periods_directory(run: Run, page: Page) -> None:
    run.answer_picker(run.fixture["periods_directory"])
    page.get_by_role("button", name="Wskaż folder okresów", exact=True).click()
    expect(page.get_by_role("table", name="Tablica okresów")).to_be_visible()


def drive_settings(run: Run, page: Page) -> None:
    feature = "ustawienia"
    register_name = Path(run.fixture["order_register"]).name

    run.step(feature, "ustawienia-pusty-stan")
    page.goto(run.url)
    expect(page.get_by_text("Wskaż folder okresów", exact=True).first).to_be_visible()
    settings = run.api("/api/settings", "ustawienia-przed")
    run.check(
        settings["order_register"] == {"state": "not_set"} and settings["periods_directory"] == {"state": "not_set"},
        "no settings file means nothing is set",
    )
    run.capture(page, "01-ustawienia-pusty-stan")

    run.step(feature, "ustawienia-folder-okresow")
    _choose_periods_directory(run, page)
    run.check(
        run.lines("dialogs.jsonl")[-1]["title"] == "Wybierz folder okresów (np. INEA)",
        "the folder picker opened with the CLI's title",
    )
    run.check(
        run.remembered("folder_okresow") == run.fixture["periods_directory"],
        "the settings file remembers the folder okresów",
    )
    run.capture(page, "02-ustawienia-folder-okresow")

    run.step(feature, "ustawienia-rejestr-zlecen")
    run.answer_picker(run.fixture["order_register"])
    page.get_by_role("button", name="Wskaż Rejestr zleceń", exact=True).click()
    register = page.get_by_role("group", name="Rejestr zleceń")
    expect(register.get_by_text(register_name)).to_be_visible()
    run.check(run.lines("dialogs.jsonl")[-1]["title"] == "Wybierz plik Rejestru zleceń", "the file picker opened")
    run.check(
        run.remembered("rejestr_zlecen") == run.fixture["order_register"],
        "the settings file remembers the Rejestr zleceń",
    )
    run.capture(page, "03-ustawienia-rejestr-zlecen")

    run.step(feature, "ustawienia-anulowanie")
    before = run.settings_text()
    dialogs = len(run.lines("dialogs.jsonl"))
    page.get_by_role("button", name="Zmień Rejestr zleceń", exact=True).click()
    run.wait_for(lambda: len(run.lines("dialogs.jsonl")) == dialogs + 1, "the cancelled picker was shown")
    expect(page.get_by_role("button", name="Zmień Rejestr zleceń", exact=True)).to_be_enabled()
    expect(register.get_by_text(register_name)).to_be_visible()
    run.check(run.settings_text() == before, "a cancelled picker leaves the settings file unchanged")

    run.step(feature, "ustawienia-nieistniejaca-sciezka")
    moved = Path(run.fixture["order_register"] + ".przeniesiony")
    Path(run.fixture["order_register"]).rename(moved)
    try:
        page.reload()
        expect(register.get_by_text(f"Nie ma już: {register_name}")).to_be_visible()
        run.check(run.api("/api/settings", "ustawienia-brak-rejestru")["order_register"] == {
            "state": "missing",
            "path": run.fixture["order_register"],
            "name": register_name,
        }, "a remembered Rejestr zleceń that is gone is reported as missing")
        run.capture(page, "04-ustawienia-brak-rejestru")
    finally:
        moved.rename(run.fixture["order_register"])
    page.reload()
    expect(register.get_by_text(register_name, exact=True)).to_be_visible()

    run.step(feature, "ustawienia-motyw")
    page.get_by_role("button", name="Włącz motyw jasny").click()
    expect(page.locator("html")).not_to_have_class("dark")
    run.wait_for(lambda: run.remembered("motyw") == "light", "the settings file remembers the light theme")
    page.reload()
    expect(page.get_by_role("button", name="Włącz motyw ciemny")).to_be_visible()
    expect(page.locator("html")).not_to_have_class("dark")
    run.capture(page, "05-ustawienia-motyw-jasny")
    page.get_by_role("button", name="Włącz motyw ciemny").click()
    expect(page.locator("html")).to_have_class("dark")
    run.wait_for(lambda: run.remembered("motyw") == "dark", "the dark theme is remembered again")


def _row(page: Page, token: str) -> Locator:
    return page.get_by_role("table", name="Tablica okresów").get_by_role("row").filter(has_text=token)


def _last_opened_is(run: Run, path: Path) -> Callable[[], bool]:
    return lambda: run.lines("opened.jsonl")[-1:] == [{"path": str(path)}]


def drive_period_board(run: Run, page: Page) -> None:
    feature = "tablica-okresow"
    periods = Path(run.fixture["periods_directory"])

    run.step(feature, "tablica-kolejnosc-i-status")
    page.goto(run.url)
    if run.api("/api/settings", "tablica-ustawienia")["periods_directory"] == {"state": "not_set"}:
        _choose_periods_directory(run, page)
    board = run.api("/api/periods", "tablica-okresow")
    rows = board["periods"]
    assert isinstance(rows, list)
    expected = run.fixture["board"]
    run.check(
        [[row["token"], row["status"], row["worker_settlement_count"], row["last_complete"]] for row in rows]
        == expected,
        "the server lists every Folder okresu newest first with its Status okresu",
    )
    table_rows = page.get_by_role("table", name="Tablica okresów").get_by_role("row")
    expect(table_rows).to_have_count(len(expected) + 1)
    labels = {"no_period_files": "Brak plików okresu", "collective_file_prepared": "Plik zbiorczy przygotowany",
              "worker_settlements_ready": "Rozliczenia pracowników gotowe"}
    for index, (token, status, _, last_complete) in enumerate(expected, start=1):
        row = table_rows.nth(index)
        expect(row).to_contain_text(token)
        expect(row).to_contain_text(labels[status])
        if last_complete:
            expect(row).to_have_attribute("data-state", "selected")
            expect(row).to_contain_text("ostatni pełny okres")
    run.check(True, "the screen shows the same order, Status okresu, and highlighted last complete period")
    run.capture(page, "06-tablica-okresow")

    run.step(feature, "tablica-nastepny-krok")
    next_step = page.get_by_role("region", name="Następny krok")
    expect(next_step).to_contain_text("Przygotuj plik zbiorczy")
    expect(next_step).to_contain_text(expected[0][0])
    expect(next_step).to_contain_text("Brak Folderu okresu")
    run.check(True, "Następny krok targets the last complete period, whose Folder okresu does not exist")

    run.step(feature, "tablica-otwieranie")
    opened_before = len(run.lines("opened.jsonl"))
    clicks = [
        ("Plik zbiorczy, okres 29_05_09_2026", periods / "29_05_09_2026" / "Rozliczenie 29_05_09_2026 - zbiorcze.xlsx"),
        ("Rozliczenie wewnętrzne, okres 22_28_09_2026", periods / "22_28_09_2026" / "Rozliczenie wew. 22_28_09_2026.xlsx"),
        ("Folder okresu, okres 15_21_09_2026", periods / "15_21_09_2026"),
        ("Rozliczenia pracowników: 3, okres 22_28_09_2026",
         periods / "22_28_09_2026" / "Rozliczenie pracowników 22_28_09_2026"),
    ]
    for name, path in clicks:
        page.get_by_role("button", name=name, exact=True).click()
        run.wait_for(_last_opened_is(run, path), f"{name} opened {path.name}")
        expect(page.get_by_text(path.name, exact=True).last).to_be_visible()
    run.check(len(run.lines("opened.jsonl")) == opened_before + len(clicks), "one open per click, nothing else")
    run.capture(page, "07-tablica-otwieranie", full_page=False)
    expect(page.get_by_role("button", name="Plik zbiorczy, okres 15_21_09_2026", exact=True)).to_be_disabled()
    run.check(True, "a period file that does not exist cannot be opened")

    run.step(feature, "tablica-zmiana-na-dysku")
    changed = periods / "15_21_09_2026"
    for name in ("Rozliczenie wew. 15_21_09_2026.xlsx", "Rozliczenie 15_21_09_2026 - zbiorcze.xlsx"):
        (changed / name).write_bytes(b"")
    page.reload()
    expect(_row(page, "15_21_09_2026")).to_contain_text("Plik zbiorczy przygotowany")
    run.check(True, "after a reload the board shows a Plik zbiorczy added outside Centrum")
    (changed / "Rozliczenie pracowników 15_21_09_2026").mkdir()
    # Headless Chromium keeps every tab visible, so returning to the tab is simulated with the
    # `focus` event the browser fires then; the page itself is not touched.
    page.evaluate("window.dispatchEvent(new FocusEvent('focus'))")
    expect(_row(page, "15_21_09_2026")).to_contain_text("Rozliczenia pracowników gotowe")
    run.check(True, "a (simulated) return to the tab shows a Folder rozliczeń pracowników added outside Centrum")
    run.capture(page, "08-tablica-po-zmianie-na-dysku")

    run.step(feature, "tablica-podpowiedz")
    _row(page, "29_05_09_2026").get_by_text("Utwórz rozliczenia pracowników").hover()
    expect(page.get_by_text("Najpierw uzupełnij Plik zbiorczy w Excelu, zapisz go i zamknij.")).to_be_visible()
    run.capture(page, "09-tablica-podpowiedz", full_page=False)

    run.step(feature, "tablica-ochrona")
    opened = len(run.lines("opened.jsonl"))
    open_url = run.url.rstrip("/") + "/api/periods/22_28_09_2026/open"
    payload = json.dumps({"target": "collective_file"}).encode()
    foreign_origin = urllib.request.Request(
        open_url, data=payload, method="POST",
        headers={"Content-Type": "application/json", "Origin": "http://zly.example"},
    )
    foreign_host = urllib.request.Request(run.url.rstrip("/") + "/api/health", headers={"Host": "zly.example"})
    run.check(run.refused(foreign_origin, "odmowa-obcy-origin") == 403, "an action from a foreign Origin is refused")
    run.check(run.refused(foreign_host, "odmowa-obcy-host") == 403, "a request with a foreign Host is refused")
    run.check(len(run.lines("opened.jsonl")) == opened, "a refused request opens nothing")


def _copy_tool(run: Run) -> Path:
    """A copy of the tool inside the run root, so the real launcher logs there and never in Dad's ``logs``."""

    tool = run.root / "narzedzie"
    if not tool.exists():
        repo = Path(__file__).resolve().parents[4]
        tool.mkdir()
        for name in ("run_centrum.py", "pyproject.toml"):
            shutil.copy2(repo / name, tool)
        shutil.copytree(repo / "src", tool / "src", ignore=shutil.ignore_patterns("__pycache__"))
    return tool


def _browser_recorder(run: Run) -> tuple[Path, Path]:
    """Stands in for the browser (``BROWSER``) and appends each opened address to ``browser.txt``."""

    record = run.root / "browser.txt"
    if os.name == "nt":
        recorder = run.root / "browser.cmd"
        recorder.write_text(f'@echo %~1>>"{record}"\r\n', encoding="utf-8")
    else:
        recorder = run.root / "browser.sh"
        recorder.write_text(f'#!/bin/sh\nprintf "%s\\n" "$1" >> "{record}"\n', encoding="utf-8")
        recorder.chmod(0o755)
    return recorder, record


def _launch(run: Run, port: int, name: str) -> subprocess.CompletedProcess[str]:
    """The real launcher (``run_centrum.py``, the console path) from the run's copy of the tool."""

    tool = _copy_tool(run)
    recorder, _ = _browser_recorder(run)
    environment = os.environ | {"PYTHONUTF8": "1", "BROWSER": str(recorder)}
    result = subprocess.run(
        [sys.executable, str(tool / "run_centrum.py"), "--port", str(port)],
        cwd=tool, env=environment, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=60,
    )
    (run.evidence / "api" / f"{name}.txt").write_text(
        f"exit_code={result.returncode}\nstdout:\n{result.stdout}\nstderr:\n{result.stderr}", encoding="utf-8"
    )
    return result


def _log_events(path: Path) -> list[str]:
    return [line.split(" ")[1] for line in path.read_text(encoding="utf-8").splitlines()] if path.exists() else []


def _answers(url: str) -> bool:
    try:
        with urllib.request.urlopen(url.rstrip("/") + "/api/health", timeout=2):
            return True
    except OSError:
        return False


def drive_start_and_close(run: Run, page: Page) -> None:
    feature = "start-i-zamykanie"
    port = int(urllib.parse.urlsplit(run.url).port or 0)
    served_log = run.root / "logs" / "centrum-rozliczen.log"
    tool_log = run.root / "narzedzie" / "logs" / "centrum-rozliczen.log"

    run.step(feature, "start-gotowosc")
    health = run.api("/api/health", "start-health")
    run.check(health["service"] == "centrum-rozliczen", "health names Centrum rozliczeń and its version")
    run.check(_log_events(served_log)[:1] == ["start"], "the Centrum log starts with a start entry")
    run.check(f"port={port}" in served_log.read_text(encoding="utf-8"), "the start entry names the port")

    run.step(feature, "start-druga-instancja")
    again = _launch(run, port, "start-druga-instancja")
    run.check(again.returncode == 0, "a second launch on the same port exits 0")
    run.check(f"Centrum rozliczeń już działa: {run.url}" in again.stdout, "it says Centrum is already running")
    run.check((run.root / "browser.txt").read_text(encoding="utf-8").split() == [run.url], "it only opens the tab")
    run.check(_log_events(tool_log) == ["juz-dziala"], "its log records the recognised running Centrum")
    run.check(_answers(run.url), "the first Centrum keeps serving")

    run.step(feature, "start-obcy-program")
    with socket.socket() as foreign_program:
        foreign_program.bind(("127.0.0.1", 0))
        foreign_program.listen()
        foreign_port = foreign_program.getsockname()[1]
        refused = _launch(run, foreign_port, "start-obcy-program")
    run.check(refused.returncode == 1, "a launch on a port held by another program exits 1")
    run.check(
        [line.split(":", 1)[0] for line in refused.stdout.splitlines()] == ["Co się stało", "Gdzie", "Co zrobić"],
        "the console shows the three-part start message",
    )
    run.check("zajmuje inny program" in refused.stdout and refused.stderr == "", "no exception text, only the message")
    run.check(_log_events(tool_log)[-1:] == ["blad-startu"], "the log records the start failure")

    run.step(feature, "zamykanie-karta")
    page.goto(run.url)
    other_tab = page.context.new_page()
    other_tab.goto(run.url)
    expect(other_tab.get_by_role("heading", name="Okresy", exact=True)).to_be_visible()
    other_tab.close()
    run.check(_answers(run.url), "closing a tab leaves Centrum running")

    run.step(feature, "zamykanie-potwierdzenie")
    close_button = page.get_by_role("button", name="Zamknij Centrum rozliczeń", exact=True)
    close_button.click()
    dialog = page.get_by_role("alertdialog", name="Zamknąć Centrum rozliczeń?")
    expect(dialog).to_be_visible()
    expect(dialog).to_contain_text("Wrócisz skrótem „Centrum rozliczeń” na pulpicie.")
    run.capture(page, "10-start-i-zamykanie-potwierdzenie", full_page=False)
    dialog.get_by_role("button", name="Anuluj", exact=True).click()
    expect(dialog).to_be_hidden()
    run.check(_answers(run.url) and "zamkniecie" not in _log_events(served_log), "Anuluj leaves Centrum running")

    run.step(feature, "zamykanie")
    close_button.click()
    page.get_by_role("button", name="Zamknij Centrum", exact=True).click()
    expect(page.get_by_role("heading", name="Centrum rozliczeń jest zamknięte", exact=True)).to_be_visible()
    run.wait_for(lambda: not _answers(run.url), "the Centrum process stops serving")
    run.wait_for(lambda: _log_events(served_log)[-2:] == ["zamkniecie", "stop"], "the log ends with zamkniecie, stop")
    run.capture(page, "11-start-i-zamykanie-zamkniete")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--root", required=True, help="Run root with fixture.json and a served Centrum.")
    parser.add_argument("--url", required=True, help="Centrum URL from <root>/server.json.")
    parser.add_argument("--evidence", required=True, help="Evidence directory that survives cleanup.")
    parser.add_argument("--feature", choices=("all", *FEATURES), default="all")
    args = parser.parse_args(argv)
    run = Run(Path(args.root).resolve(), args.url, Path(args.evidence).resolve())
    drives = {
        "ustawienia": drive_settings,
        "tablica-okresow": drive_period_board,
        "start-i-zamykanie": drive_start_and_close,
    }
    selected = FEATURES if args.feature == "all" else (args.feature,)
    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch()
            try:
                context = browser.new_context(viewport={"width": 1440, "height": 1000}, locale="pl-PL")
                page = context.new_page()
                page.set_default_timeout(10_000)
                for feature in selected:
                    drives[feature](run, page)
            except Exception:
                if "page" in locals():
                    page.screenshot(path=run.evidence / "screenshots" / "zz-failure.png", full_page=True)
                raise
            finally:
                browser.close()
    except (DriveFailure, AssertionError, PlaywrightError) as exc:
        print(f"DRIVE FAIL | {exc}", file=sys.stderr)
        return 1
    finally:
        for name in ("opened.jsonl", "dialogs.jsonl", "config/centrum-ustawienia.yaml", "logs/centrum-rozliczen.log"):
            source = run.root / name
            if source.exists():
                shutil.copy2(source, run.evidence / "state" / source.name)
    print(f"DRIVE OK | features={','.join(selected)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

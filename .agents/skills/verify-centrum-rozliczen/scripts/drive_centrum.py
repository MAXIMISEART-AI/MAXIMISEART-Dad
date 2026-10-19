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
from datetime import datetime
import json
from pathlib import Path
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request
from zoneinfo import ZoneInfo

from playwright.sync_api import Error as PlaywrightError
from playwright.sync_api import Locator, Page, expect, sync_playwright
import yaml

REPO_ROOT = Path(__file__).resolve().parents[4]
# Dad's computer runs on Polish time; dates in Centrum are shown in the browser's time zone.
DAD_TIME_ZONE = ZoneInfo("Europe/Warsaw")
# The period the CLI step names: the fixture's last complete period, without a Folder okresu.
LAST_COMPLETE_FOR_CLI = "06_12_10_2026"

FEATURES = ("ustawienia", "tablica-okresow", "metryki")


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


def _seconds(duration_ms: int) -> str:
    """The UI's duration text: tenths of a second rounded half up, Polish comma (``7250`` → ``7,3 s``)."""

    tenths = (duration_ms + 50) // 100
    return f"{tenths // 10},{tenths % 10} s"


def _local(started_at: str) -> str:
    """The UI's date text in Dad's time zone (``06.10.2026, 08:21``)."""

    return datetime.fromisoformat(started_at).astimezone(DAD_TIME_ZONE).strftime("%d.%m.%Y, %H:%M")


def _history_rows(page: Page) -> Locator:
    return page.get_by_role("table", name="Historia Uruchomień procesu").get_by_role("row")


def drive_metrics(run: Run, page: Page) -> None:
    feature = "metryki"
    fixture_metrics = run.fixture["metrics"]

    run.step(feature, "metryki-karty-okresow")
    page.goto(run.url + "#/okresy")
    if run.api("/api/settings", "metryki-ustawienia")["periods_directory"] == {"state": "not_set"}:
        _choose_periods_directory(run, page)
    metrics = run.api("/api/metrics", "metryki")
    runs = metrics["runs"]
    recent = metrics["recent"]
    assert isinstance(runs, list) and isinstance(recent, dict)
    run.check(len(runs) == fixture_metrics["runs"], "the server reads every valid record of both metrics files")
    run.check(
        {entry["process"] for entry in runs} == {"preparation", "settlement"},
        "the history holds both processes, and the records the CLI's reader skips are absent",
    )
    stats = page.get_by_role("group", name="Najważniejsze liczby")
    board = run.api("/api/periods", "metryki-tablica")["periods"]
    assert isinstance(board, list)
    prepared = next(period for period in board if period["collective_file_exists"])
    expect(stats.get_by_role("group", name="Ostatni przygotowany okres")).to_contain_text(prepared["token"])
    latest = runs[0]
    latest_card = stats.get_by_role("group", name="Ostatnie uruchomienie")
    expect(latest_card).to_contain_text(f"{latest['process_label']} · {_local(latest['started_at'])}")
    expect(latest_card).to_contain_text("OK")
    results = recent["results"]
    recent_card = stats.get_by_role("group", name=f"Ostatnie {recent['weeks']} tygodni")
    expect(recent_card).to_contain_text(f"{results['ok']} OK")
    expect(recent_card).to_contain_text(f"{results['needs_review']} do sprawdzenia · {results['critical']} zatrzymane")
    run.check(True, "Okresy shows the last prepared period, the last Uruchomienie procesu and the recent results")
    run.capture(page, "10-metryki-karty-okresow")

    run.step(feature, "metryki-p50-p95")
    page.get_by_role("link", name="Metryki", exact=True).click()
    expect(page.get_by_role("heading", name="Metryki", exact=True)).to_be_visible()
    entries = metrics["statistics"]
    assert isinstance(entries, list)
    statistics = {(entry["process"], entry["mode"]): entry for entry in entries}
    preparation_run = statistics[("preparation", "RUN")]
    percentiles = preparation_run["percentiles"]
    run.check(
        preparation_run["completed_runs"] >= 5 and percentiles is not None,
        "Przygotowanie RUN has five completed observations, so P50/P95 exist",
    )
    strip = page.get_by_role("group", name="Statystyki")
    expect(strip.get_by_role("group", name="P50")).to_contain_text(_seconds(percentiles["p50_ms"]))
    expect(strip.get_by_role("group", name="P95")).to_contain_text(_seconds(percentiles["p95_ms"]))
    counts = preparation_run["results"]
    expect(strip.get_by_role("group", name="Wyniki")).to_contain_text(f"{counts['ok']} OK")
    expect(strip.get_by_role("group", name="Wyniki")).to_contain_text(f"{counts['critical']} zatrzymane")
    run.check(True, "the strip shows the server's P50/P95 and result counts for Przygotowanie RUN")

    run.step(feature, "metryki-wykres")
    chart = page.get_by_role("figure", name="Wykres czasów etapów")
    expect(chart).to_be_visible()
    shown_runs = [entry for entry in runs if (entry["process"], entry["mode"]) == ("preparation", "RUN")][:12]
    bars = chart.locator(".recharts-bar-rectangle")
    expect(bars).to_have_count(len(shown_runs) * 4 - sum(
        1 for entry in shown_runs for phase in entry["phase_durations"] if phase["duration_ms"] == 0
    ))
    for phase in ("Sprawdzanie", "Odczyt danych", "Planowanie", "Zapisywanie"):
        expect(chart.get_by_text(phase, exact=True)).to_be_visible()
    run.check(True, "the stage-times chart stacks the four phases of each Przygotowanie RUN")
    run.capture(page, "11-metryki-wykres")

    run.step(feature, "metryki-tabela-etapow")
    page.get_by_role("tab", name="Tabela", exact=True).click()
    table = page.get_by_role("table", name="Czasy etapów")
    expect(table.get_by_role("row")).to_have_count(1 + len(shown_runs) + 2)
    p50_row = table.get_by_role("row").filter(has_text="P50")
    expect(p50_row).to_contain_text(_seconds(percentiles["p50_ms"]))
    for phase in percentiles["phases"]:
        if any(p["phase"] == phase["phase"] and p["duration_ms"] for e in shown_runs for p in e["phase_durations"]):
            expect(p50_row).to_contain_text(_seconds(phase["p50_ms"]))
    run.check(True, "the table view lists each run's phase times with per-phase P50/P95 from the server")
    run.capture(page, "12-metryki-tabela-etapow")
    page.get_by_role("tab", name="Wykres", exact=True).click()

    run.step(feature, "metryki-za-malo-obserwacji")
    page.get_by_role("group", name="Tryb", exact=True).get_by_role("button", name="DRY-RUN", exact=True).click()
    dry_run = statistics[("preparation", "DRY-RUN")]
    run.check(
        dry_run["percentiles"] is None and dry_run["completed_runs"] < 5,
        "Przygotowanie DRY-RUN has fewer than five completed observations",
    )
    expect(strip.get_by_role("group", name="P50")).to_contain_text(f"od 5 ukończonych (jest {dry_run['completed_runs']})")
    run.check(True, "below five completed observations P50/P95 show a dash and the count")
    run.capture(page, "13-metryki-za-malo-obserwacji")
    page.get_by_role("group", name="Tryb", exact=True).get_by_role("button", name="RUN", exact=True).click()

    run.step(feature, "metryki-przerwane")
    period, phase_times = fixture_metrics["interrupted"]
    interrupted = page.get_by_role("region", name="Przerwane")
    expect(interrupted).to_contain_text(period)
    expect(interrupted).to_contain_text(
        f"Sprawdzanie {_seconds(phase_times[0])} · Odczyt danych {_seconds(phase_times[1])}"
    )
    expect(interrupted).to_contain_text(f"do przerwania {_seconds(sum(phase_times))}")
    run.check(True, "an interrupted Uruchomienie procesu shows its phase times until the interruption")

    run.step(feature, "metryki-historia")
    rows = _history_rows(page)
    expect(rows).to_have_count(1 + min(10, len(runs)))
    expect(rows.nth(1)).to_contain_text(_local(runs[0]["started_at"]))
    dry_runs_on_page = sum(1 for entry in runs[:10] if entry["mode"] == "DRY-RUN")
    history = page.get_by_role("table", name="Historia Uruchomień procesu")
    expect(history.get_by_text("DRY-RUN", exact=True)).to_have_count(dry_runs_on_page)
    expect(history.get_by_text(".cmd", exact=True)).to_have_count(min(10, len(runs)))
    run.capture(page, "14-metryki-historia")
    history.get_by_role("button", name="Czas", exact=True).click()
    longest = max(runs, key=lambda entry: entry["total_duration_ms"])
    expect(rows.nth(1)).to_contain_text(_seconds(longest["total_duration_ms"]))
    expect(history.get_by_role("columnheader", name="Czas")).to_have_attribute("aria-sort", "descending")
    page.get_by_role("group", name="Proces w historii").get_by_role("button", name="Przebieg", exact=True).click()
    settlements = [entry for entry in runs if entry["process"] == "settlement"]
    expect(rows).to_have_count(1 + min(10, len(settlements)))
    for index in range(1, min(10, len(settlements)) + 1):
        expect(rows.nth(index)).to_contain_text("Przebieg rozliczeń")
    page.get_by_role("group", name="Proces w historii").get_by_role("button", name="Wszystkie", exact=True).click()
    page.get_by_role("button", name="Pokaż starsze", exact=True).click()
    expect(rows).to_have_count(1 + min(20, len(runs)))
    run.check(True, "the history sorts by time, filters by process and shows older runs on demand")
    run.capture(page, "15-metryki-historia-filtry")

    run.step(feature, "metryki-nowy-rekord-z-cli")
    completed = subprocess.run(
        [sys.executable, str(REPO_ROOT / "run_preparation.py"),
         "--register", str(run.root / "brak-rejestru.xlsx"),
         "--periods-directory", run.fixture["periods_directory"],
         "--period", LAST_COMPLETE_FOR_CLI, "--dry-run",
         "--metrics", fixture_metrics["preparation"]],
        cwd=REPO_ROOT, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=120, check=False,
    )
    run.check(completed.returncode == 1, "the CLI stopped (no Rejestr zleceń) and wrote its metrics record")
    after = run.api("/api/metrics", "metryki-po-cli")["runs"]
    assert isinstance(after, list)
    run.check(len(after) == len(runs) + 1, "the next read includes the CLI's record without restarting Centrum")
    page.reload()
    newest = _history_rows(page).nth(1)
    expect(newest).to_contain_text(_local(after[0]["started_at"]))
    expect(newest).to_contain_text(LAST_COMPLETE_FOR_CLI)
    expect(newest).to_contain_text("Zatrzymano")
    expect(newest).to_contain_text(".cmd")
    run.check(True, "the reloaded page shows the CLI's DRY-RUN as the newest Uruchomienie procesu")
    run.capture(page, "16-metryki-nowy-rekord-z-cli")

    run.step(feature, "metryki-pusty-stan")
    moved = [Path(fixture_metrics[name]) for name in ("preparation", "settlement")]
    for path in moved:
        path.rename(path.with_name(path.name + ".odlozony"))
    try:
        run.check(run.api("/api/metrics", "metryki-brak-plikow")["runs"] == [], "no metrics files is an empty list")
        page.reload()
        expect(page.get_by_text("Jeszcze nie ma metryk", exact=True)).to_be_visible()
        run.capture(page, "17-metryki-pusty-stan")
    finally:
        for path in moved:
            path.with_name(path.name + ".odlozony").rename(path)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--root", required=True, help="Run root with fixture.json and a served Centrum.")
    parser.add_argument("--url", required=True, help="Centrum URL from <root>/server.json.")
    parser.add_argument("--evidence", required=True, help="Evidence directory that survives cleanup.")
    parser.add_argument("--feature", choices=("all", *FEATURES), default="all")
    args = parser.parse_args(argv)
    run = Run(Path(args.root).resolve(), args.url, Path(args.evidence).resolve())
    drives = {"ustawienia": drive_settings, "tablica-okresow": drive_period_board, "metryki": drive_metrics}
    selected = FEATURES if args.feature == "all" else (args.feature,)
    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch()
            try:
                context = browser.new_context(
                    viewport={"width": 1440, "height": 1000}, locale="pl-PL", timezone_id=DAD_TIME_ZONE.key
                )
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
        for name in ("opened.jsonl", "dialogs.jsonl", "config/centrum-ustawienia.yaml"):
            source = run.root / name
            if source.exists():
                shutil.copy2(source, run.evidence / "state" / source.name)
    print(f"DRIVE OK | features={','.join(selected)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

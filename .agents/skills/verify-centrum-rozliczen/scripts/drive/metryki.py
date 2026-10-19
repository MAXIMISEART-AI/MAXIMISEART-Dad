"""Drive features/metryki.md."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
import subprocess
import sys

from playwright.sync_api import Page, expect

from drive.common import DAD_TIME_ZONE, LAST_COMPLETE_FOR_CLI, REPO_ROOT, Run, choose_periods_directory, history_rows


def _seconds(duration_ms: int) -> str:
    """The UI's duration text: tenths of a second rounded half up, Polish comma (``7250`` → ``7,3 s``)."""

    tenths = (duration_ms + 50) // 100
    return f"{tenths // 10},{tenths % 10} s"


def _local(started_at: str) -> str:
    """The UI's date text in Dad's time zone (``06.10.2026, 08:21``)."""

    return datetime.fromisoformat(started_at).astimezone(DAD_TIME_ZONE).strftime("%d.%m.%Y, %H:%M")


def drive_metrics(run: Run, page: Page) -> None:
    feature = "metryki"
    fixture_metrics = run.fixture["metrics"]

    run.step(feature, "metryki-karty-okresow")
    page.goto(run.url + "#/okresy")
    if run.api("/api/settings", "metryki-ustawienia")["periods_directory"] == {"state": "not_set"}:
        choose_periods_directory(run, page)
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
    run.capture(page, "20-metryki-karty-okresow")

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
    run.capture(page, "21-metryki-wykres")

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
    run.capture(page, "22-metryki-tabela-etapow")
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
    run.capture(page, "23-metryki-za-malo-obserwacji")
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
    rows = history_rows(page)
    expect(rows).to_have_count(1 + min(10, len(runs)))
    expect(rows.nth(1)).to_contain_text(_local(runs[0]["started_at"]))
    dry_runs_on_page = sum(1 for entry in runs[:10] if entry["mode"] == "DRY-RUN")
    history = page.get_by_role("table", name="Historia Uruchomień procesu")
    expect(history.get_by_text("DRY-RUN", exact=True)).to_have_count(dry_runs_on_page)
    expect(history.get_by_text(".cmd", exact=True)).to_have_count(min(10, len(runs)))
    run.capture(page, "24-metryki-historia")
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
    run.capture(page, "25-metryki-historia-filtry")

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
    newest = history_rows(page).nth(1)
    expect(newest).to_contain_text(_local(after[0]["started_at"]))
    expect(newest).to_contain_text(LAST_COMPLETE_FOR_CLI)
    expect(newest).to_contain_text("Zatrzymano")
    expect(newest).to_contain_text(".cmd")
    run.check(True, "the reloaded page shows the CLI's DRY-RUN as the newest Uruchomienie procesu")
    run.capture(page, "26-metryki-nowy-rekord-z-cli")

    run.step(feature, "metryki-pusty-stan")
    moved = [Path(fixture_metrics[name]) for name in ("preparation", "settlement")]
    for path in moved:
        path.rename(path.with_name(path.name + ".odlozony"))
    try:
        run.check(run.api("/api/metrics", "metryki-brak-plikow")["runs"] == [], "no metrics files is an empty list")
        page.reload()
        expect(page.get_by_text("Jeszcze nie ma metryk", exact=True)).to_be_visible()
        run.capture(page, "27-metryki-pusty-stan")
    finally:
        for path in moved:
            path.with_name(path.name + ".odlozony").rename(path)

"""Drive features/logi-uruchomienia.md."""

from __future__ import annotations

import json
import re
from typing import Any

from playwright.sync_api import Page, expect

from drive.common import ROW_MARKER, Run, finished_result, served_version
from drive.przebieg_rozliczen import TEMPLATE_PACING_MS, drive_settlement

FEATURE = "logi-uruchomienia"
# Centrum logs to <root>/logs/centrum-rozliczen.log, so the Logi Uruchomienia are next to it (ADR 0015).
LOGS = "logs/uruchomienia"
MODES = {"DRY-RUN": "podgląd", "RUN": "zapis"}
# What Dad could read about the Logi: the word in any of its cases, or their folder.
ABOUT_LOGS = re.compile(r"\bLog(i|ów|ach|ami)\b|uruchomienia/")

Json = dict[str, Any]
"""A file of Logi or a card, parsed from JSON."""


def _records(run: Run) -> dict[str, Json]:
    directory = run.root / LOGS
    paths = sorted(directory.glob("*.json")) if directory.is_dir() else []
    return {path.name: json.loads(path.read_text(encoding="utf-8")) for path in paths}


def _card(run: Run, name: str) -> Json:
    """The finished card as the browser got it: the one answer ``finished_result`` waited for, kept in ``api/``."""

    finished_result(run, name)
    view: Json = json.loads((run.evidence / "api" / f"{name}.json").read_text(encoding="utf-8"))
    return view


def _one_new(run: Run, before: set[str], what: str) -> Json:
    new = {name: record for name, record in _records(run).items() if name not in before}
    run.check(len(new) == 1, f"{what}: exactly one new file in {LOGS} ({', '.join(sorted(new))})")
    [record] = new.values()
    return record


def _matches_card(run: Run, record: Json, view: Json, mode: str) -> None:
    info, result = view["run"], view["result"]
    run.check(
        (record["run_id"], record["process"], record["period"], record["mode"])
        == (info["id"], info["process"], info["period"], mode),
        f"the Logi name the card's Uruchomienie {info['id']} and say it was a {mode}",
    )
    run.check(
        (record["result"], record["ending"], record["stop_kind"])
        == (result["result"], result["ending"], result["stop_kind"]),
        f"result, ending and Rodzaj Zatrzymania equal the card: {result['result']}, {result['ending']}, "
        f"{result['stop_kind']}",
    )
    shown = [("stop", stop) for stop in result["stops"]] + [("warning", warning) for warning in result["warnings"]]
    run.check(
        [(message["kind"], {part: message[part] for part in ("what", "where", "action")}) for message in record["messages"]]
        == shown,
        f"the Logi hold the card's {len(shown)} Komunikaty in three parts, stops before warnings",
    )
    run.check(
        (record["summary"], record["notices"]) == (result["summary"], result["notices"]),
        "the summary and the notices equal the card",
    )


def _names_running_tool(run: Run, record: Json) -> None:
    run.check(
        record["tool"] == {"wydanie": None, "commit": served_version(run)[0]},
        "the Logi name the commit of the tool Centrum runs",
    )


def _codes(record: Json) -> list[tuple[str, str]]:
    return [(message["kind"], message["code"]) for message in record["messages"]]


def _nothing_about_logs(run: Run, page: Page, where: str) -> None:
    text = page.locator("body").inner_text()
    run.check(ABOUT_LOGS.search(text) is None, f"{where}: Dad reads nothing about the Logi, on the card or in a toast")


def _new_settlement(run: Run, page: Page, period: str) -> None:
    page.goto(run.url + "#/uruchomienia")
    page.get_by_role("button", name="Nowe Uruchomienie procesu", exact=True).click()
    page.get_by_role("radio", name="Przebieg rozliczeń").click()
    expect(page.get_by_role("combobox", name="Okres")).to_contain_text(period)


def _ended_in_centrum_log(run: Run) -> list[tuple[str, str, str, str, str]]:
    ended = []
    for line in (run.root / "logs" / "centrum-rozliczen.log").read_text(encoding="utf-8").splitlines():
        _, event, *facts = line.split(" ")
        if event == "uruchomienie-koniec":
            fact = dict(entry.split("=", 1) for entry in facts)
            ended.append((fact["proces"], MODES[fact["tryb"]], fact["okres"], fact["wynik"], fact["koniec"]))
    return ended


def drive_run_logs(run: Run, page: Page) -> None:
    needs_check = run.fixture["settlement"]["needs_check"]
    settled = run.evidence / "api" / "przebieg-zapisane.json"
    if not settled.exists():
        # The Logi of a written Przebieg rozliczeń list its Szablony pracowników; alone, this feature drives one.
        drive_settlement(run, page)

    run.step(FEATURE, "logi-podglad")
    before = set(_records(run))
    _new_settlement(run, page, needs_check)
    page.get_by_role("button", name="Podgląd bez zapisu", exact=True).click()
    expect(page.get_by_label("Wynik")).to_contain_text("Podgląd wymaga sprawdzenia · nic nie zapisano")
    view = _card(run, "logi-podglad")
    record = _one_new(run, before, "Podgląd bez zapisu")
    _matches_card(run, record, view, "podgląd")
    _names_running_tool(run, record)
    run.check(
        _codes(record) == [("warning", "BRAK_MAPOWANIA")],
        "the warning keeps its code BRAK_MAPOWANIA, which the card does not show",
    )
    _nothing_about_logs(run, page, "after the preview")
    run.capture(page, "150-logi-podglad")

    run.step(FEATURE, "logi-zatrzymanie")
    before = set(_records(run))
    _new_settlement(run, page, needs_check)
    page.get_by_role("button", name="Uruchom", exact=True).click()
    page.get_by_role("alertdialog", name="Uruchomić z zapisem?").get_by_role("button", name="Uruchom", exact=True).click()
    expect(page.get_by_label("Zatrzymanie")).to_contain_text("W Pliku zbiorczym jest WYKONAWCA")
    view = _card(run, "logi-zatrzymanie")
    record = _one_new(run, before, "Zatrzymanie")
    _matches_card(run, record, view, "zapis")
    _names_running_tool(run, record)
    run.check(
        _codes(record) == [("stop", "NIEZNANY_WYKONAWCA")],
        "the Zatrzymanie is one message of kind stop with its code NIEZNANY_WYKONAWCA",
    )
    _nothing_about_logs(run, page, "after the Zatrzymanie")
    run.capture(page, "151-logi-zatrzymanie")

    run.step(FEATURE, "logi-szablony")
    view = json.loads(settled.read_text(encoding="utf-8"))
    [record] = [record for record in _records(run).values() if record["run_id"] == view["run"]["id"]]
    _matches_card(run, record, view, "zapis")
    workers, rows = run.fixture["workers"], run.fixture["settlement"]["rows_per_worker"]
    templates = record["templates"]
    run.check(
        [(template["wykonawca"], template["outcome"], template["rows"]) for template in templates]
        == [(worker, "ZAPISANO", count) for worker, count in zip(workers, rows, strict=True)],
        "the Logi of the written Przebieg rozliczeń list every Wykonawca in order with outcome ZAPISANO and its rows",
    )
    durations = [template["duration_ms"] for template in templates]
    run.check(
        all(isinstance(duration, int) for duration in durations) and durations[0] >= TEMPLATE_PACING_MS,
        f"each Szablon pracownika has its time; the first, paced {TEMPLATE_PACING_MS} ms (harness), took {durations[0]} ms",
    )

    run.step(FEATURE, "logi-kazde-uruchomienie")
    ended = _ended_in_centrum_log(run)
    records = sorted(_records(run).values(), key=lambda record: str(record["started_at"]))
    run.check(
        [(record["process"], record["mode"], record["period"], record["result"], record["ending"]) for record in records]
        == ended,
        f"each of the {len(ended)} Uruchomienia ended in the Centrum log has its own file of Logi, in the same order",
    )
    run.check(len({record["run_id"] for record in records}) == len(records), "no two files hold the same Uruchomienie")

    run.step(FEATURE, "logi-bez-sladu")
    page.reload()
    expect(page.get_by_label("Zatrzymanie")).to_be_visible()
    _nothing_about_logs(run, page, "Uruchomienia after a reload")
    texts = [path.read_text(encoding="utf-8") for path in sorted((run.root / LOGS).glob("*.json"))]
    run.check(
        not any(str(run.root) in text or ROW_MARKER in text for text in texts),
        "no file of Logi holds a path in the run root or workbook row content",
    )
    files = [logged["name"] for record in records for logged in record["environment"]["files"] or []]
    run.check(
        files != [] and not any("/" in name or "\\" in name for name in files),
        "the files of each process are listed by name only",
    )

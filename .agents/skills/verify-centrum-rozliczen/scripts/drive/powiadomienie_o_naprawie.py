"""Drive features/powiadomienie-o-naprawie.md."""

from __future__ import annotations

import json
from pathlib import Path

from playwright.sync_api import Locator, Page, expect

from drive import zgloszenie
from drive.common import Run, stop_banner

FEATURE = "powiadomienie-o-naprawie"
REPAIRED = "Maks naprawił zgłoszony problem."
UPDATE_BUTTON = "Zaktualizuj narzędzie"
# Synthetic key Maks would write; it must never reach the skrzynka, the log, an answer, or the browser.
KEY = "github_pat_VERIFY_SYNTETYCZNY_KLUCZ"
# The tool Dad runs when he sends the Zgłoszenie of this feature: newer than the one of features/zgloszenie.md,
# whose closed Zgłoszenie 1 would otherwise give the notice from the start.
SENDING_COMMIT = "d" * 40
# The tool after Dad's update: another commit than the one the Zgłoszenie was sent from.
UPDATED_COMMIT = "e" * 40


def _sent(config: Path) -> list[dict[str, object]]:
    path = config / "zgloszenia-wyslane.json"
    entries = json.loads(path.read_text(encoding="utf-8")) if path.exists() else []
    assert isinstance(entries, list)
    return entries


def _asked(run: Run) -> int:
    """How many times Centrum asked the file skrzynka for the state of sent Zgłoszenia."""

    asked = run.root / "skrzynka-zgloszen-zapytania.jsonl"
    return len(asked.read_text(encoding="utf-8").splitlines()) if asked.exists() else 0


def _advance_clock(run: Run, minutes: int) -> None:
    """Move Centrum's monotonic clock forward, so the next visit may ask the skrzynka again."""

    moved = run.root / "zegar" / "przesuniecie-min.txt"
    moved.parent.mkdir(exist_ok=True)
    before = float(moved.read_text(encoding="utf-8")) if moved.exists() else 0.0
    moved.write_text(str(before + minutes), encoding="utf-8")


def _enter_periods(page: Page, run: Run) -> Locator:
    """Dad enters Okresy afresh; returns the repair notice, which may be absent."""

    page.goto(run.url + "#/okresy")
    page.reload()
    expect(page.get_by_role("heading", name="Okresy", exact=True)).to_be_visible()
    page.wait_for_load_state("networkidle")
    return page.get_by_role("status").filter(has_text=REPAIRED)


def _repaired(run: Run, name: str) -> object:
    return run.api("/api/reports/repair", name)["repaired"]


def _update_tool(run: Run, commit: str) -> None:
    """Dad updates the tool to the newest ``main``: both the local commit and ``main`` become ``commit``."""

    github = run.root / "github"
    github.mkdir(exist_ok=True)
    (github / "tool-commit.txt").write_text(commit, encoding="utf-8")
    (github / "main-commit.txt").write_text(commit, encoding="utf-8")


def _send_from_updated_tool(run: Run, page: Page, box: Path) -> int:
    """After features/zgloszenie.md Dad updates the tool and sends the Zgłoszenie of the other problem from it."""

    print("  harness: Dad updates the tool, then the other problem stops again", flush=True)
    _update_tool(run, SENDING_COMMIT)
    zgloszenie._stop_for_maks(run, page, "naprawa-wysylka", missing="collective_template")
    stop_banner(page).get_by_role("button", name="Diagnoza", exact=True).click()
    page.get_by_role("region", name="Diagnoza").get_by_role("button", name="Wyślij do Maksa", exact=True).click()
    expect(page.get_by_role("status").filter(has_text=zgloszenie.SENT)).to_be_visible()
    issues = sorted(box.glob("*.json"), key=lambda path: int(path.stem))
    number = int(issues[-1].stem)
    run.check(
        json.loads(issues[-1].read_text(encoding="utf-8"))["state"] == "open",
        "the Zgłoszenie from the updated tool is open in the skrzynka",
    )
    return number


def drive_repair_notice(run: Run, page: Page) -> None:
    config = Path(run.fixture["settings"]).parent
    key_file = config / "zgloszenia-klucz.txt"
    box = run.root / "skrzynka-zgloszen"
    if not _sent(config):
        print("  harness: no Zgłoszenie sent yet, so zgloszenie runs first", flush=True)
        zgloszenie.drive_report(run, page)
    key_file.write_text(KEY + "\n", encoding="utf-8")

    run.step(FEATURE, "naprawa-czeka")
    number = _send_from_updated_tool(run, page, box)
    run.check(_sent(config)[-1]["number"] == number, "the local sent state has the new Zgłoszenie last")
    issue_file = box / f"{number}.json"
    _advance_clock(run, 10)
    asked = _asked(run)
    notice = _enter_periods(page, run)
    run.check(_asked(run) == asked + 1, "entering Okresy asks the skrzynka about the sent Zgłoszenie")
    run.check(_repaired(run, "naprawa-czeka") is False, "an open Zgłoszenie gives no repair notice")
    expect(notice).to_have_count(0)
    run.check(_asked(run) == asked + 1, "a second read within 10 minutes does not ask the skrzynka again")
    run.capture(page, "72-naprawa-czeka")

    run.step(FEATURE, "naprawa-brak-sieci")
    print(f"  harness: Maks closes Zgłoszenie #{number} in the skrzynka", flush=True)
    issue = json.loads(issue_file.read_text(encoding="utf-8"))
    issue_file.write_text(json.dumps({**issue, "state": "closed"}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    asked = _asked(run)
    notice = _enter_periods(page, run)
    run.check(_asked(run) == asked, "within 10 minutes Okresy shows the last known state without asking")
    expect(notice).to_have_count(0)
    (box / "brak-sieci").touch()
    _advance_clock(run, 10)
    notice = _enter_periods(page, run)
    run.check(_asked(run) == asked + 1, "after 10 minutes Okresy asks again")
    run.check(_repaired(run, "naprawa-brak-sieci") is False, "without network the last known state stays")
    expect(notice).to_have_count(0)
    expect(page.get_by_role("alert")).to_have_count(0)
    run.check([entry["state"] for entry in _sent(config)][-1] == "open", "no network changes no local state")
    run.capture(page, "73-naprawa-brak-sieci")

    run.step(FEATURE, "naprawa-powiadomienie")
    (box / "brak-sieci").unlink()
    _advance_clock(run, 10)
    notice = _enter_periods(page, run)
    expect(notice).to_be_visible()
    expect(notice.get_by_role("button", name=UPDATE_BUTTON, exact=True)).to_be_enabled()
    run.check(_repaired(run, "naprawa-powiadomienie") is True, "a closed Zgłoszenie from this version is repaired")
    run.check(_sent(config)[-1]["state"] == "closed", "the local sent state remembers the closed Zgłoszenie")
    run.check(KEY not in page.content(), "the key never reaches the browser")
    run.capture(page, "74-naprawa-powiadomienie")

    run.step(FEATURE, "naprawa-po-aktualizacji")
    print("  harness: Dad updates the tool, so it runs another commit", flush=True)
    _update_tool(run, UPDATED_COMMIT)
    asked = _asked(run)
    notice = _enter_periods(page, run)
    expect(notice).to_have_count(0)
    run.check(_repaired(run, "naprawa-po-aktualizacji") is False, "after the update the notice is gone by itself")
    run.check(_asked(run) == asked, "a closed Zgłoszenie is not asked about again")
    log = (run.root / "logs" / "centrum-rozliczen.log").read_text(encoding="utf-8")
    run.check(KEY not in log, "the key is not in the Centrum log")
    run.capture(page, "75-naprawa-po-aktualizacji")
    key_file.unlink()

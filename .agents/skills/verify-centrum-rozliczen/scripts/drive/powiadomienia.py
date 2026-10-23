"""Drive features/powiadomienia.md."""

from __future__ import annotations

import json
from pathlib import Path

from playwright.sync_api import Locator, Page, expect

from drive import uwaga_taty, zgloszenie
from drive.common import PAGES, Run, error_toasts

FEATURE = "powiadomienia"
BELL = "Powiadomienia"
BELL_FRESH = "Powiadomienia, są nowe"
RESOLVED = "Rozwiązana. Będzie w następnej wersji."
READ = "Maks przeczytał."
SENT_NOTE = "Wysłana do Maksa."
# Synthetic key Maks would write; it must never reach the skrzynka, the log, an answer, or the browser.
KEY = "github_pat_VERIFY_SYNTETYCZNY_KLUCZ"
CLOSED_AT = "2026-10-19T09:15:00Z"


def _asked(run: Run) -> list[str]:
    """Labels of every question for issues with a label, closed ones included (how Powiadomienia ask)."""

    asked = run.root / "skrzynka-zgloszen-zapytania.jsonl"
    return [json.loads(line)["label"] for line in asked.read_text(encoding="utf-8").splitlines()] if asked.exists() else []


def _advance_clock(run: Run, minutes: int) -> None:
    """Move Centrum's monotonic clock forward, so the next read may ask the skrzynka again."""

    moved = run.root / "zegar" / "przesuniecie-min.txt"
    moved.parent.mkdir(exist_ok=True)
    before = float(moved.read_text(encoding="utf-8")) if moved.exists() else 0.0
    moved.write_text(str(before + minutes), encoding="utf-8")


def _close_issue(box: Path, number: int, reason: str) -> None:
    """Maks closes issue ``number`` in the skrzynka with GitHub's ``state_reason``."""

    path = box / f"{number}.json"
    issue = json.loads(path.read_text(encoding="utf-8"))
    closed = {**issue, "state": "closed", "state_reason": reason, "closed_at": CLOSED_AT}
    path.write_text(json.dumps(closed, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _bell(page: Page) -> Locator:
    return page.locator("header").get_by_role("button", name=BELL, exact=False)


def _row(page: Page, kind: str, name: str) -> Locator:
    return page.get_by_role("list", name=BELL).get_by_role("listitem", name=f"{kind}: {name}", exact=True)


def _enter(page: Page, run: Run, page_id: str, heading: str) -> None:
    page.goto(run.url + f"#/{page_id}")
    page.reload()
    expect(page.get_by_role("heading", name=heading, exact=True)).to_be_visible()
    page.wait_for_load_state("networkidle")


def _toggle_theme(page: Page) -> None:
    page.locator("header").get_by_role("button", name="Włącz motyw", exact=False).click()


def drive_notifications(run: Run, page: Page) -> None:
    config = Path(run.fixture["settings"]).parent
    key_file = config / "zgloszenia-klucz.txt"
    box = run.root / "skrzynka-zgloszen"
    if not uwaga_taty._issues(box):
        print("  harness: no Uwaga taty sent yet, so zgloszenie and uwaga-taty run first", flush=True)
        if not zgloszenie._issues(box):
            zgloszenie.drive_report(run, page)
        uwaga_taty.drive_dad_note(run, page)
    key_file.write_text(KEY + "\n", encoding="utf-8")
    notes = uwaga_taty._issues(box)
    reports = zgloszenie._issues(box)
    note, report = notes[-1], next(issue for issue in reports if issue["state"] == "open")
    report_what = str(report["title"]).split(": ", 1)[1]

    run.step(FEATURE, "powiadomienia-dzwonek")
    _advance_clock(run, 10)
    for page_id, heading in PAGES.items():
        _enter(page, run, page_id, heading)
        bell, write = _bell(page), page.get_by_role("button", name=uwaga_taty.WRITE, exact=True)
        expect(bell).to_be_visible()
        bell_box, write_box = bell.bounding_box(), write.bounding_box()
        run.check(
            bell_box is not None and write_box is not None and write_box["x"] < bell_box["x"],
            f"{heading}: the bell sits right of „{uwaga_taty.WRITE}”",
        )
    answer = run.api("/api/notifications", "powiadomienia-wyslane")
    items = answer["items"]
    assert isinstance(items, list)
    run.check(
        {"kind": "uwaga", "title": note["title"], "state": "wyslana", "unread": False}.items()
        <= next(item for item in items if item.get("title") == note["title"]).items(),
        "the sent Uwaga is a Powiadomienie, sent and not new",
    )
    run.check(
        any(item.get("what") == report_what and item["state"] == "wyslana" for item in items),
        "the open Zgłoszenie is a Powiadomienie named by its „Co się stało”, without the code",
    )
    run.check(answer["unread"] == sum(item["unread"] for item in items), "the unread count is the new Powiadomienia")
    run.capture(page, "72-powiadomienia-dzwonek")

    run.step(FEATURE, "powiadomienia-zamkniete")
    print(f"  harness: Maks closes Uwaga #{note['number']} as completed and Zgłoszenie #{report['number']} as not planned", flush=True)
    _close_issue(box, int(str(note["number"])), "completed")
    _close_issue(box, int(str(report["number"])), "not_planned")
    _advance_clock(run, 10)
    asked = len(_asked(run))
    _enter(page, run, "okresy", "Okresy")
    expect(_bell(page)).to_have_accessible_name(BELL_FRESH)
    run.check(len(_asked(run)) <= asked + 2, "the 10 minutes passed, so Centrum asks once per kind of case")
    after_first = len(_asked(run))
    run.check(after_first > asked, "Centrum asked the skrzynka about Dad's open cases")
    _enter(page, run, "uruchomienia", "Uruchomienia")
    run.check(len(_asked(run)) == after_first, "a second read within 10 minutes does not ask the skrzynka again")
    run.capture(page, "73-powiadomienia-kropka")
    header = page.locator("header").first.bounding_box()
    assert header is not None
    page.screenshot(
        path=run.evidence / "screenshots" / "73b-powiadomienia-kropka-zblizenie.png",
        clip={"x": header["x"] + header["width"] - 240, "y": header["y"], "width": 240, "height": header["height"]},
    )

    run.step(FEATURE, "powiadomienia-widok")
    _bell(page).click()
    expect(page.get_by_role("heading", name=BELL, exact=True)).to_be_visible()
    run.check(page.url.endswith("#/powiadomienia"), "the bell opens the view Powiadomienia in the same tab")
    menu = page.get_by_role("list", name="Sekcje Centrum rozliczeń")
    expect(menu.get_by_role("link", name=BELL)).to_have_count(0)
    expect(menu.locator("[aria-current=page]")).to_have_count(0)
    # The Zgłoszenie that zgloszenie closed has the same „Co się stało”; the state tells the two rows apart.
    note_row = _row(page, "Uwaga", str(note["title"])).filter(has_text=RESOLVED)
    report_row = _row(page, "Zgłoszenie", report_what).filter(has_text=READ)
    expect(note_row).to_have_count(1)
    expect(report_row).to_have_count(1)
    for row in (note_row, report_row):
        expect(row.get_by_label("nowe", exact=True)).to_be_visible()
        run.check(row.get_attribute("data-fresh") == "true", "a new row keeps its light background while Dad stays")
    expect(_bell(page)).to_have_accessible_name(BELL)
    run.wait_for(
        lambda: run.api("/api/notifications", "powiadomienia-przeczytane")["unread"] == 0,
        "entering the view marks every Powiadomienie read",
    )
    stored = json.loads((config / "powiadomienia.json").read_text(encoding="utf-8"))
    run.check(stored["schema_version"] == 1 and len(stored["przeczytane"]) >= 2, "config/powiadomienia.json keeps them")
    expect(page.get_by_role("alert")).to_have_count(0)
    expect(error_toasts(page)).to_have_count(0)
    run.capture(page, "74-powiadomienia-widok")
    _toggle_theme(page)
    expect(note_row.get_by_label("nowe", exact=True)).to_be_visible()
    run.capture(page, "75-powiadomienia-widok-drugi-motyw")
    _toggle_theme(page)

    run.step(FEATURE, "powiadomienia-po-wyjsciu")
    page.get_by_role("link", name="Okresy", exact=True).click()
    expect(page.get_by_role("heading", name="Okresy", exact=True)).to_be_visible()
    _bell(page).click()
    expect(page.get_by_role("heading", name=BELL, exact=True)).to_be_visible()
    expect(page.get_by_role("list", name=BELL).get_by_label("nowe", exact=True)).to_have_count(0)
    expect(_bell(page)).to_have_accessible_name(BELL)

    run.step(FEATURE, "powiadomienia-brak-sieci")
    (box / "brak-sieci").touch()
    try:
        _close_issue(box, int(str(notes[0]["number"])), "completed")
        _advance_clock(run, 10)
        asked = len(_asked(run))
        _enter(page, run, "powiadomienia", BELL)
        run.check(len(_asked(run)) > asked, "after 10 minutes Centrum asks again")
        expect(_row(page, "Uwaga", str(notes[0]["title"]))).to_contain_text(SENT_NOTE)
        expect(page.get_by_role("alert")).to_have_count(0)
        expect(error_toasts(page)).to_have_count(0)
        expect(_bell(page)).to_have_accessible_name(BELL)
        run.capture(page, "76-powiadomienia-brak-sieci")
    finally:
        (box / "brak-sieci").unlink(missing_ok=True)
    log = (run.root / "logs" / "centrum-rozliczen.log").read_text(encoding="utf-8")
    run.check(KEY not in log and KEY not in page.content(), "the key is neither in the Centrum log nor in the browser")
    key_file.unlink()

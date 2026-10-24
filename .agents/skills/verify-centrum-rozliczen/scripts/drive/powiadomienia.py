"""Drive features/powiadomienia.md."""

from __future__ import annotations

import json
from pathlib import Path
import subprocess

from playwright.sync_api import Locator, Page, expect

from drive import aktualizacja, uwaga_taty, zgloszenie
from drive.common import PAGES, Run, error_toasts, release_only

FEATURE = "powiadomienia"
BELL = "Powiadomienia"
BELL_FRESH = "Powiadomienia, są nowe"
RESOLVED = "Rozwiązana. Będzie w następnej wersji."
READ = "Maks przeczytał."
SENT_NOTE = "Wysłana do Maksa."
# Synthetic key Maks would write; it must never reach the skrzynka, the log, an answer, or the browser.
KEY = "github_pat_VERIFY_SYNTETYCZNY_KLUCZ"
CLOSED_AT = "2026-10-19T09:15:00Z"
SUMMARY = "Plik zbiorczy ma kolumnę z kilometrami. Rozliczenia pracowników przy dużym okresie są dwa razy szybsze."
FIRST_SUMMARY = "Pierwsza wersja z Powiadomieniami. Tutaj zobaczysz, co Maks zrobił z Twoimi Uwagami i Zgłoszeniami."
# A Wydanie GitHub names as the newest on `main` that the update does not take: the clone never had this commit.
DORMANT_RELEASE = "e" * 40
CASE_LABELS = ("zgloszenie", "uwaga-taty")


def _release(tag: str, body: str, published_at: str) -> dict[str, object]:
    """One entry of GitHub's list of Releases, in GitHub's shape."""

    return {"tag_name": tag, "body": body, "published_at": published_at, "draft": False, "prerelease": False}


def _publish(run: Run, newest_tag: str, newest_commit: str | None, releases: list[dict[str, object]]) -> None:
    """The scripted GitHub: the newest Wydanie on `main` (``None``: the tool's own commit) and the list of Releases."""

    github = run.root / "github"
    github.mkdir(exist_ok=True)
    (github / "wydanie.txt").write_text(newest_tag, encoding="utf-8")
    main_commit = github / "main-commit.txt"
    if newest_commit is None:
        main_commit.unlink(missing_ok=True)
    else:
        main_commit.write_text(newest_commit, encoding="utf-8")
    (github / "wydania.json").write_text(json.dumps(releases, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _release_questions(run: Run) -> int:
    asked = run.root / "github" / "zapytania-wydan.jsonl"
    return len(asked.read_text(encoding="utf-8").splitlines()) if asked.exists() else 0


def _versions(run: Run, name: str) -> list[tuple[object, object, object]]:
    items = run.api("/api/notifications", name)["items"]
    assert isinstance(items, list)
    return [(item["version"], item["update_offered"], item["unread"]) for item in items if item["kind"] == "nowa_wersja"]


def _asked(run: Run) -> list[str]:
    """Labels of every question about Dad's cases, closed ones included; Logi Uruchomienia ask the same way."""

    asked = run.root / "skrzynka-zgloszen-zapytania.jsonl"
    lines = asked.read_text(encoding="utf-8").splitlines() if asked.exists() else []
    return [label for label in (json.loads(line)["label"] for line in lines) if label in CASE_LABELS]


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
    run.capture(page, "180-powiadomienia-dzwonek")

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
    run.capture(page, "181-powiadomienia-kropka")
    header = page.locator("header").first.bounding_box()
    assert header is not None
    page.screenshot(
        path=run.evidence / "screenshots" / "181b-powiadomienia-kropka-zblizenie.png",
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
    run.capture(page, "182-powiadomienia-widok")
    _toggle_theme(page)
    expect(note_row.get_by_label("nowe", exact=True)).to_be_visible()
    run.capture(page, "183-powiadomienia-widok-drugi-motyw")
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
        run.capture(page, "184-powiadomienia-brak-sieci")
    finally:
        (box / "brak-sieci").unlink(missing_ok=True)
    try:
        _drive_new_version(run, page, note, report, report_what)
    finally:
        for name in ("wydanie.txt", "main-commit.txt", "wydania.json", "brak-sieci"):
            (run.root / "github" / name).unlink(missing_ok=True)
    log = (run.root / "logs" / "centrum-rozliczen.log").read_text(encoding="utf-8")
    run.check(KEY not in log and KEY not in page.content(), "the key is neither in the Centrum log nor in the browser")
    key_file.unlink()


def _drive_new_version(run: Run, page: Page, note: dict[str, object], report: dict[str, object], what: str) -> None:
    run.step(FEATURE, "powiadomienia-nowa-wersja")
    notes = "\n".join(
        [
            SUMMARY,
            "",
            "## Rozwiązane sprawy taty",
            "",
            f"- Uwaga taty #{note['number']}: {note['title']}",
            f"- Zgłoszenie #{report['number']}: {report['title']}",
            "- Uwaga taty #999: Uwaga z innego komputera",
        ]
    )
    print(
        "  harness: GitHub's newest Wydanie on `main` is v0.2.0 on a commit the update does not take, with v0.1.0"
        " before it and v0.3.0 published from outside `main`",
        flush=True,
    )
    releases = [
        _release("v0.3.0", "Wydanie spoza main.", "2026-10-23T08:00:00Z"),
        _release("v0.2.0", notes, "2026-10-22T08:00:00Z"),
        _release("v0.1.0", FIRST_SUMMARY, "2026-10-08T08:00:00Z"),
    ]
    _publish(run, "v0.2.0", DORMANT_RELEASE, releases)
    _advance_clock(run, 10)
    asked = _release_questions(run)
    _enter(page, run, "okresy", "Okresy")
    expect(_bell(page)).to_have_accessible_name(BELL_FRESH)
    _enter(page, run, "uruchomienia", "Uruchomienia")
    run.check(_release_questions(run) == asked + 1, "after 10 minutes Centrum asks GitHub for the Wydania once")
    _bell(page).click()
    card = page.get_by_role("region", name="Nowa wersja 0.2.0", exact=True)
    expect(card).to_contain_text(SUMMARY)
    solved = card.get_by_role("list", name="Rozwiązane sprawy").get_by_role("listitem")
    expect(solved).to_have_text([f"Uwaga: {note['title']}", f"Zgłoszenie: {what}"])
    expect(card.get_by_role("button", name=aktualizacja.BUTTON, exact=True)).to_be_enabled()
    # In `all` the features before this one leave `Masz najnowszą wersję.` from an older Wydanie (#373).
    run.check(
        run.api("/api/tool-update", "powiadomienia-nowa-wersja-aktualizacja")["state"] != "up_to_date",
        "the button of a newer Wydanie has no earlier `Masz najnowszą wersję.`",
    )
    expect(card.get_by_role("status").filter(has_text=aktualizacja.UP_TO_DATE)).to_have_count(0)
    expect(card.get_by_label("nowe", exact=True)).to_be_visible()
    listed = page.get_by_role("list", name=BELL)
    card_box, list_box = card.bounding_box(), listed.bounding_box()
    run.check(card_box is not None and list_box is not None and card_box["y"] < list_box["y"], "the card stands above the list")
    older = listed.get_by_role("listitem", name="Nowa wersja 0.1.0", exact=True)
    expect(older).to_contain_text(FIRST_SUMMARY)
    expect(older.get_by_role("button")).to_have_count(0)
    expect(page.get_by_text("Nowa wersja 0.3.0")).to_have_count(0)
    expect(page.get_by_text("Uwaga z innego komputera")).to_have_count(0)
    run.wait_for(
        lambda: run.api("/api/notifications", "powiadomienia-nowa-wersja-przeczytane")["unread"] == 0,
        "entering the view marks the Wydania read",
    )
    run.check(
        _versions(run, "powiadomienia-nowa-wersja") == [("0.2.0", True, False), ("0.1.0", False, False)],
        "the newest Wydanie on `main` offers the update, the older one does not, the one from outside `main` is no"
        " Powiadomienie, and entering the view marked both read",
    )
    expect(page.get_by_role("alert")).to_have_count(0)
    run.capture(page, "185-powiadomienia-nowa-wersja")
    _toggle_theme(page)
    expect(card).to_be_visible()
    run.capture(page, "186-powiadomienia-nowa-wersja-drugi-motyw")
    _toggle_theme(page)

    run.step(FEATURE, "powiadomienia-aktualizacja")
    tool = run.fixture["tool"]
    clone = Path(tool["clone"])
    head = subprocess.run(["git", "-C", str(clone), "rev-parse", "HEAD"], capture_output=True, text=True, check=True).stdout.strip()
    print("  harness: the newest Wydanie in the local origin is the clone's own commit", flush=True)
    release_only(Path(tool["origin"]), head)
    log = run.root / "logs" / "centrum-rozliczen.log"
    updates = log.read_text(encoding="utf-8").count("aktualizacja-koniec")
    card.get_by_role("button", name=aktualizacja.BUTTON, exact=True).click()
    run.wait_for(
        lambda: log.read_text(encoding="utf-8").count("aktualizacja-koniec") == updates + 1,
        "the card's button starts the Aktualizacja narzędzia",
    )
    expect(card.get_by_role("status").filter(has_text=aktualizacja.UP_TO_DATE)).to_be_visible()
    run.check(
        log.read_text(encoding="utf-8").splitlines()[-1].split(" ", 2)[1:2] == ["aktualizacja-koniec"]
        and "wynik=AKTUALNA" in log.read_text(encoding="utf-8").splitlines()[-1],
        "the update does not take a Wydanie that never was the tip of `main`, so the tool stays where it is",
    )
    run.check(
        subprocess.run(["git", "-C", str(clone), "rev-parse", "HEAD"], capture_output=True, text=True, check=True).stdout.strip()
        == head,
        "the clone stays on its commit",
    )
    run.capture(page, "187-powiadomienia-aktualizacja")

    run.step(FEATURE, "powiadomienia-wydanie-aktualne")
    print("  harness: the newest Wydanie on `main` is v0.2.0 on the tool's own commit (Dad is on it)", flush=True)
    _publish(run, "v0.2.0", None, releases)
    _advance_clock(run, 10)
    _enter(page, run, "powiadomienia", BELL)
    expect(page.get_by_role("region", name="Nowa wersja 0.2.0", exact=True)).to_have_count(0)
    current = page.get_by_role("list", name=BELL).get_by_role("listitem", name="Nowa wersja 0.2.0", exact=True)
    expect(current).to_contain_text(SUMMARY)
    expect(current.get_by_role("button")).to_have_count(0)
    expect(current.get_by_label("nowe", exact=True)).to_have_count(0)
    expect(_bell(page)).to_have_accessible_name(BELL)
    run.check(
        _versions(run, "powiadomienia-wydanie-aktualne") == [("0.2.0", False, False), ("0.1.0", False, False)],
        "a Wydanie Dad is on stays in the history, read, without the button",
    )
    run.capture(page, "188-powiadomienia-wydanie-aktualne")

    run.step(FEATURE, "powiadomienia-wydania-brak-sieci")
    (run.root / "github" / "brak-sieci").touch()
    _advance_clock(run, 10)
    asked = _release_questions(run)
    _enter(page, run, "powiadomienia", BELL)
    run.check(_release_questions(run) == asked + 1, "after 10 minutes Centrum asks GitHub again")
    expect(page.get_by_role("list", name=BELL).get_by_role("listitem", name="Nowa wersja 0.2.0", exact=True)).to_be_visible()
    expect(page.get_by_role("list", name=BELL).get_by_role("listitem", name="Nowa wersja 0.1.0", exact=True)).to_be_visible()
    expect(page.get_by_role("alert")).to_have_count(0)
    expect(error_toasts(page)).to_have_count(0)
    expect(_bell(page)).to_have_accessible_name(BELL)
    run.check(
        _versions(run, "powiadomienia-wydania-brak-sieci") == [("0.2.0", False, False), ("0.1.0", False, False)],
        "without network the Powiadomienia about Wydania stay as they were, with no Komunikat",
    )
    run.capture(page, "189-powiadomienia-wydania-brak-sieci")

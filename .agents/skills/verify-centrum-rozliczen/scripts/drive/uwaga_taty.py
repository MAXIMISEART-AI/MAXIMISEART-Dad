"""Drive features/uwaga-taty.md."""

from __future__ import annotations

import json
from pathlib import Path
import urllib.request

from playwright.sync_api import Locator, Page, expect

from drive.common import PAGES, Run, error_toasts

FEATURE = "uwaga-taty"
LABEL = "uwaga-taty"
WRITE = "Napisz do Maksa"
SENT = "Uwaga wysłana do Maksa."
WAITING = "Wyślę do Maksa, gdy będzie internet."
# Synthetic key Maks would write; it must never reach the skrzynka, the log, an answer, or the browser.
KEY = "github_pat_VERIFY_SYNTETYCZNY_KLUCZ"
# Synthetic Uwagi: the first waits for the key, the second has no Treść.
FIRST = ("Brakuje kolumny z kilometrami", "W Pliku zbiorczym nie ma kilometrów.\nDopisuję je ręcznie.")
SECOND = ("Proszę o większą czcionkę", "")
# Each issue waits this long in the skrzynka, so „Wyślij” is seen sending; two issues stay under the 5 s wait.
BOX_PACING_MS = 1500


def _draft(run: Run, title: str, body: str, name: str) -> dict[str, str]:
    """The issue Maks would get, straight from the server, as the reference for the figure in the tab."""

    request = urllib.request.Request(
        run.url.rstrip("/") + "/api/dad-notes/draft",
        data=json.dumps({"title": title, "body": body}).encode(),
        method="POST",
        headers={"Content-Type": "application/json", "Origin": run.url.rstrip("/")},
    )
    with urllib.request.urlopen(request, timeout=10) as response:
        draft = json.load(response)
    (run.evidence / "api" / f"{name}.json").write_text(
        json.dumps(draft, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    assert isinstance(draft, dict)
    return {"title": str(draft["title"]), "body": str(draft["body"])}


def _shown(figure: Locator) -> tuple[str, str]:
    """Title and body as „Maks dostanie” shows them."""

    lines = figure.locator("p")
    return lines.nth(0).inner_text(), lines.nth(1).inner_text()


def _shows(run: Run, figure: Locator, draft: dict[str, str], message: str) -> None:
    run.wait_for(lambda: _shown(figure) == (draft["title"], draft["body"]), message)


def _queued(config: Path) -> list[dict[str, object]]:
    return [json.loads(path.read_text(encoding="utf-8")) for path in sorted((config / "zgloszenia" / "kolejka").glob(f"*-{LABEL}-*.json"))]


def _notes(config: Path) -> list[dict[str, object]]:
    path = config / "uwagi-taty.json"
    return json.loads(path.read_text(encoding="utf-8"))["uwagi"] if path.exists() else []


def _issues(box: Path) -> list[dict[str, object]]:
    """Uwagi taty in the skrzynka by number; Kontrole ilości and Zgłoszenia of earlier features take numbers too."""

    issues = [json.loads(path.read_text(encoding="utf-8")) for path in box.glob("*.json")]
    return sorted((issue for issue in issues if issue["labels"] == [LABEL]), key=lambda issue: int(str(issue["number"])))


def _log(run: Run) -> str:
    path = run.root / "logs" / "centrum-rozliczen.log"
    return path.read_text(encoding="utf-8") if path.exists() else ""


def _open(page: Page) -> Locator:
    page.get_by_role("button", name=WRITE, exact=True).click()
    dialog = page.get_by_role("dialog", name=WRITE, exact=True)
    expect(dialog).to_be_visible()
    return dialog


def _close(dialog: Locator) -> None:
    """„Zamknij” under the answer; the dialog's corner button of the same name comes after it."""

    dialog.get_by_role("button", name="Zamknij", exact=True).first.click()
    expect(dialog).to_have_count(0)


def _write(dialog: Locator, title: str, body: str) -> None:
    dialog.get_by_role("textbox", name="Tytuł", exact=True).fill(title)
    dialog.get_by_role("textbox", name="Treść (niekonieczna)", exact=True).fill(body)


def drive_dad_note(run: Run, page: Page) -> None:
    config = Path(run.fixture["settings"]).parent
    key_file = config / "zgloszenia-klucz.txt"
    box = run.root / "skrzynka-zgloszen"
    pacing = run.root / "pacing" / "skrzynka-ms.txt"
    key_file.unlink(missing_ok=True)
    notes_before = len(_notes(config))
    issues_before = len(_issues(box))
    run.check(_queued(config) == [], "the skrzynka queue is empty before the first Uwaga")

    run.step(FEATURE, "uwaga-ikona")
    for page_id, heading in PAGES.items():
        page.goto(run.url + f"#/{page_id}")
        expect(page.get_by_role("heading", name=heading, exact=True)).to_be_visible()
        write = page.get_by_role("button", name=WRITE, exact=True)
        theme = page.get_by_role("button", name="Włącz motyw", exact=False)
        expect(write).to_be_visible()
        write_box, theme_box = write.bounding_box(), theme.bounding_box()
        run.check(
            write_box is not None and theme_box is not None and write_box["x"] < theme_box["x"],
            f"{heading}: the header has „{WRITE}” left of the theme toggle",
        )
    page.get_by_role("button", name=WRITE, exact=True).hover()
    expect(page.get_by_text(WRITE, exact=True)).to_be_visible()
    run.capture(page, "160-uwaga-ikona-w-naglowku")
    header = page.locator("header").first.bounding_box()
    assert header is not None
    page.screenshot(
        path=run.evidence / "screenshots" / "160b-uwaga-ikona-zblizenie.png",
        clip={"x": header["x"] + header["width"] - 360, "y": header["y"], "width": 360, "height": header["height"] + 40},
    )

    run.step(FEATURE, "uwaga-puste-okno")
    dialog = _open(page)
    figure = dialog.get_by_role("figure", name="Co dostanie Maks", exact=True)
    title_box = dialog.get_by_role("textbox", name="Tytuł", exact=True)
    body_box = dialog.get_by_role("textbox", name="Treść (niekonieczna)", exact=True)
    send = dialog.get_by_role("button", name="Wyślij", exact=True)
    expect(title_box).to_be_focused()
    run.check(
        (title_box.get_attribute("maxlength"), body_box.get_attribute("maxlength")) == ("120", "10000"),
        "the fields take their limits from the contract (Tytuł 120, Treść 10000)",
    )
    expect(send).to_be_disabled()
    empty = _draft(run, "", "", "uwaga-szkic-pusty")
    run.wait_for(lambda: _shown(figure)[1] == empty["body"], "„Maks dostanie” shows the server's draft of an empty Uwaga")
    run.check(_shown(figure)[0] == "Tytuł" and empty["title"] == "", "with no Tytuł the figure shows the placeholder")
    _write(dialog, "   ", "")
    expect(send).to_be_disabled()
    title_box.fill("")
    run.capture(page, "161-uwaga-puste-okno")

    run.step(FEATURE, "uwaga-bez-klucza")
    _write(dialog, *FIRST)
    first = _draft(run, *FIRST, "uwaga-szkic-pierwsza")
    _shows(run, figure, first, "„Maks dostanie” shows exactly the server's draft of the typed Uwaga")
    run.check(first["title"] == FIRST[0] and first["body"].startswith(FIRST[1] + "\n\n"), "the draft holds Dad's text")
    expect(send).to_be_enabled()
    run.capture(page, "162-uwaga-wypelniona")
    send.click()
    expect(dialog.get_by_role("status")).to_have_text(WAITING)
    expect(page.get_by_role("alert")).to_have_count(0)
    expect(error_toasts(page)).to_have_count(0)
    run.capture(page, "163-uwaga-czeka-na-internet")
    [waiting] = _queued(config)
    run.check(
        waiting["target"] == {"kind": "new_issue", "label": LABEL, "title": first["title"]}
        and waiting["parts"] == [first["body"]],
        "one queue file labelled uwaga-taty holds the issue the figure showed",
    )
    notes = _notes(config)
    run.check(
        len(notes) == notes_before + 1 and notes[-1]["title"] == first["title"] and notes[-1]["number"] is None,
        "config/uwagi-taty.json keeps the Uwaga's title without an issue number",
    )
    run.check(
        f"skrzynka-czeka etykieta={LABEL} okres=bez-okresu przyczyna=brak-klucza" in _log(run),
        "without a key the Centrum log says the Uwaga waits",
    )
    run.check(len(_issues(box)) == issues_before, "nothing reached the skrzynka")
    _close(dialog)

    run.step(FEATURE, "uwaga-wyslana")
    print("  harness: Maks writes the key; the skrzynka answers each issue after a pause", flush=True)
    key_file.write_text(KEY + "\n", encoding="utf-8")
    pacing.parent.mkdir(exist_ok=True)
    pacing.write_text(str(BOX_PACING_MS), encoding="utf-8")
    try:
        dialog = _open(page)
        figure = dialog.get_by_role("figure", name="Co dostanie Maks", exact=True)
        title_box = dialog.get_by_role("textbox", name="Tytuł", exact=True)
        body_box = dialog.get_by_role("textbox", name="Treść (niekonieczna)", exact=True)
        send = dialog.get_by_role("button", name="Wyślij", exact=True)
        run.check(
            (title_box.input_value(), body_box.input_value()) == ("", ""), "a new opening starts an empty Uwaga"
        )
        _write(dialog, *SECOND)
        second = _draft(run, *SECOND, "uwaga-szkic-druga")
        _shows(run, figure, second, "„Maks dostanie” shows the server's draft of an Uwaga without Treść")
        send.click()
        expect(dialog.get_by_role("button", name="Trwa Wyślij", exact=True)).to_be_disabled()
        run.capture(page, "164-uwaga-wysylanie", live=True)
        expect(dialog.get_by_role("status")).to_have_text(SENT, timeout=15_000)
    finally:
        pacing.unlink(missing_ok=True)
    run.capture(page, "165-uwaga-wyslana")
    issues = _issues(box)
    (run.evidence / "api" / "uwaga-skrzynka.json").write_text(
        json.dumps(
            [{key: issue[key] for key in ("number", "title", "body", "labels")} for issue in issues[issues_before:]],
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    run.check(
        [(issue["title"], issue["body"]) for issue in issues[issues_before:]]
        == [(first["title"], first["body"]), (second["title"], second["body"])],
        "the skrzynka has both Uwagi as uwaga-taty issues, each exactly as its figure showed it",
    )
    run.wait_for(lambda: _queued(config) == [], "the waiting Uwaga left the queue in the same pass")
    notes = _notes(config)
    run.check(
        [note["number"] for note in notes[notes_before:]] == [issue["number"] for issue in issues[issues_before:]],
        "config/uwagi-taty.json has both issue numbers",
    )
    log = _log(run)
    run.check(
        all(text not in log for text in (KEY, FIRST[0], FIRST[1].splitlines()[0], SECOND[0])),
        "the Centrum log has neither the key nor the text of an Uwaga",
    )
    run.check(KEY not in page.content(), "the key never reaches the browser")
    _close(dialog)
    key_file.unlink()

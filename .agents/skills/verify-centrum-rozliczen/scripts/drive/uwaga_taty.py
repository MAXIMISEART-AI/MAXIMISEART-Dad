"""Drive features/uwaga-taty.md."""

from __future__ import annotations

from datetime import datetime
import json
from pathlib import Path
import re
from typing import Any
import urllib.parse
import urllib.request

from playwright.sync_api import Locator, Page, expect

from drive.common import PAGES, Run, current_run, ensure_files_set, error_toasts, finished_result, history_rows
from drive.metryki import _local

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
ABOUT_RUN = "Napisz do Maksa o tym Uruchomieniu"
# Synthetic Uwaga pinned to the preview.
PINNED = ("Podgląd każe sprawdzić okres", "Nie wiem, którego Wykonawcę mam dopisać.")
LOGS_LABEL = "logi-uruchomienia"
LOGS_LINE = re.compile(r"^Logi Uruchomienia: (.*)$", re.MULTILINE)
MODES = {"DRY-RUN": "podgląd", "RUN": "zapis"}
NO_RUNS = "Nie ma jeszcze Uruchomień z Centrum."


def _draft(run: Run, title: str, body: str, name: str, run_id: str | None = None) -> dict[str, str]:
    """The issue Maks would get, straight from the server, as the reference for the figure in the tab."""

    note = {"title": title, "body": body} | ({} if run_id is None else {"run_id": run_id})
    request = urllib.request.Request(
        run.url.rstrip("/") + "/api/dad-notes/draft",
        data=json.dumps(note).encode(),
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
    expect(_scope(dialog, "Ogólna")).to_have_attribute("aria-pressed", "true")
    expect(dialog.get_by_role("radiogroup", name="Uruchomienie", exact=True)).to_have_count(0)
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
    _scope(dialog, "Do Uruchomienia").click()
    if _note_runs(run, None, "uwaga-uruchomienia-z-naglowka"):
        expect(dialog.get_by_role("radiogroup", name="Uruchomienie", exact=True).get_by_role("radio", checked=True)).to_have_count(0)
    else:
        expect(dialog.get_by_text(NO_RUNS, exact=True)).to_be_visible()
    expect(send).to_be_disabled()
    run.check(True, "„Do Uruchomienia” without a checked Uruchomienie keeps Wyślij disabled (no Uruchomienia: the calm sentence)")
    run.capture(page, "162b-uwaga-bez-wybranego-uruchomienia", full_page=False)
    _scope(dialog, "Ogólna").click()
    _shows(run, figure, first, "back to Ogólna the figure shows the general draft again")
    expect(send).to_be_enabled()
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
    try:
        _drive_pinned(run, page, config, box)
    finally:
        key_file.unlink()


def _note_runs(run: Run, selected: str | None, name: str) -> list[dict[str, Any]]:
    """The Uruchomienia the dialog offers, straight from the server, as the reference for its list."""

    query = urllib.parse.urlencode({} if selected is None else {"selected": selected})
    with urllib.request.urlopen(run.url.rstrip("/") + f"/api/dad-notes/runs?{query}", timeout=10) as response:
        runs = json.load(response)
    (run.evidence / "api" / f"{name}.json").write_text(
        json.dumps(runs, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    assert isinstance(runs, list)
    return runs


def _result_word(entry: dict[str, Any]) -> str:
    if entry["result"] == "BLAD_KRYTYCZNY":
        return "Błąd" if entry["stop_kind"] == "for_maks" else "Zatrzymano"
    return {"OK": "OK", "WYMAGA_SPRAWDZENIA": "Do sprawdzenia"}[entry["result"]]


def _offers(run: Run, choices: Locator, offered: list[dict[str, Any]], checked: str) -> None:
    """The radio list shows the server's Uruchomienia in its order with ``checked`` checked."""

    rows = choices.locator("label")
    run.wait_for(lambda: rows.count() == len(offered), f"the list shows the server's {len(offered)} Uruchomienia")
    texts = [row.inner_text() for row in rows.all()]
    run.check(
        all(
            entry["process_label"] in text
            and f"{entry['period']} · {MODES[entry['mode']]} · {_local(entry['started_at'])}" in text
            and _result_word(entry) in text
            for entry, text in zip(offered, texts, strict=True)
        ),
        "each row shows process, period, podgląd or zapis, date and result, newest first",
    )
    states = [radio.get_attribute("aria-checked") for radio in choices.get_by_role("radio").all()]
    run.check(
        states == ["true" if entry["run_id"] == checked else "false" for entry in offered],
        f"exactly the Uruchomienie {checked} is checked",
    )


def _logs_comment(box: Path, run_id: str) -> str | None:
    """Address of the first comment of this Uruchomienie's Logi in the file skrzynka, as the skrzynka gave it."""

    for path in sorted(box.glob("*.json")):
        thread = json.loads(path.read_text(encoding="utf-8"))
        if thread["labels"] == [LOGS_LABEL]:
            for index, comment in enumerate(thread.get("comments", []), start=1):
                if f"- Uruchomienie: {run_id}," in comment:
                    return f"{path.as_uri()}#komentarz-{index}"
    return None


def _scope(dialog: Locator, option: str) -> Locator:
    return dialog.get_by_role("group", name="Dotyczy", exact=True).get_by_role("button", name=option, exact=True)


def _opened_about(run: Run, page: Page, run_id: str, name: str) -> tuple[Locator, list[dict[str, Any]]]:
    """A dialog opened from an Uruchomienie: a new Uwaga, „Do Uruchomienia” chosen and that Uruchomienie checked."""

    dialog = page.get_by_role("dialog", name=WRITE, exact=True)
    expect(dialog).to_be_visible()
    run.check(dialog.get_by_role("textbox", name="Tytuł", exact=True).input_value() == "", "a new, empty Uwaga")
    expect(_scope(dialog, "Do Uruchomienia")).to_have_attribute("aria-pressed", "true")
    offered = _note_runs(run, run_id, name)
    run.check(run_id in [entry["run_id"] for entry in offered], "the server offers the Uruchomienie it was opened from")
    _offers(run, dialog.get_by_role("radiogroup", name="Uruchomienie", exact=True), offered, run_id)
    box, viewport = dialog.bounding_box(), page.viewport_size
    run.check(
        box is not None and viewport is not None and box["y"] >= 0 and box["y"] + box["height"] <= viewport["height"],
        "the whole dialog fits the window; a long list scrolls inside it",
    )
    return dialog, offered


def _theme(page: Page, name: str) -> bool:
    """Clicks the header's ``Włącz motyw <name>`` when it is there; ``True`` when the theme changed."""

    toggle = page.locator("header").get_by_role("button", name=f"Włącz motyw {name}", exact=True)
    if toggle.count() == 0:
        return False
    toggle.click()
    expect(toggle).to_have_count(0)
    return True


def _drive_pinned(run: Run, page: Page, config: Path, box: Path) -> None:
    period = run.fixture["settlement"]["needs_check"]

    run.step(FEATURE, "uwaga-przycisk-na-karcie")
    page.goto(run.url)
    ensure_files_set(run, page)
    was_dark = _theme(page, "jasny")
    page.goto(run.url + "#/uruchomienia")
    if current_run(run, "uwaga-przed-podgladem")["state"] == "finished":
        page.get_by_role("button", name="Nowe Uruchomienie procesu", exact=True).click()
    page.get_by_role("radio", name="Przebieg rozliczeń").click()
    expect(page.get_by_role("combobox", name="Okres")).to_contain_text(period)
    page.get_by_role("button", name="Podgląd bez zapisu", exact=True).click()
    expect(page.get_by_label("Wynik")).to_contain_text("Podgląd wymaga sprawdzenia · nic nie zapisano")
    finished_result(run, "uwaga-podglad")
    view = json.loads((run.evidence / "api" / "uwaga-podglad.json").read_text(encoding="utf-8"))
    run_id = str(view["run"]["id"])
    card = page.get_by_role("region", name="Podgląd na żywo")
    about = card.get_by_role("button", name=ABOUT_RUN, exact=True)
    expect(about).to_have_count(1)
    about_box = about.bounding_box()
    new_box = card.get_by_role("button", name="Nowe Uruchomienie procesu", exact=True).bounding_box()
    run.check(
        about_box is not None and new_box is not None and new_box["x"] < about_box["x"],
        f"the finished card has „{ABOUT_RUN}” right of „Nowe Uruchomienie procesu”",
    )
    about.hover()
    expect(page.get_by_text(ABOUT_RUN, exact=True)).to_be_visible()
    run.wait_for(
        lambda: _logs_comment(box, run_id) is not None,
        "with the key the preview's Logi reached the skrzynka at the end of the Uruchomienie",
        timeout_s=60,
    )
    run.capture(page, "166-uwaga-przycisk-na-karcie")

    run.step(FEATURE, "uwaga-z-karty")
    about.click()
    dialog, offered = _opened_about(run, page, run_id, "uwaga-uruchomienia-z-karty")
    figure = dialog.get_by_role("figure", name="Co dostanie Maks", exact=True)
    send = dialog.get_by_role("button", name="Wyślij", exact=True)
    expect(send).to_be_disabled()
    run.capture(page, "167-uwaga-z-karty", full_page=False)

    run.step(FEATURE, "uwaga-przypieta")
    _write(dialog, *PINNED)
    pinned = _draft(run, *PINNED, "uwaga-szkic-przypieta", run_id=run_id)
    _shows(run, figure, pinned, "„Maks dostanie” shows exactly the server's draft of the Uwaga pinned to the preview")
    [entry] = [entry for entry in offered if entry["run_id"] == run_id]
    run.check(
        f"Uruchomienie: {entry['process_label']} · {period} · podgląd · do sprawdzenia · {_local(entry['started_at'])}"
        f" · wersja narzędzia " in pinned["body"],
        "the pinned Uwaga carries process, period, mode, result and date of the preview",
    )
    logs = _logs_comment(box, run_id)
    run.check(
        LOGS_LINE.findall(pinned["body"]) == [logs],
        "the pinned Uwaga leads to the first comment of the preview's Logi in the skrzynka",
    )
    expect(send).to_be_enabled()
    run.capture(page, "168-uwaga-przypieta", full_page=False)

    run.step(FEATURE, "uwaga-ogolna-i-z-powrotem")
    _scope(dialog, "Ogólna").click()
    expect(dialog.get_by_role("radiogroup", name="Uruchomienie", exact=True)).to_have_count(0)
    general = _draft(run, *PINNED, "uwaga-szkic-ogolna-z-karty")
    _shows(run, figure, general, "with Ogólna the figure shows the server's draft without the Uruchomienie")
    run.check(
        general["body"].splitlines()[-1].startswith("Uwaga ogólna · wersja narzędzia")
        and LOGS_LINE.search(general["body"]) is None,
        "the general Uwaga ends with the general footer and has no Logi",
    )
    run.capture(page, "169-uwaga-ogolna-z-karty", full_page=False)
    _scope(dialog, "Do Uruchomienia").click()
    _offers(run, dialog.get_by_role("radiogroup", name="Uruchomienie", exact=True), offered, run_id)
    _shows(run, figure, pinned, "back to Do Uruchomienia the same Uruchomienie is checked and the figure pinned again")

    run.step(FEATURE, "uwaga-przypieta-wyslana")
    issues_before = len(_issues(box))
    send.click()
    expect(dialog.get_by_role("status")).to_have_text(SENT, timeout=15_000)
    expect(error_toasts(page)).to_have_count(0)
    new = _issues(box)[issues_before:]
    (run.evidence / "api" / "uwaga-przypieta-skrzynka.json").write_text(
        json.dumps(
            [{key: issue[key] for key in ("number", "title", "body", "labels")} for issue in new],
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    run.check(
        [(issue["title"], issue["body"]) for issue in new] == [(pinned["title"], pinned["body"])],
        "the skrzynka has the pinned Uwaga as one uwaga-taty issue, exactly as its figure showed it",
    )
    run.check(
        LOGS_LINE.findall(str(new[0]["body"])) == [logs],
        "its line Logi Uruchomienia is the address of the first comment of the preview's Logi",
    )
    note = _notes(config)[-1]
    run.check(
        (note["title"], note["number"], note["run_id"]) == (pinned["title"], new[0]["number"], run_id),
        "config/uwagi-taty.json keeps the issue number and the Uruchomienie of the pinned Uwaga",
    )
    _close(dialog)

    run.step(FEATURE, "uwaga-z-historii")
    page.get_by_role("tab", name="Historia", exact=True).click()
    history = page.get_by_role("table", name="Historia Uruchomień procesu")
    expect(history).to_be_visible()
    older = page.get_by_role("button", name="Pokaż starsze", exact=True)
    while older.count() > 0:
        older.click()
    metrics = run.api("/api/metrics", "uwaga-historia")["runs"]
    assert isinstance(metrics, list)
    shown = sorted(metrics, key=lambda entry: datetime.fromisoformat(entry["started_at"]), reverse=True)
    rows = history_rows(page)
    expect(rows).to_have_count(1 + len(shown))
    buttons = [rows.nth(index).get_by_role("button", name=ABOUT_RUN, exact=True).count() for index in range(1, len(shown) + 1)]
    run.check(
        buttons == [0 if entry["run_id"] is None else 1 for entry in shown] and 0 in buttons and 1 in buttons,
        f"only the {buttons.count(1)} rows of Uruchomienia from Centrum with a run id have „{ABOUT_RUN}”",
    )
    oldest = max(index for index, entry in enumerate(shown) if entry["run_id"] is not None)
    target = str(shown[oldest]["run_id"])
    about = rows.nth(oldest + 1).get_by_role("button", name=ABOUT_RUN, exact=True)
    about.hover()
    expect(page.get_by_text(ABOUT_RUN, exact=True)).to_be_visible()
    run.capture(page, "170-uwaga-historia")
    about.click()
    dialog, _ = _opened_about(run, page, target, "uwaga-uruchomienia-z-historii")
    run.capture(page, "171-uwaga-z-historii", full_page=False)
    page.keyboard.press("Escape")
    expect(dialog).to_have_count(0)
    if was_dark:
        _theme(page, "ciemny")

"""Drive features/zgloszenie.md."""

from __future__ import annotations

import json
from pathlib import Path

from playwright.sync_api import Locator, Page, expect

from drive.common import ROW_MARKER, Run, current_run, ensure_files_set, finished_result, stop_banner

FEATURE = "zgloszenie"
# The period of features/diagnoza.md: no Folder okresu and no orders, so no Uruchomienie here writes a file.
PERIOD = "08_14_09_2026"
TEMPLATE_MISSING = "Nie znaleziono wzorca, z którego powstają pliki okresu."
NOT_FOUND = "Nie znalazłem przyczyny na tym komputerze."
TITLE = f"BRAK_WZORCA: {TEMPLATE_MISSING} Nie utworzono żadnego pliku."
NO_KEY = "Nie wysłano Zgłoszenia: na tym komputerze nie ma klucza do Zgłoszeń."
SENT = "Zgłoszenie wysłane do Maksa. Poczekaj na naprawę."
WAITING = "Zgłoszenie tego problemu już jest wysłane i czeka na naprawę."
# Synthetic key Maks would write; it must never reach the skrzynka, the log, an answer, or the browser.
KEY = "github_pat_VERIFY_SYNTETYCZNY_KLUCZ"
UNSENT = f"Zgłoszenie BRAK_WZORCA {PERIOD}.md"


def _stop_for_maks(run: Run, page: Page, name: str, missing: str = "internal_template") -> str:
    """A stop „do Maksa” whose cause is gone again: the Wzorzec ``missing`` was missing during the run.

    Another Wzorzec gives the same code with other three parts, so another problem.
    """

    configuration = run.fixture["configuration"]
    assert isinstance(configuration, dict)
    template = Path(configuration[missing])
    aside = template.with_name(f"{template.name}.odlozony")
    page.goto(run.url + "#/uruchomienia")
    page.reload()
    if current_run(run, f"{name}-przed")["state"] == "finished":
        page.get_by_role("button", name="Nowe Uruchomienie procesu").click()
    page.get_by_role("radio", name="Przygotowanie pliku zbiorczego").click()
    page.get_by_role("combobox", name="Okres").click()
    page.get_by_role("option", name=f"{PERIOD} · Brak plików okresu", exact=True).click()
    template.rename(aside)
    try:
        page.get_by_role("button", name="Podgląd bez zapisu", exact=True).click()
        expect(stop_banner(page)).to_contain_text(TEMPLATE_MISSING)
        result = finished_result(run, name)
    finally:
        aside.rename(template)
    run.check(result["stop_kind"] == "for_maks", "the stop without its Wzorzec is „do Maksa”")
    view = current_run(run, name)["run"]
    assert isinstance(view, dict)
    return str(view["id"])


def _report_state(run: Run, name: str) -> object:
    return finished_result(run, name)["report"]


def _issues(box: Path) -> list[dict[str, object]]:
    """Zgłoszenia in the skrzynka by number; a Kontrola ilości from features/kontrola-ilosci.md takes numbers too."""

    issues = [json.loads(path.read_text(encoding="utf-8")) for path in box.glob("*.json")]
    return sorted((issue for issue in issues if issue["labels"] == ["zgloszenie"]), key=lambda issue: int(str(issue["number"])))


def _shown_report(page: Page) -> tuple[str, str]:
    """The Zgłoszenie as the tab shows it under „Co zostanie wysłane”: title and Markdown body."""

    shown: Locator = page.get_by_role("figure", name="Treść Zgłoszenia")
    return shown.locator("figcaption").inner_text(), shown.locator("pre").inner_text()


def drive_report(run: Run, page: Page) -> None:
    config = Path(run.fixture["settings"]).parent
    key_file = config / "zgloszenia-klucz.txt"
    unsent = config / "zgloszenia" / UNSENT
    box = run.root / "skrzynka-zgloszen"
    diagnosis = page.get_by_role("region", name="Diagnoza")
    key_file.unlink(missing_ok=True)

    run.step(FEATURE, "zgloszenie-podglad")
    page.goto(run.url)
    ensure_files_set(run, page)
    _stop_for_maks(run, page, "zgloszenie-podglad")
    run.check(_report_state(run, "zgloszenie-podglad") == {"state": "ready"}, "the stop offers a Zgłoszenie not sent yet")
    page.reload()
    stop_banner(page).get_by_role("button", name="Diagnoza", exact=True).click()
    expect(diagnosis.get_by_label("Wyjaśnienie Diagnozy")).to_contain_text(NOT_FOUND)
    send = diagnosis.get_by_role("button", name="Wyślij do Maksa", exact=True)
    expect(send).to_be_visible()
    diagnosis.get_by_role("button", name="Co zostanie wysłane", exact=True).click()
    title, body = _shown_report(page)
    run.check(title == TITLE, "the Zgłoszenie title is the code and „Co się stało”")
    lines = body.splitlines()
    run.check(
        all(line in lines for line in ("- Kod: BRAK_WZORCA", f"- Okres: {PERIOD}", "- Tryb: DRY-RUN")),
        "the preview holds the Komunikat code, the period, and the mode",
    )
    run.check(
        any(line.startswith("| Aktualność narzędzia |") for line in lines)
        and any(line.startswith("- Commit: ") for line in lines),
        "the preview holds the tool commit and every check of the Diagnoza",
    )
    run.check(
        ROW_MARKER not in body and str(run.root) not in body and run.root.as_posix() not in body,
        "the preview holds no workbook row and no full path",
    )
    run.capture(page, "60-zgloszenie-podglad")

    run.step(FEATURE, "zgloszenie-bez-klucza")
    send.click()
    saved = diagnosis.get_by_label("Ostrzeżenie")
    expect(saved).to_contain_text(NO_KEY)
    expect(saved).to_contain_text(f"plik {UNSENT}, folder zgloszenia")
    expect(saved.get_by_role("button", name="Spróbuj ponownie", exact=True)).to_be_visible()
    run.check(unsent.read_text(encoding="utf-8") == f"# {title}\n\n{body}", "the unsent Zgłoszenie is the preview, in a file")
    run.check(_issues(box) == [], "without a key nothing reaches the skrzynka Zgłoszeń")
    state = _report_state(run, "zgloszenie-bez-klucza")
    run.check(isinstance(state, dict) and state["state"] == "saved", "the server keeps the saved state in the result")
    run.capture(page, "61-zgloszenie-bez-klucza")

    run.step(FEATURE, "zgloszenie-konfiguracja")
    page.get_by_role("link", name="Konfiguracja", exact=True).click()
    expect(page.get_by_text("Zgłoszenia: brak klucza", exact=True)).to_be_visible()
    run.capture(page, "62-zgloszenie-konfiguracja-brak-klucza")
    print("  harness: Maks writes the key to config/zgloszenia-klucz.txt", flush=True)
    key_file.write_text(KEY + "\n", encoding="utf-8")
    page.reload()
    expect(page.get_by_text("Zgłoszenia: gotowe", exact=True)).to_be_visible()
    configuration = run.api("/api/configuration", "zgloszenie-konfiguracja")
    run.check(configuration["reports"] == "ready", "Konfiguracja reports the key as ready")
    run.check(KEY not in json.dumps(configuration) and KEY not in page.content(), "the key value never reaches the browser")
    run.capture(page, "63-zgloszenie-konfiguracja-gotowe")

    run.step(FEATURE, "zgloszenie-wyslane")
    page.get_by_role("link", name="Uruchomienia", exact=True).click()
    retry = page.get_by_label("Ostrzeżenie").get_by_role("button", name="Spróbuj ponownie", exact=True)
    retry.click()
    expect(page.get_by_role("status").filter(has_text=SENT)).to_be_visible()
    expect(page.get_by_role("button", name="Spróbuj ponownie", exact=True)).to_have_count(0)
    [issue] = _issues(box)
    number = issue["number"]
    (run.evidence / "api" / "zgloszenie-skrzynka.json").write_text(
        json.dumps(issue, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    run.check(
        (issue["title"], issue["body"], issue["labels"]) == (title, body, ["zgloszenie"]),
        "the skrzynka got exactly the preview, labelled zgloszenie",
    )
    run.check(not unsent.exists(), "the sent Zgłoszenie no longer waits in a file")
    sent = json.loads((config / "zgloszenia-wyslane.json").read_text(encoding="utf-8"))
    run.check(
        [entry["number"] for entry in sent] == [number] and f"- Odcisk problemu: {sent[0]['fingerprint']}" in body.splitlines(),
        "the local sent state keeps the fingerprint and the issue number",
    )
    log = (run.root / "logs" / "centrum-rozliczen.log").read_text(encoding="utf-8")
    run.check(f"zgloszenie-wyslane proces=preparation okres={PERIOD} numer={number}" in log, "the Centrum log records the sending")
    run.check(KEY not in log and KEY not in json.dumps(issue), "the key is neither in the log nor in the Zgłoszenie")
    run.capture(page, "64-zgloszenie-wyslane")

    run.step(FEATURE, "zgloszenie-po-odswiezeniu")
    page.reload()
    expect(page.get_by_role("status").filter(has_text=SENT)).to_be_visible()
    run.check(_report_state(run, "zgloszenie-po-odswiezeniu") == {"state": "sent"}, "the confirmation survives a reload")
    run.capture(page, "65-zgloszenie-po-odswiezeniu")

    run.step(FEATURE, "zgloszenie-kolejne-uruchomienie")
    _stop_for_maks(run, page, "zgloszenie-kolejne-uruchomienie")
    expect(page.get_by_role("status").filter(has_text=WAITING)).to_be_visible()
    run.check(
        _report_state(run, "zgloszenie-kolejne-uruchomienie") == {"state": "waiting"},
        "the same problem in a new Uruchomienie shows it is already sent and waits for the fix",
    )
    stop_banner(page).get_by_role("button", name="Diagnoza", exact=True).click()
    expect(diagnosis.get_by_label("Wyjaśnienie Diagnozy")).to_contain_text(NOT_FOUND)
    expect(diagnosis.get_by_role("status").filter(has_text=WAITING)).to_be_visible()
    expect(page.get_by_role("button", name="Wyślij do Maksa", exact=True)).to_have_count(0)
    run.check(len(_issues(box)) == 1, "no second Zgłoszenie of the same problem")
    run.capture(page, "66-zgloszenie-kolejne-uruchomienie")
    _one_open_report(run, page, box, config)
    key_file.unlink()


def _one_open_report(run: Run, page: Page, box: Path, config: Path) -> None:
    """Maks closes the Zgłoszenie, the problem returns: a new Zgłoszenie links the previous one."""

    diagnosis = page.get_by_role("region", name="Diagnoza")

    run.step(FEATURE, "zgloszenie-zamkniete")
    [first] = _issues(box)
    number = first["number"]
    print(f"  harness: Maks closes Zgłoszenie {number} in the skrzynka Zgłoszeń", flush=True)
    closed = box / f"{number}.json"
    closed.write_text(json.dumps({**json.loads(closed.read_text(encoding="utf-8")), "state": "closed"}), encoding="utf-8")
    _stop_for_maks(run, page, "zgloszenie-zamkniete")
    expect(page.get_by_role("status").filter(has_text=WAITING)).to_be_visible()
    run.capture(page, "68-zgloszenie-zamkniete-przed-diagnoza")
    stop_banner(page).get_by_role("button", name="Diagnoza", exact=True).click()
    send = diagnosis.get_by_role("button", name="Wyślij do Maksa", exact=True)
    expect(send).to_be_visible()
    expect(page.get_by_role("status").filter(has_text=WAITING)).to_have_count(0)
    run.check(
        _report_state(run, "zgloszenie-zamkniete") == {"state": "ready"},
        "after the Diagnoza asked the skrzynka, the closed Zgłoszenie lets Dad send again",
    )
    diagnosis.get_by_role("button", name="Co zostanie wysłane", exact=True).click()
    title, body = _shown_report(page)
    run.check(f"- Poprzednie Zgłoszenie: #{number}" in body.splitlines(), "the new Zgłoszenie links the previous one")
    run.capture(page, "69-zgloszenie-zamkniete-po-diagnozie")

    run.step(FEATURE, "zgloszenie-nowe-z-odnosnikiem")
    send.click()
    expect(page.get_by_role("status").filter(has_text=SENT)).to_be_visible()
    issues = _issues(box)
    (run.evidence / "api" / "zgloszenie-skrzynka-nowe.json").write_text(
        json.dumps(issues, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    run.check(
        [(issue["number"], issue["state"]) for issue in issues] == [(number, "closed"), (issues[-1]["number"], "open")]
        and (issues[1]["title"], issues[1]["body"]) == (title, body),
        "the skrzynka got exactly the new preview as a second Zgłoszenie next to the closed one",
    )
    sent = json.loads((config / "zgloszenia-wyslane.json").read_text(encoding="utf-8"))
    run.check(
        [entry["number"] for entry in sent] == [issue["number"] for issue in issues],
        "the local sent state keeps both Zgłoszenia",
    )
    run.capture(page, "70-zgloszenie-nowe-z-odnosnikiem")

    run.step(FEATURE, "zgloszenie-inny-problem")
    _stop_for_maks(run, page, "zgloszenie-inny-problem", missing="collective_template")
    run.check(
        _report_state(run, "zgloszenie-inny-problem") == {"state": "ready"},
        "another problem (other three parts) is not waiting for the open Zgłoszenie",
    )
    page.reload()
    stop_banner(page).get_by_role("button", name="Diagnoza", exact=True).click()
    expect(diagnosis.get_by_role("button", name="Wyślij do Maksa", exact=True)).to_be_visible()
    run.check(len(_issues(box)) == 2, "asking the skrzynka sends nothing")
    run.capture(page, "71-zgloszenie-inny-problem")

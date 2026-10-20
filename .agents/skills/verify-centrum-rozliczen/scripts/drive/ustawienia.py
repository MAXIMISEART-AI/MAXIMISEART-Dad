"""Drive features/ustawienia.md."""

from __future__ import annotations

from pathlib import Path
from urllib.parse import urlsplit

from playwright.sync_api import Page, Request, expect

from drive.common import Run, choose_periods_directory


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
    choose_periods_directory(run, page)
    run.check(
        run.lines("dialogs.jsonl")[-1]["title"] == "Wybierz folder okresów (np. Załączniki albo INEA)",
        "the folder picker opened with the CLI's title",
    )
    run.check(
        run.remembered("folder_okresow") == run.fixture["periods_directory"],
        "the settings file remembers the folder okresów",
    )
    run.capture(page, "02-ustawienia-folder-okresow")

    run.step(feature, "ustawienia-rejestr-zlecen")
    missing_register = page.get_by_role("alert").filter(has_text="Najpierw wskaż Rejestr zleceń.")
    page.get_by_role("link", name="Uruchomienia", exact=True).click()
    expect(missing_register).to_be_visible()
    run.check(True, "before the Rejestr zleceń is set, Uruchomienia says it is missing for the start")
    page.get_by_role("link", name="Okresy", exact=True).click()
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

    run.step(feature, "ustawienia-braki-do-startu")
    page.get_by_role("link", name="Uruchomienia", exact=True).click()
    expect(page.get_by_text("Nowe Uruchomienie procesu", exact=True)).to_be_visible()
    expect(missing_register).to_have_count(0)
    expect(page.get_by_role("button", name="Podgląd bez zapisu", exact=True)).to_be_enabled()
    processes = run.api("/api/runs/setup", "ustawienia-braki-do-startu")["processes"]
    assert isinstance(processes, list)
    run.check(
        [process["blocker"] for process in processes if process["process"] == "preparation"] == [None],
        "the Rejestr zleceń pointed on Okresy is no longer missing on Uruchomienia: its start is read again",
    )
    run.capture(page, "18-ustawienia-braki-do-startu")

    run.step(feature, "ustawienia-motyw-bez-odczytu")
    setup_reads: list[str] = []

    def count_setup(request: Request) -> None:
        if urlsplit(request.url).path == "/api/runs/setup":
            setup_reads.append(request.method)

    page.on("request", count_setup)
    try:
        for click, then, theme in (
            ("Włącz motyw jasny", "Włącz motyw ciemny", "light"),
            ("Włącz motyw ciemny", "Włącz motyw jasny", "dark"),
        ):
            page.get_by_role("button", name=click, exact=True).click()
            expect(page.get_by_role("button", name=then, exact=True)).to_be_visible()
            run.wait_for(lambda theme=theme: run.remembered("motyw") == theme, f"the settings file remembers {theme}")
        page.wait_for_timeout(400)  # a remount after the server's answer would read the start again by now
    finally:
        page.remove_listener("request", count_setup)
    expect(page.get_by_role("button", name="Podgląd bez zapisu", exact=True)).to_be_enabled()
    run.check(
        setup_reads == [], f"switching the theme on Uruchomienia does not read the start again ({len(setup_reads)} reads)"
    )
    page.get_by_role("link", name="Okresy", exact=True).click()

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

"""Drive features/diagnoza.md."""

from __future__ import annotations

from pathlib import Path

from playwright.sync_api import Page, expect

from drive.common import ROW_MARKER, Run, current_run, diagnosis_answer, ensure_files_set, finished_result, stop_banner

FEATURE = "diagnoza"
# A period without a Folder okresu that no feature prepares; the Rejestr zleceń has no orders in it, so no
# Uruchomienie of this feature writes a file.
PERIOD = "08_14_09_2026"
REGISTER_OPEN = "Rejestr zleceń jest otwarty w Excelu. Nie utworzono żadnego pliku."
NO_ORDERS = "W Rejestrze zleceń nie ma żadnego zlecenia z tego okresu."
TEMPLATE_MISSING = "Nie znaleziono wzorca, z którego powstają pliki okresu."
NOT_FOUND = "Nie znalazłem przyczyny na tym komputerze."
CONFIRMS = "Diagnoza potwierdza ten komunikat."
NOT_CHECKED_UNEXPECTED = "Nie udało się sprawdzić: nieoczekiwany błąd."
# The Centrum log entry of a check that failed itself: the exception type and the check, never its text.
UNEXPECTED_IN_DIAGNOSIS = 'nieoczekiwany-wyjatek typ=RuntimeError miejsce="Diagnoza: Rejestr zleceń"'
UNEXPECTED_CODE = "BLAD_NIEOCZEKIWANY"
NO_KEY = "Nie wysłano Zgłoszenia: na tym komputerze nie ma klucza do Zgłoszeń."
PROPOSAL = "Jest też nowsza wersja narzędzia."
OTHER_MAIN = "e" * 40
CHECKS = (
    "Ustawienia taty",
    "Pliki w OneDrive",
    "Rejestr zleceń",
    "Wzorzec rozliczenia wewnętrznego",
    "Wzorzec pliku zbiorczego",
    "Konfiguracja wykonawców",
    "Folder okresu",
    "Pliki okresu w Excelu",
    "Aktualność narzędzia",
    "Dziennik Centrum rozliczeń",
)


def _snapshot(paths: list[Path]) -> list[tuple[bytes, int]]:
    return [(path.read_bytes(), path.stat().st_mtime_ns) for path in paths]


def drive_diagnosis(run: Run, page: Page) -> None:
    register = Path(run.fixture["order_register"])
    configuration = run.fixture["configuration"]
    assert isinstance(configuration, dict)
    internal_template = Path(configuration["internal_template"])
    untouched = [register, *(Path(configuration[key]) for key in ("internal_template", "collective_template", "worker_config"))]
    before = _snapshot(untouched)
    lock = register.with_name(f"~${register.name}")
    diagnosis = page.get_by_role("region", name="Diagnoza")
    proposal = diagnosis.get_by_role("note", name="Propozycja aktualizacji")
    main_commit = run.root / "github" / "main-commit.txt"

    run.step(FEATURE, "diagnoza-dla-taty")
    page.goto(run.url)
    ensure_files_set(run, page)
    lock.touch()
    page.goto(run.url + "#/uruchomienia")
    page.reload()
    if current_run(run, "diagnoza-przed")["state"] == "finished":
        page.get_by_role("button", name="Nowe Uruchomienie procesu").click()
    page.get_by_role("radio", name="Przygotowanie pliku zbiorczego").click()
    page.get_by_role("combobox", name="Okres").click()
    page.get_by_role("option", name=f"{PERIOD} · Brak plików okresu", exact=True).click()
    page.get_by_role("button", name="Podgląd bez zapisu", exact=True).click()
    expect(stop_banner(page)).to_contain_text(REGISTER_OPEN)
    result = finished_result(run, "diagnoza-dla-taty")
    run.check(result["stop_kind"] == "for_tata", "a stop Dad fixes himself is „dla taty”")
    expect(stop_banner(page).get_by_role("button", name="Uruchom ponownie", exact=True)).to_be_visible()
    expect(page.get_by_role("button", name="Diagnoza", exact=True)).to_have_count(0)
    run.check(True, "the stop offers Uruchom ponownie and no Diagnoza")
    run.capture(page, "50-diagnoza-dla-taty")

    run.step(FEATURE, "diagnoza-powtorka")
    stop_banner(page).get_by_role("button", name="Uruchom ponownie", exact=True).click()
    run.wait_for(
        lambda: finished_result(run, "diagnoza-powtorka").get("stop_kind") == "repeated",
        "the same Komunikat after Uruchom ponownie is a repetition",
    )
    current = run.api("/api/runs/current", "diagnoza-powtorka")
    run_info = current["run"]
    assert isinstance(run_info, dict)
    run.check((run_info["period"], run_info["dry_run"]) == (PERIOD, True), "Uruchom ponownie kept the period and mode")
    expect(stop_banner(page).get_by_role("button", name="Diagnoza", exact=True)).to_be_visible()
    expect(stop_banner(page).get_by_role("button", name="Uruchom ponownie", exact=True)).to_have_count(0)
    run.check(True, "the repeated stop offers Diagnoza instead of Uruchom ponownie")
    run.capture(page, "51-diagnoza-powtorka")

    run.step(FEATURE, "diagnoza-wyjasnienie")
    stop_banner(page).get_by_role("button", name="Diagnoza", exact=True).click()
    expect(diagnosis).to_contain_text(CONFIRMS)
    expect(diagnosis.get_by_label("Wyjaśnienie Diagnozy")).to_have_count(0)
    expect(stop_banner(page).get_by_role("button", name="Uruchom ponownie", exact=True)).to_be_visible()
    expect(proposal).to_have_count(0)
    run.check(True, "the Diagnoza confirms the stop without repeating it and puts Uruchom ponownie on the banner")
    answer = diagnosis_answer(run, str(run_info["id"]), "diagnoza-wyjasnienie")
    explanation = answer["explanation"]
    assert isinstance(explanation, dict)
    run.check(
        explanation["what"] == REGISTER_OPEN and answer["next_action"] == "rerun" and answer["update_proposal"] is False,
        "the Diagnoza explains the cause Dad removes himself and offers Uruchom ponownie first; the tool is up to date",
    )
    run.capture(page, "52-diagnoza-wyjasnienie")

    run.step(FEATURE, "diagnoza-sprawdzono")
    diagnosis.get_by_role("button", name=f"Sprawdzono ({len(CHECKS)})", exact=True).click()
    checks = diagnosis.get_by_role("list", name="Sprawdzono").get_by_role("listitem")
    expect(checks).to_have_count(len(CHECKS))
    for index, label in enumerate(CHECKS):
        expect(checks.nth(index)).to_contain_text(label)
    shown = answer["checks"]
    assert isinstance(shown, list)
    states = {check["label"]: check["state"] for check in shown}
    run.check(
        [check["label"] for check in shown] == list(CHECKS)
        and (states["Pliki w OneDrive"], states["Rejestr zleceń"], states["Aktualność narzędzia"])
        == ("passed", "failed", "passed"),
        "every check is listed in order; the Rejestr zleceń failed",
    )
    run.check(lock.exists() and _snapshot(untouched) == before, "the Diagnoza changed no file and kept the lock file")
    run.capture(page, "53-diagnoza-sprawdzono")

    run.step(FEATURE, "diagnoza-inny-komunikat")
    lock.unlink()
    stop_banner(page).get_by_role("button", name="Uruchom ponownie", exact=True).click()
    expect(stop_banner(page)).to_contain_text(NO_ORDERS)
    result = finished_result(run, "diagnoza-inny-komunikat")
    run.check(result["stop_kind"] == "for_tata", "a different Komunikat after the fix is not a repetition")
    expect(stop_banner(page).get_by_role("button", name="Uruchom ponownie", exact=True)).to_be_visible()
    expect(diagnosis).to_have_count(0)
    run.capture(page, "54-diagnoza-inny-komunikat")

    run.step(FEATURE, "diagnoza-do-maksa")
    aside = internal_template.with_name(f"{internal_template.name}.odlozony")
    internal_template.rename(aside)
    stop_banner(page).get_by_role("button", name="Uruchom ponownie", exact=True).click()
    expect(stop_banner(page)).to_contain_text(TEMPLATE_MISSING)
    result = finished_result(run, "diagnoza-do-maksa")
    run.check(result["stop_kind"] == "for_maks", "a stop that tells Dad to pass it on is „do Maksa”")
    expect(stop_banner(page).get_by_role("button", name="Diagnoza", exact=True)).to_be_visible()
    run.capture(page, "55-diagnoza-do-maksa")
    main_commit.parent.mkdir(exist_ok=True)
    main_commit.write_text(OTHER_MAIN, encoding="utf-8")  # `main` moved on, as it does several times a day
    try:
        stop_banner(page).get_by_role("button", name="Diagnoza", exact=True).click()
        expect(diagnosis).to_contain_text(CONFIRMS)
        expect(proposal).to_have_text(PROPOSAL)
        expect(page.get_by_role("button", name="Uruchom ponownie", exact=True)).to_have_count(0)
        run.check(True, "a cause only Maks removes has no Uruchom ponownie; the newer version is only a quiet proposal")
        current = run.api("/api/runs/current", "diagnoza-do-maksa")
        run_info = current["run"]
        assert isinstance(run_info, dict)
        answer = diagnosis_answer(run, str(run_info["id"]), "diagnoza-do-maksa-wyjasnienie")
        explanation = answer["explanation"]
        assert isinstance(explanation, dict)
        run.check(
            explanation["what"].startswith(TEMPLATE_MISSING)
            and (answer["confirms_stop"], answer["next_action"], answer["update_proposal"]) == (True, "report", True),
            "a newer version does not cover the missing Wzorzec: the Diagnoza explains it and proposes the update",
        )
        run.capture(page, "56-diagnoza-do-maksa-wyjasnienie")
    finally:
        main_commit.unlink()

    run.step(FEATURE, "diagnoza-bez-przyczyny")
    aside.rename(internal_template)
    page.reload()
    stop_banner(page).get_by_role("button", name="Diagnoza", exact=True).click()
    expect(diagnosis.get_by_label("Wyjaśnienie Diagnozy")).to_contain_text(NOT_FOUND)
    expect(diagnosis.get_by_label("Wyjaśnienie Diagnozy")).to_contain_text("Wyślij do Maksa.")
    current = run.api("/api/runs/current", "diagnoza-bez-przyczyny")
    run_info = current["run"]
    assert isinstance(run_info, dict)
    answer = diagnosis_answer(run, str(run_info["id"]), "diagnoza-bez-przyczyny")
    results = answer["checks"]
    assert isinstance(results, list)
    run.check(
        answer["next_action"] == "report" and {check["state"] for check in results} == {"passed"},
        "with every check passing the Diagnoza finds no cause on this computer",
    )
    run.check(_snapshot(untouched) == before, "the Rejestr zleceń, the Wzorce and the konfiguracja wykonawców are unchanged")
    log = (run.root / "logs" / "centrum-rozliczen.log").read_text(encoding="utf-8")
    run.check(
        f"diagnoza proces=preparation okres={PERIOD} przyczyna=NIE_ZNALEZIONO_PRZYCZYNY" in log,
        "the Centrum log records each Diagnoza with its cause code only",
    )
    run.capture(page, "57-diagnoza-bez-przyczyny")

    run.step(FEATURE, "diagnoza-nieoczekiwany-wyjatek")
    fault = run.root / "awaria" / "odczyt-rejestru"
    fault.parent.mkdir(exist_ok=True)
    fault.touch()
    try:
        page.get_by_role("button", name="Nowe Uruchomienie procesu").click()
        page.get_by_role("radio", name="Przygotowanie pliku zbiorczego").click()
        page.get_by_role("combobox", name="Okres").click()
        page.get_by_role("option", name=f"{PERIOD} · Brak plików okresu", exact=True).click()
        page.get_by_role("button", name="Podgląd bez zapisu", exact=True).click()
        # The automatic Diagnoza runs while the fault is still there, so reading the Rejestr zleceń fails in it too.
        expect(diagnosis.get_by_label("Wyjaśnienie Diagnozy")).to_contain_text(NOT_FOUND)
        result = finished_result(run, "diagnoza-nieoczekiwany-wyjatek")
        run.check(
            (result["ending"], result["diagnosis"]) == ("unexpected", "automatic"),
            "a nieoczekiwany wyjątek is „do Maksa” and its Diagnoza starts by itself",
        )
        expect(diagnosis.get_by_role("button", name="Wyślij do Maksa", exact=True)).to_be_visible()
        expect(diagnosis.get_by_role("button", name="Co zostanie wysłane", exact=True)).to_be_visible()
        expect(stop_banner(page).get_by_role("button", name="Diagnoza", exact=True)).to_have_count(0)
        run.check(True, "without a click Dad sees the Diagnoza, Wyślij do Maksa and the preview of the Zgłoszenie")
        diagnosis.get_by_role("button", name=f"Sprawdzono ({len(CHECKS)})", exact=True).click()
        checks = diagnosis.get_by_role("list", name="Sprawdzono").get_by_role("listitem")
        expect(checks).to_have_count(len(CHECKS))
        register_check = checks.nth(CHECKS.index("Rejestr zleceń"))
        expect(register_check).to_contain_text(f"Rejestr zleceń · {NOT_CHECKED_UNEXPECTED}")
        expect(register_check.get_by_label("nie sprawdzono")).to_be_visible()
        run.check(True, "the same failure in the Diagnoza leaves only the Rejestr zleceń unchecked; every check is listed")
        log = (run.root / "logs" / "centrum-rozliczen.log").read_text(encoding="utf-8")
        run.check(
            UNEXPECTED_IN_DIAGNOSIS in log and "synthetic unexpected failure" not in log,
            "the Centrum log names the exception type and the check, never the text of the exception",
        )
        diagnosis.get_by_role("button", name="Co zostanie wysłane", exact=True).click()
        shown = page.get_by_role("figure", name="Treść Zgłoszenia")
        title, body = shown.locator("figcaption").inner_text(), shown.locator("pre").inner_text()
        run.check(
            title.startswith(f"{UNEXPECTED_CODE}: ")
            and UNEXPECTED_IN_DIAGNOSIS in body
            and "synthetic unexpected failure" not in body
            and ROW_MARKER not in body,
            "the Zgłoszenie carries that log entry for Maks, without the exception text or a workbook row",
        )
        run.capture(page, "58-diagnoza-nieoczekiwany-wyjatek")
    finally:
        fault.unlink()

    run.step(FEATURE, "diagnoza-nieoczekiwany-wyjatek-zgloszenie")
    config = Path(run.fixture["settings"]).parent
    (config / "zgloszenia-klucz.txt").unlink(missing_ok=True)  # never there before features/zgloszenie.md
    unsent = config / "zgloszenia" / f"Zgłoszenie {UNEXPECTED_CODE} {PERIOD}.md"
    diagnosis.get_by_role("button", name="Wyślij do Maksa", exact=True).click()
    saved = diagnosis.get_by_label("Ostrzeżenie")
    expect(saved).to_contain_text(NO_KEY)
    expect(saved.get_by_role("button", name="Spróbuj ponownie", exact=True)).to_be_visible()
    run.check(
        unsent.read_text(encoding="utf-8") == f"# {title}\n\n{body}",
        "Wyślij do Maksa works after the nieoczekiwany wyjątek: without a key the preview waits in a file",
    )
    report = finished_result(run, "diagnoza-nieoczekiwany-wyjatek-zgloszenie")["report"]
    run.check(isinstance(report, dict) and report["state"] == "saved", "the server keeps the saved Zgłoszenie in the result")
    run.capture(page, "59-diagnoza-nieoczekiwany-wyjatek-zgloszenie")

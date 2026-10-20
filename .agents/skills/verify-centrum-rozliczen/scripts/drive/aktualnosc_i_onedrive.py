"""Drive features/aktualnosc-i-onedrive.md."""

from __future__ import annotations

from pathlib import Path

from playwright.sync_api import Locator, Page, expect

from drive.common import Run, current_run, diagnosis_answer, ensure_files_set, finished_result, stop_banner

FEATURE = "aktualnosc-i-onedrive"
# The period of features/diagnoza.md: no Folder okresu and no orders, so no Uruchomienie here writes a file.
PERIOD = "08_14_09_2026"
TEMPLATE_MISSING = "Nie znaleziono wzorca, z którego powstają pliki okresu."
NEWER = "Jest nowsza wersja narzędzia."
PROPOSAL = "Jest też nowsza wersja narzędzia."
NOT_FOUND = "Nie znalazłem przyczyny na tym komputerze."
ONLY_IN_CLOUD = "Plik jest tylko w OneDrive w chmurze, bez kopii na tym komputerze."
KEEP_ON_DEVICE = "„Zawsze zachowuj na tym urządzeniu”"
OTHER_MAIN = "f" * 40
FRESHNESS = "Aktualność narzędzia"
ONEDRIVE = "Pliki w OneDrive"


def _stop_without_cause_on_computer(run: Run, page: Page) -> str:
    """A stop „do Maksa” whose cause is gone again: the Wzorzec rozliczenia wewnętrznego was missing during the run."""

    configuration = run.fixture["configuration"]
    assert isinstance(configuration, dict)
    template = Path(configuration["internal_template"])
    aside = template.with_name(f"{template.name}.odlozony")
    page.goto(run.url)
    ensure_files_set(run, page)
    page.goto(run.url + "#/uruchomienia")
    page.reload()
    if current_run(run, "aktualnosc-przed")["state"] == "finished":
        page.get_by_role("button", name="Nowe Uruchomienie procesu").click()
    page.get_by_role("radio", name="Przygotowanie pliku zbiorczego").click()
    page.get_by_role("combobox", name="Okres").click()
    page.get_by_role("option", name=f"{PERIOD} · Brak plików okresu", exact=True).click()
    template.rename(aside)
    try:
        page.get_by_role("button", name="Podgląd bez zapisu", exact=True).click()
        expect(stop_banner(page)).to_contain_text(TEMPLATE_MISSING)
        result = finished_result(run, "aktualnosc-zatrzymanie")
    finally:
        aside.rename(template)
    run.check(result["stop_kind"] == "for_maks", "the stop without its Wzorzec is „do Maksa”")
    view = current_run(run, "aktualnosc-zatrzymanie")["run"]
    assert isinstance(view, dict)
    return str(view["id"])


def _diagnose(page: Page) -> Locator:
    """A fresh Diagnoza of the stop shown on Uruchomienia; a reload drops the previous result."""

    page.reload()
    stop_banner(page).get_by_role("button", name="Diagnoza", exact=True).click()
    explanation = page.get_by_role("region", name="Diagnoza").get_by_label("Wyjaśnienie Diagnozy")
    expect(explanation).to_be_visible()
    return explanation


def _proposal(page: Page) -> Locator:
    return page.get_by_role("region", name="Diagnoza").get_by_role("note", name="Propozycja aktualizacji")


def _state(answer: dict[str, object], label: str) -> tuple[str, str]:
    checks = answer["checks"]
    assert isinstance(checks, list)
    [found] = [check for check in checks if check["label"] == label]
    return found["state"], found["detail"]


def _shown_checks(page: Page) -> Locator:
    """Opens the collapsed list `Sprawdzono` of the Diagnoza and returns its items."""

    diagnosis = page.get_by_role("region", name="Diagnoza")
    diagnosis.get_by_role("button", name="Sprawdzono (10)", exact=True).click()
    return diagnosis.get_by_role("list", name="Sprawdzono").get_by_role("listitem")


def drive_freshness_and_onedrive(run: Run, page: Page) -> None:
    register = Path(run.fixture["order_register"])
    github = run.root / "github"
    onedrive = run.root / "onedrive"
    github.mkdir(exist_ok=True)
    onedrive.mkdir(exist_ok=True)
    main_commit = github / "main-commit.txt"
    offline = github / "brak-sieci"
    only_in_cloud = onedrive / "tylko-w-chmurze.txt"

    run.step(FEATURE, "aktualnosc-nowsza-wersja")
    run_id = _stop_without_cause_on_computer(run, page)
    main_commit.write_text(OTHER_MAIN, encoding="utf-8")
    explanation = _diagnose(page)
    expect(explanation).to_contain_text(NEWER)
    expect(explanation.get_by_role("button", name="Uruchom ponownie", exact=True)).to_be_visible()
    expect(_proposal(page)).to_have_count(0)
    answer = diagnosis_answer(run, run_id, "aktualnosc-nowsza-wersja")
    run.check(
        _state(answer, FRESHNESS) == ("failed", NEWER)
        and answer["next_action"] == "rerun"
        and answer["update_proposal"] is False,
        "with no other cause a newer `main` on GitHub explains the stop, and Dad updates the tool himself",
    )
    run.capture(page, "76-aktualnosc-nowsza-wersja")

    run.step(FEATURE, "aktualnosc-brak-sieci")
    main_commit.unlink()
    offline.touch()
    explanation = _diagnose(page)
    expect(explanation).to_contain_text(NOT_FOUND)
    shown = _shown_checks(page).filter(has_text=FRESHNESS)
    expect(shown).to_contain_text("Nie sprawdzono: brak połączenia z GitHubem.")
    expect(shown.get_by_label("nie sprawdzono")).to_be_visible()
    answer = diagnosis_answer(run, run_id, "aktualnosc-brak-sieci")
    run.check(
        _state(answer, FRESHNESS)[0] == "not_checked" and answer["next_action"] == "report",
        "without network the freshness is not checked and is no cause",
    )
    run.capture(page, "77-aktualnosc-brak-sieci")

    run.step(FEATURE, "onedrive-tylko-w-chmurze")
    offline.unlink()
    before = (register.read_bytes(), register.stat().st_mtime_ns)
    only_in_cloud.write_text(str(register) + "\n", encoding="utf-8")
    explanation = _diagnose(page)
    expect(explanation).to_contain_text(ONLY_IN_CLOUD)
    expect(explanation).to_contain_text(f"plik {register.name}")
    expect(explanation).to_contain_text(KEEP_ON_DEVICE)
    expect(explanation.get_by_role("button", name="Uruchom ponownie", exact=True)).to_be_visible()
    answer = diagnosis_answer(run, run_id, "onedrive-tylko-w-chmurze")
    run.check(
        _state(answer, ONEDRIVE)[0] == "failed" and answer["next_action"] == "rerun",
        "a Rejestr zleceń only in the cloud explains the stop with „Zawsze zachowuj na tym urządzeniu”",
    )
    run.check((register.read_bytes(), register.stat().st_mtime_ns) == before, "the Diagnoza left the Rejestr zleceń as it was")
    run.capture(page, "78-onedrive-tylko-w-chmurze")

    run.step(FEATURE, "aktualnosc-propozycja")
    main_commit.write_text(OTHER_MAIN, encoding="utf-8")
    explanation = _diagnose(page)
    expect(explanation).to_contain_text(ONLY_IN_CLOUD)
    expect(explanation.get_by_role("button", name="Uruchom ponownie", exact=True)).to_be_visible()
    expect(_proposal(page)).to_have_text(PROPOSAL)
    answer = diagnosis_answer(run, run_id, "aktualnosc-propozycja")
    shown_explanation = answer["explanation"]
    assert isinstance(shown_explanation, dict)
    run.check(
        shown_explanation["what"] == ONLY_IN_CLOUD
        and _state(answer, FRESHNESS) == ("failed", NEWER)
        and (answer["next_action"], answer["update_proposal"]) == ("rerun", True),
        "a newer `main` does not cover the Rejestr zleceń only in the cloud: it is only proposed under the explanation",
    )
    run.capture(page, "81-aktualnosc-propozycja")

    run.step(FEATURE, "aktualnosc-i-onedrive-przeszly")
    main_commit.unlink()
    only_in_cloud.unlink()
    explanation = _diagnose(page)
    expect(explanation).to_contain_text(NOT_FOUND)
    checks = _shown_checks(page)
    expect(checks.filter(has_text=FRESHNESS)).to_contain_text("Najnowsza wersja z GitHuba, commit ")
    expect(checks.filter(has_text=ONEDRIVE).get_by_label("przeszło")).to_be_visible()
    answer = diagnosis_answer(run, run_id, "aktualnosc-i-onedrive-przeszly")
    run.check(
        _state(answer, FRESHNESS)[0] == "passed" and _state(answer, ONEDRIVE)[0] == "passed",
        "an up-to-date tool and files kept on the computer pass both checks",
    )
    log = (run.root / "logs" / "centrum-rozliczen.log").read_text(encoding="utf-8")
    run.check(
        all(f"przyczyna={code}" in log for code in ("NOWSZA_WERSJA_NARZEDZIA", "PLIK_TYLKO_W_CHMURZE")),
        "the Centrum log records both causes by code only",
    )
    run.capture(page, "79-aktualnosc-i-onedrive-przeszly")


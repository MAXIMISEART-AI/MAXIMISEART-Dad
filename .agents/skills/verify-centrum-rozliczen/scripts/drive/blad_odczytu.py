"""Drive features/blad-odczytu.md."""

from __future__ import annotations

from collections.abc import Callable
import re
from urllib.parse import urlsplit

from playwright.sync_api import Locator, Page, Route, expect

from drive.common import Run, ensure_files_set, sent_requests

FEATURE = "blad-odczytu"
RETRY = "Spróbuj ponownie"
UNREACHABLE = "Centrum rozliczeń nie odpowiada."


def _failure(page: Page, what: str) -> Locator:
    return page.get_by_role("alert").filter(has_text=f"Nie udało się odczytać {what}")


def _fails_then_retries(
    run: Run,
    page: Page,
    *,
    step: str,
    path: str,
    what: str,
    open_page: Callable[[], None],
    content: Locator,
    shot: str,
) -> None:
    """One read of ``path`` fails (unreachable server, harness); „Spróbuj ponownie” reads it again and shows ``content``."""

    run.step(FEATURE, step)
    pattern = f"**{path}"
    page.route(pattern, lambda route: route.abort())
    try:
        open_page()
        failure = _failure(page, what)
        expect(failure).to_contain_text(UNREACHABLE)
        expect(content).to_have_count(0)
        expect(failure.get_by_role("button", name=RETRY, exact=True)).to_be_enabled()
        run.check(True, f"a failed read of {path} (unreachable server, harness) shows „Nie udało się odczytać {what}” with {RETRY}")
        run.capture(page, shot)
    finally:
        page.unroute(pattern)
    with sent_requests(page, "GET", path) as sent:
        failure.get_by_role("button", name=RETRY, exact=True).click()
        expect(content.first).to_be_visible()
    expect(failure).to_have_count(0)
    run.check(len(sent) >= 1, f"{RETRY} reads {path} again and its content replaces the Komunikat")


OKRESY_READS = ("/api/settings", "/api/periods", "/api/metrics")


def _whole_page_retries(run: Run, page: Page, board: Locator) -> None:
    """Every read of Okresy fails at the tab's start; one „Spróbuj ponownie” brings back the board and the key numbers."""

    run.step(FEATURE, "blad-odczytu-okresy-jednym-kliknieciem")
    stats = page.get_by_role("group", name="Najważniejsze liczby", exact=True)
    pattern = re.compile(r"/api/(settings|periods|metrics)$")
    aborted: set[str] = set()

    def abort(route: Route) -> None:
        aborted.add(urlsplit(route.request.url).path)
        route.abort()

    page.route(pattern, abort)
    try:
        page.goto(run.url + "#/okresy")
        page.reload()
        # Sync Playwright runs the route handler only inside its own calls, so the wait is one of them.
        for _ in range(100):
            if aborted == set(OKRESY_READS):
                break
            page.wait_for_timeout(100)
        run.check(aborted == set(OKRESY_READS), "settings, periods and metrics failed (unreachable, harness)")
        failures = page.get_by_role("alert").filter(has_text="Nie udało się odczytać")
        expect(failures).to_have_count(1)
        expect(failures).to_contain_text(UNREACHABLE)
        run.check(True, "three failed reads of Okresy show one „Nie udało się odczytać okresów”")
        run.capture(page, "153-blad-odczytu-okresy-trzy-odczyty")
    finally:
        page.unroute(pattern)
    with sent_requests(page, "GET", "/api/*") as sent:
        failures.get_by_role("button", name=RETRY, exact=True).click()
        expect(board).to_be_visible()
        expect(stats.get_by_text(re.compile(r"^\d+ OK$"))).to_be_visible()
    expect(failures).to_have_count(0)
    expect(stats).not_to_contain_text(UNREACHABLE)
    read = {urlsplit(request.url).path for request in sent}
    run.check(
        read >= set(OKRESY_READS),
        f"one {RETRY} reads settings, periods and metrics again; the board and the key numbers are back (read {sorted(read)})",
    )
    run.capture(page, "154-blad-odczytu-okresy-jednym-kliknieciem")


def _retry_in_flight(run: Run, page: Page) -> None:
    """While the re-read is on its way the button waits; a second failure keeps the Komunikat and the button."""

    run.step(FEATURE, "blad-odczytu-ponowna-porazka")
    held: list[Route] = []
    page.route("**/api/configuration", lambda route: route.abort())
    try:
        page.get_by_role("link", name="Okresy", exact=True).click()
        page.get_by_role("link", name="Konfiguracja", exact=True).click()
        failure = _failure(page, "konfiguracji")
        expect(failure).to_contain_text(UNREACHABLE)
        page.unroute("**/api/configuration")
        # Harness: the re-read is held, like an answer that takes its time, then fails as well.
        page.route("**/api/configuration", lambda route: held.append(route))
        button = failure.get_by_role("button", name=RETRY, exact=True)
        # The spinner turns forever once Enter is pressed, so the alert's entrance has to end before it.
        page.wait_for_function("document.getAnimations().every((animation) => animation.playState !== 'running')")
        button.focus()
        page.keyboard.press("Enter")
        expect(button).to_be_disabled()
        expect(button).to_be_focused()
        page.keyboard.press("Enter")
        run.check(
            len(held) == 1,
            f"the re-read is on its way (held, harness): {RETRY} keeps its name and the focus, waits with a spinner, and a second "
            "Enter reads nothing",
        )
        run.capture(page, "141-blad-odczytu-ponowny-odczyt", live=True)  # the spinner turns until the answer
        held.pop().abort()
        expect(button).to_be_enabled()
        expect(button).to_be_focused()
        expect(failure).to_contain_text(UNREACHABLE)
        run.check(True, "a re-read that fails again keeps the Komunikat and gives the button back, still in focus")
    finally:
        for route in held:
            route.abort()
        page.unroute("**/api/configuration")
    failure.get_by_role("button", name=RETRY, exact=True).click()
    expect(page.get_by_role("list", name="Wykonawcy")).to_be_visible()
    expect(failure).to_have_count(0)
    run.check(True, "the next try reads Konfiguracja")


def drive_load_failures(run: Run, page: Page) -> None:
    page.goto(run.url)
    ensure_files_set(run, page)
    board = page.get_by_role("table", name="Tablica okresów")
    expect(board).to_be_visible()

    def reload_tab() -> None:
        page.goto(run.url + "#/okresy")
        page.reload()

    _fails_then_retries(
        run, page, step="blad-odczytu-ustawienia", path="/api/settings", what="okresów",
        open_page=reload_tab, content=board, shot="139-blad-odczytu-ustawienia",
    )

    def via_menu(name: str) -> Callable[[], None]:
        def open_page() -> None:
            page.get_by_role("link", name="Metryki" if name == "Okresy" else "Okresy", exact=True).click()
            page.get_by_role("link", name=name, exact=True).click()
            expect(page.get_by_role("heading", name=name, level=1)).to_be_visible()

        return open_page

    _fails_then_retries(
        run, page, step="blad-odczytu-tablica", path="/api/periods", what="okresów",
        open_page=via_menu("Okresy"), content=board, shot="142-blad-odczytu-tablica",
    )
    _whole_page_retries(run, page, board)
    _fails_then_retries(
        run, page, step="blad-odczytu-uruchomienia", path="/api/runs/setup", what="Uruchomień",
        open_page=via_menu("Uruchomienia"), content=page.get_by_role("combobox", name="Okres"),
        shot="143-blad-odczytu-uruchomienia",
    )
    history = page.get_by_role("table", name="Historia Uruchomień procesu")

    def history_tab() -> None:
        page.get_by_role("tab", name="Historia", exact=True).click()

    _fails_then_retries(
        run, page, step="blad-odczytu-historia", path="/api/metrics", what="historii",
        open_page=history_tab, content=history, shot="144-blad-odczytu-historia",
    )
    _fails_then_retries(
        run, page, step="blad-odczytu-metryki", path="/api/metrics", what="metryk",
        open_page=via_menu("Metryki"), content=history, shot="145-blad-odczytu-metryki",
    )
    _fails_then_retries(
        run, page, step="blad-odczytu-konfiguracja", path="/api/configuration", what="konfiguracji",
        open_page=via_menu("Konfiguracja"), content=page.get_by_role("list", name="Wykonawcy"),
        shot="146-blad-odczytu-konfiguracja",
    )
    _retry_in_flight(run, page)

    def bell() -> None:
        page.get_by_role("button", name="Powiadomienia").click()
        expect(page.get_by_role("heading", name="Powiadomienia", level=1)).to_be_visible()

    _fails_then_retries(
        run, page, step="blad-odczytu-powiadomienia", path="/api/notifications", what="Powiadomień",
        open_page=bell,
        content=page.get_by_role("list", name="Powiadomienia", exact=True).or_(
            page.get_by_role("region", name=re.compile(r"^Nowa wersja "))
        ),
        shot="147-blad-odczytu-powiadomienia",
    )

    dialog = page.get_by_role("dialog", name="Napisz do Maksa", exact=True)

    def note_runs() -> None:
        page.get_by_role("button", name="Napisz do Maksa", exact=True).click()
        expect(dialog).to_be_visible()
        dialog.get_by_role("group", name="Dotyczy", exact=True).get_by_role(
            "button", name="Do Uruchomienia", exact=True
        ).click()

    _fails_then_retries(
        run, page, step="blad-odczytu-uwaga", path="/api/dad-notes/runs", what="Uruchomień",
        open_page=note_runs,
        content=dialog.get_by_role("radiogroup", name="Uruchomienie").or_(
            dialog.get_by_text("Nie ma jeszcze Uruchomień z Centrum.")
        ),
        shot="148-blad-odczytu-uwaga",
    )
    page.keyboard.press("Escape")
    expect(dialog).to_have_count(0)

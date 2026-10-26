"""Drive features/konfiguracja.md."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
import os
from pathlib import Path
import sys

from playwright.sync_api import Locator, Page, expect

from drive.common import Run, served_version, version_line

TEMPLATE_LABELS = ("Wzorzec rozliczenia wewnętrznego", "Wzorzec pliku zbiorczego", "Wzorzec rozliczenia pracownika")
REPORT_TO_MAINTAINER = "Przekaż ten komunikat osobie utrzymującej narzędzie."
INACCESSIBLE_TEMPLATE = "Nie można teraz odczytać wzorca. Plik może być zajęty przez inny program."


def _configuration_snapshot(files: dict[str, Path]) -> dict[str, tuple[bytes, int]]:
    """Bytes and modification time of the konfiguracja wykonawców and the three Wzorce, plus every lock file."""

    config = next(iter(files.values())).parent
    paths = [*files.values(), *config.glob("~$*")]
    return {path.name: (path.read_bytes(), path.stat().st_mtime_ns) for path in sorted(paths)}


@contextmanager
def _unreadable(path: Path) -> Iterator[None]:
    """Harness: the system refuses to read ``path`` without changing its bytes, size or modification time; always undone."""

    if sys.platform == "win32":
        import msvcrt

        # A byte-range lock makes every other read of the file fail, as when another program holds it.
        print("  harness: the drive locks the Wzorzec's bytes", flush=True)
        size = path.stat().st_size
        with path.open("rb") as handle:
            msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, size)
            try:
                yield
            finally:
                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, size)
    else:
        print("  harness: the Wzorzec has no permissions (chmod 0)", flush=True)
        mode = path.stat().st_mode
        path.chmod(0)
        try:
            yield
        finally:
            path.chmod(mode)


@contextmanager
def _changed(path: Path) -> Iterator[None]:
    """Harness: ``path`` gets a newer modification time, as when OneDrive brings it again; the old one comes back after."""

    stat = path.stat()
    print("  harness: the Wzorzec gets a newer modification time, so Centrum checks it again", flush=True)
    os.utime(path, ns=(stat.st_atime_ns, stat.st_mtime_ns + 1_000_000_000))
    try:
        yield
    finally:
        os.utime(path, ns=(stat.st_atime_ns, stat.st_mtime_ns))


def _template_group(page: Page, label: str) -> Locator:
    return page.get_by_role("group", name=label, exact=True)


def _shown_as_ready(page: Page, label: str) -> None:
    expect(_template_group(page, label).get_by_role("img", name="Na miejscu i czytelny")).to_be_visible()


def _template_answer(run: Run, name: str, label: str) -> dict[str, object]:
    templates = run.api("/api/configuration", name)["templates"]
    assert isinstance(templates, list)
    return next(template for template in templates if template["label"] == label)


def drive_configuration(run: Run, page: Page) -> None:
    """Every broken state is made by renaming or adding files and undone by renaming back, so a
    Centrum that wrote nothing leaves bytes and modification times exactly as the fixture made them."""

    feature = "konfiguracja"
    files = {name: Path(path) for name, path in run.fixture["configuration"].items()}
    before = _configuration_snapshot(files)

    run.step(feature, "konfiguracja-gotowa")
    page.goto(run.url)
    page.get_by_role("link", name="Konfiguracja", exact=True).click()
    expect(page.get_by_role("heading", name="Konfiguracja", level=1)).to_be_visible()
    configuration = run.api("/api/configuration", "konfiguracja-gotowa")
    templates = configuration["templates"]
    assert isinstance(templates, list)
    run.check(
        [(template["label"], template["state"]) for template in templates]
        == [(label, "ready") for label in TEMPLATE_LABELS],
        "the server reports all three Wzorce present and readable",
    )
    run.check(
        configuration["workers"] == {"state": "ready", "names": run.fixture["workers"]},
        "the server lists the Wykonawcy in the order of the konfiguracja wykonawców",
    )
    commit, since = served_version(run)
    run.check(
        configuration["version"] == {"commit": commit[:7], "since": since},
        "the server reports the tool's commit and the day the tool moved there",
    )
    for label in TEMPLATE_LABELS:
        _shown_as_ready(page, label)
    expect(page.get_by_text("3 z 3", exact=True)).to_be_visible()
    expect(page.get_by_role("list", name="Wykonawcy").get_by_role("listitem")).to_have_text(run.fixture["workers"])
    expect(page.get_by_role("region", name="Narzędzie").get_by_text(version_line(commit, since), exact=True)).to_be_visible()
    expect(page.get_by_role("alert")).to_have_count(0)
    run.check(True, "the screen shows the same Wzorce, Wykonawcy, and version, with no problem")
    run.capture(page, "10-konfiguracja-gotowa")

    run.step(feature, "konfiguracja-tylko-do-odczytu")
    page.get_by_text("Tylko do odczytu", exact=True).hover()
    expect(page.get_by_text("Zmiany robi osoba utrzymująca narzędzie.", exact=True)).to_be_visible()
    buttons = page.locator("main").get_by_role("button")
    run.check(
        page.url.endswith("#/konfiguracja")
        and buttons.count() == 4
        and buttons.filter(has_text="Zaktualizuj narzędzie").count() == 0
        and page.locator("main").get_by_role("button", name="Napisz do Maksa", exact=True).count() == 1
        and page.locator("main").get_by_role("button", name="Powiadomienia", exact=False).count() == 1,
        "the page offers no action besides the header's menu, `Napisz do Maksa`, Powiadomienia and theme buttons; the current tool"
        " has no `Zaktualizuj narzędzie`",
    )
    offer = run.api("/api/configuration", "konfiguracja-tylko-do-odczytu")
    run.check(
        (offer["freshness"], offer["update_offered"]) == ("current", False),
        "the server offers no Aktualizacja narzędzia for the current tool",
    )
    run.capture(page, "11-konfiguracja-tylko-do-odczytu", full_page=False)
    page.mouse.move(0, 0)

    run.step(feature, "konfiguracja-wzorzec-otwarty")
    collective = files["collective_template"]
    lock = collective.with_name(f"~${collective.name}")
    lock.write_bytes(b"")
    try:
        page.reload()
        expect(_template_group(page, "Wzorzec pliku zbiorczego")).to_contain_text("Otwarty w Excelu")
        message = page.get_by_role("alert").filter(has_text="Wzorzec jest otwarty w Excelu.")
        expect(message).to_contain_text(f"plik {collective.name}, folder config")
        expect(message).to_contain_text(f"usuń z tego samego folderu pozostawiony plik ~${collective.name}")
        expect(page.get_by_text("2 z 3", exact=True)).to_be_visible()
        answer = _template_answer(run, "konfiguracja-wzorzec-otwarty", "Wzorzec pliku zbiorczego")
        run.check(answer["problem"] == "open_in_excel", "the server reports the Wzorzec as open in Excel")
        run.capture(page, "12-konfiguracja-wzorzec-otwarty")
        run.check(lock.exists(), "Centrum leaves Excel's lock file alone")
    finally:
        lock.unlink()
    # Headless Chromium keeps every tab visible, so returning to the tab is simulated with `focus`.
    page.evaluate("window.dispatchEvent(new FocusEvent('focus'))")
    _shown_as_ready(page, "Wzorzec pliku zbiorczego")
    run.check(True, "a (simulated) return to the tab shows the Wzorzec ready once Excel has closed it")

    run.step(feature, "konfiguracja-wzorzec-niedostepny")
    internal = files["internal_template"]
    with _changed(internal):
        with _unreadable(internal):
            page.reload()
            group = _template_group(page, "Wzorzec rozliczenia wewnętrznego")
            expect(group).to_contain_text("Nie przechodzi sprawdzenia")
            message = page.get_by_role("alert").filter(has_text=INACCESSIBLE_TEMPLATE)
            expect(message).to_contain_text(f"plik {internal.name}, folder config")
            run.check("uszkodzon" not in message.inner_text(), "a Wzorzec without access is niedostępny, never uszkodzony")
            answer = _template_answer(run, "konfiguracja-wzorzec-niedostepny", "Wzorzec rozliczenia wewnętrznego")
            run.check(answer["problem"] == "unreadable", "the server reports the Wzorzec as not passing the Sprawdzanie")
            run.capture(page, "12a-konfiguracja-wzorzec-niedostepny")
        print("  harness: access to the Wzorzec is back", flush=True)
        page.evaluate("window.dispatchEvent(new FocusEvent('focus'))")
        _shown_as_ready(page, "Wzorzec rozliczenia wewnętrznego")
        expect(page.get_by_role("alert")).to_have_count(0)
        answer = _template_answer(run, "konfiguracja-wzorzec-dostepny", "Wzorzec rozliczenia wewnętrznego")
        run.check(
            answer["state"] == "ready",
            "once access is back, a (simulated) return to the tab shows the Wzorzec ready without restarting Centrum",
        )
        run.capture(page, "12b-konfiguracja-wzorzec-dostepny")

    run.step(feature, "konfiguracja-brak-wzorca")
    worker_template = files["worker_template"]
    moved = worker_template.with_name(worker_template.name + ".przeniesiony")
    worker_template.rename(moved)
    try:
        page.reload()
        expect(_template_group(page, "Wzorzec rozliczenia pracownika")).to_contain_text("Brak pliku")
        message = page.get_by_role("alert").filter(has_text=f"Nie znaleziono Wzorca rozliczenia pracownika: {worker_template.name}.")
        # The same message as the Przebieg rozliczeń stop for this Wzorzec.
        expect(message).to_contain_text("Nie można użyć Wzorca rozliczenia pracownika.")
        expect(message).to_contain_text("W innym wypadku przekaż ten komunikat osobie utrzymującej narzędzie.")
        answer = _template_answer(run, "konfiguracja-brak-wzorca", "Wzorzec rozliczenia pracownika")
        run.check(answer["problem"] == "missing", "the server reports the Wzorzec rozliczenia pracownika as missing")
        run.capture(page, "13-konfiguracja-brak-wzorca")
    finally:
        moved.rename(worker_template)

    run.step(feature, "konfiguracja-nieczytelna-konfiguracja-wykonawcow")
    worker_config = files["worker_config"]
    moved = worker_config.with_name(worker_config.name + ".przeniesiony")
    worker_config.rename(moved)
    try:
        worker_config.write_text("workers: [niedomknięta lista\n", encoding="utf-8")
        page.reload()
        # The same message as Przebieg rozliczeń's stop on this konfiguracja wykonawców.
        message = page.get_by_role("alert").filter(has_text="Konfiguracja wykonawców jest niepoprawna.")
        expect(message).to_contain_text("Plik nie jest poprawnym YAML.")
        expect(message).to_contain_text(f"plik {worker_config.name}")
        expect(message).to_contain_text(REPORT_TO_MAINTAINER)
        expect(page.get_by_role("list", name="Wykonawcy")).to_have_count(0)
        workers = run.api("/api/configuration", "konfiguracja-nieczytelna-konfiguracja-wykonawcow")["workers"]
        assert isinstance(workers, dict)
        run.check(workers["state"] == "unreadable", "the server reports the konfiguracja wykonawców as unreadable")
        run.capture(page, "14-konfiguracja-nieczytelna-konfiguracja-wykonawcow")
    finally:
        worker_config.unlink(missing_ok=True)
        moved.rename(worker_config)

    run.step(feature, "konfiguracja-bez-zmian")
    page.reload()
    for label in TEMPLATE_LABELS:
        _shown_as_ready(page, label)
    run.check(
        _configuration_snapshot(files) == before,
        "the konfiguracja wykonawców and every Wzorzec keep their bytes and modification times; no lock file is left",
    )

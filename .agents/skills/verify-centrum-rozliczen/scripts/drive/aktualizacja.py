"""Drive features/aktualizacja.md."""

from __future__ import annotations

import json
from contextlib import contextmanager
from collections.abc import Iterator
from pathlib import Path
import subprocess
import urllib.request

from playwright.sync_api import Locator, Page, expect

from drive.common import Run

FEATURE = "aktualizacja"
BUTTON = "Zaktualizuj narzędzie"
UPDATED = "Zaktualizowano. Zamknij Centrum rozliczeń i kliknij skrót."
UP_TO_DATE = "Masz najnowszą wersję."
FETCHING = "Pobieranie nowej wersji…"
NO_CONNECTION = "Nie zaktualizowano narzędzia: brak połączenia z GitHubem."
RETRY = "Narzędzie działa dalej w poprzedniej wersji. Sprawdź internet i kliknij „Zaktualizuj narzędzie” jeszcze raz."
REPORT_BUTTON = "Wyślij do Maksa"
INSTALLING = "Instalowanie bibliotek…"
LIBRARIES_FAILED = "Nie udało się zainstalować bibliotek nowej wersji narzędzia."
# Long enough to see the progress and send the refused requests; fetching from the local "origin" takes milliseconds.
PACING_MS = 4000


def _git(clone: Path, *args: str) -> str:
    result = subprocess.run(["git", "-C", str(clone), *args], capture_output=True, text=True, check=True)
    return result.stdout.strip()


def _head(clone: Path) -> str:
    return _git(clone, "rev-parse", "HEAD")


def _contents(directory: Path) -> dict[str, bytes]:
    return {str(path.relative_to(directory)): path.read_bytes() for path in directory.rglob("*") if path.is_file()}


def _dad_files_kept(run: Run, clone: Path, dad_files: dict[str, str], run_configuration: dict[str, bytes]) -> None:
    run.check(
        {name: (clone / name).read_text(encoding="utf-8") for name in dad_files} == dad_files,
        "Dad's files in the tool's config/ keep exactly their content, the changed konfiguracja wykonawców too",
    )
    run.check(
        _git(clone, "ls-files", "--", "config/worker_mapping.yaml") == "",
        "the new version no longer tracks the konfiguracja wykonawców that Dad still has",
    )
    run.check(_contents(run.root / "config") == run_configuration, "the run's configuration directory is untouched")


@contextmanager
def _without_internet(run: Run) -> Iterator[None]:
    """No internet on Dad's computer: the local "origin", the scripted GitHub and the skrzynka are out of reach."""

    origin = Path(run.fixture["tool"]["origin"])
    away = origin.with_name("origin-poza-zasiegiem.git")
    markers = [run.root / "github" / "brak-sieci", run.root / "skrzynka-zgloszen" / "brak-sieci"]
    print("  harness: no internet (the local origin moved out of reach, GitHub and the skrzynka unreachable)", flush=True)
    origin.rename(away)
    for marker in markers:
        marker.parent.mkdir(exist_ok=True)
        marker.touch()
    try:
        yield
    finally:
        away.rename(origin)
        for marker in markers:
            marker.unlink(missing_ok=True)
        print("  harness: the internet is back", flush=True)


def _drive_no_connection(run: Run, page: Page, card: Locator, clone: Path, first: str) -> None:
    run.step(FEATURE, "aktualizacja-brak-sieci")
    with _without_internet(run):
        card.get_by_role("button", name=BUTTON, exact=True).click()
        message = card.get_by_role("alert", name="Ostrzeżenie")
        expect(message).to_contain_text(NO_CONNECTION, timeout=20_000)
        expect(message).to_contain_text("narzędzie na tym komputerze")
        expect(message).to_contain_text(RETRY)
        update = card.get_by_role("button", name=BUTTON, exact=True)
        expect(update).to_be_enabled()
        report = card.get_by_role("button", name=REPORT_BUTTON, exact=True)
        expect(report).to_be_visible()
        run.check("bg-primary" in (update.get_attribute("class") or ""), "trying again is the main action")
        run.check("bg-primary" not in (report.get_attribute("class") or ""), "`Wyślij do Maksa` is the second action")
        view = run.api("/api/tool-update", "aktualizacja-brak-sieci")
        run.check(
            (view["state"], view["message"], view["next_action"], view["report"])
            == (
                "failed",
                {"what": NO_CONNECTION, "where": "narzędzie na tym komputerze", "action": RETRY},
                "retry",
                {"state": "ready"},
            ),
            "the server reports the Komunikat in three parts, a retry, and a Zgłoszenie ready to send",
        )
        run.check(_head(clone) == first, "the clone stays on the commit Dad had")
        run.check(
            _git(clone, "status", "--porcelain", "--", "config/worker_mapping.yaml") == "M config/worker_mapping.yaml",
            "Dad's changed konfiguracja wykonawców is still there, still tracked",
        )
        run.check(
            _update_entries(run)
            == [f"aktualizacja-start przed={first}", f"aktualizacja-koniec wynik=BRAK_POLACZENIA przed={first} po=- biblioteki=nie"],
            "the Centrum log has the failed update with its code and commit, and no path",
        )
        run.capture(page, "115-aktualizacja-brak-sieci")
        card.get_by_role("button", name="Co zostanie wysłane").click()
        preview = card.get_by_role("figure", name="Treść Zgłoszenia")
        expect(preview).to_contain_text(f"BRAK_POLACZENIA: {NO_CONNECTION}")
        expect(preview).to_contain_text(f"- Commit przed: {first}")
        expect(preview).to_contain_text("- Biblioteki instalowane: nie")
        expect(preview).to_contain_text("aktualizacja-koniec wynik=BRAK_POLACZENIA")
        draft = view["draft"]
        run.check(
            isinstance(draft, dict) and "origin" not in str(draft["body"]) and str(run.root) not in str(draft["body"]),
            "the Zgłoszenie has the log's facts, no path and no Git output",
        )
        run.capture(page, "116-aktualizacja-brak-sieci-zgloszenie")


def _tool_card(page: Page) -> Locator:
    return page.get_by_role("region", name="Narzędzie", exact=True)


def _post(run: Run, path: str, name: str, body: dict[str, object] | None = None) -> int:
    request = urllib.request.Request(
        run.url.rstrip("/") + path,
        data=b"" if body is None else json.dumps(body).encode(),
        method="POST",
        headers={"Origin": run.url.rstrip("/"), "Content-Type": "application/json"},
    )
    return run.refused(request, name)


def _update_entries(run: Run) -> list[str]:
    log = (run.root / "logs" / "centrum-rozliczen.log").read_text(encoding="utf-8")
    return [
        line.split(" ", 1)[1]
        for line in log.splitlines()
        if line.split(" ")[1:2] in (["aktualizacja-start"], ["aktualizacja-koniec"])
    ]


def drive_update(run: Run, page: Page) -> None:
    tool = run.fixture["tool"]
    clone, first, newest, dad_files = Path(tool["clone"]), tool["first"], tool["newest"], tool["dad_files"]
    origin, libraries = Path(tool["origin"]), tool["libraries"]
    run_configuration = _contents(run.root / "config")
    github = run.root / "github"
    github.mkdir(exist_ok=True)
    main_commit = github / "main-commit.txt"
    pacing = run.root / "pacing" / "aktualizacja-ms.txt"
    pacing.parent.mkdir(exist_ok=True)

    run.step(FEATURE, "aktualizacja-jest-nowsza")
    print("  harness: `main` on the scripted GitHub is the local origin's newest commit", flush=True)
    main_commit.write_text(newest, encoding="utf-8")
    try:
        run.check(_head(clone) == first, "the run's tool clone stands on the first commit")
        run.check(
            _git(clone, "status", "--porcelain", "--", "config/worker_mapping.yaml") == "M config/worker_mapping.yaml",
            "Dad changed the tracked konfiguracja wykonawców in the clone",
        )
        page.goto(run.url + "#/konfiguracja")
        page.reload()
        card = _tool_card(page)
        expect(card).to_contain_text(first[:7])
        expect(card).to_contain_text("Jest nowsza wersja")
        configuration = run.api("/api/configuration", "aktualizacja-jest-nowsza")
        run.check(
            (configuration["commit"], configuration["freshness"]) == (first[:7], "newer"),
            "the server reports the clone's commit and a newer version",
        )
        expect(card.get_by_role("button", name=BUTTON, exact=True)).to_be_enabled()
        run.check(
            run.api("/api/tool-update", "aktualizacja-przed")["state"] == "idle",
            "no Aktualizacja narzędzia since Centrum started",
        )
        run.capture(page, "93-aktualizacja-jest-nowsza")
        _drive_no_connection(run, page, card, clone, first)

        run.step(FEATURE, "aktualizacja-postep")
        print(f"  harness: each Aktualizacja narzędzia waits {PACING_MS} ms before it looks for Git", flush=True)
        pacing.write_text(str(PACING_MS), encoding="utf-8")
        card.get_by_role("button", name=BUTTON, exact=True).dblclick()
        expect(card.get_by_role("status").filter(has_text=FETCHING)).to_be_visible()
        expect(card.get_by_role("button", name=BUTTON, exact=True)).to_be_disabled()
        view = run.api("/api/tool-update", "aktualizacja-postep")
        run.check(view == {"state": "running", "step": "fetching"}, "the server reports the step `fetching`")
        run.check(
            _post(run, "/api/tool-update", "aktualizacja-druga-odmowa") == 409,
            "a second Aktualizacja narzędzia is refused while one runs",
        )
        run.check(
            _post(run, "/api/shutdown", "aktualizacja-zamkniecie-odmowa") == 409,
            "closing Centrum is refused while the update runs",
        )
        run.capture(page, "94-aktualizacja-postep", live=True)
        run.check(
            [entry.split(" ")[0] for entry in _update_entries(run)[2:]] == ["aktualizacja-start"],
            "with the internet back, the double click started exactly one more Aktualizacja narzędzia",
        )
    finally:
        pacing.unlink(missing_ok=True)

    try:
        run.step(FEATURE, "aktualizacja-zaktualizowano")
        expect(card.get_by_role("status").filter(has_text=UPDATED)).to_be_visible(timeout=20_000)
        expect(card).to_contain_text(newest[:7])
        expect(card).to_contain_text("Aktualna")
        expect(card.get_by_role("button", name=BUTTON, exact=True)).to_be_enabled()
        view = run.api("/api/tool-update", "aktualizacja-zaktualizowano")
        run.check(view == {"state": "updated", "commit": newest[:7]}, "the server reports the new commit")
        run.check(_head(clone) == newest, "the clone moved forward to the origin's newest commit")
        _dad_files_kept(run, clone, dad_files, run_configuration)
        configuration = run.api("/api/configuration", "aktualizacja-konfiguracja-po")
        run.check(
            (configuration["commit"], configuration["freshness"]) == (newest[:7], "current"),
            "Konfiguracja reports the new commit as current",
        )
        entries = _update_entries(run)
        run.check(
            entries[2:] == [f"aktualizacja-start przed={first}", f"aktualizacja-koniec wynik=ok przed={first} po={newest} biblioteki=nie"],
            "the Centrum log has the retry's start and end with both commits, and no path",
        )
        run.capture(page, "95-aktualizacja-zaktualizowano")

        run.step(FEATURE, "aktualizacja-najnowsza")
        card.get_by_role("button", name=BUTTON, exact=True).click()
        expect(card.get_by_role("status").filter(has_text=UP_TO_DATE)).to_be_visible()
        view = run.api("/api/tool-update", "aktualizacja-najnowsza")
        run.check(view == {"state": "up_to_date"}, "the server reports the newest version")
        run.check(_head(clone) == newest, "the clone stays on the newest commit")
        run.check(
            _update_entries(run)[-1] == f"aktualizacja-koniec wynik=AKTUALNA przed={newest} po={newest} biblioteki=nie",
            "the Centrum log has the update that changed nothing",
        )
        run.capture(page, "96-aktualizacja-najnowsza")

        _drive_failed_installation(run, page, clone, origin, newest, libraries, dad_files, run_configuration)
    finally:
        main_commit.unlink(missing_ok=True)
        pacing.with_name("instalacja-ms.txt").unlink(missing_ok=True)
        _git(origin, "update-ref", "refs/heads/main", newest)


def _drive_failed_installation(
    run: Run,
    page: Page,
    clone: Path,
    origin: Path,
    newest: str,
    libraries: str,
    dad_files: dict[str, str],
    run_configuration: dict[str, bytes],
) -> None:
    run.step(FEATURE, "aktualizacja-instalowanie")
    print("  harness: `main` in the local origin and on the scripted GitHub needs a library pip cannot install offline", flush=True)
    _git(origin, "update-ref", "refs/heads/main", libraries)
    (run.root / "github" / "main-commit.txt").write_text(libraries, encoding="utf-8")
    print(f"  harness: each installation of libraries waits {PACING_MS} ms before pip starts", flush=True)
    (run.root / "pacing" / "instalacja-ms.txt").write_text(str(PACING_MS), encoding="utf-8")
    page.reload()
    card = _tool_card(page)
    expect(card).to_contain_text("Jest nowsza wersja")
    card.get_by_role("button", name=BUTTON, exact=True).click()
    expect(card.get_by_role("status").filter(has_text=INSTALLING)).to_be_visible()
    expect(card.get_by_role("button", name=BUTTON, exact=True)).to_be_disabled()
    view = run.api("/api/tool-update", "aktualizacja-instalowanie")
    run.check(view == {"state": "running", "step": "installing"}, "the server reports the step `installing`")
    run.capture(page, "130-aktualizacja-instalowanie", live=True)
    (run.root / "pacing" / "instalacja-ms.txt").unlink()

    run.step(FEATURE, "aktualizacja-instalacja-nieudana")
    message = card.get_by_role("alert").filter(has_text=LIBRARIES_FAILED)
    expect(message).to_be_visible(timeout=20_000)
    expect(message).to_contain_text("Narzędzie działa dalej w poprzedniej wersji.")
    expect(card).to_contain_text(newest[:7])
    expect(card).to_contain_text("Jest nowsza wersja")
    expect(card.get_by_role("button", name=BUTTON, exact=True)).to_be_enabled()
    view = run.api("/api/tool-update", "aktualizacja-instalacja-nieudana")
    run.check(
        (view["state"], view["message"], view["next_action"])
        == (
            "failed",
            {
                "what": LIBRARIES_FAILED,
                "where": "narzędzie na tym komputerze",
                "action": (
                    "Narzędzie działa dalej w poprzedniej wersji. Kliknij „Zaktualizuj narzędzie” jeszcze raz. "
                    "Jeśli komunikat wraca, kliknij „Wyślij do Maksa”."
                ),
            },
            "retry",
        ),
        "the server reports the three-part Komunikat of the failed installation, to be tried again",
    )
    run.check(_head(clone) == newest, "the clone is back on the commit before the click")
    run.check(not (clone / "requirements.txt").exists(), "the new version's requirements left with it")
    run.check(_git(clone, "status", "--porcelain", "--untracked-files=no") == "", "the clone has no changes left")
    _dad_files_kept(run, clone, dad_files, run_configuration)
    run.check(
        _update_entries(run)[-1]
        == f"aktualizacja-koniec wynik=INSTALACJA_BIBLIOTEK przed={newest} po={libraries} biblioteki=tak",
        "the Centrum log has the failed installation with both commits, and no path or pip output",
    )
    run.capture(page, "131-aktualizacja-instalacja-nieudana")

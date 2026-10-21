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
UPDATED = "Zaktualizowano"
UP_TO_DATE = "Masz najnowszą wersję."
FETCHING = "Pobieranie nowej wersji…"
RESTARTING = "Ponowne uruchamianie Centrum…"
NO_CONNECTION = "Nie zaktualizowano narzędzia: brak połączenia z GitHubem."
RETRY = "Narzędzie działa dalej w poprzedniej wersji. Sprawdź internet i kliknij „Zaktualizuj narzędzie” jeszcze raz."
REPORT_BUTTON = "Wyślij do Maksa"
INSTALLING = "Instalowanie bibliotek…"
LIBRARIES_FAILED = "Nie udało się zainstalować bibliotek nowej wersji narzędzia."
REPAIRED = "Maks naprawił zgłoszony problem."
NEW_VERSION_FAILED = "Nowa wersja narzędzia nie wystartowała."
TO_MAKS = "Narzędzie działa dalej w poprzedniej wersji. Przekaż sprawę Maksowi: kliknij „Wyślij do Maksa”."
# Long enough to see the installation start; installing from no index fails in about a second.
PACING_MS = 4000
# Long enough to see the progress on Okresy, send the refused requests and see Konfiguracja during the same update;
# fetching from the local "origin" takes milliseconds.
UPDATE_PACING_MS = 8000
# Long enough to see the tab wait for the new Centrum; the restarted scripted Centrum starts in about a second.
RESTART_PACING_MS = 3000
# The restart guardian waits up to 60 s for the new Centrum; the tab reloads when it answers.
RESTART_TIMEOUT_MS = 60_000
# Konfiguracja keeps GitHub's answer about `main` for 10 minutes of Centrum's clock.
MAIN_KEPT_MIN = 10


def _git(clone: Path, *args: str) -> str:
    result = subprocess.run(["git", "-C", str(clone), *args], capture_output=True, text=True, check=True)
    return result.stdout.strip()


def _github_main(run: Run, commit: str) -> None:
    """`main` on the scripted GitHub is ``commit``; Centrum's clock moves past the time Konfiguracja keeps the old answer."""

    (run.root / "github" / "main-commit.txt").write_text(commit, encoding="utf-8")
    moved = run.root / "zegar" / "przesuniecie-min.txt"
    moved.parent.mkdir(exist_ok=True)
    before = float(moved.read_text(encoding="utf-8")) if moved.exists() else 0.0
    moved.write_text(str(before + MAIN_KEPT_MIN), encoding="utf-8")
    print(f"  harness: Centrum's clock moves {MAIN_KEPT_MIN} minutes on, so Konfiguracja asks GitHub again", flush=True)


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


def _repair_notice(page: Page) -> Locator:
    return page.get_by_role("status").filter(has_text=REPAIRED)


def _status(page: Page, text: str) -> Locator:
    return page.get_by_role("status").filter(has_text=text)


def _entered(status: Locator) -> None:
    """Waits for the status's own entrance; its spinner turns on, so a live capture cannot wait for every animation."""

    status.evaluate("element => Promise.all(element.getAnimations().map((animation) => animation.finished))")


@contextmanager
def _repaired_in_this_version(run: Run, first: str) -> Iterator[None]:
    """Maks closed a Zgłoszenie that Dad sent from the clone's first commit, so Okresy shows the repair notice."""

    sent = Path(run.fixture["settings"]).parent / "zgloszenia-wyslane.json"
    before = sent.read_bytes() if sent.exists() else None
    print("  harness: a Zgłoszenie sent from the clone's commit is closed (Maks repaired it)", flush=True)
    entries = json.loads(before) if before is not None else []
    entries.append({"fingerprint": "aktualizacja-naprawa", "number": 9000, "commit": first, "state": "closed"})
    sent.write_text(json.dumps(entries, indent=2) + "\n", encoding="utf-8")
    try:
        yield
    finally:
        if before is None:
            sent.unlink(missing_ok=True)
        else:
            sent.write_bytes(before)


def _post(run: Run, path: str, name: str, body: dict[str, object] | None = None) -> int:
    request = urllib.request.Request(
        run.url.rstrip("/") + path,
        data=b"" if body is None else json.dumps(body).encode(),
        method="POST",
        headers={"Origin": run.url.rstrip("/"), "Content-Type": "application/json"},
    )
    return run.refused(request, name)


def _repaired(run: Run, name: str) -> object:
    return run.api("/api/reports/repair", name)["repaired"]


def _update_entries(run: Run) -> list[str]:
    log = (run.root / "logs" / "centrum-rozliczen.log").read_text(encoding="utf-8")
    return [
        line.split(" ", 1)[1]
        for line in log.splitlines()
        if line.split(" ")[1:2] in (["aktualizacja-start"], ["aktualizacja-koniec"])
    ]


def _log_events(run: Run) -> list[str]:
    log = (run.root / "logs" / "centrum-rozliczen.log").read_text(encoding="utf-8")
    return [event for event in (line.split(" ")[1] for line in log.splitlines()) if event != "pomiar"]


def _since_update(run: Run) -> list[str]:
    events = _log_events(run)
    return events[len(events) - events[::-1].index("aktualizacja-start") :]


def _answers(run: Run) -> bool:
    try:
        with urllib.request.urlopen(run.url.rstrip("/") + "/api/health", timeout=2):
            return True
    except OSError:
        return False


def drive_update(run: Run, page: Page) -> None:
    with _repaired_in_this_version(run, run.fixture["tool"]["first"]):
        _drive_update(run, page)


def _drive_update(run: Run, page: Page) -> None:
    tool = run.fixture["tool"]
    clone, first, newest, dad_files = Path(tool["clone"]), tool["first"], tool["newest"], tool["dad_files"]
    origin, libraries = Path(tool["origin"]), tool["libraries"]
    run_configuration = _contents(run.root / "config")
    github = run.root / "github"
    github.mkdir(exist_ok=True)
    main_commit = github / "main-commit.txt"
    pacing = run.root / "pacing" / "aktualizacja-ms.txt"
    pacing.parent.mkdir(exist_ok=True)
    restart_pacing = run.root / "pacing" / "ponowny-start-ms.txt"

    run.step(FEATURE, "aktualizacja-jest-nowsza")
    print("  harness: `main` on the scripted GitHub is the local origin's newest commit", flush=True)
    _github_main(run, newest)
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

        run.step(FEATURE, "aktualizacja-powiadomienie")
        page.get_by_role("link", name="Okresy", exact=True).click()
        notice = _repair_notice(page)
        expect(notice).to_be_visible()
        expect(notice.get_by_role("button", name=BUTTON, exact=True)).to_be_enabled()
        run.check(_repaired(run, "aktualizacja-powiadomienie") is True, "Okresy has the repair notice for this version")
        run.capture(page, "141-aktualizacja-powiadomienie")

        run.step(FEATURE, "aktualizacja-postep")
        print(f"  harness: each Aktualizacja narzędzia waits {UPDATE_PACING_MS} ms before it looks for Git", flush=True)
        pacing.write_text(str(UPDATE_PACING_MS), encoding="utf-8")
        print(f"  harness: the restarted Centrum waits {RESTART_PACING_MS} ms before it starts", flush=True)
        restart_pacing.write_text(str(RESTART_PACING_MS), encoding="utf-8")
        before_health = run.api("/api/health", "aktualizacja-health-przed")
        page.evaluate("window.przedPonownymStartem = true")
        notice.get_by_role("button", name=BUTTON, exact=True).dblclick()
        expect(_status(page, FETCHING)).to_be_visible()
        expect(notice.get_by_role("button", name=BUTTON, exact=True)).to_be_disabled()
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
        _entered(_status(page, FETCHING))
        run.capture(page, "94-aktualizacja-postep", live=True)
        run.check(
            [entry.split(" ")[0] for entry in _update_entries(run)[2:]] == ["aktualizacja-start"],
            "with the internet back, the double click in the repair notice started exactly one more Aktualizacja narzędzia",
        )
        page.get_by_role("link", name="Konfiguracja", exact=True).click()
        card = _tool_card(page)
        expect(card.get_by_role("status").filter(has_text=FETCHING)).to_be_visible()
        expect(card.get_by_role("button", name=BUTTON, exact=True)).to_be_disabled()
        run.check(True, "on Konfiguracja the same update runs and its button cannot be clicked either")
        _entered(card.get_by_role("status").filter(has_text=FETCHING))
        run.capture(page, "142-aktualizacja-postep-konfiguracja", live=True)
        page.get_by_role("link", name="Okresy", exact=True).click()
        expect(_repair_notice(page).get_by_role("button", name=BUTTON, exact=True)).to_be_disabled()
    finally:
        pacing.unlink(missing_ok=True)

    try:
        run.step(FEATURE, "aktualizacja-ponowny-start")
        expect(_status(page, RESTARTING)).to_be_visible(timeout=20_000)
        expect(_repair_notice(page).get_by_role("button", name=BUTTON, exact=True)).to_be_disabled()
        run.check(not _answers(run), "the old Centrum has closed and the new one is not up yet")
        run.check(_log_events(run)[-2:] == ["aktualizacja-start", "zamkniecie"], "the old Centrum closed itself")
        run.check(
            "zamkniecie z=aktualizacja" in (run.root / "logs" / "centrum-rozliczen.log").read_text(encoding="utf-8"),
            "the closing names the update, not the card",
        )
        run.capture(page, "100-aktualizacja-ponowny-start", live=True)
    finally:
        restart_pacing.unlink(missing_ok=True)

    try:
        run.step(FEATURE, "aktualizacja-zaktualizowano")
        toast = page.get_by_role("region", name="Notifications").get_by_role("dialog", name=UPDATED)
        expect(toast).to_be_visible(timeout=RESTART_TIMEOUT_MS)
        expect(toast).to_contain_text(newest[:7])
        expect(toast).to_contain_text(f"Centrum działa w wersji {before_health['version']} ({newest[:7]}).")
        run.check(page.evaluate("window.przedPonownymStartem === undefined"), "the tab reloaded by itself")
        expect(page.get_by_role("heading", name="Okresy", exact=True)).to_be_visible()
        page.wait_for_load_state("networkidle")
        expect(_repair_notice(page)).to_have_count(0)
        run.check(
            _repaired(run, "aktualizacja-powiadomienie-po") is False,
            "the reloaded tab is back on Okresy in the new version, and the repair notice is gone by itself",
        )
        run.capture(page, "143-aktualizacja-bez-powiadomienia")
        page.get_by_role("link", name="Konfiguracja", exact=True).click()
        card = _tool_card(page)
        expect(card).to_contain_text(newest[:7])
        expect(card).to_contain_text("Aktualna")
        expect(card.get_by_role("button", name=BUTTON, exact=True)).to_be_enabled()
        health = run.api("/api/health", "aktualizacja-health-po")
        run.check(
            health["commit"] == newest[:7] and health["instance"] != before_health["instance"],
            "a new Centrum answers on the same address, in the new commit",
        )
        view = run.api("/api/tool-update", "aktualizacja-zaktualizowano")
        run.check(view == {"state": "updated"}, "the new Centrum reports the update's result")
        run.check(_head(clone) == newest, "the clone moved forward to the origin's newest commit")
        _dad_files_kept(run, clone, dad_files, run_configuration)
        configuration = run.api("/api/configuration", "aktualizacja-konfiguracja-po")
        run.check(
            (configuration["commit"], configuration["freshness"]) == (newest[:7], "current"),
            "Konfiguracja reports the new commit as current",
        )
        run.check(
            not (run.root / "config" / "centrum-aktualizacja.json").exists(),
            "the new Centrum read the guardian's result once and removed it",
        )
        entries = _update_entries(run)
        run.check(
            entries[2:] == [f"aktualizacja-start przed={first}", f"aktualizacja-koniec wynik=ok przed={first} po={newest} biblioteki=nie"],
            "the Centrum log has the retry's start and end with both commits, and no path",
        )
        # The old Centrum releases the port at once but gives open connections (the tab's event stream) up to
        # 5 s before it logs `stop`, so its `stop` may come after the new Centrum's `start`.
        run.wait_for(lambda: "stop" in _since_update(run), "the old Centrum stopped")
        run.check(
            [event for event in _since_update(run) if event != "stop"] == ["zamkniecie", "aktualizacja-koniec", "start"]
            and _since_update(run).count("stop") == 1,
            "the new Centrum logged the end of the update, then its start",
        )
        run.capture(page, "101-aktualizacja-zaktualizowano")

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
        try:
            _drive_new_version_not_starting(run, page, origin, tool["not_starting"], run_configuration)
        finally:
            restart_pacing.unlink(missing_ok=True)
        # Later features (pomiar-u-taty) expect Konfiguracja without an alert: one more click on the restored
        # `main` leaves this Centrum with `Masz najnowszą wersję.` instead of the failed installation.
        print("  harness: `main` in the local origin is the newest commit again", flush=True)
        _git(origin, "update-ref", "refs/heads/main", newest)
        _github_main(run, newest)
        card = _tool_card(page)
        card.get_by_role("button", name=BUTTON, exact=True).click()
        expect(card.get_by_role("status").filter(has_text=UP_TO_DATE)).to_be_visible(timeout=20_000)
        expect(card.get_by_role("alert")).to_have_count(0)
        run.check(_head(clone) == newest, "after the failed installation the tool is up to date on the newest commit")
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
    _github_main(run, libraries)
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


def _drive_new_version_not_starting(
    run: Run, page: Page, origin: Path, not_starting: str, run_configuration: dict[str, bytes]
) -> None:
    tool = run.fixture["tool"]
    clone, newest, dad_files = Path(tool["clone"]), tool["newest"], tool["dad_files"]
    run.step(FEATURE, "aktualizacja-nie-wystartowala-ponowny-start")
    print("  harness: `main` in the local origin and on the scripted GitHub is a version whose Centrum does not start", flush=True)
    _git(origin, "update-ref", "refs/heads/main", not_starting)
    _github_main(run, not_starting)
    print(f"  harness: the old version, started again, waits {RESTART_PACING_MS} ms before it starts", flush=True)
    (run.root / "pacing" / "ponowny-start-ms.txt").write_text(str(RESTART_PACING_MS), encoding="utf-8")
    with _repaired_in_this_version(run, newest):
        page.get_by_role("link", name="Okresy", exact=True).click()
        notice = _repair_notice(page)
        expect(notice).to_be_visible()
        before_health = run.api("/api/health", "aktualizacja-nie-wystartowala-health-przed")
        page.evaluate("window.przedPonownymStartem = true")
        notice.get_by_role("button", name=BUTTON, exact=True).click()
        expect(_status(page, RESTARTING)).to_be_visible(timeout=20_000)
        expect(notice.get_by_role("button", name=BUTTON, exact=True)).to_be_disabled()
        run.check(not _answers(run), "the old Centrum has closed, and no Centrum answers yet")
        _entered(_status(page, RESTARTING))
        run.capture(page, "135-aktualizacja-nie-wystartowala-ponowny-start", live=True)
        print("  Dad goes to Uruchomienia while Centrum restarts", flush=True)
        page.get_by_role("link", name="Uruchomienia", exact=True).click()
        expect(page.get_by_role("heading", name="Uruchomienia", exact=True)).to_be_visible()
    (run.root / "pacing" / "ponowny-start-ms.txt").unlink()

    run.step(FEATURE, "aktualizacja-nie-wystartowala")
    message = page.get_by_role("alert").filter(has_text=NEW_VERSION_FAILED)
    expect(message).to_be_visible(timeout=RESTART_TIMEOUT_MS)
    run.check(page.evaluate("window.przedPonownymStartem === undefined"), "the tab reloaded by itself")
    expect(page.get_by_role("heading", name="Uruchomienia", exact=True)).to_be_visible()
    run.check(True, "the tab reloaded on Uruchomienia, a page with no button of its own, and shows the Komunikat there")
    message = page.get_by_role("alert").filter(has_text=NEW_VERSION_FAILED)
    expect(message).to_contain_text("narzędzie na tym komputerze")
    expect(message).to_contain_text(TO_MAKS)
    report = page.get_by_role("button", name=REPORT_BUTTON, exact=True)
    expect(report).to_be_visible()
    run.check("bg-primary" in (report.get_attribute("class") or ""), "`Wyślij do Maksa` is the main action")
    expect(page.get_by_role("region", name="Notifications").get_by_role("dialog", name=UPDATED)).to_have_count(0)
    health = run.api("/api/health", "aktualizacja-nie-wystartowala-health-po")
    run.check(
        health["commit"] == newest[:7] and health["instance"] != before_health["instance"],
        "a new Centrum answers on the same address, in the old version",
    )
    view = run.api("/api/tool-update", "aktualizacja-nie-wystartowala")
    run.check(
        (view["state"], view["message"], view["next_action"])
        == ("failed", {"what": NEW_VERSION_FAILED, "where": "narzędzie na tym komputerze", "action": TO_MAKS}, "report"),
        "the old version reports the Komunikat in three parts and a Zgłoszenie to Maks",
    )
    run.check(_head(clone) == newest, "the guardian moved the clone back to the commit before the click")
    run.check(_git(clone, "status", "--porcelain", "--untracked-files=no") == "", "the clone has no changes left")
    _dad_files_kept(run, clone, dad_files, run_configuration)
    run.check(not (run.root / "config" / "centrum-aktualizacja.json").exists(), "the old version read the result once")
    run.check(
        _update_entries(run)[-2:]
        == [
            f"aktualizacja-start przed={newest}",
            f"aktualizacja-koniec wynik=NOWA_WERSJA_NIE_WYSTARTOWALA przed={newest} po={not_starting} biblioteki=nie",
        ],
        "the Centrum log has the update and its end in the old version, with both commits and no path",
    )
    run.wait_for(lambda: "stop" in _since_update(run), "the Centrum before the click stopped")
    run.check(
        [event for event in _since_update(run) if event != "stop"] == ["zamkniecie", "aktualizacja-koniec", "start"]
        and _since_update(run).count("stop") == 1,
        "only the old version started again; the new one never logged a start",
    )
    run.capture(page, "136-aktualizacja-nie-wystartowala")

    page.get_by_role("link", name="Konfiguracja", exact=True).click()
    card = _tool_card(page)
    expect(card).to_contain_text(newest[:7])
    expect(card).to_contain_text("Jest nowsza wersja")
    expect(page.get_by_role("alert").filter(has_text=NEW_VERSION_FAILED)).to_have_count(1)
    expect(card.get_by_role("alert")).to_have_count(0)
    run.check(True, "on Konfiguracja the same Komunikat stands once, under the title, and the card shows the old version")
    run.capture(page, "137-aktualizacja-nie-wystartowala-konfiguracja")

"""Drive features/aktualizacja.md."""

from __future__ import annotations

import hashlib
import json
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
# Long enough to see the progress and send the refused requests; fetching from the local "origin" takes milliseconds.
PACING_MS = 4000
# Long enough to see the tab wait for the new Centrum; the restarted scripted Centrum starts in about a second.
RESTART_PACING_MS = 3000
# The restart guardian waits up to 60 s for the new Centrum; the tab reloads when it answers.
RESTART_TIMEOUT_MS = 60_000


def _head(clone: Path) -> str:
    result = subprocess.run(
        ["git", "-C", str(clone), "rev-parse", "HEAD"], capture_output=True, text=True, check=True
    )
    return result.stdout.strip()


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


def _config_digest(run: Run) -> dict[str, str]:
    """Every file of the run's ``config/`` (Dad's files) by content, without the result file the guardian leaves."""

    config = run.root / "config"
    return {
        path.relative_to(config).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(config.rglob("*"))
        if path.is_file() and path.name != "centrum-aktualizacja.json"
    }


def drive_update(run: Run, page: Page) -> None:
    tool = run.fixture["tool"]
    clone, first, newest = Path(tool["clone"]), tool["first"], tool["newest"]
    github = run.root / "github"
    github.mkdir(exist_ok=True)
    main_commit = github / "main-commit.txt"
    pacing = run.root / "pacing" / "aktualizacja-ms.txt"
    pacing.parent.mkdir(exist_ok=True)
    restart_pacing = run.root / "pacing" / "ponowny-start-ms.txt"

    run.step(FEATURE, "aktualizacja-jest-nowsza")
    print("  harness: `main` on the scripted GitHub is the local origin's newest commit", flush=True)
    main_commit.write_text(newest, encoding="utf-8")
    try:
        run.check(_head(clone) == first, "the run's tool clone stands on the first commit")
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

        run.step(FEATURE, "aktualizacja-postep")
        print(f"  harness: each Aktualizacja narzędzia waits {PACING_MS} ms before it looks for Git", flush=True)
        pacing.write_text(str(PACING_MS), encoding="utf-8")
        print(f"  harness: the restarted Centrum waits {RESTART_PACING_MS} ms before it starts", flush=True)
        restart_pacing.write_text(str(RESTART_PACING_MS), encoding="utf-8")
        before_health = run.api("/api/health", "aktualizacja-health-przed")
        config_before = _config_digest(run)
        page.evaluate("window.przedPonownymStartem = true")
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
            [entry.split(" ")[0] for entry in _update_entries(run)] == ["aktualizacja-start"],
            "the double click started exactly one Aktualizacja narzędzia",
        )
    finally:
        pacing.unlink(missing_ok=True)

    try:
        run.step(FEATURE, "aktualizacja-ponowny-start")
        expect(card.get_by_role("status").filter(has_text=RESTARTING)).to_be_visible(timeout=20_000)
        expect(card.get_by_role("button", name=BUTTON, exact=True)).to_be_disabled()
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
        run.check(page.evaluate("window.przedPonownymStartem === undefined"), "the tab reloaded by itself")
        card = _tool_card(page)
        expect(card).to_contain_text(newest[:7])
        expect(card).to_contain_text("Aktualna")
        expect(card.get_by_role("button", name=BUTTON, exact=True)).to_be_enabled()
        health = run.api("/api/health", "aktualizacja-health-po")
        run.check(
            health["commit"] == newest and health["instance"] != before_health["instance"],
            "a new Centrum answers on the same address, in the new commit",
        )
        view = run.api("/api/tool-update", "aktualizacja-zaktualizowano")
        run.check(view == {"state": "updated", "commit": newest[:7]}, "the new Centrum reports the update's result")
        run.check(_head(clone) == newest, "the clone moved forward to the origin's newest commit")
        configuration = run.api("/api/configuration", "aktualizacja-konfiguracja-po")
        run.check(
            (configuration["commit"], configuration["freshness"]) == (newest[:7], "current"),
            "Konfiguracja reports the new commit as current",
        )
        run.check(
            not (run.root / "config" / "centrum-aktualizacja.json").exists(),
            "the new Centrum read the guardian's result once and removed it",
        )
        run.check(_config_digest(run) == config_before, "Dad's files in config/ are untouched")
        entries = _update_entries(run)
        run.check(
            entries == [f"aktualizacja-start przed={first}", f"aktualizacja-koniec wynik=ok przed={first} po={newest} biblioteki=nie"],
            "the Centrum log has the start and the end with both commits, and no path",
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
    finally:
        main_commit.unlink(missing_ok=True)

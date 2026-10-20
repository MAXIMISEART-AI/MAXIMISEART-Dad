"""Drive features/pomiar-u-taty.md."""

from __future__ import annotations

import json
import re
import urllib.request

from playwright.sync_api import Page, Response, expect

from drive.common import Run, ensure_files_set

FEATURE = "pomiar-u-taty"
# Pages of the sidebar menu: contract id and the heading Dad reads.
PAGES = (("okresy", "Okresy"), ("uruchomienia", "Uruchomienia"), ("metryki", "Metryki"), ("konfiguracja", "Konfiguracja"))
SERVER_TIMING = re.compile(r"centrum;dur=\d+(\.\d+)?")
TIMED_REQUEST = re.compile(r"[a-zA-Z]+:\d+/\d+")
PERIOD_TOKEN = re.compile(r"\d{2}_\d{2}_\d{2}_\d{4}")


def _log_lines(run: Run) -> list[str]:
    log = run.root / "logs" / "centrum-rozliczen.log"
    return log.read_text(encoding="utf-8").splitlines() if log.exists() else []


def _timings(run: Run, since: int) -> list[dict[str, str]]:
    """Facts of every ``pomiar`` entry after the first ``since`` log lines."""

    entries = []
    for line in _log_lines(run)[since:]:
        _, event, *facts = line.split(" ")
        if event == "pomiar":
            entries.append(dict(fact.split("=", 1) for fact in facts))
    return entries


def _wait_for_timings(run: Run, since: int, count: int, message: str) -> list[dict[str, str]]:
    run.wait_for(lambda: len(_timings(run, since)) >= count, message)
    return _timings(run, since)


def _check_requests(run: Run, timing: dict[str, str], where: str) -> None:
    requests = timing.get("zapytania", "").split(",")
    run.check(
        requests != [""] and all(TIMED_REQUEST.fullmatch(request) for request in requests),
        f"{where}: every API request has its operation, browser time and server time ({timing.get('zapytania')})",
    )


def drive_measurement(run: Run, page: Page) -> None:
    server_timings: list[dict[str, str]] = []

    def remember(response: Response) -> None:
        if "/api/" in response.url:
            server_timings.append({"url": response.url, "server-timing": response.headers.get("server-timing", "")})

    page.goto(run.url)
    ensure_files_set(run, page)

    run.step(FEATURE, "pomiar-zimny-start")
    page.on("response", remember)
    for page_id, title in PAGES:
        since = len(_log_lines(run))
        page.goto("about:blank")
        page.goto(f"{run.url}#/{page_id}")
        expect(page.get_by_role("heading", name=title, level=1)).to_be_visible()
        [timing] = _wait_for_timings(run, since, 1, f"the cold start of {title} is in the Centrum log")
        run.check(
            (timing["widok"], timing["strona"]) == ("zimny-start", page_id),
            f"the entry names the cold start of {page_id}",
        )
        run.check(
            all(timing.get(key, "").isdigit() for key in ("gotowe_ms", "fcp_ms", "szkielet_ms")),
            f"{page_id}: ready content, FCP and skeleton time in milliseconds",
        )
        _check_requests(run, timing, page_id)
    page.remove_listener("response", remember)

    run.step(FEATURE, "pomiar-server-timing")
    (run.evidence / "api" / "pomiar-server-timing.json").write_text(
        json.dumps(server_timings, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    run.check(len(server_timings) > 0, "the browser read API answers during the cold starts")
    run.check(
        all(SERVER_TIMING.fullmatch(answer["server-timing"]) for answer in server_timings),
        "every API answer the browser got has Server-Timing with only the handling time",
    )

    run.step(FEATURE, "pomiar-przejscia-w-menu")
    since = len(_log_lines(run))
    route = [*PAGES[1:], PAGES[0]]
    for _, title in route:
        page.get_by_role("link", name=title, exact=True).click()
        expect(page.get_by_role("heading", name=title, level=1)).to_be_visible()
        page.wait_for_timeout(300)  # Dad reads the page before the next click
    timings = _wait_for_timings(run, since, len(route), "every menu click is in the Centrum log")
    run.check(
        [(timing["widok"], timing["strona"]) for timing in timings] == [("przejscie-w-menu", page_id) for page_id, _ in route],
        "one menu-click entry per page, in the order of the clicks",
    )
    run.check(all("fcp_ms" not in timing for timing in timings), "menu clicks carry no FCP")
    for timing in timings:
        _check_requests(run, timing, f"menu click to {timing['strona']}")

    run.step(FEATURE, "pomiar-bez-sladu")
    expect(page.get_by_role("alert")).to_have_count(0)
    expect(page.get_by_role("dialog")).to_have_count(0)
    run.capture(page, "80-pomiar-bez-sladu")
    entries = [line for line in _log_lines(run) if line.split(" ")[1:2] == ["pomiar"]]
    (run.evidence / "api" / "pomiar-dziennik.txt").write_text("\n".join(entries) + "\n", encoding="utf-8")
    run.check(
        not any(str(run.root) in entry or "/api/" in entry or PERIOD_TOKEN.search(entry) for entry in entries),
        "the measurement entries hold no path, address or period token",
    )

    run.step(FEATURE, "pomiar-obcy-origin")
    since = len(_log_lines(run))
    body = json.dumps(
        {"kind": "navigation", "page": "okresy", "ready_ms": 1, "fcp_ms": None, "skeleton_ms": 0, "requests": []}
    ).encode()
    foreign = urllib.request.Request(
        run.url.rstrip("/") + "/api/view-timings",
        data=body,
        method="POST",
        headers={"Origin": "http://zly.example", "Content-Type": "application/json"},
    )
    run.check(run.refused(foreign, "pomiar-obcy-origin") == 403, "a measurement from a foreign Origin is refused")
    run.check(_timings(run, since) == [], "the refused measurement adds no entry")

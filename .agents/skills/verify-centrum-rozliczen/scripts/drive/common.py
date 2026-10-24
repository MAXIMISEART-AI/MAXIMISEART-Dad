"""The drive's shared run state and the helpers more than one feature uses."""

from __future__ import annotations

from collections.abc import Callable, Iterator
from contextlib import contextmanager
from datetime import date, timedelta
from fnmatch import fnmatchcase
import json
from pathlib import Path
import subprocess
import time
import urllib.error
import urllib.request
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo

from playwright.sync_api import Locator, Page, Request, expect
import yaml

REPO_ROOT = Path(__file__).resolve().parents[5]
# Pages of the sidebar menu in its order: contract id (`#/<id>`, `PageId`) and the heading Dad reads.
PAGES = {"okresy": "Okresy", "uruchomienia": "Uruchomienia", "metryki": "Metryki", "konfiguracja": "Konfiguracja"}
# Dad's computer runs on Polish time; dates in Centrum are shown in the browser's time zone.
DAD_TIME_ZONE = ZoneInfo("Europe/Warsaw")
# The fixture's last complete period, without a Folder okresu.
LAST_COMPLETE = "06_12_10_2026"
# The fixture puts this marker in every synthetic workbook row; it must never reach the Centrum log.
ROW_MARKER = "CENTRUM-SYN-ROW"
# Dad double-clicks out of habit and double-taps the touch screen: the second click comes within milliseconds,
# so a repeated request is sent well within this, and an answer reaches the screen (a refusal as a toast) too.
REPEAT_SETTLE_MS = 300


class DriveFailure(Exception):
    pass


class Run:
    def __init__(self, root: Path, url: str, evidence: Path) -> None:
        self.root = root
        self.url = url
        self.evidence = evidence
        self.fixture = json.loads((root / "fixture.json").read_text(encoding="utf-8"))
        for name in ("screenshots", "aria", "api", "state"):
            (evidence / name).mkdir(parents=True, exist_ok=True)

    def step(self, feature: str, name: str) -> None:
        print(f"STEP {feature} | {name}", flush=True)

    def check(self, condition: bool, message: str) -> None:
        if not condition:
            raise DriveFailure(message)
        print(f"  ok: {message}", flush=True)

    def capture(self, page: Page, name: str, *, full_page: bool = True, live: bool = False) -> None:
        """Screenshot and ARIA snapshot after every running transition has finished.

        ``live`` captures while a stage runs: its indeterminate bar loops forever, so do not wait.
        """

        if not live:
            page.wait_for_function(
                "document.getAnimations().every((animation) => animation.playState !== 'running')"
            )
        page.screenshot(path=self.evidence / "screenshots" / f"{name}.png", full_page=full_page)
        snapshot = page.locator("body").aria_snapshot()
        (self.evidence / "aria" / f"{name}.txt").write_text(snapshot + "\n", encoding="utf-8")

    def api(self, path: str, name: str) -> dict[str, object]:
        with urllib.request.urlopen(self.url.rstrip("/") + path, timeout=10) as response:
            body = json.load(response)
        (self.evidence / "api" / f"{name}.json").write_text(
            json.dumps(body, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        assert isinstance(body, dict)
        return body

    def refused(self, request: urllib.request.Request, name: str) -> int:
        try:
            with urllib.request.urlopen(request, timeout=10) as response:
                status, body = int(response.status), response.read()
        except urllib.error.HTTPError as error:
            status, body = error.code, error.read()
        record = {"status": status, "body": json.loads(body or b"null")}
        (self.evidence / "api" / f"{name}.json").write_text(
            json.dumps(record, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        return status

    def answer_picker(self, path: str) -> None:
        (self.root / "picker" / "answer.txt").write_text(path, encoding="utf-8")

    def lines(self, name: str) -> list[dict[str, str]]:
        log = self.root / name
        if not log.exists():
            return []
        return [json.loads(line) for line in log.read_text(encoding="utf-8").splitlines() if line]

    def settings_text(self) -> str:
        settings = Path(self.fixture["settings"])
        return settings.read_text(encoding="utf-8") if settings.exists() else ""

    def remembered(self, key: str) -> object:
        """One value of the settings file as Centrum wrote it (``folder_okresow``, ``rejestr_zlecen``, ``motyw``)."""

        document = yaml.safe_load(self.settings_text()) or {}
        assert isinstance(document, dict)
        return document.get(key)

    def wait_for(self, condition: Callable[[], bool], message: str, timeout_s: float = 10) -> None:
        deadline = time.monotonic() + timeout_s
        while not condition():
            if time.monotonic() > deadline:
                raise DriveFailure(f"timed out: {message}")
            time.sleep(0.1)
        print(f"  ok: {message}", flush=True)


def choose_periods_directory(run: Run, page: Page) -> None:
    run.answer_picker(run.fixture["periods_directory"])
    page.get_by_role("button", name="Wskaż folder okresów", exact=True).click()
    expect(page.get_by_role("table", name="Tablica okresów")).to_be_visible()


def ensure_files_set(run: Run, page: Page) -> None:
    """Points Centrum to the fixture's folder okresów and Rejestr zleceń unless a feature before did."""

    settings = run.api("/api/settings", "ustawienia-przed-uruchomieniem")
    if settings["periods_directory"] == {"state": "not_set"}:
        choose_periods_directory(run, page)
    if settings["order_register"] == {"state": "not_set"}:
        run.answer_picker(run.fixture["order_register"])
        page.get_by_role("button", name="Wskaż Rejestr zleceń", exact=True).click()
        run.wait_for(lambda: run.remembered("rejestr_zlecen") == run.fixture["order_register"], "Rejestr zleceń set")


def period_choice(token: str, status: str) -> str:
    """A period in the combobox ``Okres`` as Dad reads it: ``wt 06.10 – pon 12.10 · ostatni pełny · 06_12_10_2026``.

    The days come from the token itself (the Monday's day, month and year; the Tuesday six days earlier), not from
    the server's answer, so a wrong date on screen fails the drive.
    """

    _, monday_day, month, year = token.split("_")
    monday = date(int(year), int(month), int(monday_day))
    tuesday = monday - timedelta(days=6)
    return f"wt {tuesday:%d.%m} – pon {monday:%d.%m} · {status} · {token}"


def period_row(page: Page, token: str) -> Locator:
    return page.get_by_role("table", name="Tablica okresów").get_by_role("row").filter(has_text=token)


def last_opened_is(run: Run, path: Path) -> Callable[[], bool]:
    return lambda: run.lines("opened.jsonl")[-1:] == [{"path": str(path)}]


def history_rows(page: Page) -> Locator:
    return page.get_by_role("table", name="Historia Uruchomień procesu").get_by_role("row")


def period_files(run: Run) -> list[Path]:
    folder = Path(run.fixture["periods_directory"]) / LAST_COMPLETE
    return [
        folder / f"Rozliczenie wew. {LAST_COMPLETE}.xlsx",
        folder / f"Rozliczenie {LAST_COMPLETE} - zbiorcze.xlsx",
    ]


def current_run(run: Run, name: str) -> dict[str, object]:
    view = run.api("/api/runs/current", name)
    assert isinstance(view, dict)
    return view


def finished_result(run: Run, name: str) -> dict[str, object]:
    # One answer for both the state and the result: a second read could already see the next Uruchomienie.
    seen: dict[str, object] = {}

    def finished() -> bool:
        seen.clear()
        seen.update(current_run(run, name))
        return seen["state"] == "finished"

    run.wait_for(finished, "the Uruchomienie procesu finished")
    result = seen["result"]
    assert isinstance(result, dict)
    return result


def figure(shown: object, label: str) -> int:
    """Value of the number labelled ``label`` in a server view's ``figures`` (live progress or result summary)."""

    assert isinstance(shown, dict)
    [value] = [entry["value"] for entry in shown["figures"] if entry["label"] == label]
    assert isinstance(value, int)
    return value


def stop_banner(page: Page) -> Locator:
    """The three-part stop banner of the Uruchomienie procesu shown on Uruchomienia."""

    return page.get_by_role("region", name="Podgląd na żywo").get_by_label("Zatrzymanie")


def diagnosis_answer(run: Run, run_id: str, name: str) -> dict[str, object]:
    """The server's Diagnoza for ``run_id`` as the browser gets it, kept in ``api/``."""

    request = urllib.request.Request(
        run.url.rstrip("/") + f"/api/runs/{run_id}/diagnosis",
        data=b"",
        method="POST",
        headers={"Origin": run.url.rstrip("/")},
    )
    run.check(run.refused(request, name) == 200, "the server answers the Diagnoza")
    record = json.loads((run.evidence / "api" / f"{name}.json").read_text(encoding="utf-8"))
    body = record["body"]
    assert isinstance(body, dict)
    return body


@contextmanager
def sent_requests(page: Page, method: str, path: str) -> Iterator[list[Request]]:
    """Requests the page sends with ``method`` to ``path`` (a glob such as ``/api/runs/*/decision``) in the block."""

    sent: list[Request] = []

    def record(request: Request) -> None:
        if request.method == method and fnmatchcase(urlsplit(request.url).path, path):
            sent.append(request)

    page.on("request", record)
    try:
        yield sent
    finally:
        page.remove_listener("request", record)


def settle(page: Page, sent: list[Request]) -> int:
    """Waits until a repeated click would have sent its request and every answer reached the screen; the count."""

    page.wait_for_timeout(REPEAT_SETTLE_MS)
    for request in list(sent):
        request.response()
    page.wait_for_timeout(REPEAT_SETTLE_MS)
    return len(sent)


def error_toasts(page: Page) -> Locator:
    """Error notifications („Nie udało się …”), also those stacked behind the newest one."""

    return page.get_by_role("region", name="Notifications").get_by_role("dialog", name="Nie udało się")


def served_version(run: Run) -> tuple[str, str | None]:
    """The tool commit the served Centrum runs and the day the run's tool clone moved to it, as Git reports them.

    The commit is the clone's ``HEAD`` unless a feature pinned another one in
    ``<root>/github/tool-commit.txt``. The day (``YYYY-MM-DD``) is the last ``HEAD`` reflog entry's, in that entry's
    time zone, when that entry leads to the commit, else ``None``. Neither depends on how Centrum reads ``.git``.
    """

    def git(*arguments: str) -> str:
        return subprocess.run(
            ["git", "-C", run.fixture["tool"]["clone"], *arguments], capture_output=True, text=True, check=True
        ).stdout.strip()

    pinned = run.root / "github" / "tool-commit.txt"
    commit = pinned.read_text(encoding="utf-8").strip() if pinned.exists() else git("rev-parse", "HEAD")
    entry_commit, _, selector = git("log", "--walk-reflogs", "-1", "--date=short", "--format=%H %gd").partition(" ")
    return commit, selector.removeprefix("HEAD@{").removesuffix("}") if entry_commit == commit else None


def version_line(commit: str, since: str | None) -> str:
    """The version line Dad reads in the card ``Narzędzie``: ``Wersja 1a2b3c4 od 20.10.2026``."""

    if since is None:
        return f"Wersja {commit[:7]}"
    year, month, day = since.split("-")
    return f"Wersja {commit[:7]} od {day}.{month}.{year}"


def release_only(origin: Path, commit: str) -> None:
    """GitHub's only Wydanie, as Centrum's Aktualizacja narzędzia sees it, is ``commit``: tag ``v0.1.0`` in ``origin``.

    A real Wydanie never moves; the harness withdraws every tag instead, so one tag is always the newest. ``main``
    moves to ``commit`` too, because Centrum refuses a Wydanie that is not on ``main`` and the run's versions sit on
    side branches of the origin.
    """

    def git(*args: str) -> str:
        return subprocess.run(["git", "-C", str(origin), *args], capture_output=True, text=True, check=True).stdout

    tags = git("tag", "--list", "v*").split()
    if tags:
        git("tag", "--delete", *tags)
    git("tag", "v0.1.0", commit)
    git("update-ref", "refs/heads/main", commit)

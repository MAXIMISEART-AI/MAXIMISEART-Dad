"""The drive's shared run state and the helpers more than one feature uses."""

from __future__ import annotations

from collections.abc import Callable
import json
from pathlib import Path
import time
import urllib.error
import urllib.request
from zoneinfo import ZoneInfo

from playwright.sync_api import Locator, Page, expect
import yaml

REPO_ROOT = Path(__file__).resolve().parents[5]
# Dad's computer runs on Polish time; dates in Centrum are shown in the browser's time zone.
DAD_TIME_ZONE = ZoneInfo("Europe/Warsaw")
# The period the CLI step names: the fixture's last complete period, without a Folder okresu.
LAST_COMPLETE_FOR_CLI = "06_12_10_2026"
# The fixture puts this marker in every synthetic workbook row; it must never reach the Centrum log.
ROW_MARKER = "CENTRUM-SYN-ROW"


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


def period_row(page: Page, token: str) -> Locator:
    return page.get_by_role("table", name="Tablica okresów").get_by_role("row").filter(has_text=token)


def last_opened_is(run: Run, path: Path) -> Callable[[], bool]:
    return lambda: run.lines("opened.jsonl")[-1:] == [{"path": str(path)}]


def history_rows(page: Page) -> Locator:
    return page.get_by_role("table", name="Historia Uruchomień procesu").get_by_role("row")


def period_files(run: Run) -> list[Path]:
    folder = Path(run.fixture["periods_directory"]) / LAST_COMPLETE_FOR_CLI
    return [
        folder / f"Rozliczenie wew. {LAST_COMPLETE_FOR_CLI}.xlsx",
        folder / f"Rozliczenie {LAST_COMPLETE_FOR_CLI} - zbiorcze.xlsx",
    ]


def current_run(run: Run, name: str) -> dict[str, object]:
    view = run.api("/api/runs/current", name)
    assert isinstance(view, dict)
    return view


def finished_result(run: Run, name: str) -> dict[str, object]:
    run.wait_for(lambda: current_run(run, name)["state"] == "finished", "the Uruchomienie procesu finished")
    result = current_run(run, name)["result"]
    assert isinstance(result, dict)
    return result


def figure(shown: object, label: str) -> int:
    """Value of the number labelled ``label`` in a server view's ``figures`` (live progress or result summary)."""

    assert isinstance(shown, dict)
    [value] = [entry["value"] for entry in shown["figures"] if entry["label"] == label]
    assert isinstance(value, int)
    return value

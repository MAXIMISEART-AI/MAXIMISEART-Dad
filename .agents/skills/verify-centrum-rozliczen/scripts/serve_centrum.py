"""Serve the real Centrum rozliczeń for one verification run on 127.0.0.1.

This is the production app (``create_app`` + ``serve`` from ``rozliczenia.centrum``)
with run-local inputs: the settings file, the configuration directory
(konfiguracja wykonawców and the three Wzorce), and both metrics files live in
the run root (never Dad's files next to the tool), and the platform adapter,
the production boundary for Dad's computer, is scripted:

- the native file and folder pickers answer with the path written to
  ``<root>/picker/answer.txt`` (consumed by the next picker; no file = Dad
  cancelled) and log each dialog title to ``<root>/dialogs.jsonl``;
- opening a file in Excel or a folder in Explorer appends the path to
  ``<root>/opened.jsonl`` instead of launching an application.

The Diagnoza's two boundaries beyond Dad's files are scripted too, so the
verification never reaches GitHub and checks OneDrive on every system:

- the commit of `main` on GitHub is the tool's own commit (up to date) unless
  ``<root>/github/main-commit.txt`` names another one; while
  ``<root>/github/brak-sieci`` exists there is no network. The tool's own
  commit is the real one (``tool_commit``) from this checkout unless
  ``<root>/github/tool-commit.txt`` names another one (Dad updated the tool);
- a file whose full path is a line of ``<root>/onedrive/tylko-w-chmurze.txt``
  has the Windows attribute of a OneDrive file „tylko online”.

The skrzynka Zgłoszeń (Maks's private repository on GitHub at Dad's) is a
directory, ``<root>/skrzynka-zgloszen/``: each Zgłoszenie Dad sends becomes
``<number>.json`` with its title, body, label, and ``state`` (``open``; the
drive may edit it to ``closed``, which Centrum reads as Maks closing the
Zgłoszenie). The open Zgłoszenie of a problem is the ``open`` file whose body
has its fingerprint line. The key is never written there. While
``<root>/skrzynka-zgloszen/brak-sieci`` exists the skrzynka is unreachable.
Each question about the state of sent Zgłoszenia appends its numbers to
``<root>/skrzynka-zgloszen-zapytania.jsonl``.

Centrum asks the skrzynka for the state of sent Zgłoszenia at most once per 10
minutes of its monotonic clock; ``<root>/zegar/przesuniecie-min.txt`` moves that
clock forward by the given minutes, so the drive need not wait.

One harness-only pacing hook: while ``<root>/pacing/szablony-ms.txt`` exists,
each Szablon pracownika of a Przebieg rozliczeń RUN waits that many
milliseconds before it is written. The synthetic Szablony take milliseconds,
so without it the live Szablony pracowników progress and the refused closing
during the Uruchomienie could not be observed. Results are unchanged.

One harness-only fault hook: while ``<root>/awaria/odczyt-rejestru`` exists,
reading the Rejestr zleceń raises an exception the process does not expect, so
the drive can show Dad's path after a nieoczekiwany wyjątek. No synthetic file
causes one, because every known problem has its own Komunikat.

Once the port is bound, ``<root>/server.json`` records this process and URL.
The Centrum log goes to ``<root>/logs/centrum-rozliczen.log``, and the button
„Zamknij Centrum rozliczeń” stops this process the way it stops Dad's.
"""

from __future__ import annotations

import argparse
from collections.abc import Callable, Iterable, Sequence
from datetime import date
import json
import os
from pathlib import Path
import sys
import threading
import time
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(REPO_ROOT / "src"))

from rozliczenia import preparation_register, template_settlement  # noqa: E402
from rozliczenia.centrum.app import create_app  # noqa: E402
from rozliczenia.centrum.cloud_files import CloudFiles  # noqa: E402
from rozliczenia.centrum.configuration import ConfigurationFiles  # noqa: E402
from rozliczenia.centrum.log import CentrumLog  # noqa: E402
from rozliczenia.centrum.metrics import MetricsFiles  # noqa: E402
from rozliczenia.centrum.report_box import (  # noqa: E402
    LABEL,
    FindOutcome,
    IssueState,
    Report,
    SendOutcome,
    Sent,
    StatesOutcome,
    Unreachable,
    fingerprint_line,
)
from rozliczenia.centrum.server import listen_locally, serve  # noqa: E402
from rozliczenia.centrum.shutdown import Shutdown  # noqa: E402
from rozliczenia.centrum.tool_freshness import ToolFreshness  # noqa: E402
from rozliczenia.centrum.version import tool_commit  # noqa: E402
from rozliczenia.domain import WorkerResult  # noqa: E402
from rozliczenia.workbook_files import ExcelRow  # noqa: E402


class ScriptedPlatform:
    def __init__(self, root: Path) -> None:
        self._root = root
        self._lock = threading.Lock()

    def _log(self, name: str, record: dict[str, str]) -> None:
        with self._lock, (self._root / name).open("a", encoding="utf-8") as log:
            log.write(json.dumps(record, ensure_ascii=False) + "\n")

    def _answer(self, title: str) -> Path | None:
        self._log("dialogs.jsonl", {"title": title})
        answer = self._root / "picker" / "answer.txt"
        if not answer.exists():
            return None
        chosen = answer.read_text(encoding="utf-8").strip()
        answer.unlink()
        return Path(chosen)

    def open_path(self, path: Path) -> None:
        self._log("opened.jsonl", {"path": str(path)})

    def choose_file(self, title: str, filetypes: Sequence[tuple[str, str]]) -> Path | None:
        return self._answer(title)

    def choose_folder(self, title: str) -> Path | None:
        return self._answer(title)


class FileReportBox:
    """The skrzynka Zgłoszeń as a directory of ``<number>.json`` files (see the module doc)."""

    def __init__(self, directory: Path) -> None:
        self._directory = directory
        self._lock = threading.Lock()

    def send(self, report: Report, *, key: str) -> SendOutcome:
        if (self._directory / "brak-sieci").exists():
            return Unreachable()
        with self._lock:
            self._directory.mkdir(parents=True, exist_ok=True)
            number = len(list(self._directory.glob("*.json"))) + 1
            issue = {"number": number, "title": report.title, "body": report.body, "labels": [LABEL], "state": "open"}
            (self._directory / f"{number}.json").write_text(
                json.dumps(issue, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
            )
        return Sent(number)

    def find_open(self, fingerprint: str, *, key: str) -> FindOutcome:
        if (self._directory / "brak-sieci").exists():
            return Unreachable()
        line = fingerprint_line(fingerprint)
        with self._lock:
            issues = [json.loads(path.read_text(encoding="utf-8")) for path in self._directory.glob("*.json")]
        found = [issue["number"] for issue in issues if issue["state"] == "open" and line in issue["body"].splitlines()]
        return min(found, default=None)

    def states(self, numbers: Sequence[int], *, key: str) -> StatesOutcome:
        with self._lock, self._directory.with_name(f"{self._directory.name}-zapytania.jsonl").open("a") as asked:
            asked.write(json.dumps({"numbers": list(numbers)}) + "\n")
        if (self._directory / "brak-sieci").exists():
            return Unreachable()
        states: dict[int, IssueState] = {}
        with self._lock:
            for number in numbers:
                issue = json.loads((self._directory / f"{number}.json").read_text(encoding="utf-8"))
                states[number] = "closed" if issue["state"] == "closed" else "open"
        return states


def _scripted_github(root: Path) -> ToolFreshness:
    def local_commit() -> str | None:
        chosen = root / "github" / "tool-commit.txt"
        return chosen.read_text(encoding="utf-8").strip() if chosen.exists() else tool_commit()

    def main_commit() -> str | None:
        if (root / "github" / "brak-sieci").exists():
            return None
        chosen = root / "github" / "main-commit.txt"
        return chosen.read_text(encoding="utf-8").strip() if chosen.exists() else tool_commit()

    return ToolFreshness(local=local_commit, main=main_commit)


def _scripted_clock(root: Path) -> Callable[[], float]:
    def clock() -> float:
        moved = root / "zegar" / "przesuniecie-min.txt"
        return time.monotonic() + (float(moved.read_text(encoding="utf-8")) * 60 if moved.exists() else 0.0)

    return clock


def _scripted_onedrive(root: Path) -> CloudFiles:
    normal, online_only = 0x80, 0x400000  # FILE_ATTRIBUTE_NORMAL, FILE_ATTRIBUTE_RECALL_ON_DATA_ACCESS

    def attributes(path: Path) -> int:
        listed = root / "onedrive" / "tylko-w-chmurze.txt"
        lines = listed.read_text(encoding="utf-8").splitlines() if listed.exists() else []
        return online_only if str(path) in lines else normal

    return CloudFiles(read_attributes=attributes)


def _pace_worker_templates(root: Path) -> None:
    """Slow each written Szablon pracownika while ``<root>/pacing/szablony-ms.txt`` exists (see the module doc)."""

    write = template_settlement.process_template

    def paced(worker_name: str, template_path: Path, target_path: Path, rows: Iterable[ExcelRow]) -> WorkerResult:
        pacing = root / "pacing" / "szablony-ms.txt"
        if pacing.exists():
            time.sleep(int(pacing.read_text(encoding="utf-8")) / 1000)
        return write(worker_name, template_path, target_path, rows)

    template_settlement.process_template = paced


def _fail_register_reading(root: Path) -> None:
    """Make reading the Rejestr zleceń raise while ``<root>/awaria/odczyt-rejestru`` exists (see the module doc)."""

    read = preparation_register.read_register

    def failing(*args: Any, **kwargs: Any) -> Any:
        if (root / "awaria" / "odczyt-rejestru").exists():
            raise RuntimeError("synthetic unexpected failure")
        return read(*args, **kwargs)

    preparation_register.read_register = failing


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--root", required=True, help="Run root created by create_centrum_fixture.py.")
    parser.add_argument("--port", type=int, required=True, help="Free port on 127.0.0.1.")
    args = parser.parse_args(argv)
    root = Path(args.root).resolve()
    fixture = json.loads((root / "fixture.json").read_text(encoding="utf-8"))
    today = date.fromisoformat(fixture["today"])
    metrics = MetricsFiles(
        preparation=Path(fixture["metrics"]["preparation"]), settlement=Path(fixture["metrics"]["settlement"])
    )
    configuration = {name: Path(path) for name, path in fixture["configuration"].items()}
    log = CentrumLog(root / "logs" / "centrum-rozliczen.log")
    shutdown = Shutdown(log)
    _pace_worker_templates(root)
    _fail_register_reading(root)
    app = create_app(
        settings_path=Path(fixture["settings"]),
        platform=ScriptedPlatform(root),
        log=log,
        shutdown=shutdown,
        today=lambda: today,
        metrics_files=metrics,
        configuration_files=ConfigurationFiles(**configuration),
        tool_freshness=_scripted_github(root),
        cloud_files=_scripted_onedrive(root),
        report_box=FileReportBox(root / "skrzynka-zgloszen"),
        clock=_scripted_clock(root),
    )

    def record_bound_server(url: str) -> None:
        record = {"pid": os.getpid(), "port": args.port, "url": url}
        (root / "server.json").write_text(json.dumps(record), encoding="utf-8")
        print(f"SERVING {url}", flush=True)

    return serve(app, listener=listen_locally(args.port), on_ready=record_bound_server, shutdown=shutdown, log=log)


if __name__ == "__main__":
    raise SystemExit(main())

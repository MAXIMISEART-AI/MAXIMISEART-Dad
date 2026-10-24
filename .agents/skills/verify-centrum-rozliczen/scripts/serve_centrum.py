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

- the commit of the newest Wydanie on GitHub is the tool's own commit (up to date) unless
  ``<root>/github/main-commit.txt`` names another one; while
  ``<root>/github/brak-sieci`` exists there is no network. The tool is the
  run's synthetic clone ``<root>/aktualizacja/klon``: its own commit is the
  clone's ``HEAD`` (``tool_commit``) unless ``<root>/github/tool-commit.txt``
  names another one (Dad updated the tool), and the day it is on that commit
  comes from the clone's ``HEAD`` reflog (``commit_since``);
- a file whose full path is a line of ``<root>/onedrive/tylko-w-chmurze.txt``
  has the Windows attribute of a OneDrive file „tylko online”.

Aktualizacja narzędzia moves that clone with real Git, fetching from the
run's local "origin" ``<root>/aktualizacja/origin.git`` instead of GitHub, so no
Centrum of a verification run ever updates the checkout it runs from. After a
successful update this Centrum closes itself and the real restart guardian runs
the clone's ``run_centrum.py``, a fixture shim that runs this script again with
the same run root and port: the restarted Centrum keeps every scripted boundary
and rewrites ``server.json`` with its own pid.

The skrzynka Zgłoszeń (Maks's private repository on GitHub at Dad's) is a
directory, ``<root>/skrzynka-zgloszen/``: each issue Centrum opens (a Zgłoszenie
Dad sends, or a Kontrola ilości Centrum sends by itself) becomes
``<number>.json`` with its title, body, label, comments, and ``state`` (``open``; the
drive may edit it to ``closed``, which Centrum reads as Maks closing the
Zgłoszenie). Asked for the issues with a label, the skrzynka lists the files
with that label, only the ``open`` ones unless closed issues are asked for too;
Centrum takes the newest one whose body has its exact line (the fingerprint
line of a Zgłoszenie's problem, or the period line of a Kontrola ilości, which
then goes into that file's ``comments``). The key is never written
there. While
``<root>/skrzynka-zgloszen/brak-sieci`` exists the skrzynka is unreachable.
Each question about the state of sent Zgłoszenia appends its numbers to
``<root>/skrzynka-zgloszen-zapytania.jsonl``. While ``<root>/pacing/skrzynka-ms.txt``
exists, the skrzynka waits that many milliseconds before it opens an issue, like
GitHub over a slow connection, so the drive can see that Centrum starts without
waiting for the Kontrole ilości it sends again at start.

Centrum asks the skrzynka for the state of sent Zgłoszenia at most once per 10
minutes of its monotonic clock; ``<root>/zegar/przesuniecie-min.txt`` moves that
clock forward by the given minutes, so the drive need not wait.

One harness-only pacing hook: while ``<root>/pacing/szablony-ms.txt`` exists,
each Szablon pracownika of a Przebieg rozliczeń RUN waits that many
milliseconds before it is written. The synthetic Szablony take milliseconds,
so without it the live Szablony pracowników progress and the refused closing
during the Uruchomienie could not be observed. Results are unchanged.

One more pacing hook: while ``<root>/pacing/aktualizacja-ms.txt`` exists, each
Aktualizacja narzędzia waits that many milliseconds before it looks for Git.
Fetching from the local "origin" takes milliseconds, so without it the progress
and the refusals during an update could not be observed. Results are unchanged.
Likewise, while ``<root>/pacing/instalacja-ms.txt`` exists, each installation of
libraries waits that many milliseconds before it starts.

Libraries are installed by the production installer (``pip_install``: this
Python's ``-m pip``), but pip is offline: ``PIP_NO_INDEX`` is set for this
process, so an installation never reaches PyPI and fails when it needs a library
that is not installed. The run's virtual environment may have no pip at all;
then the installation fails the same way.

One harness-only fault hook: while ``<root>/awaria/odczyt-rejestru`` exists,
reading the Rejestr zleceń raises an exception the process does not expect, so
the drive can show Dad's path after a nieoczekiwany wyjątek. The Uruchomienie
procesu and its Diagnoza both look the reader up as
``preparation_register.read_register``, so the fault reaches the Diagnoza too,
as a real one that does not go away would. No synthetic file causes one,
because every known problem has its own Komunikat.

Once the port is bound, ``<root>/server.json`` records this process and URL.
The Centrum log goes to ``<root>/logs/centrum-rozliczen.log``, and the button
„Zamknij Centrum rozliczeń” stops this process the way it stops Dad's.
"""

from __future__ import annotations

import argparse
from collections.abc import Callable, Sequence
from dataclasses import replace
from datetime import date
import json
import os
from pathlib import Path
import sys
import threading
import time
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[4] / "tools"))
sys.path.insert(0, str(Path(__file__).resolve().parents[4] / "src"))

from rozliczenia import preparation_process, preparation_register, settlement_process
from rozliczenia.centrum.app import create_app
from rozliczenia.centrum.cloud_files import CloudFiles
from rozliczenia.centrum.configuration import ConfigurationFiles
from rozliczenia.centrum.log import CentrumLog
from rozliczenia.centrum.processes import Processes
from rozliczenia.centrum.report_box import (
    CommentOutcome,
    Commented,
    Issue,
    IssuesOutcome,
    IssueState,
    Label,
    Refused,
    SendOutcome,
    Sent,
    StatesOutcome,
    Unreachable,
)
from rozliczenia.centrum.launcher import listen_locally
from rozliczenia.centrum.server import serve
from rozliczenia.centrum.shutdown import Shutdown
from rozliczenia.centrum.tool_freshness import GitHubReleases, ToolFreshness
from rozliczenia.centrum.tool_update import ToolClone, find_git, pip_install
from rozliczenia.centrum.version import commit_since, tool_commit
from rozliczenia.workbook_files import DataRow, TemplateFile
from skrypt_skilla import Parser


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
        self._pacing = directory.parent / "pacing" / "skrzynka-ms.txt"
        self._lock = threading.Lock()

    def open_issue(self, label: Label, title: str, body: str, *, key: str) -> SendOutcome:
        if self._pacing.exists():
            time.sleep(int(self._pacing.read_text(encoding="utf-8")) / 1000)
        if (self._directory / "brak-sieci").exists():
            return Unreachable()
        with self._lock:
            self._directory.mkdir(parents=True, exist_ok=True)
            number = len(list(self._directory.glob("*.json"))) + 1
            issue = {"number": number, "title": title, "body": body, "labels": [label], "state": "open"}
            (self._directory / f"{number}.json").write_text(
                json.dumps(issue, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
            )
        return Sent(number)

    def comment(self, number: int, body: str, *, key: str) -> CommentOutcome:
        """The comment goes into the issue's own file, so numbering by ``*.json`` stays the issue count.

        Its address names the file within the run root, never the full path: the Zgłoszenie links it, and a
        Zgłoszenie holds no full path.
        """

        if (self._directory / "brak-sieci").exists():
            return Unreachable()
        path = self._directory / f"{number}.json"
        with self._lock:
            if not path.is_file():
                return Refused()
            issue = json.loads(path.read_text(encoding="utf-8"))
            issue["comments"] = [*issue.get("comments", []), body]
            path.write_text(json.dumps(issue, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            comment_id = len(issue["comments"])
        return Commented(comment_id, f"skrzynka-zgloszen/{number}.json#komentarz-{comment_id}")

    def labelled_issues(self, label: Label, *, include_closed: bool, key: str) -> IssuesOutcome:
        if (self._directory / "brak-sieci").exists():
            return Unreachable()
        with self._lock:
            issues = [json.loads(path.read_text(encoding="utf-8")) for path in self._directory.glob("*.json")]
        return tuple(
            Issue(issue["number"], issue["body"])
            for issue in issues
            if issue["labels"] == [label] and (include_closed or issue["state"] == "open")
        )

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


def _scripted_github(root: Path, clone: Path) -> ToolFreshness:
    def local_commit() -> str | None:
        chosen = root / "github" / "tool-commit.txt"
        return chosen.read_text(encoding="utf-8").strip() if chosen.exists() else tool_commit(clone)

    def since() -> date | None:
        commit = local_commit()
        return None if commit is None else commit_since(commit, clone)

    def releases() -> GitHubReleases | None:
        if (root / "github" / "brak-sieci").exists():
            return None
        chosen = root / "github" / "main-commit.txt"
        return GitHubReleases(chosen.read_text(encoding="utf-8").strip() if chosen.exists() else local_commit())

    return ToolFreshness(local=local_commit, since=since, release=releases)


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


def _paced_git(root: Path) -> Callable[[], Path | None]:
    """Git for Aktualizacja narzędzia, found after a wait while ``<root>/pacing/aktualizacja-ms.txt`` exists."""

    def found() -> Path | None:
        pacing = root / "pacing" / "aktualizacja-ms.txt"
        if pacing.exists():
            time.sleep(int(pacing.read_text(encoding="utf-8")) / 1000)
        return find_git()

    return found


def _paced_install(root: Path) -> Callable[[Path], bool]:
    """Pip for the libraries of a new version, started after a wait while ``<root>/pacing/instalacja-ms.txt`` exists."""

    def install(requirements: Path) -> bool:
        pacing = root / "pacing" / "instalacja-ms.txt"
        if pacing.exists():
            time.sleep(int(pacing.read_text(encoding="utf-8")) / 1000)
        return pip_install(requirements)

    return install


def _pace_worker_templates(root: Path, worker_template: Path) -> None:
    """Slow each written Szablon pracownika while ``<root>/pacing/szablony-ms.txt`` exists (see the module doc)."""

    create = TemplateFile.create
    worker_template = worker_template.resolve()

    def paced(template: TemplateFile, target: Path, rows: Sequence[DataRow]) -> None:
        pacing = root / "pacing" / "szablony-ms.txt"
        if template.path == worker_template and pacing.exists():
            time.sleep(int(pacing.read_text(encoding="utf-8")) / 1000)
        create(template, target, rows)

    setattr(TemplateFile, "create", paced)


def _fail_register_reading(root: Path) -> None:
    """Make reading the Rejestr zleceń raise while ``<root>/awaria/odczyt-rejestru`` exists (see the module doc).

    The one name every reader looks up is patched: the process and the Diagnoza call
    ``preparation_register.read_register``, never a copy imported by name.
    """

    read = preparation_register.read_register

    def failing(*args: Any, **kwargs: Any) -> Any:
        if (root / "awaria" / "odczyt-rejestru").exists():
            raise RuntimeError("synthetic unexpected failure")
        return read(*args, **kwargs)

    preparation_register.read_register = failing


def main(argv: list[str] | None = None) -> int:
    parser = Parser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_root("Run root created by create_centrum_fixture.py.")
    parser.add_argument("--port", type=int, required=True, help="Free port on 127.0.0.1.")
    args = parser.parse_args(argv)
    root = args.root
    fixture = json.loads((root / "fixture.json").read_text(encoding="utf-8"))
    today = date.fromisoformat(fixture["today"])
    metrics = fixture["metrics"]
    processes = Processes(
        preparation=replace(preparation_process.PROCESS, metrics_path=lambda: Path(metrics["preparation"])),
        settlement=replace(settlement_process.PROCESS, metrics_path=lambda: Path(metrics["settlement"])),
    )
    configuration = {name: Path(path) for name, path in fixture["configuration"].items()}
    clone = Path(fixture["tool"]["clone"])
    log = CentrumLog(root / "logs" / "centrum-rozliczen.log")
    shutdown = Shutdown(log)
    _pace_worker_templates(root, configuration["worker_template"])
    _fail_register_reading(root)
    # Pip never reaches PyPI from a verification run.
    os.environ["PIP_NO_INDEX"] = "1"
    app = create_app(
        settings_path=Path(fixture["settings"]),
        platform=ScriptedPlatform(root),
        log=log,
        shutdown=shutdown,
        today=lambda: today,
        processes=processes,
        configuration_files=ConfigurationFiles(**configuration),
        tool_freshness=_scripted_github(root, clone),
        cloud_files=_scripted_onedrive(root),
        report_box=FileReportBox(root / "skrzynka-zgloszen"),
        clock=_scripted_clock(root),
        tool_update=ToolClone(
            clone, origin=str(Path(fixture["tool"]["origin"])), find_git=_paced_git(root), install=_paced_install(root)
        ),
    )

    def record_bound_server(url: str) -> None:
        record = {"pid": os.getpid(), "port": args.port, "url": url}
        (root / "server.json").write_text(json.dumps(record), encoding="utf-8")
        print(f"SERVING {url}", flush=True)

    return serve(app, listener=listen_locally(args.port), on_ready=record_bound_server, shutdown=shutdown, log=log)


if __name__ == "__main__":
    raise SystemExit(main())

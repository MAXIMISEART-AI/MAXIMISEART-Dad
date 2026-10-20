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
  commit is the real one (``tool_commit``) from this checkout;
- a file whose full path is a line of ``<root>/onedrive/tylko-w-chmurze.txt``
  has the Windows attribute of a OneDrive file „tylko online”.

One harness-only pacing hook: while ``<root>/pacing/szablony-ms.txt`` exists,
each Szablon pracownika of a Przebieg rozliczeń RUN waits that many
milliseconds before it is written. The synthetic Szablony take milliseconds,
so without it the live Szablony pracowników progress and the refused closing
during the Uruchomienie could not be observed. Results are unchanged.

Once the port is bound, ``<root>/server.json`` records this process and URL.
The Centrum log goes to ``<root>/logs/centrum-rozliczen.log``, and the button
„Zamknij Centrum rozliczeń” stops this process the way it stops Dad's.
"""

from __future__ import annotations

import argparse
from collections.abc import Iterable, Sequence
from datetime import date
import json
import os
from pathlib import Path
import sys
import threading
import time

REPO_ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(REPO_ROOT / "src"))

from rozliczenia import template_settlement  # noqa: E402
from rozliczenia.centrum.app import create_app  # noqa: E402
from rozliczenia.centrum.cloud_files import CloudFiles  # noqa: E402
from rozliczenia.centrum.configuration import ConfigurationFiles  # noqa: E402
from rozliczenia.centrum.log import CentrumLog  # noqa: E402
from rozliczenia.centrum.metrics import MetricsFiles  # noqa: E402
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


def _scripted_github(root: Path) -> ToolFreshness:
    def main_commit() -> str | None:
        if (root / "github" / "brak-sieci").exists():
            return None
        chosen = root / "github" / "main-commit.txt"
        return chosen.read_text(encoding="utf-8").strip() if chosen.exists() else tool_commit()

    return ToolFreshness(local=tool_commit, main=main_commit)


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
    )

    def record_bound_server(url: str) -> None:
        record = {"pid": os.getpid(), "port": args.port, "url": url}
        (root / "server.json").write_text(json.dumps(record), encoding="utf-8")
        print(f"SERVING {url}", flush=True)

    return serve(app, listener=listen_locally(args.port), on_ready=record_bound_server, shutdown=shutdown, log=log)


if __name__ == "__main__":
    raise SystemExit(main())

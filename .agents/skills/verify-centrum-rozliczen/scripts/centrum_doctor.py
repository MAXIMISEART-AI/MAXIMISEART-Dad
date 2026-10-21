"""Read-only check that the Centrum of one verification run is worth driving.

``DOCTOR OK`` means: this run's ``server.json`` exists (written by
``serve_centrum.py`` only after it bound the port), the URL is on
``127.0.0.1``, ``/api/health`` answers with Centrum's identity, the version
from ``pyproject.toml``, the commit of this run's tool clone, and an identifier of this start, the page at ``/`` is the built Centrum frontend, and the
settings the server reads are this run's (the folder okresów is not set yet,
or points inside the run root), and so are the metrics (the oldest Uruchomienie
procesu is the fixture's, not one from Dad's history).
"""

from __future__ import annotations

import argparse
from datetime import datetime
import json
from pathlib import Path
import sys
import tomllib
import urllib.request

REPO_ROOT = Path(__file__).resolve().parents[4]


def _get(url: str) -> tuple[int, bytes]:
    with urllib.request.urlopen(url, timeout=5) as response:
        return response.status, response.read()


def check(root: Path, expected_version: str) -> list[str]:
    problems: list[str] = []
    server_file = root / "server.json"
    if not server_file.exists():
        return [f"{server_file} is missing; serve_centrum.py did not bind its port"]
    server = json.loads(server_file.read_text(encoding="utf-8"))
    url = str(server["url"])
    if not url.startswith("http://127.0.0.1:"):
        problems.append(f"Centrum is not on 127.0.0.1: {url}")
    try:
        _, health_body = _get(url + "api/health")
        health = json.loads(health_body)
        fixture = json.loads((root / "fixture.json").read_text(encoding="utf-8"))
        identity = {"service": "centrum-rozliczen", "version": expected_version, "commit": fixture["tool"]["first"]}
        if {key: health.get(key) for key in identity} != identity or not health.get("instance"):
            problems.append(f"unexpected health answer: {health}")
        _, page = _get(url)
        if "<title>Centrum rozliczeń</title>".encode() not in page:
            problems.append("the page at / is not the built Centrum frontend (run `npm run build` in frontend/)")
        _, settings_body = _get(url + "api/settings")
        periods = json.loads(settings_body)["periods_directory"]
        if periods["state"] != "not_set" and not Path(periods["path"]).resolve().is_relative_to(root.resolve()):
            problems.append("the server reads settings that are not this run's")
        _, metrics_body = _get(url + "api/metrics")
        runs = json.loads(metrics_body)["runs"]
        oldest = datetime.fromisoformat(fixture["metrics"]["oldest"])
        if not runs or datetime.fromisoformat(runs[-1]["started_at"]) != oldest:
            problems.append("the server reads metrics files that are not this run's")
    except OSError as exc:
        problems.append(f"Centrum does not answer at {url}: {exc}")
    return problems


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--root", required=True, help="Run root of the served Centrum.")
    parser.add_argument("--expected-version", help="Defaults to the version in pyproject.toml.")
    args = parser.parse_args(argv)
    if args.expected_version is None:
        with (REPO_ROOT / "pyproject.toml").open("rb") as stream:
            args.expected_version = str(tomllib.load(stream)["project"]["version"])
    problems = check(Path(args.root), args.expected_version)
    if problems:
        for problem in problems:
            print(f"DOCTOR FAIL | {problem}", file=sys.stderr)
        return 1
    print(f"DOCTOR OK | version={args.expected_version} | python={sys.version_info.major}.{sys.version_info.minor}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

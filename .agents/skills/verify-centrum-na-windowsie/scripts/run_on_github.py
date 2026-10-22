"""Run verify-centrum-na-windowsie on GitHub's Windows machine from any computer, and bring the evidence home.

    .venv/bin/python .agents/skills/verify-centrum-na-windowsie/scripts/run_on_github.py [--feature all] [--ref <branch>]
    .venv/bin/python .agents/skills/verify-centrum-na-windowsie/scripts/run_on_github.py --run <run id>

Without ``--run`` it dispatches the workflow ``verify-centrum-na-windowsie.yml`` on ``--ref`` (default: the current
branch, which must be pushed; the workflow must already be on ``main`` for a dispatch). With ``--run`` it waits for
an existing run, e.g. the one a pull request started. Either way it waits for the run, downloads its evidence to
``.verification/evidence/github-<run id>/`` and prints the run's own ``VERIFY OK``/``VERIFY FAIL`` line, exiting 0
only for ``VERIFY OK``. A run takes about 10 minutes: start this as a background command.
"""

from __future__ import annotations

import argparse
from datetime import datetime
import json
from pathlib import Path
import subprocess
import sys
import time

REPO_ROOT = Path(__file__).resolve().parents[4]
WORKFLOW = "verify-centrum-na-windowsie.yml"


def _gh(*args: str) -> str:
    result = subprocess.run(["gh", *args], cwd=REPO_ROOT, capture_output=True, text=True, check=False)
    if result.returncode != 0:
        raise SystemExit(f"VERIFY FAIL | gh {' '.join(args)}: {result.stderr.strip()}")
    return result.stdout.strip()


def _dispatch(ref: str, feature: str) -> str:
    started = time.time()
    _gh("workflow", "run", WORKFLOW, "--ref", ref, "-f", f"feature={feature}")
    for _ in range(60):
        time.sleep(5)
        runs = json.loads(
            _gh("run", "list", "--workflow", WORKFLOW, "--branch", ref, "--event", "workflow_dispatch",
                "--limit", "5", "--json", "databaseId,createdAt")
        )
        for run in runs:
            created = datetime.fromisoformat(run["createdAt"].replace("Z", "+00:00")).timestamp()
            if created >= started - 60:
                return str(run["databaseId"])
    raise SystemExit("VERIFY FAIL | the dispatched run did not appear within 5 minutes")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--feature", default="all")
    parser.add_argument("--ref", default=None)
    parser.add_argument("--run", default=None, help="Wait for this existing run instead of dispatching one.")
    args = parser.parse_args(argv)
    run_id = args.run
    if run_id is None:
        current = subprocess.run(["git", "branch", "--show-current"], cwd=REPO_ROOT, capture_output=True, text=True, check=True)
        ref = args.ref or current.stdout.strip()
        run_id = _dispatch(ref, args.feature)
    print(f"RUN {run_id} | https://github.com/MAXIMISEART-AI/MAXIMISEART-Dad/actions/runs/{run_id}", flush=True)
    subprocess.run(["gh", "run", "watch", run_id, "--interval", "30"], cwd=REPO_ROOT, stdout=subprocess.DEVNULL, check=False)
    conclusion = json.loads(_gh("run", "view", run_id, "--json", "conclusion"))["conclusion"]
    evidence = REPO_ROOT / ".verification" / "evidence" / f"github-{run_id}"
    evidence.mkdir(parents=True, exist_ok=True)
    subprocess.run(["gh", "run", "download", run_id, "--dir", str(evidence)], cwd=REPO_ROOT, check=False)
    verdicts = [
        line
        for drive in sorted(evidence.rglob("drive.txt"))
        for line in drive.read_text(encoding="utf-8", errors="replace").splitlines()
        if line.startswith(("VERIFY OK", "VERIFY FAIL"))
    ]
    verdict = verdicts[-1] if verdicts else f"VERIFY FAIL | no verdict in the evidence (run {conclusion})"
    print(f"{verdict} | run={run_id} | conclusion={conclusion} | downloaded={evidence}", flush=True)
    return 0 if verdict.startswith("VERIFY OK") and conclusion == "success" else 1


if __name__ == "__main__":
    sys.exit(main())

"""Run ``ci.yml`` mieści się w limicie zadań konta, a ``Required CI status`` czerwienieje, gdy którekolwiek zadanie nie przeszło.

Konto GitHub (plan Free) uruchamia naraz najwyżej 20 zadań ze wszystkich workflowów, więc run, który sam zajmuje
prawie cały limit, każe kolejnym pushom czekać w kolejce. Zadanie, którego nie ma w ``needs`` Required, nie
blokuje merge'a, choćby padło.
"""

from __future__ import annotations

from collections import Counter
import json
import os
import subprocess
import sys
import pytest

from tests.fixtures.ci_workflow import combinations, jobs

# Najwięcej zadań jednego runu na zdarzenie; na push do `main` Change mutations nie startuje.
JOB_LIMITS = {"pull_request": 14, "push": 11}
# Warunek `if:` zadania i zdarzenia, przy których zadanie startuje.
STARTS = {
    None: set(JOB_LIMITS),
    "${{ always() }}": set(JOB_LIMITS),
    "${{ github.event_name == 'pull_request' }}": {"pull_request"},
}
REQUIRED = "required"


def _jobs_of_run(event: str) -> list[str]:
    started = []
    for name, job in jobs().items():
        assert job.get("if") in STARTS, f"{name}: nieznany warunek {job.get('if')!r}, dopisz go do STARTS"
        if event in STARTS[job.get("if")]:
            started += [name] * len(combinations(job.get("strategy", {}).get("matrix", {})))
    return started


def test_run_ci_miesci_sie_w_limicie_zadan_na_kazde_zdarzenie() -> None:
    counts = {event: len(_jobs_of_run(event)) for event in JOB_LIMITS}

    assert {event: count for event, count in counts.items() if count > JOB_LIMITS[event]} == {}


def test_required_czeka_na_kazde_inne_zadanie() -> None:
    workflow = jobs()

    assert set(workflow[REQUIRED]["needs"]) == set(workflow) - {REQUIRED}


def _required(event: str, results: dict[str, str]) -> subprocess.CompletedProcess[str]:
    step = jobs()[REQUIRED]["steps"][-1]
    assert step["shell"] == "python3 {0}"
    needs = {job: {"result": result, "outputs": {}} for job, result in results.items()}
    env = {**os.environ, "NEEDS": json.dumps(needs), "EVENT": event}
    return subprocess.run([sys.executable, "-c", step["run"]], capture_output=True, text=True, encoding="utf-8", env=env, check=False)


def _all_succeeded() -> dict[str, str]:
    return dict.fromkeys(jobs()[REQUIRED]["needs"], "success")


@pytest.mark.parametrize(
    ("event", "changed", "passes"),
    [
        ("pull_request", {}, True),
        ("push", {}, True),
        ("push", {"change-mutations": "skipped"}, True),
        ("pull_request", {"change-mutations": "skipped"}, False),
        ("push", {"change-mutations": "failure"}, False),
        ("push", {"pytest": "skipped"}, False),
        ("pull_request", {"szybkie": "failure"}, False),
        ("pull_request", {"mutations": "cancelled"}, False),
    ],
)
def test_required_przechodzi_tylko_gdy_kazde_zadanie_przeszlo(event: str, changed: dict[str, str], passes: bool) -> None:
    done = _required(event, {**_all_succeeded(), **changed})

    assert (done.returncode == 0) == passes, done.stdout + done.stderr
    for job, result in changed.items():
        assert (f"{job}={result}" in done.stderr) != passes


def test_run_liczy_kazda_kombinacje_macierzy_i_tylko_zadania_tego_zdarzenia() -> None:
    only_pull_request = Counter(_jobs_of_run("pull_request")) - Counter(_jobs_of_run("push"))

    assert only_pull_request == Counter({"change-mutations": 3})

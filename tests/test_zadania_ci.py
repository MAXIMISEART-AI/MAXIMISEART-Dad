"""Run ``ci.yml`` mieści się w limicie zadań konta, a ``Required CI status`` czerwienieje, gdy którekolwiek zadanie nie przeszło.

Konto GitHub (plan Free) uruchamia naraz najwyżej 20 zadań ze wszystkich workflowów, więc run, który sam zajmuje
prawie cały limit, każe kolejnym pushom czekać w kolejce. Zadanie, którego nie ma w ``needs`` Required, nie
blokuje merge'a, choćby padło.
"""

from __future__ import annotations

from collections import Counter
import json
import os
import re
import subprocess
import sys
from typing import Any

import pytest
import yaml

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
# Kroki części pytest, które biegną tylko w kombinacji macierzy z flagą, i kombinacje Windows (wersja Pythona, część), które ją mają.
FLAGS = {
    "e2e": {("3.11", "1/2"), ("3.14", "1/2")},
    "timing": {("3.14", "2/2")},
}
FLAGGED_COMMANDS = {
    "e2e": ("verify-rozliczenia/scripts/run_verification.py",),
    "timing": ("tools/syntetyczne_wzorce.py", "tools/benchmark_przebiegu.py"),
}
INDEPENDENT = "${{ !cancelled() && steps.deps.outcome == 'success' }}"


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
    step = next(step for step in jobs()[REQUIRED]["steps"] if step.get("name") == "Require every CI check to succeed")
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


def test_flagi_e2e_i_timing_wypadaja_na_zamierzonych_czesciach_windows_bez_dodatkowych_zadan() -> None:
    matrix = jobs()["pytest"]["strategy"]["matrix"]
    without_flags = {**matrix, "include": [entry for entry in matrix["include"] if not FLAGS.keys() & entry.keys()]}
    found = {
        flag: [(c["os"], c["python-version"], c["part"]) for c in combinations(matrix) if c.get(flag) is True]
        for flag in FLAGS
    }

    assert found == {flag: sorted(("windows-latest", *where) for where in FLAGS[flag]) for flag in FLAGS}
    assert len(combinations(matrix)) == len(combinations(without_flags))


def _gated_steps(steps: list[dict[str, Any]], flag: str) -> list[dict[str, Any]]:
    """Kroki, które biegną tylko z flagą: warunek na fladze albo na sukcesie takiego kroku."""

    gated: list[dict[str, Any]] = []
    for step in steps:
        condition = step.get("if", "")
        after = set(re.findall(r"steps\.([\w-]+)\.outcome == 'success'", condition))
        if f"matrix.{flag}" in condition or after & {gate.get("id") for gate in gated}:
            gated.append(step)
    return gated


def test_kroki_e2e_i_timing_biegna_tylko_z_flaga_takze_po_czerwonym_pytest_i_z_limitem_czasu() -> None:
    steps = jobs()["pytest"]["steps"]
    wrong = {}
    for flag, commands in FLAGGED_COMMANDS.items():
        gated = _gated_steps(steps, flag)
        running = [step["name"] for step in steps if any(command in step.get("run", "") for command in commands)]
        wrong[flag] = {
            "bez flagi": [name for name in running if name not in [step["name"] for step in gated]],
            "bez !cancelled()": [step["name"] for step in gated if not step["if"].startswith("${{ !cancelled() && ")],
            "bez limitu czasu": [step["name"] for step in gated if "timeout-minutes" not in step],
        }
        assert running, f"{flag}: żaden krok nie uruchamia {commands}"

    assert wrong == dict.fromkeys(FLAGS, {"bez flagi": [], "bez !cancelled()": [], "bez limitu czasu": []})


def test_kazdy_krok_wskazany_w_wyrazeniu_jest_wczesniej_w_tym_samym_zadaniu() -> None:
    unknown = {}
    for name, job in jobs().items():
        earlier: set[str] = set()
        for step in job["steps"]:
            referenced = set(re.findall(r"steps\.([\w-]+)\.", yaml.safe_dump(step)))
            if referenced - earlier:
                unknown[f"{name}: {step.get('name', step.get('uses'))}"] = sorted(referenced - earlier)
            earlier.add(step.get("id", ""))

    assert unknown == {}


def test_w_szybkich_porazka_jednego_sprawdzenia_nie_ukrywa_pozostalych() -> None:
    steps = jobs()["szybkie"]["steps"]
    deps = next(index for index, step in enumerate(steps) if step.get("id") == "deps")
    checks = [step.get("if") for step in steps[deps + 1 :]]
    python_checks = [step["run"].split()[2] for step in steps[deps + 1 :] if step.get("if") == INDEPENDENT]

    assert checks[checks.index(INDEPENDENT) :] == [INDEPENDENT] * 3
    assert python_checks == ["ruff", "mypy", "mypy"]
    assert set(checks[: checks.index(INDEPENDENT)]) == {None}

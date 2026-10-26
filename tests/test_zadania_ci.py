"""Run ``ci.yml`` mieści się w limicie zadań konta, a ``Required CI status`` czerwienieje, gdy którekolwiek zadanie nie przeszło.

Konto GitHub (plan Free) uruchamia naraz najwyżej 20 zadań ze wszystkich workflowów, więc run, który sam zajmuje
prawie cały limit, każe kolejnym pushom czekać w kolejce. Liczbę zadań pytest i start Change mutations ustala plan
(``tools/plan_ci.py``), więc ci.yml i plan muszą się zgadzać co do zadań o stałej liczbie. Zadanie, którego nie ma w
``needs`` Required, nie blokuje merge'a, choćby padło.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import re
import shlex
import subprocess
import sys

import pytest
import yaml

from tests.fixtures.ci_workflow import combinations, jobs

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

import plan_ci  # noqa: E402

REQUIRED = "required"
# Zadanie, którego macierz albo start ustala plan, i wyrażenie ci.yml, które czyta wyjście planu.
FROM_PLAN = {
    "pytest": ("${{ needs.plan.outputs.pytest != '[]' }}", "${{ fromJSON(needs.plan.outputs.pytest) }}"),
    "change-mutations": ("${{ needs.plan.outputs.mutacje-zmiany != '0' }}", None),
}
INDEPENDENT = "${{ !cancelled() && steps.deps.outcome == 'success' }}"


def test_plan_zna_liczbe_zadan_runu_o_stalej_liczbie_i_czesci_change_mutations() -> None:
    workflow = jobs()
    fixed = {name: len(combinations(job.get("strategy", {}).get("matrix", {}))) for name, job in workflow.items() if name not in FROM_PLAN}

    assert sum(fixed.values()) == plan_ci.STALE_ZADANIA, fixed
    assert len(combinations(workflow["change-mutations"]["strategy"]["matrix"])) == plan_ci.ZADANIA_ZMIANY
    assert set(FROM_PLAN) == set(plan_ci.Z_PLANU)


def test_required_czeka_na_kazde_inne_zadanie() -> None:
    workflow = jobs()

    assert set(workflow[REQUIRED]["needs"]) == set(workflow) - {REQUIRED}


def test_zadania_z_planu_czekaja_na_plan_i_startuja_tylko_z_praca_od_niego() -> None:
    workflow = jobs()
    outputs = workflow["plan"]["outputs"]

    assert {name: (workflow[name]["needs"], workflow[name]["if"]) for name in FROM_PLAN} == {name: ("plan", start) for name, (start, _) in FROM_PLAN.items()}
    assert workflow["pytest"]["strategy"]["matrix"] == {"include": FROM_PLAN["pytest"][1]}
    assert outputs == {"pytest": "${{ steps.plan.outputs.pytest }}", "mutacje-zmiany": "${{ steps.plan.outputs.mutacje-zmiany }}"}


def test_zadanie_pytest_czyta_z_planu_tylko_pola_wpisu_macierzy() -> None:
    plan = plan_ci.Plan("push", plan_ci.CEL_S, (), 0, (plan_ci.Zadanie("linux-3.14-1", "linux-3.14", "pytest (Python 3.14, Linux, 1/1)", ("pytest:tests/test_adr.py",), 1.0),))
    used = set(re.findall(r"matrix\.([\w-]+)", yaml.safe_dump(jobs()["pytest"])))

    assert used == set(plan.macierz()[0])


def _required(tmp_path: Path, plan: plan_ci.Plan | None, results: dict[str, str], *, complete: bool = True) -> subprocess.CompletedProcess[str]:
    """Krok werdyktu Required z ci.yml na planie i zapisach czasów tam, gdzie kładą je kroki pobrania artefaktów."""

    steps = jobs()[REQUIRED]["steps"]
    downloads = {step["with"].get("name") or step["with"]["pattern"]: tmp_path / step["with"]["path"] for step in steps if "download-artifact" in step.get("uses", "")}
    downloads["czasy-zadanie-*"].mkdir(parents=True)
    if plan is not None:
        downloads["plan"].mkdir(parents=True)
        (downloads["plan"] / "plan.json").write_text(plan.do_json(), encoding="utf-8")
        for index, job in enumerate(plan.zadania):
            units = [{"klucz": unit.partition("#")[0], "s": 1.0, "status": "ok"} for unit in job.jednostki[: None if complete else -1]]
            record = {"wersja": 1, "run": 1, "proba": 1, "szablon": "pytest", "zadanie": job.nazwa, "tor": job.tor, "zdarzenie": plan.zdarzenie,
                      "sha": "0" * 40, "narzut_s": 9.0, "jednostki": units, "bledy": [], "plan": plan.digest, "zadanie_planu": job.id}  # fmt: skip
            (downloads["czasy-zadanie-*"] / f"pytest-{index}-1.json").write_text(json.dumps(record), encoding="utf-8")
    step = next(step for step in steps if "tools/plan_ci.py werdykt" in step.get("run", ""))
    python, script, *arguments = shlex.split(step["run"])
    assert python == "python3"
    needs = {job: {"result": result, "outputs": {}} for job, result in results.items()}
    env = {**os.environ, **step["env"], "NEEDS": json.dumps(needs)}
    return subprocess.run([sys.executable, str(ROOT / script), *arguments], cwd=tmp_path, capture_output=True, text=True, encoding="utf-8", env=env, check=False)


def _all_succeeded() -> dict[str, str]:
    return dict.fromkeys(jobs()[REQUIRED]["needs"], "success")


def _plan(event: str, mutations: int) -> plan_ci.Plan:
    job = plan_ci.Zadanie("windows-3.11-1", "windows-3.11", "pytest (Python 3.11, 1/1)", ("pytest:tests/test_a.py#1/2", "pytest:tests/test_b.py", "krok:e2e"), 99.0)
    return plan_ci.Plan(event, plan_ci.CEL_S, (), mutations, (job,))


@pytest.mark.parametrize(
    ("event", "mutations", "changed", "reported"),
    [
        ("pull_request", 4, {}, []),
        ("push", 0, {"change-mutations": "skipped"}, []),
        ("pull_request", 0, {"change-mutations": "skipped"}, []),
        ("pull_request", 4, {"change-mutations": "skipped"}, ["change-mutations=skipped"]),
        ("push", 0, {"change-mutations": "failure"}, ["change-mutations=failure"]),
        ("push", 0, {"pytest": "skipped", "change-mutations": "skipped"}, ["pytest=skipped"]),
        ("pull_request", 4, {"szybkie": "failure"}, ["szybkie=failure"]),
        ("pull_request", 4, {"mutations": "cancelled"}, ["mutations=cancelled"]),
    ],
)
def test_required_przechodzi_tylko_gdy_kazde_zadanie_przeszlo_a_pominiete_jest_tylko_bez_pracy_z_planu(
    tmp_path: Path, event: str, mutations: int, changed: dict[str, str], reported: list[str]
) -> None:
    done = _required(tmp_path, _plan(event, mutations), {**_all_succeeded(), **changed})

    assert done.returncode == (1 if reported else 0), done.stdout + done.stderr
    assert done.stdout.splitlines() == ([f"REQUIRED FAIL | {reason}" for reason in reported] or [done.stdout.splitlines()[0]])
    assert reported or done.stdout.startswith("REQUIRED OK | 5 zadań, 1 zadań pytest z planu ")


def test_required_czerwienieje_bez_planu_i_gdy_zadanie_planu_nie_zglosilo_jednostki(tmp_path: Path) -> None:
    without_plan = _required(tmp_path / "bez-planu", None, {**_all_succeeded(), "plan": "failure", "pytest": "skipped"})
    incomplete = _required(tmp_path / "bez-kroku", _plan("push", 0), {**_all_succeeded(), "change-mutations": "skipped"}, complete=False)

    assert without_plan.returncode == incomplete.returncode == 1
    assert "REQUIRED FAIL | plan CI: .ci-plan/plan.json nieczytelny (" in without_plan.stdout
    assert "REQUIRED FAIL | plan=failure" in without_plan.stdout
    assert incomplete.stdout.splitlines() == ["REQUIRED FAIL | pytest (Python 3.11, 1/1): jednostki bez wyniku: krok:e2e"]


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

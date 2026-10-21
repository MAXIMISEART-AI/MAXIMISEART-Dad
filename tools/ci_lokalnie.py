"""Lokalnie te same sprawdzenia co zadania CI ruff, mypy, pytest, mutations i frontend, przed zgłoszeniem gotowości.

Uruchamia każdy krok po kolei Pythonem, który uruchomił skrypt (w worktree: jego ``.venv``,
patrz ``tools/setup_worktree.py``), i drukuje wynik kroku jedną linią; wyjście pokazuje tylko
przy porażce. Kończy się ``CI LOKALNIE OK`` albo ``CI LOKALNIE FAIL | <kroki>``. Zadania E2E i
Timing guard mają swoje narzędzia (``--kroki-ci`` je wymienia), bo trwają kilka minut.

    py -3 tools/ci_lokalnie.py                  # Windows
    .venv/bin/python tools/ci_lokalnie.py       # macOS i Linux
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
FRONTEND = ROOT / "frontend"
# Wygenerowany kontrakt i zbudowany frontend muszą zgadzać się ze źródłami (u taty nie ma Node).
GENERATED = ("frontend/src/api", "src/rozliczenia/centrum/static")
JOBS_ELSEWHERE = {
    "e2e": "skill verify-rozliczenia: .agents/skills/verify-rozliczenia/scripts/run_verification.py --variant all",
    "timing": "tools/benchmark_przebiegu.py measure --scenario typowy-tydzien",
    "required": "zbiorczy status pozostałych zadań, nic do odtworzenia",
}
OUTPUT_ON_FAILURE = 40


@dataclass(frozen=True)
class Step:
    name: str
    job: str
    # Fragment polecenia `run:` w ci.yml, które ten krok odtwarza.
    ci: str
    command: tuple[str, ...]
    cwd: Path = ROOT


def _npm() -> str:
    return shutil.which("npm") or "npm"


def _steps() -> list[Step]:
    python, npm = sys.executable, _npm()
    return [
        Step("ruff", "ruff", "-m ruff check", (python, "-m", "ruff", "check")),
        Step("mypy", "mypy", "-m mypy", (python, "-m", "mypy")),
        # Zadanie mypy w CI biegnie na Windows, gdzie gałęzie tylko dla innych systemów nie mają ich API.
        Step("mypy (Windows)", "mypy", "-m mypy", (python, "-m", "mypy", "--platform", "win32")),
        Step("pytest", "pytest", "-m pytest -n auto", (python, "-m", "pytest", "-q", "-n", "auto")),
        Step(
            "mutacje publikacji",
            "mutations",
            "check_mutations.py",
            (python, ".agents/skills/verify-publikacja-plikow-okresu/scripts/check_mutations.py"),
        ),
        Step(
            "mutacje jednego Uruchomienia naraz",
            "mutations",
            "check_runs_mutations.py",
            (python, ".agents/skills/verify-jedno-uruchomienie-naraz/scripts/check_runs_mutations.py"),
        ),
        Step(
            "mutacje kopii Wzorca",
            "mutations",
            "verify-kopia-wzorca/scripts/check_copy_mutations.py",
            (python, ".agents/skills/verify-kopia-wzorca/scripts/check_copy_mutations.py"),
        ),
        Step("npm ci", "frontend", "npm ci", (npm, "ci"), FRONTEND),
        *(
            Step(f"npm run {script}", "frontend", f"npm run {script}", (npm, "run", script), FRONTEND)
            for script in ("contract", "typecheck", "lint", "rules", "unused", "duplicates", "build")
        ),
        Step(
            "kontrakt i build zacommitowane",
            "frontend",
            f"git status --porcelain -- {' '.join(GENERATED)}",
            ("git", "status", "--porcelain", "--", *GENERATED),
        ),
    ]


def _dependencies_fresh() -> bool:
    """``node_modules`` zainstalowane z bieżącego ``package-lock.json`` (wtedy ``npm ci`` jest zbędne)."""

    installed = FRONTEND / "node_modules" / ".package-lock.json"
    return installed.exists() and installed.stat().st_mtime >= (FRONTEND / "package-lock.json").stat().st_mtime


def _run(step: Step) -> tuple[bool, str]:
    environment = {**os.environ, "PYTHON": sys.executable, "PYTHONUTF8": "1"}
    completed = subprocess.run(
        step.command,
        cwd=step.cwd,
        env=environment,
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    output = completed.stdout + completed.stderr
    if step.command[:2] == ("git", "status"):
        stale = completed.stdout.strip()
        hint = "\nUruchom 'npm run contract' i 'npm run build' we frontend/ i zacommituj wynik."
        return completed.returncode == 0 and not stale, stale + hint
    return completed.returncode == 0, output


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--kroki-ci", action="store_true", help="Wypisz JSON: odtwarzane zadania CI i ich polecenia.")
    args = parser.parse_args(argv)
    steps = _steps()
    if args.kroki_ci:
        jobs = sorted({step.job for step in steps})
        print(json.dumps({"lokalnie": jobs, "gdzie_indziej": JOBS_ELSEWHERE, "fragmenty": [s.ci for s in steps]}))
        return 0
    failed = []
    for step in steps:
        if step.name == "npm ci" and _dependencies_fresh():
            print(f"POMINIĘTO {step.name} (node_modules z bieżącego package-lock.json)", flush=True)
            continue
        started = time.monotonic()
        passed, output = _run(step)
        elapsed = time.monotonic() - started
        print(f"{'OK  ' if passed else 'FAIL'} {step.name} ({elapsed:.0f} s)", flush=True)
        if not passed:
            failed.append(step.name)
            print("\n".join(output.rstrip().splitlines()[-OUTPUT_ON_FAILURE:]), flush=True)
    try:
        overlaps = (sys.executable, str(ROOT / "tools" / "praca_w_toku.py"), "--nakladania")
        subprocess.run(overlaps, cwd=ROOT, stdin=subprocess.DEVNULL, timeout=120, check=False)
    except (OSError, subprocess.TimeoutExpired) as error:
        print(f"NAKŁADANIA POMINIĘTE | {error}", flush=True)
    if failed:
        print(f"CI LOKALNIE FAIL | {', '.join(failed)}")
        return 1
    print("CI LOKALNIE OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

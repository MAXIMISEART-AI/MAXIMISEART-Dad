"""Lokalnie te same sprawdzenia co zadania CI ruff, mypy, pytest, mutations i frontend, przed zgłoszeniem gotowości.

Uruchamia każdy krok po kolei Pythonem, który uruchomił skrypt (w worktree: jego ``.venv``,
patrz ``tools/setup_worktree.py``), i drukuje wynik kroku jedną linią; wyjście pokazuje tylko
przy porażce. Kończy się ``CI LOKALNIE OK`` albo ``CI LOKALNIE FAIL | <kroki>``. Zadania E2E i
Timing guard mają swoje narzędzia (``--kroki-ci`` je wymienia), bo trwają kilka minut.

``--kazdy-commit`` sprawdza każdy commit gałęzi od bazy (domyślnie ``origin/main``) we własnym
tymczasowym worktree, domyślnie krokami ruff, mypy i pytest, i nie dotyka checkoutu: zastępuje
ręczne ``git rebase --exec``. Niezacommitowanych zmian nie sprawdza.

Po ``CI LOKALNIE OK`` pełnego przebiegu (bez ``--tylko``) na czystym checkoucie zapisuje jego drzewo HEAD w pieczątce
``$(git rev-parse --git-dir)/ci-lokalnie-ok``: brama ``tools/hooks/pre-push`` przepuszcza wtedy push
tego drzewa bez ponownego przebiegu.

    py -3 tools/ci_lokalnie.py                  # Windows
    .venv/bin/python tools/ci_lokalnie.py       # macOS i Linux
    .venv/bin/python tools/ci_lokalnie.py --kazdy-commit
    .venv/bin/python tools/ci_lokalnie.py --tylko ruff,mypy
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time

from mutacje import environment

ROOT = Path(__file__).resolve().parents[1]
# Wygenerowany kontrakt i zbudowany frontend muszą zgadzać się ze źródłami (u taty nie ma Node).
GENERATED = ("frontend/src/api", "src/rozliczenia/centrum/static")
JOBS_ELSEWHERE = {
    "e2e": "skill verify-rozliczenia: .agents/skills/verify-rozliczenia/scripts/run_verification.py --variant all",
    "timing": "tools/benchmark_przebiegu.py measure --scenario typowy-tydzien",
    "required": "zbiorczy status pozostałych zadań, nic do odtworzenia",
}
OUTPUT_ON_FAILURE = 40
EVERY_COMMIT_JOBS = ("ruff", "mypy", "pytest")
STAMP = "ci-lokalnie-ok"


@dataclass(frozen=True)
class Step:
    name: str
    job: str
    # Fragment polecenia `run:` w ci.yml, które ten krok odtwarza.
    ci: str
    command: tuple[str, ...]
    cwd: Path


def _npm() -> str:
    return shutil.which("npm") or "npm"


def _steps(root: Path) -> list[Step]:
    python, npm, frontend = sys.executable, _npm(), root / "frontend"
    return [
        Step("ruff", "ruff", "-m ruff check", (python, "-m", "ruff", "check"), root),
        Step("mypy", "mypy", "-m mypy", (python, "-m", "mypy"), root),
        # Zadanie mypy w CI biegnie na Windows, gdzie gałęzie tylko dla innych systemów nie mają ich API.
        Step("mypy (Windows)", "mypy", "-m mypy", (python, "-m", "mypy", "--platform", "win32"), root),
        Step("pytest", "pytest", "-m pytest -n auto", (python, "-m", "pytest", "-q", "-n", "auto"), root),
        Step(
            "mutacje publikacji",
            "mutations",
            "check_mutations.py",
            (python, ".agents/skills/verify-publikacja-plikow-okresu/scripts/check_mutations.py"),
            root,
        ),
        Step(
            "mutacje jednego Uruchomienia naraz",
            "mutations",
            "check_runs_mutations.py",
            (python, ".agents/skills/verify-jedno-uruchomienie-naraz/scripts/check_runs_mutations.py"),
            root,
        ),
        Step(
            "mutacje kopii Wzorca",
            "mutations",
            "verify-kopia-wzorca/scripts/check_copy_mutations.py",
            (python, ".agents/skills/verify-kopia-wzorca/scripts/check_copy_mutations.py"),
            root,
        ),
        Step("npm ci", "frontend", "npm ci", (npm, "ci"), frontend),
        *(
            Step(f"npm run {script}", "frontend", f"npm run {script}", (npm, "run", script), frontend)
            for script in ("contract", "typecheck", "lint", "rules", "unused", "duplicates", "build")
        ),
        Step(
            "kontrakt i build zacommitowane",
            "frontend",
            f"git status --porcelain -- {' '.join(GENERATED)}",
            ("git", "status", "--porcelain", "--", *GENERATED),
            root,
        ),
    ]


def _dependencies_fresh(frontend: Path) -> bool:
    """``node_modules`` zainstalowane z bieżącego ``package-lock.json`` (wtedy ``npm ci`` jest zbędne)."""

    installed = frontend / "node_modules" / ".package-lock.json"
    return installed.exists() and installed.stat().st_mtime >= (frontend / "package-lock.json").stat().st_mtime


def _clean_tree() -> str | None:
    """Drzewo HEAD, gdy checkout nie ma zmian ani nieśledzonych plików (pytest uruchomiłby i je)."""

    return None if _git("status", "--porcelain") else _git("rev-parse", "HEAD^{tree}")


def _run(step: Step, root: Path) -> tuple[bool, str]:
    completed = subprocess.run(
        step.command,
        cwd=step.cwd,
        env={**environment(root), "PYTHON": sys.executable},
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


def _check(root: Path, jobs: set[str], *, fail_fast: bool = False) -> list[str]:
    """Uruchamia kroki wybranych zadań w ``root``; zwraca nazwy kroków, które padły."""

    failed: list[str] = []
    for step in _steps(root):
        if failed and fail_fast:
            break
        if step.job not in jobs:
            continue
        if step.name == "npm ci" and _dependencies_fresh(step.cwd):
            print(f"POMINIĘTO {step.name} (node_modules z bieżącego package-lock.json)", flush=True)
            continue
        started = time.monotonic()
        passed, output = _run(step, root)
        elapsed = time.monotonic() - started
        print(f"{'OK  ' if passed else 'FAIL'} {step.name} ({elapsed:.0f} s)", flush=True)
        if not passed:
            failed.append(step.name)
            print("\n".join(output.rstrip().splitlines()[-OUTPUT_ON_FAILURE:]), flush=True)
    return failed


def _git(*arguments: str) -> str:
    completed = subprocess.run(["git", *arguments], cwd=ROOT, capture_output=True, text=True, encoding="utf-8", check=True)
    return completed.stdout.strip()


def _check_every_commit(base: str, jobs: set[str], *, fail_fast: bool) -> int:
    known = subprocess.run(["git", "rev-parse", "--verify", "--quiet", f"{base}^{{commit}}"], cwd=ROOT, capture_output=True, check=False)
    if known.returncode != 0:
        print(f"COMMITY FAIL | nieznana baza {base}")
        return 1
    commits = _git("rev-list", "--reverse", f"{base}..HEAD").split()
    if not commits:
        print(f"COMMITY FAIL | brak commitów między {base} a HEAD")
        return 1
    if _git("status", "--porcelain", "--untracked-files=no"):
        print("UWAGA: niezacommitowane zmiany nie są sprawdzane", flush=True)
    failed = []
    _git("worktree", "prune")
    with tempfile.TemporaryDirectory(prefix="commit-", ignore_cleanup_errors=True) as scratch:
        for commit in commits:
            print(f"== {_git('log', '-1', '--format=%h %s', commit)}", flush=True)
            if _git("diff", "--name-only", commit, "HEAD", "--", "pyproject.toml", "requirements.txt"):
                print("UWAGA: zależności różnią się od HEAD, a .venv jest zainstalowane z HEAD", flush=True)
            tree = Path(scratch) / commit
            _git("worktree", "add", "--quiet", "--detach", str(tree), commit)
            try:
                if steps := _check(tree, jobs, fail_fast=fail_fast):
                    failed.append(f"{commit[:7]} ({', '.join(steps)})")
            finally:
                _git("worktree", "remove", "--force", str(tree))
    if failed:
        print(f"COMMITY FAIL | {'; '.join(failed)}")
        return 1
    print(f"COMMITY OK ({len(commits)})")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--kroki-ci", action="store_true", help="Wypisz JSON: odtwarzane zadania CI i ich polecenia.")
    parser.add_argument(
        "--kazdy-commit",
        nargs="?",
        const="origin/main",
        metavar="BAZA",
        help="Sprawdź każdy commit od BAZA (domyślnie origin/main) do HEAD w osobnym worktree.",
    )
    parser.add_argument("--tylko", metavar="ZADANIA", help="Tylko te zadania CI, po przecinku, np. ruff,mypy.")
    parser.add_argument(
        "--do-pierwszego-bledu",
        action="store_true",
        help="Zakończ po pierwszym nieudanym kroku (brama pre-push: nieudany push odpowiada szybko).",
    )
    args = parser.parse_args(argv)
    steps = _steps(ROOT)
    known = {step.job for step in steps}
    if args.kroki_ci:
        print(json.dumps({"lokalnie": sorted(known), "gdzie_indziej": JOBS_ELSEWHERE, "fragmenty": [s.ci for s in steps]}))
        return 0
    jobs = set(args.tylko.split(",")) if args.tylko else set(EVERY_COMMIT_JOBS if args.kazdy_commit else known)
    if unknown := jobs - known:
        parser.error(f"nieznane zadania: {', '.join(sorted(unknown))}; znane: {', '.join(sorted(known))}")
    if args.kazdy_commit:
        return _check_every_commit(args.kazdy_commit, jobs, fail_fast=args.do_pierwszego_bledu)
    tree = _clean_tree() if jobs == known else None
    failed = _check(ROOT, jobs, fail_fast=args.do_pierwszego_bledu)
    try:
        overlaps = (sys.executable, str(ROOT / "tools" / "praca_w_toku.py"), "--nakladania")
        subprocess.run(overlaps, cwd=ROOT, stdin=subprocess.DEVNULL, timeout=120, check=False)
    except (OSError, subprocess.TimeoutExpired) as error:
        print(f"NAKŁADANIA POMINIĘTE | {error}", flush=True)
    if failed:
        print(f"CI LOKALNIE FAIL | {', '.join(failed)}")
        return 1
    # Commit albo zmiana w trakcie przebiegu znaczy, że sprawdzone drzewo nie jest już drzewem HEAD.
    if tree is not None and _clean_tree() == tree:
        (ROOT / _git("rev-parse", "--git-dir") / STAMP).write_text(tree, encoding="utf-8")
    print("CI LOKALNIE OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

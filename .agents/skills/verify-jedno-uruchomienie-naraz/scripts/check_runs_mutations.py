"""Show that explore_runs.py fails on broken variants of RunHost and Shutdown.

Each mutation is applied to a copy of ``src`` in a temporary directory, never to
the checkout. The checker then runs against that copy and must end with the
expected result. A mutation whose anchor text is no longer in its file is
reported as NIEAKTUALNA: update it to the new code.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent
REPO_ROOT = SCRIPTS.parents[3]
RUNS = Path("rozliczenia") / "centrum" / "runs.py"
SHUTDOWN = Path("rozliczenia") / "centrum" / "shutdown.py"
EXPLORER = SCRIPTS / "explore_runs.py"


@dataclass(frozen=True)
class Mutation:
    name: str
    harm: str
    file: Path
    anchor: str
    replacement: str
    scope: str  # the explorer scope that catches it; every scope for every mutation costs minutes in CI
    expected: str  # last line of the checker's report


MUTATIONS = (
    Mutation(
        "sprawdzenie i zajęcie w RunHost.start pod dwiema blokadami",
        "dwie karty „Uruchom” prowadzą dwa Uruchomienia naraz na tym samym Folderze okresu",
        RUNS,
        "            run = _Run(self, prepared)\n",
        "        with self._lock:\n            run = _Run(self, prepared)\n",
        "dwie-karty",
        "URUCHOMIENIA: NOWE NARUSZENIE",
    ),
    Mutation(
        "odmowa zamknięcia pomija Uruchomienie czekające na Decyzję",
        "Centrum zamyka się, gdy tata jeszcze nie odpowiedział na Decyzję",
        RUNS,
        "        if run is None or run.ended:\n",
        "        if run is None or run.ended or run.awaiting_decision:\n",
        "zamknij-w-trakcie",
        "URUCHOMIENIA: NOWE NARUSZENIE",
    ),
    Mutation(
        "ended ustawione na początku _Run.work",
        "Centrum zamyka się w trakcie silnika i kolejne „Uruchom” startuje drugie Uruchomienie",
        RUNS,
        "        prepared = self._prepared\n        stop: Stop | None\n",
        "        prepared = self._prepared\n        self.ended = True\n        stop: Stop | None\n",
        "zamknij-w-trakcie",
        "URUCHOMIENIA: NOWE NARUSZENIE",
    ),
    Mutation(
        "Shutdown.request bez odmowy",
        "„Zamknij” zamyka Centrum w trakcie każdego Uruchomienia",
        SHUTDOWN,
        "        message = self._blocker()\n",
        "        message = None\n",
        "zamknij-w-trakcie",
        "URUCHOMIENIA: NOWE NARUSZENIE",
    ),
    Mutation(
        "zamknięcie przyjęte bez odcięcia nowych startów",
        "„Uruchom” albo „Zaktualizuj narzędzie” tuż po „Zamknij” startuje wątek, który koniec serwera zabija",
        RUNS,
        "                self._closing = True\n",
        "                pass\n",
        "zamknij-w-trakcie",
        "URUCHOMIENIA: NOWE NARUSZENIE",
    ),
    Mutation(
        "begin_update bez odmowy po przyjętym zamknięciu",
        "aktualizacja startuje po „Zamknij” i ginie w trakcie Gita albo pip",
        RUNS,
        "            if self._closing:\n                raise contract.Refusal(409, _CLOSING.format(then=\"zaktualizuj narzędzie\"))\n",
        "",
        "aktualizacja",
        "URUCHOMIENIA: NOWE NARUSZENIE",
    ),
    Mutation(
        "begin_update bez sprawdzenia trwającego Uruchomienia",
        "aktualizacja przesuwa klon narzędzia pod pracującym silnikiem",
        RUNS,
        "            busy = self._busy_locked(\"zaktualizuj narzędzie\")\n",
        "            busy = None\n",
        "aktualizacja",
        "URUCHOMIENIA: NOWE NARUSZENIE",
    ),
    Mutation(
        "RunHost.start bez odmowy w trakcie aktualizacji",
        "Uruchomienie startuje, gdy aktualizacja zmienia kod i biblioteki narzędzia",
        RUNS,
        "            if self._updating:\n                raise contract.Refusal(409, _UPDATING.format(then=\"uruchom proces\"))\n",
        "",
        "aktualizacja",
        "URUCHOMIENIA: NOWE NARUSZENIE",
    ),
    Mutation(
        "RLock zamiast Lock w RunHost",
        "model nie zna tej blokady, więc nie może nic orzec",
        RUNS,
        "        self._lock = threading.Lock()\n",
        "        self._lock = threading.RLock()\n",
        "zamknij-w-trakcie",
        "URUCHOMIENIA: LUKA MODELU",
    ),
)


def run_mutation(mutation: Mutation) -> tuple[bool, str]:
    with tempfile.TemporaryDirectory(prefix="uruchomienia-mutacja-") as scratch:
        source = Path(scratch) / "src"
        shutil.copytree(
            REPO_ROOT / "src",
            source,
            ignore=shutil.ignore_patterns("__pycache__", "*.egg-info"),
        )
        verified = source / mutation.file
        code = verified.read_text(encoding="utf-8")
        if code.count(mutation.anchor) != 1:
            return (
                False,
                f"NIEAKTUALNA: kotwicy nie ma dokładnie raz w {mutation.file.name}",
            )
        verified.write_text(code.replace(mutation.anchor, mutation.replacement), encoding="utf-8")
        environment = {
            **os.environ,
            "VERIFY_URUCHOMIENIA_SRC": str(source),
            "PYTHONUTF8": "1",
        }
        completed = subprocess.run(
            [sys.executable, str(EXPLORER), "--scope", mutation.scope],
            capture_output=True,
            text=True,
            encoding="utf-8",
            env=environment,
            timeout=600,
            check=False,
        )
    lines = completed.stdout.strip().splitlines()
    last = lines[-1] if lines else completed.stderr.strip()[-300:]
    return last.startswith(mutation.expected), last


def main() -> int:
    failures = 0
    for mutation in MUTATIONS:
        caught, last = run_mutation(mutation)
        failures += not caught
        verdict = "WYKRYTA" if caught else "NIEWYKRYTA"
        print(f"{verdict}: {mutation.name} ({mutation.harm}) → {last}", flush=True)
    print("MUTACJE OK" if not failures else f"MUTACJE: {failures} bez oczekiwanego wyniku")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())

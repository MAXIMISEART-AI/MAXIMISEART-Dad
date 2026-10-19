"""Show that explore_publication.py fails on broken variants of the publication code.

Each mutation is applied to a copy of ``src`` in a temporary directory, never to
the checkout. The checker then runs against that copy and must end with the
expected result. A mutation whose anchor text is no longer in
``preparation_files.py`` is reported as NIEAKTUALNA: update it to the new code.
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
VERIFIED = Path("rozliczenia") / "preparation_files.py"
EXPLORER = SCRIPTS / "explore_publication.py"


@dataclass(frozen=True)
class Mutation:
    name: str
    harm: str
    anchor: str
    replacement: str
    expected: str  # last line of the checker's report


MUTATIONS = (
    Mutation(
        "os.replace zamiast os.rename",
        "plik taty o nazwie pliku okresu zostaje zastąpiony",
        "            os.rename(staged_directory / filename, target)\n",
        "            os.replace(staged_directory / filename, target)\n",
        "PUBLIKACJA: NOWE NARUSZENIE",
    ),
    Mutation(
        "bez wycofania opublikowanego pliku",
        "po błędzie zostaje samo Rozliczenie wewnętrzne",
        "                target.unlink(missing_ok=True)\n",
        "                pass\n",
        "PUBLIKACJA: NOWE NARUSZENIE",
    ),
    Mutation(
        "nieudane wycofanie zgłaszane jak zwykły błąd zapisu",
        "zostaje Rozliczenie wewnętrzne, a komunikat mówi, że nie utworzono żadnego pliku",
        "                raise StopError(messages.write_failed_with_file_left(period_directory, target.name)) from exc\n",
        "                raise\n",
        "PUBLIKACJA: NOWE NARUSZENIE",
    ),
    Mutation(
        "zapis na listę do wycofania przed os.rename",
        "wycofanie usuwa plik taty",
        "            os.rename(staged_directory / filename, target)\n            published.append(target)\n",
        "            published.append(target)\n            os.rename(staged_directory / filename, target)\n",
        "PUBLIKACJA: NOWE NARUSZENIE",
    ),
    Mutation(
        "błąd sprzątania katalogu tymczasowego jako błąd zapisu",
        "oba pliki okresu są w Folderze okresu, a komunikat mówi, że nie utworzono żadnego pliku",
        ", ignore_cleanup_errors=True\n",
        "\n",
        "PUBLIKACJA: NOWE NARUSZENIE",
    ),
    Mutation(
        "shutil.move zamiast os.rename",
        "przy zajętej nazwie shutil.move kopiuje plik i nadpisuje cel",
        "            os.rename(staged_directory / filename, target)\n",
        "            __import__('shutil').move(staged_directory / filename, target)\n",
        "PUBLIKACJA: LUKA MODELU",
    ),
)


def run_mutation(mutation: Mutation) -> tuple[bool, str]:
    with tempfile.TemporaryDirectory(prefix="publikacja-mutacja-") as scratch:
        source = Path(scratch) / "src"
        shutil.copytree(REPO_ROOT / "src", source, ignore=shutil.ignore_patterns("__pycache__", "*.egg-info"))
        verified = source / VERIFIED
        code = verified.read_text(encoding="utf-8")
        if code.count(mutation.anchor) != 1:
            return False, "NIEAKTUALNA: kotwicy nie ma dokładnie raz w preparation_files.py"
        verified.write_text(code.replace(mutation.anchor, mutation.replacement), encoding="utf-8")
        environment = {**os.environ, "VERIFY_PUBLIKACJA_SRC": str(source), "PYTHONUTF8": "1"}
        completed = subprocess.run(
            [sys.executable, str(EXPLORER)],
            capture_output=True,
            text=True,
            encoding="utf-8",
            env=environment,
            timeout=300,
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
        print(f"{verdict}: {mutation.name} ({mutation.harm}) → {last}")
    print("MUTACJE OK" if not failures else f"MUTACJE: {failures} bez oczekiwanego wyniku")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())

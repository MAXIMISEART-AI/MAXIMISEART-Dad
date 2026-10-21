"""Uruchamia po kolei każde sprawdzenie mutacji skilli weryfikacji: ``.agents/skills/*/scripts/check_*mutations.py``.

Skill dodaje swoje sprawdzenie samą nazwą pliku, bez wpisu w CI ani w ``tools/ci_lokalnie.py``.
Sprawdzenia biegną po kolei Pythonem, który uruchomił skrypt, bo każde samo zajmuje rdzenie runnera.
Wyjście sprawdzeń idzie bez zmian; na końcu jedna linia na sprawdzenie i ``MUTACJE SKILLI OK``
albo ``MUTACJE SKILLI FAIL | <sprawdzenia>``. Brak sprawdzeń to porażka, żeby zmiana nazw
nie wyłączyła ich po cichu.

    py -3 tools/mutacje.py                  # Windows
    .venv/bin/python tools/mutacje.py       # macOS i Linux
"""

from __future__ import annotations

from pathlib import Path
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
SKILLS = ROOT / ".agents" / "skills"
PATTERN = "*/scripts/check_*mutations.py"


def main() -> int:
    checks = sorted(SKILLS.glob(PATTERN))
    if not checks:
        print(f"MUTACJE SKILLI FAIL | brak plików {SKILLS.relative_to(ROOT).as_posix()}/{PATTERN}")
        return 1
    results = []
    for check in checks:
        name = check.relative_to(SKILLS).as_posix()
        print(f"== {name}", flush=True)
        started = time.monotonic()
        passed = subprocess.run((sys.executable, str(check)), cwd=ROOT, check=False).returncode == 0
        results.append((name, passed, time.monotonic() - started))
    for name, passed, elapsed in results:
        print(f"{'OK  ' if passed else 'FAIL'} {name} ({elapsed:.0f} s)")
    failed = [name for name, passed, _ in results if not passed]
    if failed:
        print(f"MUTACJE SKILLI FAIL | {', '.join(failed)}")
        return 1
    print(f"MUTACJE SKILLI OK | {len(results)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

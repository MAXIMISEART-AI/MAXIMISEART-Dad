"""Uruchamia po kolei skrypty mutacji wszystkich skilli weryfikacji, jak zadanie CI mutations.

Skrypt mutacji skilla to ``.agents/skills/<skill>/scripts/check_<co>_mutations.py``: dowodzi, że
sprawdzenie skilla pada na zepsutych wariantach kodu. Nowy skrypt o takiej nazwie trafia do CI
i do ``tools/ci_lokalnie.py`` bez wpisu w ``ci.yml``. Kończy się ``MUTACJE SKILLI OK`` albo
``MUTACJE SKILLI FAIL | <skrypty>``.

    py -3 tools/mutacje_skilli.py                  # Windows
    .venv/bin/python tools/mutacje_skilli.py       # macOS i Linux
"""

from __future__ import annotations

from pathlib import Path
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ".agents/skills/*/scripts/check_*mutations.py"


def main() -> int:
    scripts = sorted(ROOT.glob(SCRIPTS))
    if not scripts:
        print(f"MUTACJE SKILLI FAIL | brak skryptów {SCRIPTS}")
        return 1
    failed = []
    # Po kolei: mutacje kilku skilli naraz na czterech rdzeniach runnera przekraczają swoje limity czasu.
    for script in scripts:
        name = script.relative_to(ROOT).as_posix()
        print(f"== {name}", flush=True)
        started = time.monotonic()
        code = subprocess.run([sys.executable, str(script)], cwd=ROOT, stdin=subprocess.DEVNULL, check=False).returncode
        print(f"{'OK  ' if code == 0 else 'FAIL'} {name} ({time.monotonic() - started:.0f} s)", flush=True)
        if code != 0:
            failed.append(name)
    if failed:
        print(f"MUTACJE SKILLI FAIL | {', '.join(failed)}")
        return 1
    print("MUTACJE SKILLI OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

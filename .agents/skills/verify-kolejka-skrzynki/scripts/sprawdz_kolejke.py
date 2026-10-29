"""Podstawa skilla w CI: model TLA+ Kolejki Skrzynki (TLC) i sprawdzenie prawdziwego kodu, oba do końca.

Uruchamia po kolei ``sprawdz_model_kolejki.py`` i ``explore_outbox.py`` tym samym Pythonem, z ich wyjściem, i kończy
się linią ``KOLEJKA SKRZYNKI OK`` albo ``KOLEJKA SKRZYNKI: PADŁO <skrypty>`` z kodem 1.

    .venv/bin/python .agents/skills/verify-kolejka-skrzynki/scripts/sprawdz_kolejke.py
    py -3 .agents\\skills\\verify-kolejka-skrzynki\\scripts\\sprawdz_kolejke.py
"""

from __future__ import annotations

import argparse
from pathlib import Path
import subprocess
import sys

CHECKS = ("sprawdz_model_kolejki.py", "explore_outbox.py")


def main(argv: list[str] | None = None) -> int:
    argparse.ArgumentParser(description=__doc__.splitlines()[0] if __doc__ else None).parse_args(argv)
    here = Path(__file__).resolve().parent
    failed = [name for name in CHECKS if subprocess.run([sys.executable, str(here / name)], check=False).returncode != 0]
    print()
    if failed:
        print(f"KOLEJKA SKRZYNKI: PADŁO {' '.join(failed)}")
        return 1
    print("KOLEJKA SKRZYNKI OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

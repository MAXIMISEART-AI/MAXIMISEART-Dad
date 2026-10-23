"""Wypisuje skille ``verify-*``, które trzeba załadować dla zmiany od bazy (domyślnie ``origin/main``), każdy z powodem.

Zmiana to pliki z ``git diff BAZA...HEAD`` oraz pliki niezacommitowane i nieśledzone. Skill deklaruje we
frontmatterze ``SKILL.md`` klucz ``pilnuje:``, listę globów ścieżek względem korzenia repozytorium (``*`` obejmuje
też ``/``). Ten sam klucz, tym samym czytnikiem, wybiera mutacje skilla w CI (``tools/mutacje_skilli.py``). Skill
obowiązuje, gdy zmieniony plik pasuje do jego globu albo leży w jego folderze. Skill bez klucza albo z kluczem,
którego nie da się odczytać, obowiązuje zawsze.

Każdy skill, który obowiązuje, dostaje linię ``<skill>: <plik> (<glob>), …``. Ostatnia linia to
``SKILLE VERIFY: <skille po przecinku>`` albo ``SKILLE VERIFY: brak``. Gdy git nie wyznaczy zmiany (np. nie ma
bazy), ostatnia linia to ``SKILLE VERIFY: nieznane (<powód>)``, a kod wyjścia 1.

    .venv/bin/python tools/skille_dla_zmiany.py            # macOS i Linux
    py -3 tools/skille_dla_zmiany.py origin/main           # Windows
"""

from __future__ import annotations

import argparse
from collections.abc import Iterable
from fnmatch import fnmatchcase
from pathlib import Path
import subprocess

from mutacje_skilli import ROOT, SKILLS, guarded

VERDICT = "SKILLE VERIFY"
SHOWN = 3


def _names(*arguments: str) -> set[str]:
    out = subprocess.run(["git", *arguments], cwd=ROOT, capture_output=True, check=True).stdout.decode("utf-8")
    return {name for name in out.split("\0") if name}


def _changed(base: str) -> set[str]:
    return {
        *_names("diff", "--name-only", "--no-renames", "-z", f"{base}...HEAD"),
        *_names("diff", "--name-only", "--no-renames", "-z", "HEAD"),
        *_names("ls-files", "-z", "--others", "--exclude-standard"),
    }


def _reasons(skill_md: Path, files: Iterable[str]) -> list[str]:
    """Zmienione pliki, które dotykają skilla, każdy z globem, do którego pasuje; pusta lista, gdy żaden."""

    folder = skill_md.parent.relative_to(ROOT).as_posix()
    try:
        declared = guarded(skill_md)
    except ValueError as error:
        return [str(error)]
    if declared is None:
        return [f"{folder}/SKILL.md nie ma klucza pilnuje"]
    own = f"{folder}/*"
    found = []
    for name in sorted(files):
        glob = next((glob for glob in (own, *declared) if fnmatchcase(name, glob)), None)
        if glob is not None:
            found.append(name if glob == name else f"{name} ({'folder skilla' if glob == own else glob})")
    return found


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("baza", nargs="?", default="origin/main", help="Commit albo gałąź, od której liczy się zmiana.")
    args = parser.parse_args(argv)
    try:
        files = _changed(args.baza)
    except subprocess.CalledProcessError as error:
        detail = (error.stderr.decode("utf-8", "replace").strip().splitlines() or [f"kod {error.returncode}"])[0]
        print(f"{VERDICT}: nieznane (git {error.cmd[1]}: {detail})")
        return 1
    chosen = []
    for skill_md in sorted(SKILLS.glob("verify-*/SKILL.md")):
        found = _reasons(skill_md, files)
        if found:
            chosen.append(skill_md.parent.name)
            more = f" i {len(found) - SHOWN} innych" if len(found) > SHOWN else ""
            print(f"{skill_md.parent.name}: {', '.join(found[:SHOWN])}{more}")
    print(f"{VERDICT}: {', '.join(chosen) or 'brak'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

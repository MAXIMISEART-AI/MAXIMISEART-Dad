"""Wypisuje skille ``verify-*``, które trzeba załadować dla zmiany od bazy (domyślnie ``origin/main``), każdy z powodem.

Zmiana to pliki z ``git diff BAZA...HEAD`` oraz pliki niezacommitowane i nieśledzone. Skill deklaruje we
frontmatterze ``SKILL.md`` klucz ``pilnuje:``, listę globów ścieżek względem korzenia repozytorium (``*`` obejmuje
też ``/``). Ten sam klucz, tym samym czytnikiem, wybiera mutacje skilla w CI (``tools/mutacje_skilli.py``). Skill
obowiązuje, gdy zmieniony plik pasuje do jego globu, leży w jego folderze albo jest plikiem spoza ``src/``, który
wykonują skrypty skilla: ich importem (przechodnio) albo skryptem ``.py``, który uruchamiają ścieżką z ``/``, razem z
jego importami. Tych plików ``pilnuje`` nie musi wymieniać. Skill bez klucza albo z kluczem, którego nie da się
odczytać, obowiązuje zawsze.

Każdy skill, który obowiązuje, dostaje linię ``<skill>: <plik> (<glob>), …``. Ostatnia linia to
``SKILLE VERIFY: <skille po przecinku>`` albo ``SKILLE VERIFY: brak``. Gdy git nie wyznaczy zmiany (np. nie ma
bazy), ostatnia linia to ``SKILLE VERIFY: nieznane (<powód>)``, a kod wyjścia 1.

    .venv/bin/python tools/skille_dla_zmiany.py            # macOS i Linux
    py -3 tools/skille_dla_zmiany.py origin/main           # Windows
"""

from __future__ import annotations

import argparse
import ast
from collections.abc import Iterable
from fnmatch import fnmatchcase
from pathlib import Path
import subprocess

from mutacje_skilli import PATTERN, ROOT, SKILLS, closure, guarded
from szybko import references

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


def _executed(skill: Path) -> set[Path]:
    """Pliki spoza ``src/``, które wykonują skrypty skilla.

    Produkt w ``src/`` wybiera tylko ``pilnuje``: skrypty importują prawie cały pakiet, a skill pilnuje swojego
    zachowania. Skrypty mutacji pomija, bo ich werdykt sprawdza zadanie CI mutations (``tools/mutacje_skilli.py``).
    """

    scripts = [path for path in skill.glob("scripts/**/*.py") if not fnmatchcase(path.name, PATTERN)]
    launched = {
        ROOT / text
        for script in scripts
        for text in references(ast.parse(script.read_bytes(), filename=str(script)))[0]
        if "/" in text and text.endswith(".py") and (ROOT / text).is_file()
    }
    return {path for path in closure([*scripts, *launched]) if not path.is_relative_to(ROOT / "src")}


def _reasons(skill_md: Path, files: Iterable[str]) -> list[str]:
    """Zmienione pliki, które dotykają skilla, każdy z powodem; pusta lista, gdy żaden."""

    folder = skill_md.parent.relative_to(ROOT).as_posix()
    try:
        declared = guarded(skill_md)
        executed = _executed(skill_md.parent)
    except SyntaxError as error:
        where = Path(error.filename or "")
        shown = where.relative_to(ROOT).as_posix() if where.is_relative_to(ROOT) else where.name
        return [f"{shown} się nie parsuje, więc skill obowiązuje zawsze ({error.msg})"]
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
        elif ROOT / name in executed:
            found.append(f"{name} (wykonują go skrypty skilla)")
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

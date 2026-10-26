"""Wypisuje skille ``verify-*``, które obowiązują dla zmiany od bazy (domyślnie ``origin/main``), każdy z powodem.

Zmiana to ``szybko.changed_since``: pliki z ``git diff`` od rozgałęzienia z bazą oraz pliki niezacommitowane i
nieśledzone. Skill deklaruje we frontmatterze ``SKILL.md`` klucz ``pilnuje:``, listę globów ścieżek względem korzenia
repozytorium (``*`` obejmuje też ``/``). Skill obowiązuje, gdy zmieniony plik pasuje do jego globu albo leży w jego
folderze: to ten sam wybór (``mutacje_skilli.hits``), który na pull request uruchamia w CI podstawę skilla. Skill bez
klucza albo z kluczem, którego nie da się odczytać, obowiązuje zawsze.

Każdy skill, który obowiązuje, dostaje linię ``<skill>: <plik> (<glob>), …``. Ostatnia linia to
``SKILLE VERIFY: <skille po przecinku>`` albo ``SKILLE VERIFY: brak``: każdy skill, który obowiązuje, także taki,
którego polecenia liczy CI, bo jego workflow ma kroki, których CI nie zrobi (osąd, prawdziwe Wzorce, Excel na Macu).
Przed nią linia ``LICZY CI: <skill> (<polecenie>, …); …`` wymienia polecenia tych skilli, które liczy CI na tym SHA: kroki
skilla z wyboru planu runu pull request (``mutacje_skilli.wybor``) i wywołania jego skryptów w krokach CI (``ci_runs``),
więc agent nie uruchamia ich lokalnie poza odtworzeniem czerwonego kroku CI. Gdy git nie wyznaczy zmiany (np. nie ma
bazy), ostatnia linia to ``SKILLE VERIFY: nieznane (<powód>)``, a kod wyjścia 1.

    .venv/bin/python tools/skille_dla_zmiany.py            # macOS i Linux
    py -3 tools/skille_dla_zmiany.py origin/main           # Windows
"""

from __future__ import annotations

import argparse
from collections.abc import Iterable
from pathlib import Path
import re
import subprocess

from mutacje_skilli import ROOT, SKILLS, Step, hits, wybor
import szybko

VERDICT = "SKILLE VERIFY"
IN_CI = "LICZY CI"
SHOWN = 3
# Pliki, w których CI wywołuje skrypty skilli: kroki ci.yml i kroki planu runu (E2E w zadaniach pytest).
CI_FILES = (ROOT / ".github" / "workflows" / "ci.yml", ROOT / "tools" / "plan_ci.py")
# Wywołanie skryptu skilla: skill, ścieżka skryptu w ``scripts/`` i argumenty do końca linii.
SKILL_COMMAND = re.compile(r"\.agents/skills/([\w-]+)/scripts/([\w/]+\.py)((?:[ \t]+[^\s`\"']+)*)")

def ci_runs(skill: Path, steps: Iterable[Step]) -> list[tuple[str, ...]]:
    """Polecenia skilla (nazwa skryptu z argumentami), które liczy CI: jego kroki z ``steps`` i wywołania w krokach CI.

    Kroki to podstawa ``ci:`` i skrypty mutacji (zadanie Mutation checks), a wywołania stoją w ``ci.yml`` i
    ``tools/plan_ci.py``. Klucz ``ci:``, którego nie da się odczytać, nie daje kroku: plan CI zgłasza go w Required.
    """

    runs = [(Path(step.command[0]).name, *step.command[1:]) for step in steps if step.skill == skill]
    workflow = "\n".join(path.read_text(encoding="utf-8") for path in CI_FILES if path.is_file())
    runs += [(Path(script).name, *arguments.split()) for name, script, arguments in SKILL_COMMAND.findall(workflow) if name == skill.name]
    return list(dict.fromkeys(runs))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("baza", nargs="?", default="origin/main", help="Commit albo gałąź, od której liczy się zmiana.")
    args = parser.parse_args(argv)
    try:
        files = szybko.changed_since(args.baza)
    except subprocess.CalledProcessError as error:
        detail = (error.stderr.strip().splitlines() or [f"kod {error.returncode}"])[0]
        print(f"{VERDICT}: nieznane (git {error.cmd[1]}: {detail})")
        return 1
    chosen_steps = [step for step, _ in wybor(files).chosen]
    chosen: list[str] = []
    in_ci: list[str] = []
    for skill_md in sorted(SKILLS.glob("verify-*/SKILL.md")):
        found = hits(skill_md.parent, files)
        reasons = [found.always] if found.always else [name if glob == name else f"{name} ({glob})" for name, glob in found.files.items()]
        if not reasons:
            continue
        chosen.append(skill_md.parent.name)
        if runs := ci_runs(skill_md.parent, chosen_steps):
            in_ci.append(f"{skill_md.parent.name} ({', '.join(' '.join(run) for run in runs)})")
        more = f" i {len(reasons) - SHOWN} innych" if len(reasons) > SHOWN else ""
        print(f"{skill_md.parent.name}: {', '.join(reasons[:SHOWN])}{more}")
    if in_ci:
        print(f"{IN_CI}: {'; '.join(in_ci)}")
    print(f"{VERDICT}: {', '.join(chosen) or 'brak'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

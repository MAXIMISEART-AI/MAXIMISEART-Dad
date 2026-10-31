"""Wypisuje skille verify-*, które obowiązują dla zmiany od bazy, każdy z powodem; użyj przed pushem i przed oceną gotowości PR.

Wypisuje skille ``verify-*``, które obowiązują dla zmiany od bazy (domyślnie ``origin/main``), każdy z powodem.

Zmiana to ``szybko.changed_since``: pliki z ``git diff`` od rozgałęzienia z bazą oraz pliki niezacommitowane i
nieśledzone. Skill deklaruje we frontmatterze ``SKILL.md`` klucz ``pilnuje:``, listę globów ścieżek względem korzenia
repozytorium (``*`` obejmuje też ``/``). Skill obowiązuje, gdy zmieniony plik pasuje do jego globu albo leży w jego
folderze: to ten sam wybór (``mutacje_skilli.hits``), który na pull request uruchamia w CI podstawę skilla. Skill bez
klucza albo z kluczem, którego nie da się odczytać, obowiązuje zawsze.

Każdy skill, który obowiązuje, dostaje linię ``<skill>: <plik> (<glob>), …``. Ostatnia linia to
``SKILLE VERIFY: <skille po przecinku>`` albo ``SKILLE VERIFY: brak``: każdy skill, który obowiązuje, także taki,
którego polecenia liczy CI, bo jego workflow ma kroki, których CI nie zrobi (osąd, prawdziwe Wzorce, Excel na Macu).
Przed nią linia ``LICZY CI: <skill> (<polecenie>, …); …`` wymienia polecenia tych skilli, które liczy CI na tym SHA, tak
jak plan runu pull request: podstawy skilla z wyboru ``mutacje_skilli.wybor`` i wywołania jego skryptów w ``ci.yml`` i w
krokach CI, które ``plan_ci.zakres`` daje tej zmianie (E2E przy zmianie ``src/``). Linia ``LICZY NOC: <skill>
(<skrypt>, …); …`` wymienia skrypty mutacji tych skilli, które po merge'u liczy noc na ``main`` (``mutacje_skilli.wybor``
z ``night``, ADR 0021). Agent nie uruchamia ich lokalnie poza odtworzeniem czerwonego kroku CI albo issue nocy. Gdy git
nie wyznaczy zmiany (np. nie ma bazy), ostatnia linia to ``SKILLE VERIFY: nieznane (<powód>)``, a kod wyjścia 1.

    .venv/bin/python tools/skille_dla_zmiany.py            # macOS i Linux
    py -3 tools/skille_dla_zmiany.py origin/main           # Windows
"""

from __future__ import annotations

import argparse
from collections.abc import Iterable
from pathlib import Path
import re
import subprocess
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools/ci"))

from mutacje_skilli import ROOT, SKILLS, Step, hits, wybor
import plan_ci
import szybko

VERDICT = "SKILLE VERIFY"
IN_CI = "LICZY CI"
AT_NIGHT = "LICZY NOC"
SHOWN = 3
# Plik kroków CI; kroki planu runu (E2E w zadaniach pytest) to ``plan_ci.KROKI``.
CI_FILES = (ROOT / ".github" / "workflows" / "ci.yml",)
# Wywołanie skryptu skilla: skill, ścieżka skryptu w ``scripts/`` i argumenty do końca linii.
SKILL_COMMAND = re.compile(r"\.agents/skills/([\w-]+)/scripts/([\w/]+\.py)((?:[ \t]+[^\s`\"']+)*)")

def ci_runs(skill: Path, steps: Iterable[Step], ci_steps: Iterable[plan_ci.Krok]) -> list[tuple[str, ...]]:
    """Polecenia skilla (nazwa skryptu z argumentami), które liczy CI: jego kroki z ``steps`` i wywołania w krokach CI.

    Kroki to podstawa ``ci:`` i skrypty mutacji (zadanie Mutation checks), a wywołania stoją w ``ci.yml`` i w
    poleceniach ``ci_steps``. Klucz ``ci:``, którego nie da się odczytać, nie daje kroku: plan CI zgłasza go w Required.
    """

    runs = [(Path(step.command[0]).name, *step.command[1:]) for step in steps if step.skill == skill]
    texts = [path.read_text(encoding="utf-8") for path in CI_FILES if path.is_file()]
    workflow = "\n".join([*texts, *(command for step in ci_steps for command in step.polecenia)])
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
    night_steps = [step for step, _ in wybor(files, night=True).chosen]
    ci_steps = [plan_ci.KROKI[name] for name in sorted({name for lane in plan_ci.zakres("pull_request", files).tory for name in lane.kroki})]
    chosen: list[str] = []
    in_ci: list[str] = []
    at_night: list[str] = []
    for skill_md in sorted(SKILLS.glob("verify-*/SKILL.md")):
        found = hits(skill_md.parent, files)
        reasons = [found.always] if found.always else [name if glob == name else f"{name} ({glob})" for name, glob in found.files.items()]
        if not reasons:
            continue
        chosen.append(skill_md.parent.name)
        if runs := ci_runs(skill_md.parent, chosen_steps, ci_steps):
            in_ci.append(f"{skill_md.parent.name} ({', '.join(' '.join(run) for run in runs)})")
        if scripts := [Path(step.command[0]).name for step in night_steps if step.skill == skill_md.parent]:
            at_night.append(f"{skill_md.parent.name} ({', '.join(scripts)})")
        more = f" i {len(reasons) - SHOWN} innych" if len(reasons) > SHOWN else ""
        print(f"{skill_md.parent.name}: {', '.join(reasons[:SHOWN])}{more}")
    if in_ci:
        print(f"{IN_CI}: {'; '.join(in_ci)}")
    if at_night:
        print(f"{AT_NIGHT}: {'; '.join(at_night)}")
    print(f"{VERDICT}: {', '.join(chosen) or 'brak'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

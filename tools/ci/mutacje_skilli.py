"""Uruchamia po kolei skrypty mutacji wszystkich skilli weryfikacji, jak zadanie CI mutations.

Skrypt mutacji skilla to ``.agents/skills/<skill>/scripts/check_<co>_mutations.py``: dowodzi, że
sprawdzenie skilla pada na zepsutych wariantach kodu, i kończy się linią ``MUTACJE OK``. Nowy
skrypt o takiej nazwie trafia do CI i do ``tools/ci_lokalnie.py`` bez wpisu w ``ci.yml``.

Skrypt nie może zgubić się po cichu. FAIL dostaje plik ``.py`` w skillu z ``mutation`` w nazwie,
który nie pasuje do wzorca, oraz skrypt mutacji wskazany w ``SKILL.md`` skilla, którego nie ma.
FAIL dostaje też skrypt, który przekroczył limit czasu, skończył się kodem innym niż 0 albo nie
wydrukował na końcu ``MUTACJE OK``. Skrypt biegnie przez ``tools/lib/potomne.py``: jego procesy
potomne giną po jego końcu i po limicie, a cały skrypt ginie razem z runnerem, choćby zabitym
przez SIGKILL. Kończy się ``MUTACJE SKILLI OK`` albo ``MUTACJE SKILLI FAIL | <skrypty>``.

Z ``--zmiany-od REF`` biegnie tylko krok, którego werdykt może zmienić zmiana od ``REF`` (``szybko.changed_since``, z
niezacommitowanymi), jak na pull request w CI (ADR 0020): podstawy skilli. Skill deklaruje we frontmatterze ``SKILL.md``
klucz ``pilnuje:``, listę globów ścieżek względem korzenia repozytorium (``*`` obejmuje też ``/``). Podstawa skilla
biegnie, gdy zmieniony jest plik z ``pilnuje`` albo plik w folderze skilla; ten sam wybór (``hits``) wskazuje skille
``verify-*`` w ``tools/skille_dla_zmiany.py``. Skrypty mutacji na pull request nie biegną, tylko nocą na ``main``
(``--noc``, workflow ``mutacje-nocne.yml``, ADR 0021): mierzą jakość sprawdzenia skilla, tak jak mutacje zmienionych
linii mierzą jakość testów. Z ``--zmiany-od REF --noc`` biegną same skrypty mutacji, a skrypt biegnie, gdy zmieniony
jest plik w folderze skilla, runner mutacji (``RUNNER``) albo sprawdzenie, które uruchamiają jego mutacje. Importów ani
plików, które krok czyta, wybór nie liczy: każdy krok uruchamia pełne CI ``main``. Zmiana ``INFRASTRUCTURE`` uruchamia
każdy krok swojego rodzaju, a skill bez klucza ``pilnuje`` albo z kluczem, którego nie da się odczytać, biegnie zawsze.
Pominięty krok dostaje linię ``POMINIĘTY``.

Krok to podstawa skilla albo jeden jego skrypt mutacji. W CI kroki dzieli między zadania Mutation checks plan runu
(``tools/plan_ci.py``): bierze ten sam wybór (``wybor``), waży kroki czasami z ``czasy-ci``, a skrypt mutacji dłuższy niż
zadanie dzieli na części, które ``run`` uruchamia z ``MUTACJE_CZESC`` (``tools/mutacje.py``). Skrypty zgubione i zły
klucz ``ci:`` plan zgłasza w ``Required CI status``.

Skill może zadeklarować we frontmatterze klucz ``ci:``: polecenie (skrypt ``.py`` z repozytorium, ścieżka od korzenia,
i jego argumenty), którym CI sprawdza skill na niezmienionym kodzie. Runner uruchamia je jako krok ``PODSTAWA``
(przed skryptami mutacji skilla, gdy biegną w tym samym zadaniu), także w skillu bez skryptu mutacji. Polecenie, które wybrany
skrypt mutacji i tak uruchamia bez mutacji (podstawa ``check_all``), nie biegnie drugi raz. Podstawa przechodzi z kodem 0.
Klucz ``ci-czesci: <n>`` mówi, że polecenie ``ci:`` dzieli się na najwyżej n części, które plan CI uruchamia jak części
skryptu mutacji, z ``MUTACJE_CZESC=k/n`` (``tools/lib/skrypt_skilla.py``, ``part``); bez klucza podstawa jest niepodzielna.
Na pull request biegną części jednego n, więc taką podstawę wybiera też noc (``--noc``), przy tej samej zmianie co pull
request, a jej plan uruchamia każdą część każdego n od 1 do ``ci-czesci``: część, która pada tylko przy innym n, wychodzi
w nocy, zanim plan pull requestu po zmianie celu ściany wybierze to n.

    py -3 tools/ci/mutacje_skilli.py                  # Windows
    .venv/bin/python tools/ci/mutacje_skilli.py       # macOS i Linux
    .venv/bin/python tools/ci/mutacje_skilli.py --zmiany-od origin/main
    .venv/bin/python tools/ci/mutacje_skilli.py --zmiany-od origin/main --noc
"""

from __future__ import annotations

import argparse
import ast
from collections.abc import Iterable, Mapping
from fnmatch import fnmatchcase
from functools import cache
import importlib.util
import os
from pathlib import Path
import re
import subprocess
import sys
import time
from typing import Any, NamedTuple

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools"))
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools/lib"))

import potomne
import szybko

ROOT = Path(__file__).resolve().parents[2]
SKILLS = ROOT / ".agents" / "skills"
PATTERN = "check_*_mutations.py"
# Wywołanie skryptu mutacji w SKILL.md; ścieżka bez ``.agents`` na początku liczy się od folderu skilla.
MENTION = re.compile(r"[\w.\\/-]*scripts[\\/]check_\w+_mutations\.py")
VERDICT = "MUTACJE OK"
BASELINE = "PODSTAWA"
# Najdłuższy skrypt trwał w CI na Windows 770 s; limit łapie zawieszenie, a nie wolny runner.
LIMIT_S = 30 * 60
# Zmiana, po której na pull request biegnie każdy krok każdego skilla: biblioteki, zadanie CI, końce linii kopii.
INFRASTRUCTURE = ("requirements.txt", ".github/workflows/ci.yml", ".gitattributes")
# Runner mutacji: jego zmiana może zmienić werdykt każdego skryptu mutacji.
RUNNER = ("tools/mutacje.py", "tools/ci/mutacje_skilli.py")
# Powód w ``Hits`` dla pliku w folderze skilla.
FOLDER = "folder skilla"
# Powody pominięcia kroku, który biegnie przy innym zdarzeniu niż wybór.
NIGHTLY = "skrypt mutacji biegnie nocą na main (mutacje-nocne.yml, ADR 0021)"
ON_PULL_REQUEST = "podstawa biegnie na pull request, nie nocą"


def _name(path: Path) -> str:
    return path.relative_to(ROOT).as_posix() if path.is_relative_to(ROOT) else path.as_posix()


@cache
def _mutations(script: Path) -> tuple[Any, ...]:
    spec = importlib.util.spec_from_file_location(f"_mutacje_{script.parents[1].name}", script)
    if spec is None or spec.loader is None:
        raise ImportError(f"nie da się wczytać {_name(script)}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return tuple(module.MUTATIONS)


def _front(skill_md: Path) -> list[str]:
    """Linie frontmattera ``SKILL.md``.

    Czytniki kluczy nie parsują frontmattera jako YAML, bo opisy skilli mają w tekście dwukropki, których YAML nie
    przyjmuje.
    """

    lines = skill_md.read_text(encoding="utf-8").splitlines() if skill_md.is_file() else []
    end = lines.index("---", 1) if lines[:1] == ["---"] and "---" in lines[1:] else 0
    return lines[1:end]


def _values(skill_md: Path, key: str) -> list[str]:
    """Wartości linii ``<key>: <wartość>`` frontmattera, w kolejności."""

    return [line.split(":", 1)[1] for line in _front(skill_md) if line.split(":", 1)[0] == key]


def guarded(skill_md: Path) -> tuple[str, ...] | None:
    """Globy z klucza ``pilnuje`` frontmattera ``SKILL.md``; ``None``, gdy klucza nie ma.

    Klucz to linia ``pilnuje:``, a pod nią linie ``  - <glob>``.
    """

    front = _front(skill_md)
    keys = [number for number, line in enumerate(front) if line.split(":", 1)[0] == "pilnuje"]
    if not keys:
        return None
    if front[keys[0]] != "pilnuje:":
        raise ValueError(f"pilnuje w {_name(skill_md)} nie jest listą globów pod kluczem")
    globs = []
    for line in front[keys[0] + 1 :]:
        if not line.startswith("  - "):
            break
        globs.append(line.removeprefix("  - ").strip())
    if not globs:
        raise ValueError(f"pilnuje w {_name(skill_md)} nie ma żadnego globu")
    return tuple(globs)


def ci_parts(skill_md: Path) -> int:
    """Najwięcej części polecenia ``ci`` z klucza ``ci-czesci`` frontmattera ``SKILL.md``; bez klucza 1.

    Klucz to jedna linia ``ci-czesci: <liczba całkowita od 1>``.
    """

    values = _values(skill_md, "ci-czesci")
    if not values:
        return 1
    if not values[0].strip().isdigit() or int(values[0]) < 1:
        raise ValueError(f"ci-czesci w {_name(skill_md)} nie jest liczbą części od 1")
    return int(values[0])


def ci_command(skill_md: Path) -> tuple[str, ...] | None:
    """Polecenie z klucza ``ci`` frontmattera ``SKILL.md``; ``None``, gdy klucza nie ma.

    Klucz to jedna linia ``ci: <skrypt .py od korzenia repozytorium> <argumenty>``.
    """

    values = _values(skill_md, "ci")
    if not values:
        return None
    command = tuple(values[0].split())
    if not command or not command[0].endswith(".py") or not (ROOT / command[0]).is_file():
        raise ValueError(f"ci w {_name(skill_md)} nie zaczyna się skryptem .py z repozytorium")
    return command


class Hits(NamedTuple):
    """Zmienione pliki, przy których skill obowiązuje: plik → glob ``pilnuje``, który go obejmuje, albo ``FOLDER``.

    ``always`` to powód, gdy skill obowiązuje przy każdej zmianie: nie ma klucza ``pilnuje`` albo nie da się go odczytać.
    """

    files: dict[str, str]
    always: str | None


def hits(skill: Path, changed: Iterable[str]) -> Hits:
    """Pliki ``changed``, przy których skill obowiązuje, a na pull request biegnie jego podstawa ``ci``."""

    try:
        globs = guarded(skill / "SKILL.md")
    except ValueError as error:
        return Hits({}, str(error))
    if globs is None:
        return Hits({}, f"{_name(skill)}/SKILL.md nie ma klucza pilnuje")
    own = f"{_name(skill)}/"
    found = {}
    for name in sorted(changed):
        glob = FOLDER if name.startswith(own) else next((glob for glob in globs if fnmatchcase(name, glob)), None)
        if glob is not None:
            found[name] = glob
    return Hits(found, None)


class Step(NamedTuple):
    """Krok zadania: podstawa ``ci`` skilla (``verdict`` ``None``) albo jeden jego skrypt mutacji.

    ``parts`` to najwięcej części kroku: liczba mutacji skryptu, bo więcej części skrypt nie ma, a podstawy ``ci-czesci``
    (bez klucza 1); ``browser``: skrypty skilla importują Playwright, więc zadanie CI potrzebuje Chromium.
    """

    skill: Path
    key: str
    name: str
    command: tuple[str, ...]
    verdict: str | None
    parts: int
    browser: bool


class Selection(NamedTuple):
    """Kroki, które biegną przy tych zmianach, i dlaczego; pominięte i dlaczego; FAIL-e znalezienia kroków."""

    chosen: list[tuple[Step, str]]
    skipped: list[tuple[Step, str]]
    failed: dict[str, str]


def _lost(scripts: list[Path]) -> dict[str, str]:
    """Skrypty mutacji, których runner by nie uruchomił, z powodem."""

    lost = {
        _name(path): f"nazwa spoza wzorca scripts/{PATTERN}"
        for path in SKILLS.glob("*/**/*.py")
        if "mutation" in path.name.lower() and path not in scripts
    }
    for skill_md in SKILLS.glob("*/SKILL.md"):
        for mentioned in set(MENTION.findall(skill_md.read_text(encoding="utf-8"))):
            relative = mentioned.replace("\\", "/").removeprefix("./")
            base = ROOT if relative.startswith(".agents/") else skill_md.parent
            path = Path(os.path.normpath(base / relative))
            if path not in scripts:
                lost.setdefault(_name(path), f"wskazany w {_name(skill_md)}, a nie ma go pod tą nazwą")
    return lost


def run(step: Step, limit_s: float = LIMIT_S, env: Mapping[str, str] | None = None) -> str | None:
    """Uruchamia krok z echem wyjścia i zmiennymi ``env``; zwraca powód porażki albo ``None``.

    Skrypt mutacji kończy się linią ``VERDICT``, podstawie wystarczy kod 0. Plan CI daje części skryptu
    ``MUTACJE_CZESC`` przez ``env``.
    """

    command = step.command
    try:
        done = potomne.run(
            [sys.executable, str(ROOT / command[0]), *command[1:]],
            cwd=ROOT,
            env={**os.environ, "PYTHONIOENCODING": "utf-8", **(env or {})},
            timeout=limit_s,
            echo=True,
        )
    except subprocess.TimeoutExpired:
        return f"przekroczył limit {limit_s:.0f} s"
    if done.returncode != 0:
        return f"kod wyjścia {done.returncode}"
    if step.verdict is not None and [line.strip() for line in done.stdout.splitlines() if line.strip()][-1:] != [step.verdict]:
        return f"brak końcowej linii {step.verdict}"
    return None


@cache
def _browser(skill: Path) -> bool:
    """Skrypty skilla importują Playwright; skrypt, który się nie parsuje, liczy się jak taki, co importuje."""

    for path in skill.glob("scripts/**/*.py"):
        try:
            tree = ast.parse(path.read_bytes(), filename=str(path))
        except SyntaxError:
            return True
        for node in ast.walk(tree):
            names = [alias.name for alias in node.names] if isinstance(node, ast.Import) else []
            names += [node.module] if isinstance(node, ast.ImportFrom) and node.module and not node.level else []
            if any(name.split(".")[0] == "playwright" for name in names):
                return True
    return False


def _count(script: Path) -> int:
    """Liczba mutacji skryptu; tabela, której nie da się wczytać, to jedna niepodzielna część, która pokaże swój błąd."""

    try:
        return max(1, len(_mutations(script)))
    except Exception:  # noqa: BLE001 - błąd tabeli zgłasza sam skrypt mutacji, gdy biegnie
        return 1


def steps(failed: dict[str, str]) -> list[Step]:
    """Kroki wszystkich skilli, podstawa każdego skilla z kluczem ``ci`` przed jego skryptami; zły klucz ``ci`` albo
    ``ci-czesci`` trafia do ``failed``."""

    skills: dict[Path, list[Path]] = {skill_md.parent: [] for skill_md in SKILLS.glob("*/SKILL.md") if _values(skill_md, "ci")}
    for script in sorted(SKILLS.glob(f"*/scripts/{PATTERN}")):
        skills.setdefault(script.parents[1], []).append(script)
    found = []
    for skill, scripts in sorted(skills.items()):
        try:
            command, parts = ci_command(skill / "SKILL.md"), ci_parts(skill / "SKILL.md")
        except ValueError as error:
            failed[f"{BASELINE} {skill.name}"] = str(error)
            command = None
        browser = _browser(skill)
        if command:
            found.append(Step(skill, f"{skill.name}/ci", f"{BASELINE} {skill.name}", command, None, parts, browser))
        found += [
            Step(skill, f"{skill.name}/{script.name}", _name(script), (_name(script),), VERDICT, _count(script), browser) for script in scripts
        ]
    return found


def _changes(names: Iterable[str]) -> str:
    names = sorted(names)
    return f"zmienione: {', '.join(names[:3])}" + (f" i {len(names) - 3} innych" if len(names) > 3 else "")


def watched(step: Step) -> tuple[str, ...]:
    """Ścieżki, których zmiana uruchamia skrypt mutacji ``step``: folder skilla (z ``/`` na końcu), ``RUNNER`` i
    sprawdzenia, które uruchamiają jego mutacje; tabela, której nie da się wczytać, to wyjątek z ``exec_module``."""

    checkers = sorted({mutation.command[0] for mutation in _mutations(ROOT / step.command[0])})
    return (f"{_name(step.skill)}/", *RUNNER, *checkers)


def _why_run(step: Step, changed: frozenset[str], night: bool) -> tuple[bool, str]:
    """Czy krok biegnie przy zmianie ``changed``, i dlaczego: na pull request podstawa, nocą (``night``) skrypt mutacji
    i podstawa z ``ci-czesci``, której plan CI daje nocą każdą część każdej liczby części.

    Podstawa biegnie przy trafieniu w ``pilnuje`` albo w folder skilla, skrypt mutacji przy zmianie ścieżki z
    ``watched``. Zmiana ``INFRASTRUCTURE`` uruchamia każdy krok swojego rodzaju.
    """

    if night == (step.verdict is None) and not (night and step.parts > 1):
        return False, ON_PULL_REQUEST if night else NIGHTLY
    found = hits(step.skill, changed)
    if found.always:
        return True, found.always
    if infrastructure := changed.intersection(INFRASTRUCTURE):
        return True, _changes(infrastructure)
    if step.verdict is None:
        if found.files:
            return True, _changes(found.files)
        return False, "zmiany nie trafiają w pilnuje ani w folder skilla"
    try:
        paths = watched(step)
    except Exception as error:  # noqa: BLE001 - skrypt, którego tabeli nie da się wczytać, biegnie i pokazuje swój błąd
        return True, f"nie da się wczytać tabeli mutacji: {error}"
    touched = {name for name in changed if name.startswith(paths[0]) or name in paths[1:]}
    if touched:
        return True, _changes(touched)
    return False, "zmiany nie dotykają folderu skilla, runnera mutacji ani sprawdzeń, które uruchamiają mutacje skryptu"


def _repeats(step: Step, chosen: Iterable[Step]) -> bool:
    """Podstawę uruchamia bez mutacji (podstawa ``check_all``) wybrany skrypt mutacji jej skilla."""

    scripts = [ROOT / other.command[0] for other in chosen if other.skill == step.skill and other.verdict]
    try:
        return any(step.command == tuple(mutation.command) for script in scripts for mutation in _mutations(script))
    except Exception:  # noqa: BLE001 - tabeli, której nie da się wczytać, podstawa nie zastąpi: biegnie polecenie ci
        return False


def wybor(changed: frozenset[str] | None, *, night: bool = False) -> Selection:
    """Kroki, które biegną przy zmianie ``changed`` (``None``: push, wszystkie), pominięte i FAIL-e znalezienia.

    Przy zmianie biegną podstawy jak na pull request, a z ``night`` skrypty mutacji jak nocą na ``main``.
    """

    scripts = sorted(SKILLS.glob(f"*/scripts/{PATTERN}"))
    failed = _lost(scripts)
    found = steps(failed)
    if not scripts and not failed:
        failed[f"scripts/{PATTERN}"] = f"brak skryptów .agents/skills/*/scripts/{PATTERN}"
    why = {step: (True, "") if changed is None else _why_run(step, changed, night) for step in found}
    running = [step for step in found if why[step][0]]
    chosen = [(step, why[step][1]) for step in running if step.verdict or not _repeats(step, running)]
    skipped = [(step, why[step][1]) for step in found if not why[step][0]]
    return Selection(chosen, skipped, failed)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--limit-s", type=float, default=LIMIT_S, help="Limit czasu jednego skryptu w sekundach.")
    parser.add_argument("--zmiany-od", metavar="REF", help="Tylko kroki, których werdykt może zmienić zmiana od REF.")
    parser.add_argument("--noc", action="store_true", help="Z --zmiany-od: skrypty mutacji, które uruchamia noc, zamiast podstaw.")
    args = parser.parse_args(argv)
    if args.noc and args.zmiany_od is None:
        parser.error("--noc wybiera kroki zmiany, więc wymaga --zmiany-od")
    selection = wybor(None if args.zmiany_od is None else szybko.changed_since(args.zmiany_od), night=args.noc)
    failed = dict(selection.failed)
    for name, why in sorted(failed.items()):
        print(f"FAIL {name}: {why}", flush=True)
    for step, why in selection.skipped:
        print(f"POMINIĘTY {step.name}: {why}", flush=True)
    # Po kolei: mutacje kilku skilli naraz na czterech rdzeniach runnera przekraczają swoje limity czasu.
    for step, why in selection.chosen:
        shown = step.name if step.verdict else f"{step.name}: {' '.join(step.command)}"
        print(f"== {shown}" + (f" ({why})" if why else ""), flush=True)
        started = time.monotonic()
        reason = run(step, args.limit_s)
        elapsed = f"({time.monotonic() - started:.0f} s)"
        print(f"OK   {step.name} {elapsed}" if reason is None else f"FAIL {step.name} {elapsed}: {reason}", flush=True)
        if reason is not None:
            failed[step.name] = reason
    if failed:
        print(f"MUTACJE SKILLI FAIL | {', '.join(sorted(failed))}")
        return 1
    print("MUTACJE SKILLI OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

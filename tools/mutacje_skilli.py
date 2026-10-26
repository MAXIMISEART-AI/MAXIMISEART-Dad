"""Uruchamia po kolei skrypty mutacji wszystkich skilli weryfikacji, jak zadanie CI mutations.

Skrypt mutacji skilla to ``.agents/skills/<skill>/scripts/check_<co>_mutations.py``: dowodzi, że
sprawdzenie skilla pada na zepsutych wariantach kodu, i kończy się linią ``MUTACJE OK``. Nowy
skrypt o takiej nazwie trafia do CI i do ``tools/ci_lokalnie.py`` bez wpisu w ``ci.yml``.

Skrypt nie może zgubić się po cichu. FAIL dostaje plik ``.py`` w skillu z ``mutation`` w nazwie,
który nie pasuje do wzorca, oraz skrypt mutacji wskazany w ``SKILL.md`` skilla, którego nie ma.
FAIL dostaje też skrypt, który przekroczył limit czasu, skończył się kodem innym niż 0 albo nie
wydrukował na końcu ``MUTACJE OK``. Skrypt biegnie przez ``tools/potomne.py``: jego procesy
potomne giną po jego końcu i po limicie, a cały skrypt ginie razem z runnerem, choćby zabitym
przez SIGKILL. Kończy się ``MUTACJE SKILLI OK`` albo ``MUTACJE SKILLI FAIL | <skrypty>``.

Z ``--zmiany-od REF`` biegnie tylko skrypt, którego werdykt mogą zmienić zmiany od ``REF`` (jak
w ``git diff REF...HEAD``, z niezacommitowanymi). Skill deklaruje we frontmatterze ``SKILL.md`` klucz
``pilnuje:``, listę globów ścieżek względem korzenia repozytorium (``*`` obejmuje też ``/``). Skill
bez tego klucza biegnie zawsze. Skrypt skilla z kluczem biegnie, gdy zmieniony jest plik z
``pilnuje``, plik w folderze skilla albo plik, który skrypt czyta: on sam, sprawdzenia z poleceń
jego mutacji, pliki, które mutacje zmieniają, ich importy z repozytorium (każdy ``import`` w kodzie,
także w funkcji), skrypty ``.py``, które pliki spoza ``src/`` uruchamiają ścieżką z ``/`` (``executed``, ten sam
wybór co w ``tools/skille_dla_zmiany.py``), oraz infrastruktura mutacji: ten runner z importami i ``INFRASTRUCTURE``.
Pliki czytane liczy runner, więc lista ``pilnuje`` nie musi ich powtarzać i nie zawęża selekcji poniżej nich. Skrypt,
którego plików nie da się tak wyznaczyć (polecenie mutacji nie jest skryptem z repozytorium, kod się nie parsuje),
biegnie zawsze. Pominięty skrypt dostaje linię ``POMINIĘTY``.

Krok to podstawa skilla albo jeden jego skrypt mutacji. W CI kroki dzieli między zadania Mutation checks plan runu
(``tools/plan_ci.py``): bierze ten sam wybór (``wybor``), waży kroki czasami z ``czasy-ci``, a skrypt mutacji dłuższy niż
zadanie dzieli na części, które ``run`` uruchamia z ``MUTACJE_CZESC`` (``tools/mutacje.py``). Skrypty zgubione i zły
klucz ``ci:`` plan zgłasza w ``Required CI status``.

Skill może zadeklarować we frontmatterze klucz ``ci:``: polecenie (skrypt ``.py`` z repozytorium, ścieżka od korzenia,
i jego argumenty), którym CI sprawdza skill na niezmienionym kodzie. Runner uruchamia je jako krok ``PODSTAWA``
(przed skryptami mutacji skilla, gdy biegną w tym samym zadaniu), z tym samym wyborem co skrypt mutacji, także w skillu bez skryptu mutacji. Polecenie, które skrypt
mutacji i tak uruchamia bez mutacji (podstawa ``check_all``), nie biegnie drugi raz. Podstawa przechodzi z kodem 0.

    py -3 tools/mutacje_skilli.py                  # Windows
    .venv/bin/python tools/mutacje_skilli.py       # macOS i Linux
    .venv/bin/python tools/mutacje_skilli.py --zmiany-od origin/main
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

import potomne
from sciezki_w_kodzie import references

ROOT = Path(__file__).resolve().parents[1]
SKILLS = ROOT / ".agents" / "skills"
SRC = ROOT / "src"
PATTERN = "check_*_mutations.py"
# Wywołanie skryptu mutacji w SKILL.md; ścieżka bez ``.agents`` na początku liczy się od folderu skilla.
MENTION = re.compile(r"[\w.\\/-]*scripts[\\/]check_\w+_mutations\.py")
VERDICT = "MUTACJE OK"
BASELINE = "PODSTAWA"
# Najdłuższy skrypt trwał w CI na Windows 770 s; limit łapie zawieszenie, a nie wolny runner.
LIMIT_S = 30 * 60
# Pliki spoza Pythona, od których zależy przebieg mutacji w CI: biblioteki, zadanie CI, końce linii kopii.
INFRASTRUCTURE = ("requirements.txt", ".github/workflows/ci.yml", ".gitattributes")
# Katalogi, w których skrypty i sprawdzenia szukają importów (sys.path), poza katalogiem importującego pliku.
IMPORT_ROOTS = (ROOT / "src", ROOT / "tools", ROOT)


def _name(path: Path) -> str:
    return path.relative_to(ROOT).as_posix() if path.is_relative_to(ROOT) else path.as_posix()


def _git(*arguments: str) -> list[str]:
    out = subprocess.run(["git", *arguments], cwd=ROOT, capture_output=True, check=True).stdout.decode("utf-8")
    return [name for name in out.split("\0") if name]


def _changed(base: str) -> set[str]:
    return {
        *_git("diff", "--name-only", "--no-renames", "-z", f"{base}...HEAD"),
        *_git("diff", "--name-only", "--no-renames", "-z", "HEAD"),
        *_git("ls-files", "-z", "--others", "--exclude-standard"),
    }


def _modules(name: str, roots: Iterable[Path]) -> set[Path]:
    """Pliki, które może wykonać import ``name``: pakiety po drodze i sam moduł.

    Także te, których nie ma: usunięty plik zmienia, co wykona import w niezmienionym pliku.
    """

    parts = name.split(".")
    return {
        candidate
        for root in roots
        for depth in range(1, len(parts) + 1)
        for candidate in (root.joinpath(*parts[:depth], "__init__.py"), root.joinpath(*parts[:depth]).with_suffix(".py"))
    }


@cache
def _imports(path: Path) -> set[Path]:
    roots = (*IMPORT_ROOTS, path.parent)
    found = set()
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"), filename=str(path))):
        if isinstance(node, ast.Import):
            for alias in node.names:
                found |= _modules(alias.name, roots)
        elif isinstance(node, ast.ImportFrom):
            bases = (path.parents[node.level - 1],) if node.level else roots
            module = node.module or ""
            names = [module] if module else []
            names += [f"{module}.{alias.name}" if module else alias.name for alias in node.names]
            for name in names:
                found |= _modules(name, bases)
    return found


def closure(starts: Iterable[Path]) -> set[Path]:
    """Pliki, które wykonuje uruchomienie ``starts``: one same i ich importy, przechodnio, także te, których nie ma."""

    seen: set[Path] = set()
    # Importy już są bezwzględne i bez ``..``: ``resolve`` setek tysięcy kandydatów trwałby sekundy.
    todo = [path.resolve() for path in starts]
    while todo:
        path = todo.pop()
        if path in seen:
            continue
        seen.add(path)
        if path.suffix == ".py" and path.is_file():
            todo += _imports(path)
    return seen


@cache
def launched(path: Path) -> set[Path]:
    """Skrypty ``.py`` z repozytorium, które plik uruchamia ścieżką z ``/`` (``"tools/x.py"``, ``ROOT / "tools" / "x.py"``)."""

    texts = references(ast.parse(path.read_bytes(), filename=str(path)))[0]
    return {ROOT / text for text in texts if "/" in text and text.endswith(".py") and (ROOT / text).is_file()}


def executed(starts: Iterable[Path]) -> set[Path]:
    """Pliki, które wykonuje uruchomienie ``starts``: ``closure`` razem ze skryptami, które uruchamiają ścieżką, przechodnio.

    Uruchomień szuka tylko poza ``src/``: produkt nie uruchamia skryptów repozytorium, a skill może pilnować go ``pilnuje``.
    """

    seen = closure(starts)
    todo = seen
    while todo:
        found = {
            script
            for path in todo
            if path.suffix == ".py" and path.is_file() and not path.is_relative_to(SRC)
            for script in launched(path)
        }
        todo = closure(found) - seen
        seen |= todo
    return seen


@cache
def _mutations(script: Path) -> tuple[Any, ...]:
    spec = importlib.util.spec_from_file_location(f"_mutacje_{script.parents[1].name}", script)
    if spec is None or spec.loader is None:
        raise ImportError(f"nie da się wczytać {_name(script)}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return tuple(module.MUTATIONS)


def reads(script: Path) -> set[str]:
    """Pliki repozytorium, których zmiana może zmienić werdykt skryptu."""

    starts = {script, Path(__file__), *(ROOT / name for name in INFRASTRUCTURE)}
    for mutation in _mutations(script):
        checker = ROOT / mutation.command[0]
        if checker.suffix != ".py" or not checker.is_file():
            raise ValueError(f"polecenie mutacji {mutation.name!r} nie zaczyna się skryptem z repozytorium")
        starts |= {checker, *(ROOT / edit.file for edit in mutation.edits)}
    return {_name(path) for path in executed(starts) if path.is_relative_to(ROOT)}


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


def skill_scripts(skill: Path) -> list[Path]:
    """Skrypty skilla bez skryptów mutacji: te uruchamia jego workflow i polecenie ``ci``."""

    return [path for path in skill.glob("scripts/**/*.py") if not fnmatchcase(path.name, PATTERN)]


def read_in_ci(skill: Path, scripts: list[Path]) -> set[str]:
    """Pliki repozytorium, których zmiana może zmienić werdykt podstawy ``ci`` skilla albo jego skryptów mutacji ``scripts``."""

    command = ci_command(skill / "SKILL.md")
    # Polecenie ``ci`` uruchamia też skrypty skilla ścieżką od ``__file__``, której ``launched`` nie nazwie, więc liczą się
    # wszystkie, jak w ``tools/skille_dla_zmiany.py``.
    ran = [ROOT / command[0], *skill_scripts(skill)] if command else []
    starts = {Path(__file__), *(ROOT / name for name in INFRASTRUCTURE), *ran}
    return {_name(path) for path in executed(starts) if path.is_relative_to(ROOT)}.union(*map(reads, scripts))


def _why_run(skill: Path, scripts: list[Path], changed: set[str]) -> tuple[bool, str]:
    """Czy podstawa i skrypty mutacji skilla biegną przy tych zmianach, i dlaczego."""

    try:
        globs = guarded(skill / "SKILL.md")
        if globs is None:
            return True, f"{_name(skill)}/SKILL.md nie ma klucza pilnuje"
        read = read_in_ci(skill, scripts)
    except Exception as error:  # noqa: BLE001 - skill, którego plików nie da się wyznaczyć, biegnie i pokazuje swój błąd
        return True, f"nie da się wyznaczyć plików, które czyta: {error}"
    touched = sorted(
        name
        for name in changed
        if name.startswith(f"{_name(skill)}/") or name in read or any(fnmatchcase(name, glob) for glob in globs)
    )
    if touched:
        return True, f"zmienione: {', '.join(touched[:3])}" + (f" i {len(touched) - 3} innych" if len(touched) > 3 else "")
    files = sum((ROOT / name).is_file() for name in read)
    return False, f"zmiany nie dotykają pilnuje, folderu skilla ani {files} plików repozytorium, które skill czyta w CI"


class Step(NamedTuple):
    """Krok zadania: podstawa ``ci`` skilla (``verdict`` ``None``) albo jeden jego skrypt mutacji.

    ``mutations`` to liczba mutacji skryptu (podstawa: 0), bo więcej części skrypt nie ma; ``browser``: skrypty skilla
    importują Playwright, więc zadanie CI potrzebuje Chromium.
    """

    skill: Path
    key: str
    name: str
    command: tuple[str, ...]
    verdict: str | None
    mutations: int
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
    ``MUTACJE_CZESC`` przez ``env``, bez importu ``tools/mutacje.py`` tutaj: import poszerzyłby pliki, które czyta każdy skill.
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


def _baseline(skill: Path, scripts: list[Path]) -> tuple[str, ...] | None:
    """Polecenie ``ci`` skilla, gdy żaden jego skrypt mutacji nie uruchamia go sam bez mutacji; ``ValueError``, gdy zły klucz."""

    command = ci_command(skill / "SKILL.md")
    if command is None:
        return None
    try:
        repeated = any(command == tuple(mutation.command) for script in scripts for mutation in _mutations(script))
    except Exception:  # noqa: BLE001 - tabeli, której nie da się wczytać, podstawa nie zastąpi: biegnie polecenie ci
        repeated = False
    return None if repeated else command


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
    """Kroki wszystkich skilli; zły klucz ``ci`` trafia do ``failed``."""

    skills: dict[Path, list[Path]] = {skill_md.parent: [] for skill_md in SKILLS.glob("*/SKILL.md") if _values(skill_md, "ci")}
    for script in sorted(SKILLS.glob(f"*/scripts/{PATTERN}")):
        skills.setdefault(script.parents[1], []).append(script)
    found = []
    for skill, scripts in sorted(skills.items()):
        try:
            command = _baseline(skill, scripts)
        except ValueError as error:
            failed[f"{BASELINE} {skill.name}"] = str(error)
            command = None
        browser = _browser(skill)
        if command:
            found.append(Step(skill, f"{skill.name}/ci", f"{BASELINE} {skill.name}", command, None, 0, browser))
        found += [
            Step(skill, f"{skill.name}/{script.name}", _name(script), (_name(script),), VERDICT, _count(script), browser) for script in scripts
        ]
    return found


def wybor(changed_from: str | None) -> Selection:
    """Kroki, które biegną przy zmianach od ``changed_from`` (``None``: wszystkie), pominięte i FAIL-e znalezienia."""

    scripts = sorted(SKILLS.glob(f"*/scripts/{PATTERN}"))
    failed = _lost(scripts)
    # Przed krokami: wczytanie tabel mutacji zostawia w skillach __pycache__, a to nie jest zmiana od bazy.
    changed = None if changed_from is None else _changed(changed_from)
    found = steps(failed)
    if not scripts and not failed:
        failed[f"scripts/{PATTERN}"] = f"brak skryptów .agents/skills/*/scripts/{PATTERN}"
    why: dict[Path, tuple[bool, str]] = {}
    for skill in dict.fromkeys(step.skill for step in found):
        mutations = [ROOT / step.command[0] for step in found if step.skill == skill and step.verdict]
        why[skill] = (True, "") if changed is None else _why_run(skill, mutations, changed)
    chosen = [(step, why[step.skill][1]) for step in found if why[step.skill][0]]
    skipped = [(step, why[step.skill][1]) for step in found if not why[step.skill][0]]
    return Selection(chosen, skipped, failed)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--limit-s", type=float, default=LIMIT_S, help="Limit czasu jednego skryptu w sekundach.")
    parser.add_argument("--zmiany-od", metavar="REF", help="Tylko skrypty, których werdykt mogą zmienić zmiany od REF.")
    args = parser.parse_args(argv)
    selection = wybor(args.zmiany_od)
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

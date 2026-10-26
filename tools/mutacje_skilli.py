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
wybór co w ``tools/skille_dla_zmiany.py``), oraz infrastruktura mutacji: ten runner z importami i ``INFRASTRUCTURE``. Pliki
czytane liczy runner, więc lista ``pilnuje`` nie musi ich powtarzać i nie zawęża selekcji poniżej
nich. Skrypt, którego plików nie da się tak wyznaczyć (polecenie mutacji nie jest skryptem z
repozytorium, kod się nie parsuje), biegnie zawsze. Pominięty skrypt dostaje linię ``POMINIĘTY``.
Z ``--czesc K/N`` biegną kroki K-tej z N części o podobnym czasie w CI (``CI_TIMES_S``), więc
N zadań CI dzieli kroki bez listy w ``ci.yml``. Części powstają z kroków, które przeszły wybór ``--zmiany-od``, więc
pominięty krok nie waży w żadnej, a linię ``POMINIĘTY`` drukuje każda część. Każda część liczy podział sama, z wyboru i
tabeli, bez zależności od kolejności zbiorów ani czasu, więc N części uruchamia każdy wybrany krok dokładnie raz.
Krok to podstawa skilla albo jeden jego skrypt mutacji, więc
podstawa i mutacje jednego skilla mogą biec w różnych częściach. Krok spoza tabeli waży tyle, co mediana tabeli:
nieaktualna tabela psuje tylko równowagę części, nie gubi kroku.

Skill może zadeklarować we frontmatterze klucz ``ci:``: polecenie (skrypt ``.py`` z repozytorium, ścieżka od korzenia,
i jego argumenty), którym CI sprawdza skill na niezmienionym kodzie. Runner uruchamia je jako krok ``PODSTAWA``
(w części z mutacjami skilla przed nimi), z tym samym wyborem co skrypt mutacji, także w skillu bez skryptu mutacji. Polecenie, które skrypt
mutacji i tak uruchamia bez mutacji (podstawa ``check_all``), nie biegnie drugi raz. Podstawa przechodzi z kodem 0.

    py -3 tools/mutacje_skilli.py                  # Windows
    .venv/bin/python tools/mutacje_skilli.py       # macOS i Linux
    .venv/bin/python tools/mutacje_skilli.py --zmiany-od origin/main
"""

from __future__ import annotations

import argparse
import ast
from collections.abc import Iterable
from fnmatch import fnmatchcase
from functools import cache
import importlib.util
import os
from pathlib import Path
import re
import statistics
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
# Czas kroku w zadaniu CI na windows-latest, mediana runów 40205575015, 40207090403, 40207957312, 40208186531 i
# 40209671390 (bez pierwszego; podstawa Centrum z jednej próby, skrypty mutacji Centrum z runu 40236525553 po
# podziale w #464); dzieli kroki na części.
# Klucz to ``<skill>/ci`` dla podstawy i ``<skill>/<skrypt>`` dla skryptu mutacji.
CI_TIMES_S: dict[str, float] = {
    "verify-aktualizacja-narzedzia/ci": 22,
    "verify-centrum-rozliczen/ci": 259,
    "verify-centrum-rozliczen/check_centrum_aktualizacja_mutations.py": 111,
    "verify-centrum-rozliczen/check_centrum_diagnoza_mutations.py": 48,
    "verify-centrum-rozliczen/check_centrum_karta_z_logow_mutations.py": 53,
    "verify-centrum-rozliczen/check_centrum_przebieg_rozliczen_mutations.py": 147,
    "verify-centrum-rozliczen/check_centrum_przygotowanie_pliku_zbiorczego_mutations.py": 80,
    "verify-centrum-rozliczen/check_centrum_uwaga_taty_mutations.py": 95,
    "verify-centrum-rozliczen/check_centrum_uzupelnienie_mutations.py": 257,
    "verify-centrum-rozliczen/check_centrum_zgloszenie_mutations.py": 49,
    "verify-jedno-uruchomienie-naraz/ci": 33,
    "verify-jedno-uruchomienie-naraz/check_runs_mutations.py": 332,
    "verify-kopia-wzorca/check_copy_mutations.py": 342,
    "verify-publikacja-plikow-okresu/check_publication_mutations.py": 90,
    "verify-rozliczenia/check_quantity_rules_mutations.py": 77,
    "verify-skoroszyty-w-excelu/check_excel_cleanup_mutations.py": 22,
}
# Pliki spoza Pythona, od których zależy przebieg mutacji w CI: biblioteki, zadanie CI, końce linii kopii.
INFRASTRUCTURE = ("requirements.txt", ".github/workflows/ci.yml", ".gitattributes")
# Katalogi, w których skrypty i sprawdzenia szukają importów (sys.path), poza katalogiem importującego pliku.
IMPORT_ROOTS = (ROOT / "src", ROOT / "tools", ROOT)


def _name(path: Path) -> str:
    return path.relative_to(ROOT).as_posix() if path.is_relative_to(ROOT) else path.as_posix()


def _part(text: str) -> tuple[int, int]:
    number, _, count = text.partition("/")
    if not (number.isdigit() and count.isdigit() and 1 <= int(number) <= int(count)):
        raise argparse.ArgumentTypeError(f"część K/N z 1 <= K <= N, nie {text!r}")
    return int(number), int(count)


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
    """Krok zadania: podstawa ``ci`` skilla (``verdict`` ``None``) albo jeden jego skrypt mutacji."""

    skill: Path
    key: str
    name: str
    command: tuple[str, ...]
    verdict: str | None


def parts(steps: list[Step], count: int, times: dict[str, float]) -> list[list[Step]]:
    """Kroki w ``count`` częściach: każdy następny najdłuższy krok do części o najmniejszej sumie czasu.

    W części podstawa skilla biegnie przed jego skryptami mutacji.
    """

    default = statistics.median(times.values()) if times else 1.0
    weight = {step: times.get(step.key, default) for step in steps}
    chosen: list[list[Step]] = [[] for _ in range(count)]
    sums = [0.0] * count
    for step in sorted(steps, key=lambda step: (-weight[step], step.key)):
        lightest = sums.index(min(sums))
        chosen[lightest].append(step)
        sums[lightest] += weight[step]
    return [sorted(part, key=lambda step: (step.skill, step.verdict is not None, step.key)) for part in chosen]


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


def _run(command: tuple[str, ...], limit_s: float, verdict: str | None) -> str | None:
    """Uruchamia skrypt z argumentami z echem wyjścia; zwraca powód porażki albo ``None``.

    ``verdict`` to wymagana ostatnia linia wyjścia; ``None``: wystarczy kod 0.
    """

    try:
        done = potomne.run(
            [sys.executable, str(ROOT / command[0]), *command[1:]],
            cwd=ROOT,
            env={**os.environ, "PYTHONIOENCODING": "utf-8"},
            timeout=limit_s,
            echo=True,
        )
    except subprocess.TimeoutExpired:
        return f"przekroczył limit {limit_s:.0f} s"
    if done.returncode != 0:
        return f"kod wyjścia {done.returncode}"
    if verdict is not None and [line.strip() for line in done.stdout.splitlines() if line.strip()][-1:] != [verdict]:
        return f"brak końcowej linii {verdict}"
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
        if command:
            found.append(Step(skill, f"{skill.name}/ci", f"{BASELINE} {skill.name}", command, None))
        found += [Step(skill, f"{skill.name}/{script.name}", _name(script), (_name(script),), VERDICT) for script in scripts]
    return found


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--limit-s", type=float, default=LIMIT_S, help="Limit czasu jednego skryptu w sekundach.")
    parser.add_argument("--zmiany-od", metavar="REF", help="Tylko skrypty, których werdykt mogą zmienić zmiany od REF.")
    parser.add_argument("--czesc", metavar="K/N", type=_part, help="Tylko skrypty K-tej z N części o podobnym czasie w CI.")
    args = parser.parse_args(argv)
    scripts = sorted(SKILLS.glob(f"*/scripts/{PATTERN}"))
    failed = _lost(scripts)
    # Przed krokami: wczytanie tabel mutacji zostawia w skillach __pycache__, a to nie jest zmiana od bazy.
    changed = None if args.zmiany_od is None else _changed(args.zmiany_od)
    found = steps(failed)
    for name, why in sorted(failed.items()):
        print(f"FAIL {name}: {why}", flush=True)
    if not scripts and not failed:
        print(f"MUTACJE SKILLI FAIL | brak skryptów .agents/skills/*/scripts/{PATTERN}")
        return 1
    number, count = args.czesc or (1, 1)
    selected: dict[Path, tuple[bool, str]] = {}
    for step in found:
        if step.skill not in selected:
            mutations = [ROOT / other.command[0] for other in found if other.skill == step.skill and other.verdict]
            selected[step.skill] = (True, "") if changed is None else _why_run(step.skill, mutations, changed)
        runs, why = selected[step.skill]
        if not runs:
            print(f"POMINIĘTY {step.name}: {why}", flush=True)
    # Po kolei: mutacje kilku skilli naraz na czterech rdzeniach runnera przekraczają swoje limity czasu.
    for step in parts([step for step in found if selected[step.skill][0]], count, CI_TIMES_S)[number - 1]:
        why = selected[step.skill][1]
        shown = step.name if step.verdict else f"{step.name}: {' '.join(step.command)}"
        print(f"== {shown}" + (f" ({why})" if why else ""), flush=True)
        started = time.monotonic()
        reason = _run(step.command, args.limit_s, step.verdict)
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

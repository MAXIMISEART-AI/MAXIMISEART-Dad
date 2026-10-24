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
także w funkcji) oraz infrastruktura mutacji: ten runner z importami i ``INFRASTRUCTURE``. Pliki
czytane liczy runner, więc lista ``pilnuje`` nie musi ich powtarzać i nie zawęża selekcji poniżej
nich. Skrypt, którego plików nie da się tak wyznaczyć (polecenie mutacji nie jest skryptem z
repozytorium, kod się nie parsuje), biegnie zawsze. Pominięty skrypt dostaje linię ``POMINIĘTY``.
Z ``--czesc K/N`` biegną skrypty K-tej z N części o podobnym czasie w CI (``CI_TIMES_S``), więc
N zadań CI dzieli skrypty bez listy w ``ci.yml``. Skrypt spoza tabeli waży tyle, co mediana tabeli:
nieaktualna tabela psuje tylko równowagę części, nie gubi skryptu.

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

import potomne

ROOT = Path(__file__).resolve().parents[1]
SKILLS = ROOT / ".agents" / "skills"
PATTERN = "check_*_mutations.py"
# Wywołanie skryptu mutacji w SKILL.md; ścieżka bez ``.agents`` na początku liczy się od folderu skilla.
MENTION = re.compile(r"[\w.\\/-]*scripts[\\/]check_\w+_mutations\.py")
VERDICT = "MUTACJE OK"
# Najdłuższy skrypt trwał w CI na Windows 770 s; limit łapie zawieszenie, a nie wolny runner.
LIMIT_S = 30 * 60
# Czas skryptu skilla w zadaniu CI na windows-latest (mediana 3 prób run 40062771086); dzieli skrypty na części.
CI_TIMES_S: dict[str, float] = {
    "verify-centrum-rozliczen": 145,
    "verify-jedno-uruchomienie-naraz": 325,
    "verify-kopia-wzorca": 293,
    "verify-publikacja-plikow-okresu": 97,
    "verify-rozliczenia": 75,
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


def reads(script: Path) -> set[str]:
    """Pliki repozytorium, których zmiana może zmienić werdykt skryptu."""

    spec = importlib.util.spec_from_file_location(f"_mutacje_{script.parents[1].name}", script)
    if spec is None or spec.loader is None:
        raise ImportError(f"nie da się wczytać {_name(script)}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    starts = {script, Path(__file__), *(ROOT / name for name in INFRASTRUCTURE)}
    for mutation in module.MUTATIONS:
        checker = ROOT / mutation.command[0]
        if checker.suffix != ".py" or not checker.is_file():
            raise ValueError(f"polecenie mutacji {mutation.name!r} nie zaczyna się skryptem z repozytorium")
        starts |= {checker, *(ROOT / edit.file for edit in mutation.edits)}
    return {_name(path) for path in closure(starts) if path.is_relative_to(ROOT)}


def guarded(skill_md: Path) -> tuple[str, ...] | None:
    """Globy z klucza ``pilnuje`` frontmattera ``SKILL.md``; ``None``, gdy klucza nie ma.

    Klucz to linia ``pilnuje:``, a pod nią linie ``  - <glob>``. Czytnik nie parsuje reszty frontmattera
    jako YAML, bo opisy skilli mają w tekście dwukropki, których YAML nie przyjmuje.
    """

    lines = skill_md.read_text(encoding="utf-8").splitlines() if skill_md.is_file() else []
    end = lines.index("---", 1) if lines[:1] == ["---"] and "---" in lines[1:] else 0
    front = lines[1:end]
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


def _why_run(script: Path, changed: set[str]) -> tuple[bool, str]:
    """Czy skrypt biegnie przy tych zmianach, i dlaczego."""

    skill = script.parents[1]
    try:
        globs = guarded(skill / "SKILL.md")
        if globs is None:
            return True, f"{_name(skill)}/SKILL.md nie ma klucza pilnuje"
        read = reads(script)
    except Exception as error:  # noqa: BLE001 - skrypt, którego plików nie da się wyznaczyć, biegnie i pokazuje swój błąd
        return True, f"nie da się wyznaczyć plików, które czyta: {error}"
    touched = sorted(
        name
        for name in changed
        if name.startswith(f"{_name(skill)}/") or name in read or any(fnmatchcase(name, glob) for glob in globs)
    )
    if touched:
        return True, f"zmienione: {', '.join(touched[:3])}" + (f" i {len(touched) - 3} innych" if len(touched) > 3 else "")
    files = sum((ROOT / name).is_file() for name in read)
    return False, f"zmiany nie dotykają pilnuje, folderu skilla ani {files} plików repozytorium, które skrypt czyta"


def parts(scripts: list[Path], count: int, times: dict[str, float]) -> list[list[Path]]:
    """Skrypty w ``count`` częściach: każdy następny najdłuższy skrypt do części o najmniejszej sumie czasu."""

    default = statistics.median(times.values()) if times else 1.0
    weight = {script: times.get(script.parents[1].name, default) for script in scripts}
    chosen: list[list[Path]] = [[] for _ in range(count)]
    sums = [0.0] * count
    for script in sorted(scripts, key=lambda script: (-weight[script], _name(script))):
        lightest = sums.index(min(sums))
        chosen[lightest].append(script)
        sums[lightest] += weight[script]
    return [sorted(part) for part in chosen]


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


def _run(script: Path, limit_s: float) -> str | None:
    """Uruchamia skrypt z echem wyjścia; zwraca powód porażki albo ``None``."""

    try:
        done = potomne.run(
            [sys.executable, str(script)],
            cwd=ROOT,
            env={**os.environ, "PYTHONIOENCODING": "utf-8"},
            timeout=limit_s,
            echo=True,
        )
    except subprocess.TimeoutExpired:
        return f"przekroczył limit {limit_s:.0f} s"
    if done.returncode != 0:
        return f"kod wyjścia {done.returncode}"
    if [line.strip() for line in done.stdout.splitlines() if line.strip()][-1:] != [VERDICT]:
        return f"brak końcowej linii {VERDICT}"
    return None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--limit-s", type=float, default=LIMIT_S, help="Limit czasu jednego skryptu w sekundach.")
    parser.add_argument("--zmiany-od", metavar="REF", help="Tylko skrypty, których werdykt mogą zmienić zmiany od REF.")
    parser.add_argument("--czesc", metavar="K/N", type=_part, help="Tylko skrypty K-tej z N części o podobnym czasie w CI.")
    args = parser.parse_args(argv)
    scripts = sorted(SKILLS.glob(f"*/scripts/{PATTERN}"))
    failed = _lost(scripts)
    for name, why in sorted(failed.items()):
        print(f"FAIL {name}: {why}", flush=True)
    if not scripts and not failed:
        print(f"MUTACJE SKILLI FAIL | brak skryptów .agents/skills/*/scripts/{PATTERN}")
        return 1
    changed = None if args.zmiany_od is None else _changed(args.zmiany_od)
    number, count = args.czesc or (1, 1)
    # Po kolei: mutacje kilku skilli naraz na czterech rdzeniach runnera przekraczają swoje limity czasu.
    for script in parts(scripts, count, CI_TIMES_S)[number - 1]:
        name = _name(script)
        runs, why = (True, "") if changed is None else _why_run(script, changed)
        if not runs:
            print(f"POMINIĘTY {name}: {why}", flush=True)
            continue
        print(f"== {name}" + (f" ({why})" if why else ""), flush=True)
        started = time.monotonic()
        reason = _run(script, args.limit_s)
        elapsed = f"({time.monotonic() - started:.0f} s)"
        print(f"OK   {name} {elapsed}" if reason is None else f"FAIL {name} {elapsed}: {reason}", flush=True)
        if reason is not None:
            failed[name] = reason
    if failed:
        print(f"MUTACJE SKILLI FAIL | {', '.join(sorted(failed))}")
        return 1
    print("MUTACJE SKILLI OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

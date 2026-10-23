"""Szybkie sprawdzenie zmiany: ruff, mypy dla obu systemów, testy struktury i testy dotknięte zmianą.

Agent uruchamia je po każdej zmianie; pełną bramką jest CI na GitHubie. Zmiana to pliki, którymi checkout,
razem z niezacommitowanymi i nieśledzonymi plikami, różni się od ``merge-base`` HEAD z ``--baza`` (domyślnie
``origin/main``). Kroki ruff i mypy to kroki ``tools/ci_lokalnie.py``, a pytest to jego krok z wybranymi
testami. Kroki biegną naraz.

Test jest dotknięty, gdy zmiana obejmuje jego plik albo plik, od którego zależy. Zależności wynikają z samego
kodu, więc świeży worktree wybiera tak samo: importy modułów Pythona, a w ``tests/`` także ścieżki i nazwy
modułów w napisach, czyli skrypt, który test uruchamia, plik, który czyta, albo pliki katalogu. Zależność jest
przechodnia, z wyjątkiem plików katalogu. Zmiana w ``FULL`` (konfiguracja i zależności, ``conftest.py`` każdego
testu) wybiera wszystkie testy. Test, który już przeszedł na tych samych plikach, nie biegnie drugi raz:
pamięć zielonych testów leży w katalogu gita worktree.

Testy ``STRUCTURE`` pilnują reguł z tabeli w ``AGENTS.md`` i biegną przy każdej zmianie, a gdy ``--baza`` poszła
dalej niż HEAD, także na mergu z nią (to drzewo sprawdza CI PR-u; numer ADR zajęty równolegle pada dopiero tam).
Szybko nie pobiera ``origin``, więc merge jest z bazą z ostatniego ``git fetch``.

Kończy się ``SZYBKO OK`` albo ``SZYBKO FAIL | <kroki>``.

    .venv/bin/python tools/szybko.py
    .venv/bin/python tools/szybko.py --baza feat/galaz-rodzica
"""

from __future__ import annotations

import argparse
import ast
from collections import defaultdict
from collections.abc import Iterable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, replace
import hashlib
import json
from pathlib import Path, PurePosixPath
import subprocess
import sys
import threading
import time
from typing import TypeGuard
import xml.etree.ElementTree as ET

import ci_lokalnie
from mutacje import environment
import potomne

ROOT = Path(__file__).resolve().parents[1]
BASE = "origin/main"
FULL = ("pyproject.toml", "requirements.txt", "tests/conftest.py")
STRUCTURE = (
    "tests/test_adr.py",
    "tests/test_potomne.py::test_drzewa_procesow_i_kopie_commitow_narzedzi_buduje_tylko_potomne",
    "tests/test_struktura_testow.py",
    "tests/test_uszkodzone_wejscia.py::test_macierz_obejmuje_kazda_operacje_kontraktu_centrum",
)
STATIC_JOBS = ("ruff", "mypy")
MODULE_ROOTS = ("src", ".", "tools")
SKILL_SCRIPTS = ".agents/skills/*/scripts"
GREEN = "szybko-zielone.json"


@dataclass(frozen=True)
class Selection:
    """Pliki testów do sprawdzenia, każdy z odciskiem plików, od których zależy; ``full``: powód pełnego zestawu."""

    tests: dict[str, str]
    full: str | None = None


@dataclass(frozen=True)
class Dependencies:
    """Od czego zależy każdy plik Pythona.

    ``follows`` jest przechodnie (import, skrypt, który test uruchamia, plik, który czyta), a ``reads`` nie: pliki
    katalogu, który wskazuje test.
    """

    follows: dict[str, set[str]]
    reads: dict[str, set[str]]

    @classmethod
    def of(cls, root: Path, files: frozenset[str]) -> Dependencies:
        modules = _modules(files)
        directories = {str(parent) for path in files for parent in PurePosixPath(path).parents if str(parent) != "."}
        follows: dict[str, set[str]] = defaultdict(set)
        reads: dict[str, set[str]] = defaultdict(set)
        for path in sorted(files):
            if not _is_python(root, path):
                continue
            try:
                tree = ast.parse((root / path).read_bytes())
            except (OSError, SyntaxError, ValueError):
                continue
            for name in _imports(tree, path):
                follows[path].update(_resolve(name, path, modules, files))
            if path.startswith("tests/"):
                for text in _texts(tree):
                    if text in modules:
                        follows[path] |= _resolve(text, path, modules, files)
                    named, under = _named(text, files, directories)
                    follows[path] |= named
                    reads[path] |= under
            follows[path].update(_packages(path, files))
            follows[path].discard(path)
        return cls(follows, reads)

    def inputs(self, test: str) -> set[str]:
        """Plik testu i pliki, od których zależy."""

        found, pending = {test}, [test]
        while pending:
            for target in self.follows.get(pending.pop(), set()) - found:
                found.add(target)
                pending.append(target)
        return found | {path for source in found for path in self.reads.get(source, set())}

    def dependents(self, changed: Iterable[str]) -> set[str]:
        """Zmienione pliki i pliki, które od nich zależą."""

        back: dict[str, set[str]] = defaultdict(set)
        for source, targets in self.follows.items():
            for target in targets:
                back[target].add(source)
        changed = set(changed)
        found = changed | {source for source, under in self.reads.items() if under & changed}
        pending = list(found)
        while pending:
            for source in back[pending.pop()] - found:
                found.add(source)
                pending.append(source)
        return found


def _is_python(root: Path, path: str) -> bool:
    if path.endswith(".py"):
        return True
    if PurePosixPath(path).suffix:
        return False
    try:
        with (root / path).open("rb") as file:
            first = file.readline()
    except OSError:
        return False
    return first.startswith(b"#!") and b"python" in first


def _module_roots(files: frozenset[str]) -> list[str]:
    skills = {"/".join(PurePosixPath(path).parts[:4]) for path in files if PurePosixPath(path).match(f"{SKILL_SCRIPTS}/**")}
    return [*MODULE_ROOTS, *sorted(skills)]


def _modules(files: frozenset[str]) -> dict[str, set[str]]:
    """Nazwa modułu → pliki, które ją dają, względem katalogów na ``sys.path`` (``src``, korzeń, ``tools``, skilli)."""

    modules: dict[str, set[str]] = defaultdict(set)
    roots = _module_roots(files)
    for path in files:
        if not path.endswith(".py"):
            continue
        parts = PurePosixPath(path).with_suffix("").parts
        for root in roots:
            depth = 0 if root == "." else len(PurePosixPath(root).parts)
            if depth and PurePosixPath(*parts[:depth]) != PurePosixPath(root):
                continue
            names = parts[depth:]
            if names and names[-1] == "__init__":
                names = names[:-1]
            if names:
                modules[".".join(names)].add(path)
    return modules


def _imports(tree: ast.AST, path: str) -> set[str]:
    package = PurePosixPath(path).parent.parts
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            prefix = node.module or ""
            if node.level:
                prefix = ".".join([*package[: len(package) - node.level + 1], *filter(None, [node.module])])
            names.add(prefix)
            names.update(f"{prefix}.{alias.name}" for alias in node.names)
    return {".".join(name.split(".")[:end]) for name in names for end in range(1, name.count(".") + 2)}


def _resolve(name: str, importer: str, modules: dict[str, set[str]], files: frozenset[str]) -> set[str]:
    """Moduł obok importującego (skrypt z własnym katalogiem na ``sys.path``) wygrywa z modułem z ``_modules``."""

    here = PurePosixPath(importer).parent / name.replace(".", "/")
    local = {str(candidate) for candidate in (here.with_suffix(".py"), here / "__init__.py") if str(candidate) in files}
    return local or modules.get(name, set())


def _packages(path: str, files: frozenset[str]) -> set[str]:
    parents = PurePosixPath(path).parents
    return {init for parent in parents if (init := str(parent / "__init__.py")) in files}


def _texts(tree: ast.AST) -> set[str]:
    """Napisy modułu i całe ścieżki składane operatorem ``/`` (``ROOT / "docs" / "adr"`` daje ``docs/adr``).

    Początek ścieżki się nie liczy: ``ROOT / ".agents" / "skills"`` z ``ROOT / ".agents" / "skills" / "x"`` wskazałby
    wszystkie skille.
    """

    def is_path(node: ast.AST) -> TypeGuard[ast.BinOp]:
        return isinstance(node, ast.BinOp) and isinstance(node.op, ast.Div)

    def pieces(node: ast.expr) -> list[str | None]:
        if is_path(node):
            return pieces(node.left) + pieces(node.right)
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            return [node.value.strip("/")]
        return [None]

    nodes = list(ast.walk(tree))
    beginnings = {id(node.left) for node in nodes if is_path(node)}
    found = {node.value for node in nodes if isinstance(node, ast.Constant) and isinstance(node.value, str)}
    for node in nodes:
        if not is_path(node) or id(node) in beginnings:
            continue
        joined: list[str] = []
        for piece in [*pieces(node), None]:
            if piece is not None:
                joined.append(piece)
                continue
            if len(joined) > 1:
                found.add("/".join(joined))
            joined = []
    return found


def _named(text: str, files: frozenset[str], directories: set[str]) -> tuple[set[str], set[str]]:
    """Pliki, które napis wskazuje (ścieżka albo jednoznaczna nazwa pliku), i pliki katalogu, który wskazuje (ścieżka).

    Nazwa pliku, którą nosi kilka plików (``SKILL.md``), to zwykle plik w repozytorium testu, a nie w tym.
    """

    text = text.strip().replace("\\", "/").strip("/")
    if "/" not in text and "." not in text or not text.strip(".") or any(c.isspace() for c in text):
        return set(), set()
    named = {path for path in files if path == text or path.endswith("/" + text)}
    if "/" not in text and len(named) > 1:
        named = set()
    under: set[str] = set()
    if "/" in text:
        for directory in directories:
            if directory == text or directory.endswith("/" + text):
                under.update(path for path in files if str(PurePosixPath(path).parent) == directory)
    if any(PurePosixPath(path).name == "__init__.py" for path in under):
        under = set()
    return named, under


def _is_test(path: str) -> bool:
    pure = PurePosixPath(path)
    return pure.parts[0] == "tests" and pure.name.startswith("test_") and pure.suffix == ".py"


def select(root: Path, changed: frozenset[str]) -> Selection:
    files = _files(root) | changed
    dependencies = Dependencies.of(root, files)
    tests = {path for path in files if _is_test(path) and (root / path).is_file()}
    full = sorted(changed & set(FULL))
    if not full:
        tests &= dependencies.dependents(changed)
    fingerprints = {test: _fingerprint(root, dependencies.inputs(test)) for test in sorted(tests)}
    return Selection(fingerprints, f"zmiana w {', '.join(full)}" if full else None)


def _fingerprint(root: Path, inputs: Iterable[str]) -> str:
    """Odcisk treści plików, od których test zależy, z konfiguracją z ``FULL`` i wersją Pythona."""

    digest = hashlib.sha256(sys.version.encode())
    for path in sorted({*inputs, *FULL}):
        try:
            content = (root / path).read_bytes()
        except OSError:
            content = b"brak pliku"
        digest.update(f"{path}\0{len(content)}\0".encode() + content)
    return digest.hexdigest()


@dataclass(frozen=True)
class GreenMemory:
    """Pliki testów, które przeszły, z odciskiem plików, od których zależą; każdy worktree ma własną w katalogu gita."""

    path: Path

    @classmethod
    def of_checkout(cls) -> GreenMemory:
        return cls(ROOT / _git("rev-parse", "--git-path", GREEN).strip())

    def to_run(self, selection: Selection) -> list[str]:
        green = self._recalled()
        return [test for test, fingerprint in selection.tests.items() if green.get(test) != fingerprint]

    def remember(self, selection: Selection, junit: Path, ran: Iterable[str]) -> None:
        """Zapamiętuje pliki z ``ran``, których każdy przypadek w raporcie JUnit przeszedł albo został pominięty."""

        green = {test: selection.tests[test] for test in _passed(junit, ran)}
        written = self.path.with_suffix(".tmp")
        written.write_text(json.dumps({**self._recalled(), **green}, indent=1, sort_keys=True), encoding="utf-8")
        written.replace(self.path)

    def _recalled(self) -> dict[str, str]:
        try:
            loaded = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}
        return {str(test): str(fingerprint) for test, fingerprint in loaded.items()} if isinstance(loaded, dict) else {}


def _passed(junit: Path, ran: Iterable[str]) -> set[str]:
    try:
        cases = list(ET.parse(junit).iter("testcase"))
    except (OSError, ET.ParseError):
        return set()
    ran = set(ran)
    seen: set[str] = set()
    failed: set[str] = set()
    for case in cases:
        # ``tests.test_x`` albo ``tests.test_x.TestKlasa``
        parts = case.get("classname", "").split(".")
        test = next((path for end in range(len(parts), 0, -1) if (path := "/".join(parts[:end]) + ".py") in ran), None)
        if test is None:
            continue
        seen.add(test)
        if case.find("failure") is not None or case.find("error") is not None:
            failed.add(test)
    return seen - failed


def _git(*arguments: str) -> str:
    completed = subprocess.run(["git", *arguments], cwd=ROOT, capture_output=True, text=True, encoding="utf-8", check=True)
    return completed.stdout


def _files(root: Path) -> frozenset[str]:
    listed = subprocess.run(
        ["git", "ls-files", "-z", "--cached", "--others", "--exclude-standard"], cwd=root, capture_output=True, check=True
    ).stdout.decode("utf-8")
    return frozenset(path for path in listed.split("\0") if path)


def _changed(base: str) -> frozenset[str]:
    """Pliki zmienione od ``merge-base`` HEAD z ``base``: zacommitowane, niezacommitowane i nieśledzone."""

    fork = _git("merge-base", "HEAD", base).strip()
    diff = _git("diff", "-z", "--name-only", "--no-renames", fork)
    untracked = _git("ls-files", "-z", "--others", "--exclude-standard")
    return frozenset(path for path in (diff + untracked).split("\0") if path)


def _merge_with(base: str) -> str | None:
    """Commit HEAD połączony z ``base``, jak drzewo CI PR-u; None, gdy ``base`` jest już w HEAD albo merge ma konflikt."""

    if subprocess.run(["git", "merge-base", "--is-ancestor", base, "HEAD"], cwd=ROOT, capture_output=True).returncode == 0:
        return None
    merged = subprocess.run(
        ["git", "merge-tree", "--write-tree", "--name-only", "HEAD", base],
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    tree, *conflicts = merged.stdout.split("\n\n", 1)[0].splitlines()
    if merged.returncode != 0:
        print(f"UWAGA: merge z {base} ma konflikt w {', '.join(conflicts)}; testy struktury po mergu pominięte", flush=True)
        return None
    author = ("-c", "user.name=szybko", "-c", "user.email=szybko@localhost")
    return _git(*author, "commit-tree", tree, "-p", "HEAD", "-p", base, "-m", f"szybko: HEAD z {base}").strip()


def _pytest_arguments(tests: Iterable[str], junit: Path) -> tuple[str, ...]:
    tests = sorted(tests)
    structure = (node for node in STRUCTURE if node.split("::")[0] not in tests)
    return (*tests, *structure, f"--junitxml={junit}")


def _own_cache(step: ci_lokalnie.Step) -> ci_lokalnie.Step:
    """Cache mypy zależy od ``--platform``: przebiegi dla dwóch systemów w jednym cache unieważniają go sobie nawzajem."""

    if "--platform" not in step.command or "--cache-dir" in step.command:
        return step
    platform = step.command[step.command.index("--platform") + 1]
    return replace(step, command=(*step.command, "--cache-dir", f".mypy_cache/{platform}"))


def _pytest(root: Path, name: str, arguments: Iterable[str]) -> ci_lokalnie.Step:
    pytest = next(step for step in ci_lokalnie._steps(root) if step.job == "pytest")
    return replace(pytest, name=name, command=(*pytest.command, *arguments))


def _steps(root: Path, tests: Iterable[str], junit: Path) -> list[ci_lokalnie.Step]:
    static = (_own_cache(step) for step in ci_lokalnie._steps(root) if step.job in STATIC_JOBS)
    return [*static, _pytest(root, "pytest", _pytest_arguments(tests, junit))]


def _run_all(steps: list[ci_lokalnie.Step], root: Path) -> list[str]:
    """Uruchamia kroki w ``root`` naraz i drukuje wynik każdego jedną linią, po kolei; zwraca nazwy kroków, które padły.

    Kroki od siebie nie zależą, więc czas to najdłuższy krok, a nie ich suma: zimny mypy w świeżym worktree
    biegnie w trakcie testów.
    """

    stop = threading.Event()

    def run(step: ci_lokalnie.Step) -> tuple[bool, str, float]:
        started = time.monotonic()
        done = potomne.run(step.command, cwd=step.cwd, env={**environment(root), "PYTHON": sys.executable}, stop=stop)
        return done.returncode == 0, done.stdout + done.stderr, time.monotonic() - started

    failed = []
    pool = ThreadPoolExecutor(max_workers=len(steps))
    try:
        for step, (passed, output, elapsed) in zip(steps, pool.map(run, steps), strict=True):
            print(f"{'OK  ' if passed else 'FAIL'} {step.name} ({elapsed:.0f} s)", flush=True)
            if not passed:
                failed.append(step.name)
                print("\n".join(output.rstrip().splitlines()[-ci_lokalnie.OUTPUT_ON_FAILURE :]), flush=True)
    except BaseException:
        # Przerwanie w głównym wątku nie dociera do wątków, które czekają na swoje polecenia.
        stop.set()
        raise
    finally:
        pool.shutdown(cancel_futures=True)
    return failed


def _describe(selection: Selection, to_run: list[str], changed: frozenset[str], base: str) -> str:
    kind = f"pełny zestaw ({selection.full})" if selection.full else "dotknięte zmianą"
    names = ", ".join(PurePosixPath(path).name for path in to_run) or "brak"
    green = len(selection.tests) - len(to_run)
    return (
        f"Zmiana: {len(changed)} plików od {base}. Testy {kind}: {len(selection.tests)},"
        f" do uruchomienia {len(to_run)} ({names}), zielone na tych samych plikach {green}; i testy struktury."
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--baza", default=BASE, help=f"Gałąź, od której liczy się zmiana (domyślnie {BASE}).")
    args = parser.parse_args(argv)
    try:
        changed = _changed(args.baza)
    except subprocess.CalledProcessError:
        print(f"SZYBKO FAIL | nieznana baza {args.baza}")
        return 1
    selection = select(ROOT, changed)
    memory = GreenMemory.of_checkout()
    to_run = memory.to_run(selection)
    print(_describe(selection, to_run, changed, args.baza), flush=True)
    junit = memory.path.with_name("szybko-junit.xml")
    junit.unlink(missing_ok=True)
    failed = _run_all(_steps(ROOT, to_run, junit), ROOT)
    memory.remember(selection, junit, to_run)
    if merge := _merge_with(args.baza):
        with potomne.commit_copy(ROOT, merge) as copy:
            failed += _run_all([_pytest(copy, f"testy struktury po mergu z {args.baza}", STRUCTURE)], copy)
    print(f"SZYBKO FAIL | {', '.join(failed)}" if failed else "SZYBKO OK")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())

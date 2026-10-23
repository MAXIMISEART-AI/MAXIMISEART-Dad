"""Szybkie sprawdzenie zmiany: ruff, mypy dla obu systemów, testy struktury i testy dotknięte zmianą.

Agent uruchamia je po każdej zmianie; pełną bramką jest CI na GitHubie. Zmiana to pliki, którymi checkout,
razem z niezacommitowanymi i nieśledzonymi plikami, różni się od ``merge-base`` HEAD z ``--baza`` (domyślnie
``origin/main``). Kroki ruff i mypy to kroki ``tools/ci_lokalnie.py``, a pytest to jego krok z wybranymi testami.

Test jest dotknięty, gdy zmiana obejmuje jego plik albo plik, od którego zależy. Zależności wynikają z samego
kodu, bez stanu z poprzednich przebiegów, więc świeży worktree odpowiada tak samo szybko: importy modułów
Pythona, a w ``tests/`` także ścieżki i nazwy modułów w napisach, czyli skrypt, który test uruchamia, plik,
który czyta, albo katalog. Zależność jest przechodnia, z wyjątkiem katalogu: test zależy od jego plików, ale nie
od ich zależności. Zmiana w ``FULL`` (konfiguracja i zależności, ``conftest.py`` każdego testu) uruchamia pełny
zestaw. Testy ``STRUCTURE`` pilnują reguł z tabeli w ``AGENTS.md`` i biegną przy każdej zmianie.

Kończy się ``SZYBKO OK`` albo ``SZYBKO FAIL | <kroki>``.

    .venv/bin/python tools/szybko.py
    .venv/bin/python tools/szybko.py --baza feat/galaz-rodzica
"""

from __future__ import annotations

import argparse
import ast
from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass, replace
from pathlib import Path, PurePosixPath
import subprocess
import time

import ci_lokalnie

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


@dataclass(frozen=True)
class Full:
    reason: str


@dataclass(frozen=True)
class Affected:
    tests: tuple[str, ...]


Selection = Full | Affected


@dataclass(frozen=True)
class Dependencies:
    """``follows``: przechodnie (import, uruchomiony skrypt, czytany plik); ``reads``: pliki katalogu wymienionego w teście."""

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
                    follows[path].update(_resolve(text, path, modules, files) if text in modules else ())
                    named, under = _named(text, files, directories)
                    follows[path].update(named)
                    reads[path].update(under)
            follows[path].update(_packages(path, files))
            follows[path].discard(path)
        return cls(follows, reads)

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
    skills = sorted({"/".join(PurePosixPath(path).parts[:4]) for path in files if PurePosixPath(path).match(f"{SKILL_SCRIPTS}/**")})
    return [*MODULE_ROOTS, *skills]


def _modules(files: frozenset[str]) -> dict[str, set[str]]:
    """Nazwa modułu → pliki, które ją dają, względem każdego katalogu na ``sys.path`` (``src``, korzeń, ``tools``, skrypty skilli)."""

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
    """Napisy modułu, także ścieżki składane operatorem ``/`` (``ROOT / "docs" / "adr"`` daje ``docs/adr``)."""

    def pieces(node: ast.expr) -> list[str | None]:
        if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Div):
            return pieces(node.left) + pieces(node.right)
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            return [node.value.strip("/")]
        return [None]

    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            found.add(node.value)
        if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Div):
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
    """Pliki, które napis wskazuje (ścieżka albo nazwa pliku), i pliki katalogu, który wskazuje (ścieżka)."""

    text = text.strip().replace("\\", "/").strip("/")
    if "/" not in text and "." not in text or not text.strip(".") or any(c.isspace() for c in text):
        return set(), set()
    named = {path for path in files if path == text or path.endswith("/" + text)}
    under: set[str] = set()
    if "/" in text:
        for directory in directories:
            if directory == text or directory.endswith("/" + text):
                under.update(path for path in files if path.startswith(directory + "/"))
    return named, under


def _is_test(path: str) -> bool:
    pure = PurePosixPath(path)
    return pure.parts[0] == "tests" and pure.name.startswith("test_") and pure.suffix == ".py"


def select(root: Path, changed: frozenset[str]) -> Selection:
    if full := sorted(changed & set(FULL)):
        return Full(f"zmiana w {', '.join(full)}")
    files = _files(root) | changed
    affected = Dependencies.of(root, files).dependents(changed)
    return Affected(tuple(sorted(path for path in affected if _is_test(path) and (root / path).is_file())))


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


def _pytest_arguments(selection: Selection) -> tuple[str, ...]:
    if isinstance(selection, Full):
        return ()
    structure = (node for node in STRUCTURE if node.split("::")[0] not in selection.tests)
    return (*selection.tests, *structure)


def _steps(root: Path, selection: Selection) -> list[ci_lokalnie.Step]:
    steps = ci_lokalnie._steps(root)
    pytest = next(step for step in steps if step.job == "pytest")
    return [
        *(step for step in steps if step.job in STATIC_JOBS),
        replace(pytest, command=(*pytest.command, *_pytest_arguments(selection))),
    ]


def _describe(selection: Selection, changed: frozenset[str], base: str) -> str:
    if isinstance(selection, Full):
        return f"Zmiana: {len(changed)} plików od {base}. Testy: pełny zestaw ({selection.reason})."
    tests = ", ".join(PurePosixPath(path).name for path in selection.tests) or "brak"
    return f"Zmiana: {len(changed)} plików od {base}. Testy dotknięte zmianą ({len(selection.tests)}): {tests}; i testy struktury."


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
    print(_describe(selection, changed, args.baza), flush=True)
    failed = []
    for step in _steps(ROOT, selection):
        started = time.monotonic()
        passed, output = ci_lokalnie._run(step, ROOT)
        print(f"{'OK  ' if passed else 'FAIL'} {step.name} ({time.monotonic() - started:.0f} s)", flush=True)
        if not passed:
            failed.append(step.name)
            print("\n".join(output.rstrip().splitlines()[-ci_lokalnie.OUTPUT_ON_FAILURE :]), flush=True)
    print(f"SZYBKO FAIL | {', '.join(failed)}" if failed else "SZYBKO OK")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())

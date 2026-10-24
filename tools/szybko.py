"""Szybkie sprawdzenie zmiany: ruff, mypy dla obu systemów, testy struktury i testy dotknięte zmianą.

Agent uruchamia je po każdej zmianie; pełną bramką jest CI na GitHubie. Zmiana to pliki, którymi checkout,
razem z niezacommitowanymi i nieśledzonymi plikami, różni się od ``merge-base`` HEAD z ``--baza`` (domyślnie
``origin/main``). Kroki ruff i mypy to kroki ``tools/ci_lokalnie.py``, a pytest to jego krok z wybranymi
testami. Gdy ``.venv`` ma Pythona nowszego niż najstarszy z ``requires-python``, który CI też testuje, krok
``import src pod Pythonem <wersja>`` importuje każdy moduł ``src/`` tym Pythonem przez ``uv`` (bez ``uv`` pada).
Kroki biegną naraz.

Test jest dotknięty, gdy zmiana obejmuje jego plik albo plik, od którego zależy. Zależności wynikają z samego
kodu, więc świeży worktree wybiera tak samo:

- importy modułów Pythona;
- w ``tests/`` ścieżki i nazwy modułów w napisach, czyli skrypt, który test uruchamia, plik, który czyta, albo
  pliki katalogu; poza ``tests/`` tylko ścieżki z ``/``, i bez zależności dalej;
- pliki z globu (``glob``, ``rglob``, ``iterdir``) na katalogu o znanej nazwie;
- pliki inne niż Python w katalogu pakietu (``centrum/static``) dla każdego modułu tego pakietu.

Zależność przez import i skrypt testu jest przechodnia, a przez katalog, glob i plik danych nie. Zmiana w ``FULL``
(konfiguracja i zależności, ``conftest.py`` każdego testu i fixture gita, którą wczytuje dla całej sesji) wybiera
wszystkie testy. Test, który już przeszedł na tych samych plikach, nie biegnie drugi raz: pamięć zielonych testów
leży w katalogu gita worktree. Krok pytest bierze ``WORKERS`` workerów, chyba że ustawiono
``PYTEST_XDIST_AUTO_NUM_WORKERS``.

Testy ``STRUCTURE`` (reguły z tabeli w ``AGENTS.md`` i testy całego repozytorium) biegną przy każdej zmianie, a gdy
``--baza`` poszła dalej niż HEAD, także na mergu z nią (to drzewo sprawdza CI PR-u; numer ADR zajęty równolegle
pada dopiero tam). Na mergu biegną tylko one, bez mypy i testów dotkniętych zmianą. Szybko nie pobiera ``origin``,
więc merge jest z bazą z ostatniego ``git fetch``. Nie uruchamia zadań CI ``mutations`` (skrypty mutacji skilli),
``Frontend``, E2E ani Timing guard.

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
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import subprocess
import sys
import threading
import time
import tomllib
from typing import TypeGuard
import xml.etree.ElementTree as ET

import ci_lokalnie
from mutacje import environment
import potomne

ROOT = Path(__file__).resolve().parents[1]
BASE = "origin/main"
FULL = ("pyproject.toml", "requirements.txt", "tests/conftest.py", "tests/fixtures/git_config.py")
STRUCTURE = (
    "tests/test_adr.py",
    "tests/test_dokumenty_regul.py",
    "tests/test_granice_importow.py",
    "tests/test_jeden_odczyt_skoroszytu.py",
    "tests/test_jeden_zapis_skoroszytu.py",
    "tests/test_mapy_funkcji.py",
    "tests/test_miejsce_skilli.py",
    "tests/test_potomne.py::test_drzewa_procesow_i_kopie_commitow_narzedzi_buduje_tylko_potomne",
    "tests/test_potomne.py::test_polecenia_narzedzi_ktore_trwaja_biegna_przez_potomne_run",
    "tests/test_skille_dla_zmiany.py::test_agents_md_nie_wymienia_skilli_verify",
    "tests/test_skille_dla_zmiany.py::test_kazdy_skill_verify_deklaruje_pilnuje",
    "tests/test_skrypty_bez_instalacji.py",
    "tests/test_struktura_testow.py",
    "tests/test_systemowy_python.py",
    "tests/test_uszkodzone_wejscia.py::test_macierz_obejmuje_kazda_operacje_kontraktu_centrum",
    "tests/test_wycofane_pojecia.py",
    "tests/test_wywolanie_skryptow_skilli.py::test_skrypty_skilli_biora_katalog_runu_warianty_i_sciezki_tylko_z_parsera",
    # Globy ``pilnuje:`` z frontmatteru SKILL.md i pliki, które wczytują sprawdzenia skilli, to całe repozytorium,
    # a graf ich nie widzi.
    "tests/test_mutacje_skilli.py::test_kazdy_glob_pilnuje_trafia_w_plik_repozytorium",
    "tests/test_mutacje_skilli.py::test_skrypt_mutacji_czyta_kazdy_plik_repozytorium_ladowany_przez_jego_sprawdzenia",
    "tests/test_skille_dla_zmiany.py::test_frontmatter_kazdego_skilla_jest_poprawnym_yaml",
    "tests/test_skille_dla_zmiany.py::test_workflow_skilla_windows_biegnie_dla_tych_samych_sciezek_co_jego_pilnuje",
    # ``.gitignore`` czyta tu ``git check-ignore``, nie Python, więc graf nie wiąże go z tym testem.
    "tests/test_centrum_rozliczen.py::test_lokalne_pliki_taty_sa_poza_gitem",
)
STATIC_JOBS = ("ruff", "mypy")
MODULE_ROOTS = ("src", ".", "tools")
SKILL_SCRIPTS = ".agents/skills/*/scripts"
GREEN = "szybko-zielone.json"
PATH_TYPES = frozenset({"Path", "PurePath", "PurePosixPath", "PureWindowsPath"})
GLOBS = frozenset({"glob", "rglob", "iterdir"})
WORKERS = "4"
# Importuje każdy moduł ``src/`` i wypisuje te, które padają; moduł, który się nie importuje, wywraca każdy test.
IMPORT_ALL = """\
import importlib, pathlib, sys
src = pathlib.Path(sys.argv[1])
names = sorted({".".join(p.relative_to(src).with_suffix("").parts).removesuffix(".__init__") for p in src.rglob("*.py")})
failed = []
for name in names:
    try:
        importlib.import_module(name)
    except Exception as error:
        failed.append(f"{name}: {type(error).__name__}: {error}")
print("\\n".join(failed) or f"{len(names)} modułów")
sys.exit(3 if failed or not names else 0)
"""
# ``uv run --offline`` z ciepłym cache działa bez sieci; dopiero porażka samego uv (inny kod niż 0 i 3) pyta sieć.
WITH_UV = """\
import subprocess, sys
uv, version, imports, *requirements = sys.argv[1:]
command = [uv, "run", "--no-project", "--quiet", "--python", version, *requirements, "python", "-c", imports, "src"]
code = subprocess.run([*command[:2], "--offline", *command[2:]]).returncode
if code not in (0, 3):
    code = subprocess.run(command).returncode
sys.exit(code)
"""


@dataclass(frozen=True)
class Selection:
    fingerprints: dict[str, str]
    full_reason: str | None = None


@dataclass(frozen=True)
class Dependencies:
    depends_on: dict[str, set[str]]
    folder_files: dict[str, set[str]]

    @classmethod
    def of(cls, root: Path, files: frozenset[str]) -> Dependencies:
        modules = _modules(files)
        directories = {str(parent) for path in files for parent in PurePosixPath(path).parents if str(parent) != "."}
        package_data = _package_data(files)
        depends_on: dict[str, set[str]] = defaultdict(set)
        folder_files: dict[str, set[str]] = defaultdict(set)
        for path in sorted(files):
            if not _is_python(root, path):
                continue
            try:
                tree = ast.parse((root / path).read_bytes())
            except (OSError, SyntaxError, ValueError):
                continue
            for name in _imports(tree, path):
                depends_on[path] |= _resolve(name, path, modules, files)
            texts, globs = references(tree)
            test = path.startswith("tests/")
            if not test:
                # Poza testami sama nazwa pliku albo modułu to zwykle nazwa procesu albo pliku w cudzym katalogu.
                texts = {text for text in texts if "/" in text.strip("/")}
            for text in texts:
                if text in modules and test:
                    depends_on[path] |= _resolve(text, path, modules, files)
                # Skrypt, który uruchamia test, zależy dalej od swoich importów; plik wskazany przez narzędzie już nie,
                # a katalog w narzędziu to zwykle lista miejsc do sprawdzenia (``GENERATED``), nie plik, który czyta.
                (depends_on if test else folder_files)[path] |= _files_named(text, files)
                if test:
                    folder_files[path] |= _folder_files(text, files, directories)
            for glob in globs:
                folder_files[path] |= _globbed(glob, files, directories)
            folder_files[path] |= package_data.get(str(PurePosixPath(path).parent), set())
            depends_on[path] |= _packages(path, files)
            depends_on[path].discard(path)
        return cls(depends_on, folder_files)

    def inputs_of(self, test: str) -> set[str]:
        found, pending = {test}, [test]
        while pending:
            for target in self.depends_on.get(pending.pop(), set()) - found:
                found.add(target)
                pending.append(target)
        return found | {path for source in found for path in self.folder_files.get(source, set())}

    def affected_by(self, changed: Iterable[str]) -> set[str]:
        back: dict[str, set[str]] = defaultdict(set)
        for source, targets in self.depends_on.items():
            for target in targets:
                back[target].add(source)
        changed = set(changed)
        found = changed | {source for source, folder in self.folder_files.items() if folder & changed}
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


@dataclass(frozen=True)
class _Glob:
    folder: str
    pattern: str
    recursive: bool


def references(tree: ast.AST) -> tuple[set[str], set[_Glob]]:
    """Napisy modułu, ścieżki składane operatorem ``/`` (``ROOT / "docs" / "adr"`` daje ``docs/adr``) i globy na katalogach."""

    def is_path(node: ast.AST) -> TypeGuard[ast.BinOp]:
        return isinstance(node, ast.BinOp) and isinstance(node.op, ast.Div)

    names: dict[str, list[str | None]] = {}

    def pieces(node: ast.AST) -> list[str | None]:
        if is_path(node):
            return pieces(node.left) + pieces(node.right)
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            return [node.value.strip("/")]
        if isinstance(node, ast.Name) and node.id in names:
            return names[node.id]
        if _is_path_call(node):
            return [piece for argument in node.args for piece in pieces(argument)]
        return [None]

    def runs(path: list[str | None]) -> list[str]:
        found, joined = [], []
        for piece in [*path, None]:
            if piece is not None:
                joined.append(piece)
                continue
            if joined:
                found.append("/".join(joined))
            joined = []
        return found

    nodes = list(ast.walk(tree))
    assignments = [node for node in nodes if isinstance(node, ast.Assign) and len(node.targets) == 1]
    for assignment in sorted(assignments, key=lambda node: (node.lineno, node.col_offset)):
        target, value = assignment.targets[0], assignment.value
        if isinstance(target, ast.Name) and (is_path(value) or isinstance(value, ast.Name) and value.id in names):
            names[target.id] = pieces(value)
    # Tylko cała ścieżka: początek ``ROOT / ".agents" / "skills"`` łańcucha ``... / "x"`` wskazałby wszystkie skille.
    beginnings = {id(node.left) for node in nodes if is_path(node)}
    texts = {node.value for node in nodes if isinstance(node, ast.Constant) and isinstance(node.value, str)}
    paths = [node for node in nodes if (is_path(node) or _is_path_call(node)) and id(node) not in beginnings]
    texts |= {run for node in paths for run in runs(pieces(node)) if "/" in run}
    globs: set[_Glob] = set()
    for node in nodes:
        if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr in GLOBS):
            continue
        folder = pieces(node.func.value)
        if folder[-1] is None:
            continue
        if node.func.attr == "iterdir":
            globs.add(_Glob(runs(folder)[-1], "*", recursive=False))
        elif node.args and isinstance(node.args[0], ast.Constant) and isinstance(node.args[0].value, str):
            globs.add(_Glob(runs(folder)[-1], node.args[0].value, recursive=node.func.attr == "rglob"))
    return texts, globs


def _as_path(text: str) -> str | None:
    path = text.strip().replace("\\", "/").strip("/")
    if ("/" in path or "." in path) and path.strip(".") and not any(c.isspace() for c in path):
        return path
    return None


def _files_named(text: str, files: frozenset[str]) -> set[str]:
    if (path := _as_path(text)) is None:
        return set()
    return {file for file in files if file == path or file.endswith("/" + path)}


def _folder_files(text: str, files: frozenset[str], directories: set[str]) -> set[str]:
    if (path := _as_path(text)) is None or "/" not in path:
        return set()
    folders = {folder for folder in directories if folder == path or folder.endswith("/" + path)}
    found = {file for file in files if str(PurePosixPath(file).parent) in folders}
    # Pakiet test zna przez importy; jego katalog w napisie to ścieżka w repozytorium, które test sam buduje.
    return set() if any(PurePosixPath(file).name == "__init__.py" for file in found) else found


def _is_path_call(node: ast.AST) -> TypeGuard[ast.Call]:
    return isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id in PATH_TYPES and bool(node.args)


def _globbed(glob: _Glob, files: frozenset[str], directories: set[str]) -> set[str]:
    folders = {folder for folder in directories if folder == glob.folder or folder.endswith("/" + glob.folder)}
    depth = len(PurePosixPath(glob.pattern).parts)
    found = set()
    for file in files:
        for folder in folders:
            if file.startswith(folder + "/"):
                inside = PurePosixPath(file[len(folder) + 1 :])
                if inside.match(glob.pattern) and (glob.recursive or "**" in glob.pattern or len(inside.parts) == depth):
                    found.add(file)
    return found


def _package_data(files: frozenset[str]) -> dict[str, set[str]]:
    """Katalog pakietu → jego pliki inne niż Python, także z podkatalogów, które nie są pakietami (``centrum/static``)."""

    packages = {str(PurePosixPath(file).parent) for file in files if PurePosixPath(file).name == "__init__.py"}
    data: dict[str, set[str]] = defaultdict(set)
    for file in files:
        if file.endswith(".py"):
            continue
        parent = PurePosixPath(file).parent
        owner = next((str(folder) for folder in (parent, *parent.parents) if str(folder) in packages), None)
        if owner is not None:
            data[owner].add(file)
    return data


def _is_test(path: str) -> bool:
    pure = PurePosixPath(path)
    return pure.parts[0] == "tests" and pure.name.startswith("test_") and pure.suffix == ".py"


def select(root: Path, changed: frozenset[str]) -> Selection:
    files = _files(root) | changed
    dependencies = Dependencies.of(root, files)
    tests = {path for path in files if _is_test(path) and (root / path).is_file()}
    full = sorted(changed & set(FULL))
    if not full:
        tests &= dependencies.affected_by(changed)
    fingerprints = {test: _fingerprint(root, dependencies.inputs_of(test)) for test in sorted(tests)}
    return Selection(fingerprints, f"zmiana w {', '.join(full)}" if full else None)


def _fingerprint(root: Path, inputs: Iterable[str]) -> str:
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
    path: Path

    @classmethod
    def of_checkout(cls) -> GreenMemory:
        return cls(ROOT / _git("rev-parse", "--git-path", GREEN).strip())

    def to_run(self, selection: Selection) -> list[str]:
        green = self._recalled()
        return [test for test, fingerprint in selection.fingerprints.items() if green.get(test) != fingerprint]

    def remember(self, selection: Selection, junit: Path, ran: Iterable[str]) -> None:
        green = {test: selection.fingerprints[test] for test in _passed(junit, ran)}
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
    fork = _git("merge-base", "HEAD", base).strip()
    diff = _git("diff", "-z", "--name-only", "--no-renames", fork)
    untracked = _git("ls-files", "-z", "--others", "--exclude-standard")
    return frozenset(path for path in (diff + untracked).split("\0") if path)


def _merge_with(base: str) -> str | None:
    ancestor = subprocess.run(["git", "merge-base", "--is-ancestor", base, "HEAD"], cwd=ROOT, capture_output=True, check=False)
    if ancestor.returncode == 0:
        return None
    merged = subprocess.run(
        ["git", "merge-tree", "--write-tree", "--name-only", "HEAD", base],
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
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


def _pytest(root: Path, name: str, arguments: Iterable[str]) -> ci_lokalnie.Step:
    pytest = next(step for step in ci_lokalnie._steps(root) if step.job == "pytest")
    return replace(pytest, name=name, command=(*pytest.command, *arguments))


def _failing(root: Path, name: str, why: str) -> ci_lokalnie.Step:
    return ci_lokalnie.Step(name, "pytest", "", (sys.executable, "-c", f"raise SystemExit({why!r})"), root)


def _imports_on_oldest(root: Path) -> list[ci_lokalnie.Step]:
    """CI testuje też najstarszy Python z ``requires-python``, a ``.venv`` bywa nowszy: kod tylko dla nowszego Pythona
    pada dopiero w CI. Krok jest pusty, gdy szybko biegnie tym najstarszym albo projekt go nie podaje."""

    try:
        required = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))["project"]["requires-python"]
    except (OSError, KeyError, tomllib.TOMLDecodeError):
        return []
    oldest = re.fullmatch(r">=\s*(\d+)\.(\d+)", str(required).strip())
    if oldest is None:
        why = f"requires-python {required!r} nie ma postaci >=X.Y, więc szybko nie zna najstarszego Pythona"
        return [_failing(root, "import src pod najstarszym Pythonem", why)]
    if sys.version_info[:2] <= (int(oldest[1]), int(oldest[2])):
        return []
    version = f"{oldest[1]}.{oldest[2]}"
    name = f"import src pod Pythonem {version}"
    uv = shutil.which("uv")
    if uv is None:
        return [_failing(root, name, f"brak uv, więc szybko nie sprawdzi Pythona {version}: zainstaluj uv albo .venv z {version}")]
    requirements = ("--with-requirements", "requirements.txt") if (root / "requirements.txt").is_file() else ()
    return [ci_lokalnie.Step(name, "pytest", "", (sys.executable, "-c", WITH_UV, uv, version, IMPORT_ALL, *requirements), root)]


def _steps(root: Path, tests: Iterable[str], junit: Path) -> list[ci_lokalnie.Step]:
    static = (step for step in ci_lokalnie._steps(root) if step.job in STATIC_JOBS)
    return [*static, _pytest(root, "pytest", _pytest_arguments(tests, junit)), *_imports_on_oldest(root)]


def _environment(root: Path) -> dict[str, str]:
    # Gołe ``-n auto`` bierze wszystkie rdzenie Maca, na którym pracuje naraz kilku agentów.
    return {"PYTEST_XDIST_AUTO_NUM_WORKERS": WORKERS, **environment(root), "PYTHON": sys.executable}


def _run_all(steps: list[ci_lokalnie.Step], root: Path) -> list[str]:
    stop = threading.Event()

    def run(step: ci_lokalnie.Step) -> tuple[bool, str, float]:
        started = time.monotonic()
        done = potomne.run(step.command, cwd=step.cwd, env=_environment(root), stop=stop)
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
    kind = f"pełny zestaw ({selection.full_reason})" if selection.full_reason else "dotknięte zmianą"
    names = ", ".join(PurePosixPath(path).name for path in to_run) or "brak"
    green = len(selection.fingerprints) - len(to_run)
    return (
        f"Zmiana: {len(changed)} plików od {base}. Testy {kind}: {len(selection.fingerprints)},"
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
    junit = memory.path.with_name(f"szybko-junit-{os.getpid()}.xml")
    failed = _run_all(_steps(ROOT, to_run, junit), ROOT)
    memory.remember(selection, junit, to_run)
    junit.unlink(missing_ok=True)
    if merge := _merge_with(args.baza):
        with potomne.commit_copy(ROOT, merge) as copy:
            failed += _run_all([_pytest(copy, f"testy struktury po mergu z {args.baza}", STRUCTURE)], copy)
    print(f"SZYBKO FAIL | {', '.join(failed)}" if failed else "SZYBKO OK")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())

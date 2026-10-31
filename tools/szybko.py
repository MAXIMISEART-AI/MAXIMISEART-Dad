"""Szybko sprawdza zmianę: ruff, mypy dla obu systemów, testy struktury i testy dotknięte zmianą; uruchom po każdej zmianie przed pushem.

Agent uruchamia je po każdej zmianie; pełną bramką jest CI na GitHubie. Zmiana to pliki, którymi checkout,
razem z niezacommitowanymi i nieśledzonymi plikami, różni się od ``merge-base`` HEAD z ``--baza`` (domyślnie
``origin/main``). Kroki ruff i mypy to kroki ``tools/ci_lokalnie.py``, a pytest to jego krok z wybranymi
testami. Gdy ``.venv`` ma Pythona nowszego niż najstarszy z ``requires-python``, który CI też testuje, krok
``import src pod Pythonem <wersja>`` importuje każdy moduł ``src/`` tym Pythonem przez ``uv`` (bez ``uv`` pada).
Kroki biegną naraz, a gdy padnie inny krok, szybko przerywa krok pytest i wypisuje, że go przerwał.

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

Z wybranych testów biegną zawsze pliki w odległości najwyżej 1 od zmiany w grafie zależności (``plan``), czyli
zmienione albo zależne wprost od zmienionego pliku, a dalsze po odległości i czasie w CI rosnąco, dopóki mieszczą
się w budżecie ``BUDGET_S``. Czas pliku to jego koszt na Linuksie z ostatnich runów main (``tools/ci/czasy_ci.py``,
kopia w ``.git/czasy-ci`` odświeżana raz na dobę, a po nieudanym pobraniu w następnym przebiegu); bez niej, na przykład
bez sieci, każdy plik waży 0 i biegnie, a szybko mówi to linią ``SZYBKO | bez czasów CI (<przyczyna>)``. Odległość liczy się od zmiany bez plików ``FULL``, a test, który
importuje albo czyta plik ``FULL``, ma najwyżej 2, więc przy zmianie konfiguracji biegnie w budżecie przed testami
bez drogi w grafie. Resztę liczy pełny pytest w CI, a szybko wypisuje ją przed wynikiem
jako „zostawione CI”, więc ``SZYBKO OK`` znaczy, że przeszły uruchomione testy.

Testy ``STRUCTURE`` (reguły z tabel w ``AGENTS.md``, ``CODING_STANDARDS.md`` i ``docs/agents/`` oraz testy całego
repozytorium) biegną przy każdej zmianie, a gdy ``--baza`` poszła dalej niż HEAD, także na mergu z nią (to drzewo
sprawdza CI PR-u; numer ADR zajęty równolegle pada dopiero tam). Na mergu biegną tylko one, bez mypy, testów
dotkniętych zmianą i workerów xdist, razem z pozostałymi krokami.
Szybko nie pobiera ``origin``, więc merge jest z bazą z ostatniego ``git fetch``. Nie uruchamia zadań CI
``mutations`` (skrypty mutacji skilli), ``Frontend``, E2E ani Timing guard.

Kończy się ``SZYBKO OK`` albo ``SZYBKO FAIL | <kroki>``, z dopiskiem `` | pytest przerwany``, gdy szybko przerwał
krok pytest.

    .venv/bin/python tools/szybko.py
    .venv/bin/python tools/szybko.py --baza feat/galaz-rodzica
"""

from __future__ import annotations

import argparse
import ast
from collections import defaultdict, deque
from collections.abc import Iterable
from concurrent.futures import ThreadPoolExecutor
from contextlib import ExitStack
from dataclasses import dataclass, replace
import hashlib
import json
import math
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import statistics
import subprocess
import sys
import threading
import time
import tomllib
import xml.etree.ElementTree as ET

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools/lib"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools/ci"))

import ci_lokalnie
import czasy_ci
from mutacje import environment
import potomne
from sciezki_w_kodzie import Glob, references

ROOT = Path(__file__).resolve().parents[1]
BASE = "origin/main"
FULL = ("pyproject.toml", "requirements.txt", "tests/conftest.py", "tests/fixtures/git_config.py")
STRUCTURE = (
    "tests/test_adr.py",
    "tests/test_decyzje_na_faktach.py",
    "tests/test_dokumenty_regul.py",
    "tests/test_granice_importow.py",
    "tests/test_granice_wyjatkow.py",
    "tests/test_jeden_odczyt_skoroszytu.py",
    "tests/test_jeden_zapis_skoroszytu.py",
    "tests/test_kwarantanna.py",
    "tests/test_mapy_funkcji.py",
    "tests/test_miejsce_skilli.py",
    "tests/test_potomne.py::test_drzewa_procesow_i_kopie_commitow_narzedzi_buduje_tylko_potomne",
    "tests/test_potomne.py::test_polecenia_narzedzi_ktore_trwaja_biegna_przez_potomne_run",
    "tests/test_skille_dla_zmiany.py::test_agents_md_nie_wymienia_skilli_verify",
    "tests/test_skille_dla_zmiany.py::test_kazdy_skill_verify_deklaruje_pilnuje",
    "tests/test_skille_dla_zmiany.py::test_skill_nie_kaze_uruchamiac_przed_pushem_tego_co_liczy_ci",
    "tests/test_skille_dla_zmiany.py::test_skill_z_poleceniami_w_ci_mowi_co_liczy_ci_a_co_zostaje_lokalnie",
    "tests/test_skrypty_bez_instalacji.py",
    "tests/test_slowo_flaky_test.py",
    "tests/test_spis_narzedzi.py",
    "tests/test_struktura_testow.py",
    "tests/test_systemowy_python.py",
    "tests/test_uszkodzone_wejscia.py::test_macierz_obejmuje_kazda_operacje_kontraktu_centrum",
    "tests/test_wycofane_pojecia.py",
    "tests/test_wywolanie_skryptow_skilli.py::test_skrypty_skilli_biora_katalog_runu_warianty_i_sciezki_tylko_z_parsera",
    # Globy ``pilnuje:`` z frontmatteru SKILL.md obejmują całe repozytorium, a graf ich nie widzi.
    "tests/test_mutacje_skilli.py::test_kazdy_glob_pilnuje_trafia_w_plik_repozytorium",
    "tests/test_mutacje_skilli.py::test_kazdy_modul_silnika_jest_w_pilnuje_verify_rozliczenia_albo_na_liscie_wylaczen",
    # Kotwice mutacji skilli leżą w plikach całego repozytorium, a skrypty mutacji na pull request nie biegną.
    "tests/test_mutacje_skilli.py::test_kotwica_kazdej_mutacji_skilla_trafia_w_swoj_plik_dokladnie_raz",
    "tests/test_skille_dla_zmiany.py::test_frontmatter_kazdego_skilla_jest_poprawnym_yaml",
    "tests/test_skille_dla_zmiany.py::test_workflow_skilla_windows_biegnie_dla_tych_samych_sciezek_co_jego_pilnuje",
    # Plan bramki liczy graf zależności całego repozytorium, więc test, który zaczyna zależeć od wszystkiego, rośnie
    # bramkę bez zmiany kodu CI.
    "tests/test_ksztalt_bramki.py",
    # ``.gitignore`` czyta tu ``git check-ignore``, nie Python, więc graf nie wiąże go z tym testem.
    "tests/test_centrum_rozliczen.py::test_lokalne_pliki_taty_sa_poza_gitem",
)
STATIC_JOBS = ("ruff", "mypy")
MODULE_ROOTS = ("src", ".", "tools", "tools/lib", "tools/ci")
SKILL_SCRIPTS = ".agents/skills/*/scripts"
GREEN = "szybko-zielone.json"
WORKERS = "4"
# Tor CI, którego czasy plików waży szybko: Linux, jak komputer agenta, nie Windows.
TIMES_TOR = "linux-3.14"
# Sekundy czasów CI na workera. Porażki pytest w szybko z 23–24.10 łapie ten sam plan od 20 s wzwyż, bo prawie
# wszystkie padły w odległości 0–1 albo w testach struktury, więc budżet stoi blisko tej granicy.
BUDGET_S = 45.0
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
    distances: dict[str, int]
    full_reason: str | None = None


@dataclass(frozen=True)
class Plan:
    """Pliki testów, które biegną, i te zostawione CI (``deferred_s`` to ich czas w CI)."""

    run: tuple[str, ...]
    deferred: tuple[str, ...]
    deferred_s: float


def plan(tests: Iterable[str], distances: dict[str, int], times: dict[str, float], budget_s: float = BUDGET_S) -> Plan:
    """Pliki w odległości najwyżej 1 od zmiany biegną zawsze, także ponad budżet. Dalsze, po odległości i koszcie
    rosnąco, biegną, gdy suma kosztów na ``WORKERS`` workerów mieści się jeszcze w ``budget_s``. Koszt pliku bez
    pomiaru to mediana pomiarów."""

    default = statistics.median(times.values()) if times else 0.0
    cost = {test: times.get(test, default) for test in tests}
    capacity, used = budget_s * int(WORKERS), 0.0
    run, deferred = [], []
    for test in sorted(cost, key=lambda test: (distances.get(test, math.inf), cost[test], test)):
        if distances.get(test, math.inf) <= 1 or used + cost[test] <= capacity:
            run.append(test)
            used += cost[test]
        else:
            deferred.append(test)
    return Plan(tuple(sorted(run)), tuple(sorted(deferred)), sum(cost[test] for test in deferred))


@dataclass(frozen=True)
class Dependencies:
    depends_on: dict[str, set[str]]
    folder_files: dict[str, set[str]]

    @classmethod
    def of(cls, root: Path, files: frozenset[str]) -> Dependencies:
        modules = _modules(files)
        directories = {str(parent) for path in files for parent in PurePosixPath(path).parents if str(parent) != "."}
        in_folder: dict[str, set[str]] = defaultdict(set)
        for file in files:
            in_folder[str(PurePosixPath(file).parent)].add(file)
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
            nodes = list(ast.walk(tree))
            for name in _imports(nodes, path):
                depends_on[path] |= _resolve(name, path, modules, files)
            texts, globs = references(nodes)
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
                    folder_files[path] |= _folder_files(text, in_folder)
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
        return set(self.distances_from(changed))

    def distances_from(self, changed: Iterable[str]) -> dict[str, int]:
        """Najmniejsza liczba krawędzi od pliku do zmiany: zmieniony plik ma 0, a plik, który czyta zmieniony plik
        z katalogu, globu albo danych pakietu, 1."""

        back: dict[str, set[str]] = defaultdict(set)
        for source, targets in self.depends_on.items():
            for target in targets:
                back[target].add(source)
        changed = set(changed)
        distances = dict.fromkeys(sorted(changed), 0)
        readers = sorted(source for source, folder in self.folder_files.items() if folder & changed)
        distances |= {reader: 1 for reader in readers if reader not in changed}
        pending = deque(distances)
        while pending:
            target = pending.popleft()
            for source in sorted(back[target] - distances.keys()):
                distances[source] = distances[target] + 1
                pending.append(source)
        return distances


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


def _imports(nodes: Iterable[ast.AST], path: str) -> set[str]:
    package = PurePosixPath(path).parent.parts
    names: set[str] = set()
    for node in nodes:
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


def _as_path(text: str) -> str | None:
    path = text.strip().replace("\\", "/").strip("/")
    if ("/" in path or "." in path) and path.strip(".") and not any(c.isspace() for c in path):
        return path
    return None


def _files_named(text: str, files: frozenset[str]) -> set[str]:
    if (path := _as_path(text)) is None:
        return set()
    return {file for file in files if file == path or file.endswith("/" + path)}


def _folder_files(text: str, in_folder: dict[str, set[str]]) -> set[str]:
    """Pliki leżące wprost w katalogu ``text`` (``in_folder``: katalog → jego pliki)."""

    if (path := _as_path(text)) is None or "/" not in path:
        return set()
    found = {file for folder, inside in in_folder.items() if folder == path or folder.endswith("/" + path) for file in inside}
    # Pakiet test zna przez importy; jego katalog w napisie to ścieżka w repozytorium, które test sam buduje.
    return set() if any(PurePosixPath(file).name == "__init__.py" for file in found) else found


def _globbed(glob: Glob, files: frozenset[str], directories: set[str]) -> set[str]:
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


@dataclass(frozen=True)
class Reach:
    """Pliki testów, których dotyczy zmiana, i odległość plików od niej, bez odcisków: tyle bierze Plan CI."""

    tests: tuple[str, ...]
    distances: dict[str, int]
    full_reason: str | None
    dependencies: Dependencies


def reach(root: Path, changed: frozenset[str]) -> Reach:
    files = _files(root) | changed
    dependencies = Dependencies.of(root, files)
    tests = {path for path in files if _is_test(path) and (root / path).is_file()}
    full = sorted(changed & set(FULL))
    # Plik z ``FULL`` dotyczy każdego testu, a drogę w grafie mają do niego tylko testy, które wymieniają jego nazwę.
    distances = dependencies.distances_from(changed - set(FULL))
    readers = {source for source, targets in dependencies.depends_on.items() if targets & set(full)}
    distances |= {reader: min(distances.get(reader, 2), 2) for reader in readers}
    if not full:
        tests &= distances.keys()
    return Reach(tuple(sorted(tests)), distances, f"zmiana w {', '.join(full)}" if full else None, dependencies)


def select(root: Path, changed: frozenset[str]) -> Selection:
    found = reach(root, changed)
    fingerprints = {test: _fingerprint(root, found.dependencies.inputs_of(test)) for test in found.tests}
    return Selection(fingerprints, found.distances, found.full_reason)


def _times(root: Path) -> dict[str, float]:
    folder = root / _git("rev-parse", "--git-common-dir").strip() / "czasy-ci"
    times = czasy_ci.z_mainu(folder, odswiez_po_s=czasy_ci.ODSWIEZ_S)
    costs = times.pliki(TIMES_TOR)
    if not costs:
        why = times.blad or f"brak plików testów toru {TIMES_TOR} w {czasy_ci.ARTEFAKT}"
        print(f"SZYBKO | bez czasów CI ({why}): każdy plik waży 0, więc biegnie cały wybór", flush=True)
    return costs


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


def changed_since(base: str) -> frozenset[str]:
    """Paths in which the checkout (with uncommitted and untracked files) differs from the merge-base of HEAD and ``base``."""

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


def _run_all(steps: list[ci_lokalnie.Step], interruptible: ci_lokalnie.Step | None = None) -> tuple[list[str], list[str]]:
    """Kroki naraz; zwraca nazwy kroków, które padły, i przerwanych. Gdy padnie krok inny niż ``interruptible``,
    ``interruptible`` jest przerywany: wynik i tak jest FAIL, a na koniec długiego kroku pytest nie trzeba czekać."""

    stop, failure = threading.Event(), threading.Event()

    def run(step: ci_lokalnie.Step) -> tuple[bool | None, str, float]:
        started = time.monotonic()
        try:
            done = potomne.run(
                step.command, cwd=step.cwd, env=_environment(step.cwd), stop=failure if step is interruptible else stop
            )
        except potomne.Stopped:
            return None, "", time.monotonic() - started
        if done.returncode:
            failure.set()
        return done.returncode == 0, done.stdout + done.stderr, time.monotonic() - started

    failed, interrupted = [], []
    pool = ThreadPoolExecutor(max_workers=len(steps))
    try:
        for step, (passed, output, elapsed) in zip(steps, pool.map(run, steps), strict=True):
            if passed is None:
                print(f"PRZERWANY {step.name} ({elapsed:.0f} s): padł inny krok, więc jego testy nie są sprawdzone", flush=True)
                interrupted.append(step.name)
                continue
            print(f"{'OK  ' if passed else 'FAIL'} {step.name} ({elapsed:.0f} s)", flush=True)
            if not passed:
                failed.append(step.name)
                print("\n".join(output.rstrip().splitlines()[-ci_lokalnie.OUTPUT_ON_FAILURE :]), flush=True)
    except BaseException:
        # Przerwanie w głównym wątku nie dociera do wątków, które czekają na swoje polecenia.
        stop.set()
        failure.set()
        raise
    finally:
        pool.shutdown(cancel_futures=True)
    return failed, interrupted


def _describe(selection: Selection, chosen: Plan, changed: frozenset[str], base: str) -> str:
    kind = f"pełny zestaw ({selection.full_reason})" if selection.full_reason else "dotknięte zmianą"
    names = ", ".join(PurePosixPath(path).name for path in chosen.run) or "brak"
    green = len(selection.fingerprints) - len(chosen.run) - len(chosen.deferred)
    return (
        f"Zmiana: {len(changed)} plików od {base}. Testy {kind}: {len(selection.fingerprints)},"
        f" do uruchomienia {len(chosen.run)} ({names}), zielone na tych samych plikach {green}; i testy struktury."
    )


def _deferred(chosen: Plan, selected: int) -> str:
    names = ", ".join(PurePosixPath(path).name for path in chosen.deferred)
    return f"zostawione CI: {len(chosen.deferred)} z {selected} plików testów (~{chosen.deferred_s:.0f} s w CI): {names}"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--baza", default=BASE, help=f"Gałąź, od której liczy się zmiana (domyślnie {BASE}).")
    args = parser.parse_args(argv)
    try:
        changed = changed_since(args.baza)
    except subprocess.CalledProcessError:
        print(f"SZYBKO FAIL | nieznana baza {args.baza}")
        return 1
    selection = select(ROOT, changed)
    memory = GreenMemory.of_checkout()
    chosen = plan(memory.to_run(selection), selection.distances, _times(ROOT))
    print(_describe(selection, chosen, changed, args.baza), flush=True)
    junit = memory.path.with_name(f"szybko-junit-{os.getpid()}.xml")
    steps = _steps(ROOT, chosen.run, junit)
    with ExitStack() as copies:
        if merge := _merge_with(args.baza):
            copy = copies.enter_context(potomne.commit_copy(ROOT, merge))
            # Biegnie razem z krokiem pytest, więc bez workerów xdist nie podwaja liczby rdzeni szybko.
            steps.append(_pytest(copy, f"testy struktury po mergu z {args.baza}", (*STRUCTURE, "-n", "0")))
        failed, interrupted = _run_all(steps, next(step for step in steps if step.name == "pytest"))
    memory.remember(selection, junit, chosen.run)
    junit.unlink(missing_ok=True)
    if chosen.deferred:
        print(_deferred(chosen, len(selection.fingerprints)))
    stopped = "".join(f" | {name} przerwany" for name in interrupted)
    print(f"SZYBKO FAIL | {', '.join(failed)}{stopped}" if failed else "SZYBKO OK")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())

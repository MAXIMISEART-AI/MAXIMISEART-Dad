"""Struktura testów: moduły niczego nie eksportują, test czeka na stan i mierzy czas bez stałej liczby sekund, a eksplorator
przeplotów skilla biegnie we własnym procesie.

Wspólne dane i pomocniki są w ``tests.fixtures``.
"""

from __future__ import annotations

import ast
from collections.abc import Iterable, Iterator
from itertools import pairwise
from pathlib import Path
import re

import pytest

from tests.fixtures.skladnia import dotted, imports

TESTS = Path(__file__).resolve().parent
CLOCKS = frozenset({"time.monotonic", "time.perf_counter"})
TIME_READINGS = CLOCKS | {
    "time.time",
    "time.monotonic_ns",
    "time.perf_counter_ns",
    "time.time_ns",
    "datetime.datetime.now",
    "datetime.datetime.utcnow",
}
SLEEPS = frozenset({"time.sleep", "asyncio.sleep"})
SIMULATED_TIME = {
    "test_centrum_przygotowanie.py::test_czas_czekania_na_decyzje_nie_wlicza_sie_do_czasu_ani_metryk": (
        "tata myśli 1,5 s nad Decyzją, a test mierzy zegarem testu, że ten czas nie wlicza się do metryk (f17b7fe)"
    ),
    "test_opiekun_ponownego_startu.py::test_skrot_klikniety_w_trakcie_ponownego_startu_nie_cofa_nowej_wersji_ktora_dziala": (
        "test gra skrót, który trzyma port przez 3 s w trakcie startu nowej wersji"
    ),
}


def test_moduly_testow_importuja_pomocniki_tylko_z_fixtures() -> None:
    imports = {
        f"{path.name}: {node.module}"
        for path in sorted(TESTS.rglob("*.py"))
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8")))
        if isinstance(node, ast.ImportFrom)
        and node.module is not None
        and node.module.startswith("tests.")
        and not node.module.startswith("tests.fixtures")
    }

    assert imports == set(), "przenieś pomocnik do tests/fixtures i importuj go stamtąd; moduł testu niczego nie eksportuje"


Definition = ast.Lambda | ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef


def _is_sleep(call: ast.Call, names: dict[str, str]) -> bool:
    """``time.sleep`` i ``asyncio.sleep`` pod każdą nazwą z importu i czekanie na nowe ``threading.Event``, którego nikt nie ustawi."""

    function = call.func
    return dotted(function, names, "") in SLEEPS or (
        isinstance(function, ast.Attribute)
        and function.attr == "wait"
        and isinstance(function.value, ast.Call)
        and dotted(function.value.func, names, "") == "threading.Event"
    )


def _handed_over(definition: Definition, tree: ast.Module, parents: dict[ast.AST, ast.AST]) -> bool:
    """Test przekazuje podróbkę jako wartość, więc jej sen woła kod pod testem, a nie sam test.

    Funkcję test woła sam, gdy jej nazwa stoi tylko w ``f(...)``, klasę, gdy tylko w ``C(...).metoda``, a lambdę,
    gdy woła ją od razu albo przez nazwę, do której ją przypisał.
    """

    if isinstance(definition, ast.Lambda):
        parent = parents[definition]
        if isinstance(parent, ast.Call) and parent.func is definition:
            return False
        if not (isinstance(parent, ast.Assign) and len(parent.targets) == 1 and isinstance(parent.targets[0], ast.Name)):
            return True
        name = parent.targets[0].id
    else:
        name = definition.name
    for use in ast.walk(tree):
        if not (isinstance(use, ast.Name) and use.id == name and isinstance(use.ctx, ast.Load)):
            continue
        call = parents[use]
        called = isinstance(call, ast.Call) and call.func is use
        if isinstance(definition, ast.ClassDef):
            called = called and isinstance(parents.get(call), ast.Attribute)
        if not called:
            return True
    return False


def _fixed_sleeps(tree: ast.Module) -> Iterator[tuple[ast.Call, str]]:
    """Sen poza pętlą z terminem i poza podróbką, z nazwą funkcji, w której jest.

    Pętla (``while`` albo ``for``) ma termin, gdy pyta zegar (``time.monotonic()``). Podróbka to lambda, funkcja
    albo klasa, którą test przekazuje dalej jako wartość: jej sen udaje czas pracy kodu pod testem. Znana granica:
    zdarzenie w zmiennej, którego nikt nie ustawia (``hold.wait(2)``), i podróbka, którą test woła sam przez inną
    nazwę, przechodzą, bo odróżnienie ich wymaga analizy przepływu danych.
    """

    names = imports(tree)
    parents = {child: node for node in ast.walk(tree) for child in ast.iter_child_nodes(node)}
    for call in ast.walk(tree):
        if not (isinstance(call, ast.Call) and _is_sleep(call, names)):
            continue
        enclosing: list[ast.AST] = []
        node: ast.AST = call
        while node in parents:
            node = parents[node]
            enclosing.append(node)
        polling = any(
            isinstance(loop, (ast.While, ast.For))
            and any(isinstance(asked, ast.Call) and dotted(asked.func, names, "") in CLOCKS for asked in ast.walk(loop))
            for loop in enclosing
        )
        faked = any(isinstance(node, Definition) and _handed_over(node, tree, parents) for node in enclosing)
        if not (polling or faked):
            functions = [node for node in enclosing if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))]
            yield call, functions[0].name if functions else "<moduł>"


def test_testy_czekaja_na_stan_a_nie_stala_liczbe_sekund() -> None:
    found, simulated = [], set()
    for path in sorted(TESTS.rglob("*.py")):
        name = path.relative_to(TESTS).as_posix()
        for call, function in _fixed_sleeps(ast.parse(path.read_text(encoding="utf-8"))):
            if f"{name}::{function}" in SIMULATED_TIME:
                simulated.add(f"{name}::{function}")
            else:
                found.append(f"tests/{name}:{call.lineno}: {ast.unparse(call)} czeka stałą liczbą sekund")
    found += [f"SIMULATED_TIME: {key} nie ma już snu, usuń wpis" for key in sorted(SIMULATED_TIME.keys() - simulated)]

    assert not found, "\n".join(
        [
            *found,
            "Czekaj na stan przez wait_for z tests/fixtures/potomne.py (brak zdarzenia: assert not wait_for(zdarzenie, s)); "
            "czas pracy podróbki śpi w funkcji, lambdzie albo klasie, którą test przekazuje kodowi pod testem, a czas "
            "symulowany w samym teście wpisz do SIMULATED_TIME z powodem.",
        ]
    )


TIME_NAME = re.compile(r"elapsed|duration|_m?s$")
CONSTANT_TIME_BOUNDS = {
    "test_aktualizacja_narzedzia.py::test_github_proszacy_o_logowanie_konczy_sie_od_razu_bez_pytania_a_klon_zostaje_bez_zmian"
    "::elapsed < 20": (
        "granica 20 s oddziela koniec od zawieszenia: pomocnik logowania, na którego narzędzie nie może czekać, śpi 60 s"
    ),
    "test_aktualizacja_narzedzia.py::test_pomocnik_gita_trzymajacy_jego_wyjscie_nie_wstrzymuje_aktualizacji::elapsed < 20": (
        "granica 20 s oddziela koniec od zawieszenia: pomocnik gita trzyma jego wyjście otwarte przez 60 s"
    ),
    "test_aktualnosc_narzedzia.py::test_milczacy_serwer_nie_wydluza_diagnozy_ponad_limit_czasu"
    "::time.monotonic() - started < 1.5": (
        "serwer nie odpowiada nigdy, więc bez limitu 0,3 s diagnoza czekałaby bez końca; granica to 5× ten limit"
    ),
    "test_potomne.py::test_potomek_spoza_drzewa_z_otwartym_wyjsciem_nie_wstrzymuje_wyniku::time.monotonic() - started < 30": (
        "granica 30 s oddziela koniec od zawieszenia: potomek z otwartym wyjściem śpi 600 s"
    ),
    "test_weryfikacja_w_excelu.py::test_start_excela_bez_zgody_na_automatyzacje_konczy_sie_od_razu_nazwana_przyczyna"
    "::time.monotonic() - started < 10": (
        "granica 10 s to połowa limitu startu Excela (20 s), do którego launch czekałby, gdyby nie rozpoznał odmowy"
    ),
}


def _unpacked(target: ast.expr, value: ast.expr | None) -> Iterator[tuple[str, ast.expr | None]]:
    """Nazwa w celu przypisania i jej wartość: ``took, _ = a, b`` wiąże ``took`` z ``a``."""

    if isinstance(target, ast.Name):
        yield target.id, value
        return
    if isinstance(target, (ast.Tuple, ast.List)):
        values = value.elts if isinstance(value, (ast.Tuple, ast.List)) else []
        paired = len(values) == len(target.elts) and not any(
            isinstance(item, ast.Starred) for item in [*values, *target.elts]
        )
        for index, item in enumerate(target.elts):
            yield from _unpacked(item.value if isinstance(item, ast.Starred) else item, values[index] if paired else None)
        return
    for name in ast.walk(target):
        if isinstance(name, ast.Name):
            yield name.id, None


def _bindings(nodes: Iterable[ast.AST]) -> dict[str, list[ast.expr | None]]:
    """Każda wartość przypisana nazwie w węzłach; ``None``, gdy nazwę wiąże coś innego niż przypisanie.

    ``took += x`` to ``took = took + x``: dla ``_constant`` nazwa zależy od siebie, więc nie jest stałą, a dla
    ``_measured`` niesie odczyt zegara z ``x``.
    """

    bound: dict[str, list[ast.expr | None]] = {}
    for node in nodes:
        if isinstance(node, ast.Assign):
            for target in node.targets:
                for bound_name, value in _unpacked(target, node.value):
                    bound.setdefault(bound_name, []).append(value)
        elif isinstance(node, ast.AugAssign) and isinstance(node.target, ast.Name):
            itself = ast.Name(id=node.target.id, ctx=ast.Load())
            bound.setdefault(node.target.id, []).append(ast.BinOp(left=itself, op=node.op, right=node.value))
        elif isinstance(node, (ast.AnnAssign, ast.NamedExpr)) and isinstance(node.target, ast.Name):
            bound.setdefault(node.target.id, []).append(node.value)
        elif isinstance(node, (ast.For, ast.comprehension, ast.withitem)):
            loop_target = node.optional_vars if isinstance(node, ast.withitem) else node.target
            for name in ast.walk(loop_target) if loop_target is not None else ():
                if isinstance(name, ast.Name):
                    bound.setdefault(name.id, []).append(None)
        elif isinstance(node, ast.arg):
            bound.setdefault(node.arg, []).append(None)
    return bound


def _constant(expression: ast.expr, bound: dict[str, list[ast.expr | None]], seen: frozenset[str] = frozenset()) -> bool:
    """Liczba znana przed uruchomieniem: literał, działanie na literałach albo nazwa przypisana tylko takiej liczbie."""

    if isinstance(expression, ast.Constant):
        return isinstance(expression.value, (int, float)) and not isinstance(expression.value, bool)
    if isinstance(expression, ast.UnaryOp):
        return _constant(expression.operand, bound, seen)
    if isinstance(expression, ast.BinOp):
        return _constant(expression.left, bound, seen) and _constant(expression.right, bound, seen)
    if isinstance(expression, ast.Name) and expression.id not in seen and expression.id in bound:
        return all(
            value is not None and _constant(value, bound, seen | {expression.id}) for value in bound[expression.id]
        )
    return False


def _measured(
    expression: ast.expr, bound: dict[str, list[ast.expr | None]], names: dict[str, str], seen: frozenset[str] = frozenset()
) -> bool:
    """Zmierzony czas: wyrażenie z nazwą czasu (``elapsed``, ``duration``, ``_ms``, ``_s``), z odczytem zegara
    albo z nazwą, której moduł przypisuje takie wyrażenie (``took = time.monotonic() - started``)."""

    if _constant(expression, bound):
        return False
    for node in ast.walk(expression):
        if isinstance(node, ast.Call) and dotted(node.func, names, "") in TIME_READINGS:
            return True
        name = node.id if isinstance(node, ast.Name) else node.attr if isinstance(node, ast.Attribute) else None
        if name is not None and TIME_NAME.search(name) and not (isinstance(node, ast.Name) and _constant(node, bound)):
            return True
        if isinstance(node, ast.Name) and node.id not in seen and any(
            value is not None and _measured(value, bound, names, seen | {node.id}) for value in bound.get(node.id, ())
        ):
            return True
    return False


def _negated(compare: ast.Compare, statement: ast.Assert, parents: dict[ast.AST, ast.AST]) -> bool:
    """Porównanie pod nieparzystą liczbą ``not``: ``assert not elapsed >= 2`` to ``assert elapsed < 2``."""

    nots = 0
    node: ast.AST = compare
    while node is not statement:
        node = parents[node]
        nots += isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.Not)
    return nots % 2 == 1


def _constant_time_bounds(tree: ast.Module) -> Iterator[tuple[ast.Compare, str]]:
    """Asercja, że zmierzony czas jest mniejszy od stałej liczby, z nazwą funkcji, w której jest.

    Znana granica, bo wymaga analizy przepływu danych albo znajomości bibliotek: stała, która przychodzi parametrem
    (``pytest.mark.parametrize``), z innego modułu, z atrybutu klasy albo z ``timedelta(...)``; nazwa, którą moduł
    gdzie indziej wiąże z czymś innym niż liczba; zmierzony czas w pomocniku z innego modułu; granica bez porównania
    w ``assert``: ``pytest.approx(..., abs=...)``, ``math.isclose(..., abs_tol=...)`` i ``if elapsed > 2:
    pytest.fail(...)``.
    """

    names = imports(tree)
    bound = _bindings(ast.walk(tree))
    parents = {child: node for node in ast.walk(tree) for child in ast.iter_child_nodes(node)}
    for statement in ast.walk(tree):
        if not isinstance(statement, ast.Assert):
            continue
        for compare in ast.walk(statement.test):
            if not isinstance(compare, ast.Compare):
                continue
            negated = _negated(compare, statement, parents)
            for operator, (left, right) in zip(compare.ops, pairwise([compare.left, *compare.comparators]), strict=True):
                if isinstance(operator, (ast.Lt, ast.LtE)):
                    measured, limit = left, right
                elif isinstance(operator, (ast.Gt, ast.GtE)):
                    measured, limit = right, left
                else:
                    continue
                if negated:
                    measured, limit = limit, measured
                if _measured(measured, bound, names) and _constant(limit, bound):
                    node: ast.AST = statement
                    while node in parents and not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                        node = parents[node]
                    yield compare, node.name if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) else "<moduł>"
                    break


def test_zmierzony_czas_nie_jest_ograniczony_stala_liczba() -> None:
    found, excepted = [], set()
    for path in sorted(TESTS.rglob("*.py")):
        name = path.relative_to(TESTS).as_posix()
        for compare, function in _constant_time_bounds(ast.parse(path.read_text(encoding="utf-8"))):
            key = f"{name}::{function}::{ast.unparse(compare)}"
            if key in CONSTANT_TIME_BOUNDS:
                excepted.add(key)
            else:
                found.append(f"tests/{name}:{compare.lineno}: {ast.unparse(compare)} ogranicza zmierzony czas stałą liczbą ({key})")
    found += [
        f"CONSTANT_TIME_BOUNDS: {key} nie ma już takiej asercji, usuń wpis"
        for key in sorted(CONSTANT_TIME_BOUNDS.keys() - excepted)
    ]

    assert not found, "\n".join(
        [
            *found,
            "Na wolnym runnerze sama praca trwa dłużej niż stała. Daj kodowi pod testem podróbkę zegara "
            "(ManualClock z tests/fixtures/clock.py, parametr clock) i sprawdź czas równością; gdy kod mierzy "
            "prawdziwy czas, ogranicz go zegarem testu (time.perf_counter() przed i po); gdy podróbka trzyma "
            "odpowiedź, sprawdź stan (jeszcze nie odpowiedziała), a granicę końca kontra zawieszenia wpisz do "
            "CONSTANT_TIME_BOUNDS pod kluczem z nawiasu, z powodem.",
        ]
    )


EXPLORER_FILE = re.compile(r"(explore_\w+)(?:\.py)?")
EXPLORER_RUNS = frozenset({"explore", "main"})
IN_PROCESS_EXPLORERS = {
    "explore_publication": (
        "prowadzi greenlety na wątku testu: nie ma wątku sprawdzenia, który mógłby porzucić z prawdziwą blokadą, "
        "a limit pytest przerywa go jak każdy wiszący test (werdykt #660 r3, punkt 4)"
    ),
}
Scope = ast.Module | ast.FunctionDef | ast.AsyncFunctionDef | ast.Lambda
SCOPES = (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)


def _own_nodes(scope: Scope) -> Iterator[ast.AST]:
    """Węzły zakresu, jego parametry i ciało, bez wnętrza zagnieżdżonych funkcji i klas."""

    pending = list(ast.iter_child_nodes(scope))
    while pending:
        node = pending.pop()
        yield node
        if not isinstance(node, (*SCOPES, ast.ClassDef)):
            pending.extend(ast.iter_child_nodes(node))


Frames = dict[Scope, dict[str, frozenset[str]]]
# Nazwa w zakresie i funkcja, które wyrażenie już rozwija, żeby rekurencja w module testu się kończyła.
Seen = frozenset[tuple[str, Scope] | ast.FunctionDef | ast.AsyncFunctionDef]


class _Explorers:
    """Które eksploratory (``explore_<co>``) może wskazywać wyrażenie modułu testu.

    Eksplorator wskazuje napis z nazwą jego pliku albo modułu (``"explore_runs.py"``), import (``import explore_runs``)
    i nazwa przypisana takiemu wyrażeniu w swoim zakresie albo w module. Wynik wywołania wskazuje to, co jego argumenty
    i obiekt, na którym biegnie metoda (``spec_from_file_location(..., EXPLORER)``, ``module_from_spec(spec)``),
    a wywołanie funkcji z tego modułu także to, co wskazuje jej ``return``, z parametrami związanymi z argumentami tego
    wywołania albo z wartościami domyślnymi (``_load()``, ``_load(EXPLORER)``, ale nie ``_load(SCRIPT)``). Atrybut
    eksploratora (``explorer.runs``) nie jest już eksploratorem. Napis z kodem dla ``subprocess`` (``"-c", "import
    explore_runs"``) nie jest napisem z nazwą pliku, więc nie wskazuje niczego.
    """

    def __init__(self, tree: ast.Module) -> None:
        self.names = imports(tree)
        self.parents = {child: node for node in ast.walk(tree) for child in ast.iter_child_nodes(node)}
        self.scopes = {node: _bindings(_own_nodes(node)) for node in ast.walk(tree) if isinstance(node, SCOPES)}
        self.functions = {
            node.name: node for node in ast.walk(tree) if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        }

    def _scope(self, node: ast.AST) -> Scope:
        while not isinstance(node, SCOPES):
            node = self.parents[node]
        return node

    def _name(self, name: ast.Name, seen: Seen, frames: Frames) -> frozenset[str]:
        imported = self.names.get(name.id, "").rpartition(".")[2]
        if EXPLORER_FILE.fullmatch(imported):
            return frozenset({imported})
        node: ast.AST = name
        while node in self.parents:
            scope = self._scope(self.parents[node])
            if name.id in frames.get(scope, {}):
                return frames[scope][name.id]
            if name.id in self.scopes[scope]:
                if (name.id, scope) in seen:
                    return frozenset()
                values = [value for value in self.scopes[scope][name.id] if value is not None]
                return frozenset().union(*(self.of(value, seen | {(name.id, scope)}, frames) for value in values))
            node = scope
        return frozenset()

    def _parameters(
        self, function: ast.FunctionDef | ast.AsyncFunctionDef, call: ast.Call, seen: Seen, frames: Frames
    ) -> dict[str, frozenset[str]]:
        """Co wskazuje każdy parametr ``function`` w wywołaniu ``call``: jego argument albo wartość domyślna.

        Znana granica: argument ``*args`` wiąże się z jednym parametrem, a ``**kwargs`` z żadnym.
        """

        arguments = function.args
        positional = [*arguments.posonlyargs, *arguments.args]
        with_default = positional[len(positional) - len(arguments.defaults) :]
        defaults = {parameter.arg: default for parameter, default in zip(with_default, arguments.defaults, strict=True)}
        defaults |= {
            parameter.arg: default
            for parameter, default in zip(arguments.kwonlyargs, arguments.kw_defaults, strict=True)
            if default is not None
        }
        count = min(len(positional), len(call.args))
        given = {parameter.arg: argument for parameter, argument in zip(positional[:count], call.args[:count], strict=True)}
        given |= {keyword.arg: keyword.value for keyword in call.keywords if keyword.arg is not None}
        return {name: self.of(default, seen) for name, default in defaults.items()} | {
            name: self.of(argument, seen, frames) for name, argument in given.items()
        }

    def of(self, expression: ast.AST, seen: Seen = frozenset(), frames: Frames | None = None) -> frozenset[str]:
        frames = frames or {}
        if isinstance(expression, ast.Constant) and isinstance(expression.value, str):
            matched = EXPLORER_FILE.fullmatch(expression.value)
            return frozenset({matched.group(1)}) if matched else frozenset()
        if isinstance(expression, ast.Name):
            return self._name(expression, seen, frames)
        if isinstance(expression, (ast.Attribute, Definition)):
            return frozenset()
        found = frozenset().union(*(self.of(child, seen, frames) for child in ast.iter_child_nodes(expression)))
        if not isinstance(expression, ast.Call):
            return found
        if isinstance(expression.func, ast.Attribute):
            found |= self.of(expression.func.value, seen, frames)
        function = self.functions.get(expression.func.id) if isinstance(expression.func, ast.Name) else None
        if function is not None and function not in seen:
            inside = {**frames, function: self._parameters(function, expression, seen, frames)}
            returned = [node.value for node in ast.walk(function) if isinstance(node, ast.Return) and node.value]
            found |= frozenset().union(*(self.of(value, seen | {function}, inside) for value in returned))
        return found

    def run_in_process(self, call: ast.Call) -> frozenset[str]:
        """Eksploratory, których ``explore`` albo ``main`` biegnie w tym wywołaniu w procesie testu.

        ``explorer.explore(...)``, ``explore_runs.main(...)``, ``main(...)`` po ``from explore_runs import main``
        i ``runpy.run_path(EXPLORER)``. Znana granica: wywołanie przez inną nazwę (``run = explorer.main``)
        i przez ``getattr``.
        """

        function = call.func
        if isinstance(function, ast.Attribute) and function.attr in EXPLORER_RUNS:
            return self.of(function.value)
        if isinstance(function, ast.Name):
            owner, _, attribute = self.names.get(function.id, "").rpartition(".")
            if attribute in EXPLORER_RUNS and EXPLORER_FILE.fullmatch(owner.rpartition(".")[2]):
                return frozenset({owner.rpartition(".")[2]})
        if dotted(function, self.names, "") in {"runpy.run_path", "runpy.run_module"}:
            return frozenset().union(*(self.of(argument) for argument in call.args[:1]))
        return frozenset()


def _explorers_in_process(tree: ast.Module) -> Iterator[tuple[ast.Call, str]]:
    explorers = _Explorers(tree)
    calls = sorted((node for node in ast.walk(tree) if isinstance(node, ast.Call)), key=lambda call: call.lineno)
    for call in calls:
        for explorer in sorted(explorers.run_in_process(call)):
            yield call, explorer


LOADER = """
import importlib.util
from pathlib import Path

EXPLORER = Path("scripts") / "explore_runs.py"
SCRIPT = Path("scripts") / "sprawdz_model.py"


def _load(path=EXPLORER):
    spec = importlib.util.spec_from_file_location(path.stem, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_wczytuje_eksplorator():
    module = _load(EXPLORER)


def test_ta_sama_nazwa_w_innym_zakresie():
    module = _load(SCRIPT)
    module.main([])
"""


@pytest.mark.parametrize(
    ("test", "in_process"),
    [
        pytest.param("_load().explore(SCOPE)", ["explore_runs"], id="wynik-wczytania-z-domyslna-sciezka"),
        pytest.param("explorer = _load(EXPLORER)\nexplorer.main([])", ["explore_runs"], id="nazwa-wczytanego-modulu"),
        pytest.param("import explore_runs as er\ner.main([])", ["explore_runs"], id="import-z-inna-nazwa"),
        pytest.param("from explore_outbox import explore\nexplore(SCOPE)", ["explore_outbox"], id="import-funkcji"),
        pytest.param("from scripts import explore_runs\nexplore_runs.main([])", ["explore_runs"], id="import-z-pakietu"),
        pytest.param("import runpy\nrunpy.run_path(str(EXPLORER))", ["explore_runs"], id="runpy"),
        pytest.param("_load(SCRIPT).main([])", [], id="inny-skrypt-przez-ten-sam-pomocnik"),
        pytest.param("_load().runs.main()", [], id="atrybut-eksploratora"),
        pytest.param(
            "import subprocess, sys\nsubprocess.run([sys.executable, '-c', 'import explore_runs; explore_runs.main([])'], timeout=9)",
            [],
            id="kod-w-napisie-dla-subprocess",
        ),
        pytest.param("import subprocess, sys\nsubprocess.run([sys.executable, str(EXPLORER)], timeout=9)", [], id="sciezka-dla-subprocess"),
    ],
)
def test_eksplorator_w_procesie_testu_to_wywolanie_explore_albo_main_modulu_eksploratora(test: str, in_process: list[str]) -> None:
    body = "".join(f"    {line}\n" for line in test.splitlines())
    tree = ast.parse(f"{LOADER}\n\ndef test_przyklad():\n{body}")

    assert [explorer for _, explorer in _explorers_in_process(tree)] == in_process


def test_eksplorator_przeplotow_biegnie_we_wlasnym_procesie_testu_z_limitem() -> None:
    """Eksplorator przeplotów skilla ``verify-*`` (``.agents/skills/*/scripts/explore_*.py``) biegnie w teście przez
    ``subprocess`` z limitem, nie w procesie pytest.

    Wątek modelu, który czeka na prawdziwą blokadę spoza modelu, staje na zawsze, a eksplorator porzuca go razem z tą
    blokadą. W workerze pytest stawał wtedy każdy następny test Centrum, który brał tę blokadę, a sesja wisiała bez
    linii LUKA (#651, przegląd #660 rundy 1 i 2). Objaw widać tylko przy defekcie, więc żaden zielony test go nie
    pokaże. Sprawdzenie czyta AST modułów testów (``_Explorers``), nie tekst: kod w napisie dla ``subprocess`` nie
    jest wywołaniem. Wyjątki są w ``IN_PROCESS_EXPLORERS`` z powodem.
    """

    found, excepted = [], set()
    for path in sorted(TESTS.rglob("*.py")):
        name = path.relative_to(TESTS).as_posix()
        for call, explorer in _explorers_in_process(ast.parse(path.read_text(encoding="utf-8"))):
            if explorer in IN_PROCESS_EXPLORERS:
                excepted.add(explorer)
            else:
                found.append(f"tests/{name}:{call.lineno}: {ast.unparse(call.func)}(…) uruchamia {explorer} w procesie testu")
    found += [
        f"IN_PROCESS_EXPLORERS: {explorer} nie biegnie już w procesie testu, usuń wpis"
        for explorer in sorted(IN_PROCESS_EXPLORERS.keys() - excepted)
    ]

    assert not found, "\n".join(
        [
            *found,
            "Uruchom eksplorator we własnym procesie z limitem poniżej limitu pytest, jak _in_own_process w "
            "tests/test_jedno_uruchomienie_naraz.py (skrypt w -c albo ścieżka do explore_*.py), i sprawdź kod wyjścia "
            "i linie wyjścia; eksplorator, który nie może porzucić wątku, wpisz do IN_PROCESS_EXPLORERS z powodem.",
        ]
    )

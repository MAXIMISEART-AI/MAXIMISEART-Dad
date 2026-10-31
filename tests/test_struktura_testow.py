"""Struktura testów: moduły niczego nie eksportują, test czeka na stan i mierzy czas bez stałej liczby sekund, a eksplorator
przeplotów skilla biegnie we własnym procesie.

Wspólne dane i pomocniki są w ``tests.fixtures``.
"""

from __future__ import annotations

import ast
from collections.abc import Iterable, Iterator, Sequence
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


def _bindings(tree: ast.Module) -> dict[str, list[ast.expr | None]]:
    """Każda wartość przypisana nazwie w module; ``None``, gdy nazwę wiąże coś innego niż przypisanie.

    ``took += x`` to ``took = took + x``: dla ``_constant`` nazwa zależy od siebie, więc nie jest stałą, a dla
    ``_measured`` niesie odczyt zegara z ``x``.
    """

    bound: dict[str, list[ast.expr | None]] = {}
    for node in ast.walk(tree):
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
    bound = _bindings(tree)
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


EXPLORER = re.compile(r"explore_\w+")
# Wywołania, które wykonują w swoim procesie moduł z jego nazwy albo ścieżki albo przygotowują to wykonanie (spec,
# loader), oraz ``exec``, ``eval`` i ``compile``, które wykonują kod z napisu.
LOADERS = frozenset(
    {
        "builtins.__import__",
        "importlib.__import__",
        "importlib.import_module",
        "importlib.util.find_spec",
        "importlib.util.spec_from_file_location",
        "importlib.machinery.SourceFileLoader",
        "importlib.machinery.SourcelessFileLoader",
        "pytest.importorskip",
        "runpy.run_module",
        "runpy.run_path",
        "builtins.compile",
        "builtins.eval",
        "builtins.exec",
    }
)
CODE_FROM_TEXT = frozenset({"builtins.compile", "builtins.eval", "builtins.exec"})
# Atrybuty ścieżki, które zachowują nazwę pliku: ``EXPLORER.stem`` to wciąż ``explore_runs``, a ``EXPLORER.parent`` już nie.
KEEPS_NAME = frozenset({"name", "stem"})
IN_PROCESS_EXPLORERS = {
    "explore_publication": (
        "prowadzi greenlety na wątku testu: nie ma wątku sprawdzenia, który mógłby porzucić z prawdziwą blokadą, "
        "a limit pytest przerywa go jak każdy wiszący test (werdykt #660 r3, punkt 4)"
    ),
}
Function = ast.FunctionDef | ast.AsyncFunctionDef | ast.Lambda
Scope = ast.Module | ast.ClassDef | Function
SCOPES = (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)
# Nazwa w zakresie, parametr funkcji i funkcja, które wyrażenie już rozwija, żeby rekurencja w module testu się kończyła.
Seen = frozenset[tuple[str, ast.AST] | ast.AST]


def _explorer_named(text: str) -> frozenset[str]:
    """Eksplorator, który nazywa napis: plik (``scripts/explore_runs.py``, ``.pyc``) albo moduł (``scripts.explore_runs``)."""

    stem = re.sub(r"\.pyc?$", "", re.split(r"[/\\]", text)[-1]).rpartition(".")[2]
    return frozenset({stem}) if EXPLORER.fullmatch(stem) else frozenset()


def _own_nodes(scope: Scope) -> Iterator[ast.AST]:
    """Węzły zakresu, jego parametry i ciało, bez wnętrza zagnieżdżonych funkcji i klas."""

    pending = list(ast.iter_child_nodes(scope))
    while pending:
        node = pending.pop()
        yield node
        if not isinstance(node, SCOPES):
            pending.extend(ast.iter_child_nodes(node))


def _targets(target: ast.expr, value: ast.expr) -> Iterator[tuple[str, ast.expr]]:
    """Nazwa w celu przypisania i jej wartość: ``a, b = x, y`` wiąże ``a`` z ``x``, inny kształt każdą nazwę z całością."""

    if isinstance(target, ast.Name):
        yield target.id, value
    elif isinstance(target, ast.Starred):
        yield from _targets(target.value, value)
    elif isinstance(target, (ast.Tuple, ast.List)):
        paired = value.elts if isinstance(value, (ast.Tuple, ast.List)) and len(value.elts) == len(target.elts) else None
        for index, item in enumerate(target.elts):
            yield from _targets(item, paired[index] if paired else value)


def _sources(nodes: Iterable[ast.AST]) -> dict[str, list[ast.expr]]:
    """Wyrażenia, z których nazwa w zakresie bierze wartość: przypisanie, ``:=``, pętla i comprehension (zbiór, po
    którym idą) oraz ``with ... as`` (menedżer kontekstu)."""

    found: dict[str, list[ast.expr]] = {}
    for node in nodes:
        pairs: list[tuple[ast.expr, ast.expr]] = []
        if isinstance(node, ast.Assign):
            pairs = [(target, node.value) for target in node.targets]
        elif isinstance(node, (ast.AugAssign, ast.AnnAssign, ast.NamedExpr)) and node.value is not None:
            pairs = [(node.target, node.value)]
        elif isinstance(node, (ast.For, ast.AsyncFor, ast.comprehension)):
            pairs = [(node.target, node.iter)]
        elif isinstance(node, ast.withitem) and node.optional_vars is not None:
            pairs = [(node.optional_vars, node.context_expr)]
        for target, value in pairs:
            for name, bound in _targets(target, value):
                found.setdefault(name, []).append(bound)
    return found


def _called(expression: ast.expr) -> str | None:
    """Nazwa funkcji w ``f`` albo ``obiekt.f``."""

    if isinstance(expression, ast.Name):
        return expression.id
    return expression.attr if isinstance(expression, ast.Attribute) else None


def _arguments(call: ast.Call) -> list[ast.expr]:
    return [*call.args, *(keyword.value for keyword in call.keywords)]


def _parametrized(names: ast.expr) -> set[str]:
    """Nazwy parametrów z pierwszego argumentu ``pytest.mark.parametrize``: ``"a, b"`` albo ``("a", "b")``."""

    if isinstance(names, ast.Constant) and isinstance(names.value, str):
        return {name.strip() for name in names.value.split(",")}
    if isinstance(names, (ast.Tuple, ast.List)):
        return {item.value for item in names.elts if isinstance(item, ast.Constant) and isinstance(item.value, str)}
    return set()


class _Loads:
    """Wczytania eksploratora przeplotów (``explore_<co>``) w procesie testu w jednym module ``tests/``.

    Wczytanie to ``import`` albo ``from ... import`` modułu eksploratora i wywołanie z ``LOADERS``, którego argument
    może nazywać eksplorator: napis z nazwą jego pliku albo modułu (``"explore_runs.py"``, ``"explore_runs"``) i każde
    wyrażenie zbudowane z takiego napisu, także przez nazwy. Nazwa bierze wartość z przypisania, ``:=``, pętli,
    comprehension i ``with ... as`` w swoim zakresie albo w zakresach nad nim, a parametr funkcji z wartości domyślnej,
    z argumentów każdego jej wywołania w module (także gdy funkcję podano dalej: ``partial(_load, EXPLORER)``,
    ``submit(_load, EXPLORER)``), z ``pytest.mark.parametrize`` i z ``return``/``yield`` fixtury o tej nazwie w module
    albo w ``conftest.py`` nad nim. Kod z napisu dla ``exec``/``eval``/``compile`` sprawdza ten sam parser; napis
    z kodem dla ``subprocess`` (``"-c", "import explore_runs"``) nie jest wczytaniem w procesie testu.

    Wczytanie nie zależy od tego, co test robi potem z modułem, więc postać wywołania ``explore`` albo ``main``
    (alias, ``getattr``, ``Thread(target=...)``, ``partial``, moduł podany przez fixturę) nie ma znaczenia.

    Znana granica, której parser nie widzi: nazwa albo ścieżka eksploratora spoza modułu i jego ``conftest.py``
    (stała zaimportowana z innego modułu, ``request.getfixturevalue``, ``params`` fixtury), sklejona z kawałków
    (``f"explore_{co}.py"``, ``glob("explore_*.py")``) albo wzięta z atrybutu innego niż ``name``/``stem``; loader spoza
    ``LOADERS`` (``zipimport``, własny ``importlib.abc.Loader``), kopia pliku eksploratora pod inną nazwą i moduł spoza
    ``tests/``, który sam importuje eksplorator (dziś żaden skrypt skilla ani narzędzie tego nie robi).
    """

    def __init__(self, tree: ast.Module, conftests: Sequence[_Loads] = ()) -> None:
        self.tree = tree
        self.conftests = conftests
        self.names = imports(tree)
        self.parents = {child: node for node in ast.walk(tree) for child in ast.iter_child_nodes(node)}
        self.scopes = {node: _sources(_own_nodes(node)) for node in ast.walk(tree) if isinstance(node, SCOPES)}
        self.functions: dict[str, list[Function]] = {}
        self.calls: dict[str, list[ast.Call]] = {}
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                self.functions.setdefault(node.name, []).append(node)
            elif isinstance(node, ast.Assign) and isinstance(node.value, ast.Lambda):
                for target in node.targets:
                    if isinstance(target, ast.Name):
                        self.functions.setdefault(target.id, []).append(node.value)
            elif isinstance(node, ast.Call):
                for name in {_called(node.func), *map(_called, _arguments(node))}:
                    if name is not None:
                        self.calls.setdefault(name, []).append(node)

    def loads(self) -> Iterator[tuple[ast.stmt | ast.Call, str]]:
        for node in ast.walk(self.tree):
            if isinstance(node, ast.Import):
                found = frozenset().union(*(_explorer_named(alias.name) for alias in node.names))
            elif isinstance(node, ast.ImportFrom):
                found = _explorer_named(node.module or "").union(*(_explorer_named(alias.name) for alias in node.names))
            elif isinstance(node, ast.Call) and dotted(node.func, self.names, "builtins") in LOADERS:
                found = self._loaded(node)
            else:
                continue
            for explorer in sorted(found):
                yield node, explorer

    def _loaded(self, call: ast.Call) -> frozenset[str]:
        code = call.args[0] if call.args else None
        if (
            dotted(call.func, self.names, "builtins") in CODE_FROM_TEXT
            and isinstance(code, ast.Constant)
            and isinstance(code.value, str)
        ):
            try:
                tree = ast.parse(code.value)
            except SyntaxError:
                pass
            else:
                return frozenset(explorer for _, explorer in _Loads(tree).loads())
        return frozenset().union(*(self.of(argument) for argument in _arguments(call)))

    def of(self, expression: ast.AST, seen: Seen = frozenset()) -> frozenset[str]:
        """Eksploratory, które może nazywać wartość wyrażenia."""

        if isinstance(expression, ast.Constant):
            return _explorer_named(expression.value) if isinstance(expression.value, str) else frozenset()
        if isinstance(expression, ast.Name):
            return self._name(expression, seen)
        if isinstance(expression, ast.Attribute):
            return self.of(expression.value, seen) if expression.attr in KEEPS_NAME else frozenset()
        if isinstance(expression, Definition):
            return frozenset()
        found = frozenset().union(*(self.of(child, seen) for child in ast.iter_child_nodes(expression)))
        if isinstance(expression, ast.Call):
            if isinstance(expression.func, ast.Attribute):
                found |= self.of(expression.func.value, seen)
            for function in self.functions.get(_called(expression.func) or "", []):
                found |= self._returned(function, seen)
        return found

    def _scope(self, node: ast.AST) -> Scope:
        while not isinstance(node, SCOPES):
            node = self.parents[node]
        return node

    def _name(self, name: ast.Name, seen: Seen) -> frozenset[str]:
        node: ast.AST = name
        while node in self.parents:
            scope = self._scope(self.parents[node])
            sources = self.scopes[scope].get(name.id, [])
            parameter = isinstance(scope, Function) and name.id in {
                argument.arg for argument in ast.walk(scope.args) if isinstance(argument, ast.arg)
            }
            if sources or parameter:
                if (name.id, scope) in seen:
                    return frozenset()
                inner = seen | {(name.id, scope)}
                found = frozenset().union(*(self.of(source, inner) for source in sources))
                if isinstance(scope, Function) and parameter:
                    found |= self._parameter(scope, name.id, inner)
                return found
            node = scope
        return frozenset()

    def _parameter(self, function: Function, name: str, seen: Seen) -> frozenset[str]:
        arguments = function.args
        positional = [parameter.arg for parameter in [*arguments.posonlyargs, *arguments.args]]
        with_default = positional[len(positional) - len(arguments.defaults) :]
        defaults = [*zip(with_default, arguments.defaults, strict=True)]
        defaults += [
            (parameter.arg, default)
            for parameter, default in zip(arguments.kwonlyargs, arguments.kw_defaults, strict=True)
            if default is not None
        ]
        found = frozenset().union(*(self.of(default, seen) for parameter, default in defaults if parameter == name))
        found |= self._calls(function, name, positional, seen)
        if not isinstance(function, ast.Lambda):
            found |= self._parametrize(function, name, seen) | self._fixture(name, seen)
        return found

    def _calls(self, function: Function, name: str, positional: list[str], seen: Seen) -> frozenset[str]:
        """Co wskazuje parametr ``name`` w każdym wywołaniu ``function`` w module, także przez metodę obiektu."""

        callee = function.name if not isinstance(function, ast.Lambda) else _lambda_name(self.parents[function])
        method = isinstance(self.parents.get(function), ast.ClassDef)
        variadic = function.args.vararg.arg if function.args.vararg else None
        keywords = function.args.kwarg.arg if function.args.kwarg else None
        found: frozenset[str] = frozenset()
        for call in self.calls.get(callee or "", []):
            if _called(call.func) != callee:
                found = found.union(*(self.of(argument, seen) for argument in _arguments(call) if _called(argument) != callee))
                continue
            bound = positional[1:] if method and isinstance(call.func, ast.Attribute) else positional
            for index, argument in enumerate(call.args):
                if isinstance(argument, ast.Starred):
                    found |= self.of(argument.value, seen)
                elif (bound[index] if index < len(bound) else variadic) == name:
                    found |= self.of(argument, seen)
            for keyword in call.keywords:
                if keyword.arg in (None, name) or (name == keywords and keyword.arg not in positional):
                    found |= self.of(keyword.value, seen)
        return found

    def _parametrize(self, function: ast.FunctionDef | ast.AsyncFunctionDef, name: str, seen: Seen) -> frozenset[str]:
        found: frozenset[str] = frozenset()
        for decorator in function.decorator_list:
            if not isinstance(decorator, ast.Call) or not decorator.args:
                continue
            if not (dotted(decorator.func, self.names, "") or "").endswith(".parametrize"):
                continue
            values = [*decorator.args[1:2], *(keyword.value for keyword in decorator.keywords if keyword.arg == "argvalues")]
            if name in _parametrized(decorator.args[0]):
                found = found.union(*(self.of(value, seen) for value in values))
        return found

    def _fixture(self, name: str, seen: Seen) -> frozenset[str]:
        """``return`` i ``yield`` fixtury ``name`` z tego modułu, a gdy jej tu nie ma, z najbliższego ``conftest.py``."""

        for module in (self, *self.conftests):
            fixtures = [function for function in module.functions.get(name, []) if module._is_fixture(function)]
            if fixtures:
                return frozenset().union(*(module._returned(fixture, seen) for fixture in fixtures))
        return frozenset()

    def _is_fixture(self, function: Function) -> bool:
        decorators = [] if isinstance(function, ast.Lambda) else function.decorator_list
        return any(
            (dotted(decorator.func if isinstance(decorator, ast.Call) else decorator, self.names, "") or "").endswith("fixture")
            for decorator in decorators
        )

    def _returned(self, function: Function, seen: Seen) -> frozenset[str]:
        if function in seen:
            return frozenset()
        if isinstance(function, ast.Lambda):
            values = [function.body]
        else:
            values = [
                node.value
                for node in _own_nodes(function)
                if isinstance(node, (ast.Return, ast.Yield, ast.YieldFrom)) and node.value is not None
            ]
        return frozenset().union(*(self.of(value, seen | {function}) for value in values))


def _lambda_name(assignment: ast.AST) -> str | None:
    """Nazwa, której przypisano ``lambda`` (``load = lambda path: ...``)."""

    targets = assignment.targets if isinstance(assignment, ast.Assign) else []
    return next((target.id for target in targets if isinstance(target, ast.Name)), None)


def _modules(root: Path) -> dict[Path, _Loads]:
    """``_Loads`` każdego modułu pod ``root``; fixtury bierze z ``conftest.py`` swojego katalogu i katalogów nad nim."""

    modules: dict[Path, _Loads] = {}
    for path in sorted(root.rglob("*.py"), key=lambda path: (len(path.parts), path.name != "conftest.py", path)):
        conftests = [
            modules[folder / "conftest.py"]
            for folder in [path.parent, *path.parent.parents]
            if folder / "conftest.py" in modules
        ]
        modules[path] = _Loads(ast.parse(path.read_text(encoding="utf-8")), conftests)
    return modules


def _in_process(root: Path) -> list[tuple[str, int, str, str]]:
    """Każde wczytanie eksploratora pod ``root``: plik, linia, postać wczytania i eksplorator."""

    found = []
    for path, module in sorted(_modules(root).items()):
        for node, explorer in module.loads():
            shape = f"{ast.unparse(node.func)}(…)" if isinstance(node, ast.Call) else ast.unparse(node)
            found.append((path.relative_to(root).as_posix(), node.lineno, shape, explorer))
    return sorted(found)


PRELUDE = """
import importlib
import importlib.util
import runpy
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPTS = Path("scripts")
EXPLORER = SCRIPTS / "explore_runs.py"
SCRIPT = SCRIPTS / "sprawdz_model.py"


def _load(path=SCRIPT):
    spec = importlib.util.spec_from_file_location(path.stem, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module
"""
HELPER = "spec = importlib.util.spec_from_file_location(path.stem, path)"
CONFTEST = """
import importlib
from pathlib import Path

import pytest


@pytest.fixture
def explorer():
    return importlib.import_module("explore_runs")


@pytest.fixture
def explorer_path():
    return Path("scripts") / "explore_outbox.py"
"""


@pytest.mark.parametrize(
    ("test", "loads"),
    [
        pytest.param(
            "@pytest.fixture\n"
            "def explorer():\n"
            "    spec = importlib.util.spec_from_file_location('explore_runs', SCRIPTS / 'explore_runs.py')\n"
            "    module = importlib.util.module_from_spec(spec)\n"
            "    spec.loader.exec_module(module)\n"
            "    return module\n"
            "def test_w_procesie(explorer):\n"
            "    explorer.explore(explorer.SCOPES['zamknij-w-trakcie'])\n",
            [("spec = importlib.util.spec_from_file_location('explore_runs', SCRIPTS / 'explore_runs.py')", "explore_runs")],
            id="fixtura-z-przegladu",
        ),
        pytest.param(
            "@pytest.fixture\ndef explorer():\n    yield _load(EXPLORER)\ndef test_w_procesie(explorer):\n    explorer.main([])\n",
            [(HELPER, "explore_runs")],
            id="fixtura-z-yield-przez-pomocnika",
        ),
        pytest.param("def test_w_procesie(explorer):\n    explorer.main([])\n", [], id="modul-z-fixtury-conftest"),
        pytest.param(
            "def test_w_procesie(explorer_path):\n    runpy.run_path(str(explorer_path))\n",
            [("runpy.run_path(str(explorer_path))", "explore_outbox")],
            id="sciezka-z-fixtury-conftest",
        ),
        pytest.param(
            "import threading\ndef test_w_procesie():\n    threading.Thread(target=_load(EXPLORER).explore, args=(1,)).start()\n",
            [(HELPER, "explore_runs")],
            id="thread-target",
        ),
        pytest.param(
            "from functools import partial\ndef test_w_procesie():\n    partial(_load, EXPLORER)().main([])\n",
            [(HELPER, "explore_runs")],
            id="partial",
        ),
        pytest.param(
            "from concurrent.futures import ThreadPoolExecutor\n"
            "def test_w_procesie():\n"
            "    ThreadPoolExecutor().submit(_load, path=EXPLORER).result(timeout=60)\n",
            [(HELPER, "explore_runs")],
            id="submit",
        ),
        pytest.param("import explore_runs as er\n", [("import explore_runs as er", "explore_runs")], id="import"),
        pytest.param(
            "from explore_outbox import explore\n",
            [("from explore_outbox import explore", "explore_outbox")],
            id="import-funkcji",
        ),
        pytest.param(
            "from scripts import explore_runs\n", [("from scripts import explore_runs", "explore_runs")], id="import-z-pakietu"
        ),
        pytest.param(
            "import scripts.explore_intermax\n",
            [("import scripts.explore_intermax", "explore_intermax")],
            id="import-modulu-pakietu",
        ),
        pytest.param(
            "SCOPES = importlib.import_module('explore_outbox').SCOPES\n",
            [("SCOPES = importlib.import_module('explore_outbox').SCOPES", "explore_outbox")],
            id="import_module",
        ),
        pytest.param(
            "runpy.run_module(mod_name='explore_runs')\n", [("runpy.run_module(mod_name='explore_runs')", "explore_runs")], id="run_module"
        ),
        pytest.param(
            "runpy.run_path(path_name=str(EXPLORER))\n", [("runpy.run_path(path_name=str(EXPLORER))", "explore_runs")], id="run_path-po-nazwie"
        ),
        pytest.param("_load(path=EXPLORER)\n", [(HELPER, "explore_runs")], id="argument-po-nazwie"),
        pytest.param("_load(*[EXPLORER])\n", [(HELPER, "explore_runs")], id="argumenty-z-gwiazdka"),
        pytest.param("_load(**{'path': EXPLORER})\n", [(HELPER, "explore_runs")], id="argumenty-ze-slownika"),
        pytest.param(
            "def _run(path=EXPLORER):\n    return runpy.run_path(str(path))\n",
            [("return runpy.run_path(str(path))", "explore_runs")],
            id="wartosc-domyslna",
        ),
        pytest.param(
            "def _run(*paths):\n    return [runpy.run_path(str(path)) for path in paths]\n_run(SCRIPT, EXPLORER)\n",
            [("return [runpy.run_path(str(path)) for path in paths]", "explore_runs")],
            id="parametr-z-gwiazdka",
        ),
        pytest.param(
            "def _run(**paths):\n    return runpy.run_path(str(paths['x']))\n_run(x=EXPLORER)\n",
            [("return runpy.run_path(str(paths['x']))", "explore_runs")],
            id="parametr-z-dwiema-gwiazdkami",
        ),
        pytest.param("exec(EXPLORER.read_text())\n", [("exec(EXPLORER.read_text())", "explore_runs")], id="exec-tresci-pliku"),
        pytest.param(
            "exec('import explore_runs\\nexplore_runs.main([])')\n", [("exec('import explore_runs\\nexplore_runs.main([])')", "explore_runs")], id="exec-kodu"
        ),
        pytest.param(
            "with open(EXPLORER) as source:\n    exec(source.read())\n", [("exec(source.read())", "explore_runs")], id="with"
        ),
        pytest.param("for path in (SCRIPT, EXPLORER):\n    _load(path)\n", [(HELPER, "explore_runs")], id="petla"),
        pytest.param(
            "@pytest.mark.parametrize('name, path', [('model', SCRIPT), ('eksplorator', EXPLORER)])\n"
            "def test_w_procesie(name, path):\n"
            "    _load(path)\n",
            [(HELPER, "explore_runs")],
            id="parametrize",
        ),
        pytest.param(
            "def _path(name):\n    return SCRIPTS / f'{name}.py'\n_load(_path('explore_runs'))\n",
            [(HELPER, "explore_runs")],
            id="sciezka-z-pomocnika",
        ),
        pytest.param(
            "class TestEksplorator:\n"
            "    def _run(self, path):\n"
            "        return runpy.run_path(str(path))\n"
            "    def test_w_procesie(self):\n"
            "        self._run(EXPLORER)\n",
            [("return runpy.run_path(str(path))", "explore_runs")],
            id="metoda",
        ),
        pytest.param(
            "load = lambda path: runpy.run_path(str(path))\nload(EXPLORER)\n",
            [("load = lambda path: runpy.run_path(str(path))", "explore_runs")],
            id="lambda",
        ),
        *(
            pytest.param(f"{call}\n", [(call, "explore_runs")], id=call.partition("(")[0])
            for call in [
                "__import__('explore_runs')",
                "importlib.__import__('explore_runs')",
                "importlib.util.find_spec('explore_runs')",
                "importlib.machinery.SourceFileLoader('explore_runs', str(EXPLORER)).load_module()",
                "importlib.machinery.SourcelessFileLoader('m', 'scripts/explore_runs.pyc').load_module()",
                "pytest.importorskip('scripts.explore_runs')",
                "compile(EXPLORER.read_text(), str(EXPLORER), 'exec')",
                "eval(\"__import__('explore_runs')\")",
                "runpy.run_path('scripts/explore_runs.py')",
                "runpy.run_path('scripts\\\\explore_runs.py')",
                "importlib.import_module(EXPLORER.stem)",
            ]
        ),
        pytest.param("name, path = SCRIPT, EXPLORER\n_load(path)\n", [(HELPER, "explore_runs")], id="rozpakowanie"),
        pytest.param("path: Path = EXPLORER\n_load(path)\n", [(HELPER, "explore_runs")], id="przypisanie-z-adnotacja"),
        pytest.param("if (path := EXPLORER):\n    _load(path)\n", [(HELPER, "explore_runs")], id="walrus"),
        pytest.param(
            "def _run(*, path=EXPLORER):\n    return runpy.run_path(str(path))\n",
            [("return runpy.run_path(str(path))", "explore_runs")],
            id="domyslna-parametru-po-nazwie",
        ),
        pytest.param("path, name = SCRIPT, EXPLORER\n_load(path)\n", [], id="rozpakowanie-innej-nazwy"),
        pytest.param(
            "def _explorer():\n    return SCRIPTS / 'explore_runs.py'\nrunpy.run_path(str(_explorer()))\n",
            [("runpy.run_path(str(_explorer()))", "explore_runs")],
            id="sciezka-z-return-pomocnika",
        ),
        pytest.param(
            "explorer = lambda: EXPLORER\nrunpy.run_path(str(explorer()))\n",
            [("runpy.run_path(str(explorer()))", "explore_runs")],
            id="sciezka-z-lambdy",
        ),
        pytest.param(
            "@pytest.mark.parametrize('path', argvalues=[EXPLORER])\ndef test_w_procesie(path):\n    _load(path)\n",
            [(HELPER, "explore_runs")],
            id="parametrize-argvalues",
        ),
        pytest.param("_load()\n_load(SCRIPT)\n", [], id="inny-skrypt-przez-ten-sam-pomocnik"),
        pytest.param("_load(EXPLORER.parent / 'sprawdz_model.py')\n", [], id="katalog-eksploratora"),
        pytest.param(
            "@pytest.mark.parametrize('path', [SCRIPT], ids=['explore_runs'])\ndef test_model(path):\n    _load(path)\n",
            [],
            id="ids-parametrize",
        ),
        pytest.param(
            "subprocess.run([sys.executable, '-c', 'import explore_runs; explore_runs.main([])'], timeout=9)\n",
            [],
            id="kod-w-napisie-dla-subprocess",
        ),
        pytest.param("subprocess.run([sys.executable, str(EXPLORER)], timeout=9)\n", [], id="sciezka-dla-subprocess"),
        pytest.param(
            "def test_model():\n"
            "    path = SCRIPT\n"
            "    def inner():\n"
            "        path = EXPLORER\n"
            "        return path\n"
            "    runpy.run_path(str(path))\n",
            [],
            id="ta-sama-nazwa-w-zagniezdzonej-funkcji",
        ),
        pytest.param(
            "path = SCRIPT\npath = path.with_suffix('.txt')\nrunpy.run_path(str(path))\n", [], id="nazwa-z-samej-siebie"
        ),
        pytest.param(
            "def _again(path):\n    return _again(path)\nrunpy.run_path(str(_again(SCRIPT)))\n", [], id="rekurencja"
        ),
    ],
)
def test_wczytanie_eksploratora_w_procesie_testu_to_import_albo_loader_z_jego_nazwa(
    tmp_path: Path, test: str, loads: list[tuple[str, str]]
) -> None:
    (tmp_path / "conftest.py").write_text(CONFTEST, encoding="utf-8")
    module = tmp_path / "test_przyklad.py"
    module.write_text(f"{PRELUDE}\n{test}", encoding="utf-8")

    lines = module.read_text(encoding="utf-8").splitlines()
    found = [(lines[line - 1].strip(), explorer) for path, line, _, explorer in _in_process(tmp_path) if path == module.name]

    assert found == loads


def test_fixtura_z_conftest_tego_katalogu_i_katalogu_nad_nim_podaje_sciezke_eksploratora(tmp_path: Path) -> None:
    test = "import runpy\ndef test_w_procesie(explorer_path):\n    runpy.run_path(explorer_path)\n"
    (tmp_path / "pakiet").mkdir()
    (tmp_path / "conftest.py").write_text(CONFTEST, encoding="utf-8")
    (tmp_path / "_test_przed_conftest.py").write_text(test, encoding="utf-8")
    (tmp_path / "pakiet" / "test_przyklad.py").write_text(test, encoding="utf-8")

    assert _in_process(tmp_path) == [
        ("_test_przed_conftest.py", 3, "runpy.run_path(…)", "explore_outbox"),
        ("conftest.py", 10, "importlib.import_module(…)", "explore_runs"),
        ("pakiet/test_przyklad.py", 3, "runpy.run_path(…)", "explore_outbox"),
    ]


def _violations(tests: Path) -> list[str]:
    """Wczytania eksploratora spoza ``IN_PROCESS_EXPLORERS`` w module pod ``tests`` i wpisy, których nic nie wczytuje."""

    found, excepted = [], set()
    for path, line, shape, explorer in _in_process(tests):
        if explorer in IN_PROCESS_EXPLORERS:
            excepted.add(explorer)
        else:
            found.append(f"{tests.name}/{path}:{line}: {shape} wczytuje {explorer} w procesie testu")
    return found + [
        f"IN_PROCESS_EXPLORERS: {explorer} nie jest już wczytany w procesie testu, usuń wpis"
        for explorer in sorted(IN_PROCESS_EXPLORERS.keys() - excepted)
    ]


@pytest.mark.parametrize(
    ("modules", "violations"),
    [
        pytest.param(
            {"test_a.py": "import explore_runs\n", "test_b.py": "import explore_publication\n"},
            ["tests/test_a.py:1: import explore_runs wczytuje explore_runs w procesie testu"],
            id="wyjatek-i-wczytanie-spoza-wyjatkow",
        ),
        pytest.param(
            {"test_a.py": "import subprocess\n"},
            ["IN_PROCESS_EXPLORERS: explore_publication nie jest już wczytany w procesie testu, usuń wpis"],
            id="wpis-bez-wczytania",
        ),
    ],
)
def test_wczytanie_spoza_wyjatkow_i_wpis_wyjatku_bez_wczytania_to_bledy(
    tmp_path: Path, modules: dict[str, str], violations: list[str]
) -> None:
    (tmp_path / "tests").mkdir()
    for name, text in modules.items():
        (tmp_path / "tests" / name).write_text(text, encoding="utf-8")

    assert _violations(tmp_path / "tests") == violations


def test_eksplorator_przeplotow_biegnie_we_wlasnym_procesie_testu_z_limitem() -> None:
    """Eksplorator przeplotów skilla ``verify-*`` (``.agents/skills/*/scripts/explore_*.py``) biegnie w teście przez
    ``subprocess`` z limitem, a test nie wczytuje jego modułu w procesie pytest.

    Wątek modelu, który czeka na prawdziwą blokadę spoza modelu, staje na zawsze, a eksplorator porzuca go razem z tą
    blokadą. W workerze pytest stawał wtedy każdy następny test Centrum, który brał tę blokadę, a sesja wisiała bez
    linii LUKA (#651, przegląd #660 rundy 1 i 2). Objaw widać tylko przy defekcie, więc żaden zielony test go nie
    pokaże. Sprawdzenie czyta AST modułów ``tests/`` (``_Loads``, tam też granica tego, czego nie widzi) i szuka
    wczytania modułu, nie wywołania ``explore`` albo ``main``: moduł, którego nie ma w procesie, nie biegnie w nim
    żadną drogą. Wyjątki są w ``IN_PROCESS_EXPLORERS`` z powodem.
    """

    found = _violations(TESTS)

    assert not found, "\n".join(
        [
            *found,
            "Uruchom eksplorator we własnym procesie z limitem poniżej limitu pytest, jak _in_own_process w "
            "tests/test_jedno_uruchomienie_naraz.py (skrypt w -c albo ścieżka do explore_*.py), i sprawdź kod wyjścia "
            "i linie wyjścia; eksplorator, który nie może porzucić wątku, wpisz do IN_PROCESS_EXPLORERS z powodem.",
        ]
    )

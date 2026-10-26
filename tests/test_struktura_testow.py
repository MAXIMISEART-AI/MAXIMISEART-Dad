"""Struktura testów: moduły niczego nie eksportują, a test czeka na stan, mierzy czas bez stałej liczby sekund i nie daje odpowiedzi krótkiego limitu czasu.

Wspólne dane i pomocniki są w ``tests.fixtures``.
"""

from __future__ import annotations

import ast
from collections.abc import Iterable, Iterator
from itertools import pairwise
from operator import add, mul, sub, truediv
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
        enclosing = _enclosing(call, parents)
        faked = any(isinstance(node, Definition) and _handed_over(node, tree, parents) for node in enclosing)
        if not (_polling(enclosing, names) or faked):
            yield call, _function(enclosing)


def _enclosing(node: ast.AST, parents: dict[ast.AST, ast.AST]) -> list[ast.AST]:
    enclosing = []
    while node in parents:
        node = parents[node]
        enclosing.append(node)
    return enclosing


def _polling(enclosing: list[ast.AST], names: dict[str, str]) -> bool:
    """Wewnątrz pętli (``while`` albo ``for``), która pyta zegar (``time.monotonic()``) o termin."""

    return any(
        isinstance(loop, (ast.While, ast.For))
        and any(isinstance(asked, ast.Call) and dotted(asked.func, names, "") in CLOCKS for asked in ast.walk(loop))
        for loop in enclosing
    )


def _function(enclosing: list[ast.AST]) -> str:
    functions = [node for node in enclosing if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))]
    return functions[0].name if functions else "<moduł>"


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
    """Każda wartość przypisana nazwie w tych węzłach; ``None``, gdy nazwę wiąże coś innego niż przypisanie.

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


SHORT_TIMEOUT_S = 10
MANUAL_CLOCK = "tests.fixtures.clock.ManualClock"
SHORT_TIMEOUTS = {
    "test_aktualnosc_narzedzia.py::test_milczacy_serwer_nie_wydluza_diagnozy_ponad_limit_czasu"
    "::releases_from(f'http://127.0.0.1:{silent.getsockname()[1]}/tagi', timeout_s=0.3)": (
        "test sprawdza sam limit: serwer nie odpowiada nigdy, więc pytanie kończy tylko limit 0,3 s, a wpis w "
        "CONSTANT_TIME_BOUNDS pilnuje, że diagnoza nie czeka dłużej"
    ),
    "test_centrum_zgloszenie.py::test_zatrzymanie_centrum_czeka_na_kazdy_jego_watek_takze_sprzed_ponownego_startu_a_drugie_nic_nie_robi"
    "::centrum.client.stop(timeout_s=0)": (
        "test sprawdza sam limit: wątek skrzynki trzyma hold, którego test nie zwolni przed tym stop, więc stop ma paść "
        "po limicie, a limit 0 s robi to od razu"
    ),
    "test_centrum_zgloszenie.py::test_zatrzymanie_centrum_nie_czeka_na_budzik_centrum_poprzedniego_testu_nastawiony_po_jego_starcie"
    "::started.client.stop(timeout_s=0)": (
        "test sprawdza sam limit: budzik poprzedniego testu nie kończy się nigdy, a test sprawdził, że Centrum nie ma "
        "już wątków, więc każde czekanie na budzik wywraca test, a limit 0 s robi to od razu"
    ),
    "test_potomne.py::test_po_limicie_drzewo_ginie_a_run_rzuca_timeout"
    "::potomne.run(with_grandchild(beats, 'time.sleep(60)'), cwd=tmp_path, timeout=5)": (
        "test sprawdza sam limit: dziecko śpi 60 s, więc limit 5 s kończy polecenie zawsze"
    ),
    "test_potomne.py::test_wnuk_uruchomiony_zanim_narzedzie_wroci_ze_startu_polecenia_ginie_z_drzewem"
    "::potomne.run(with_grandchild(beats, 'time.sleep(60)'), cwd=tmp_path, timeout=5)": (
        "test sprawdza sam limit: dziecko śpi 60 s, więc limit 5 s kończy polecenie zawsze"
    ),
}
FUNCTION_SCOPES = (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)
ARITHMETIC = {ast.Add: add, ast.Sub: sub, ast.Mult: mul, ast.Div: truediv}
Scope = dict[str, list[ast.expr | None]]


def _scope(scope: ast.AST) -> Iterator[ast.AST]:
    """Węzły zasięgu nazw (modułu albo funkcji z jej parametrami) bez funkcji zagnieżdżonych, które mają własny."""

    for child in ast.iter_child_nodes(scope):
        yield child
        if not isinstance(child, FUNCTION_SCOPES):
            yield from _scope(child)


def _manual_clocks(nodes: list[ast.AST], names: dict[str, str]) -> set[str]:
    """Nazwy podróbki zegara w zasięgu: przypisane ``ManualClock(...)`` albo parametry z adnotacją ``ManualClock``."""

    if MANUAL_CLOCK not in names.values():
        return set()

    def made(value: ast.expr | None) -> bool:
        return isinstance(value, ast.Call) and dotted(value.func, names, "") == MANUAL_CLOCK

    annotated = {
        node.arg
        for node in nodes
        if isinstance(node, ast.arg) and node.annotation is not None and dotted(node.annotation, names, "") == MANUAL_CLOCK
    }
    return annotated | {name for name, values in _bindings(nodes).items() if any(made(value) for value in values)}


def _visible(name: str, scopes: list[Scope]) -> list[ast.expr | None]:
    """Wartości nazwy z najbliższego zasięgu, który ją wiąże; ``[None]``, gdy żaden."""

    return next((scope[name] for scope in scopes if name in scope), [None])


def _seconds(
    expression: ast.expr, scopes: list[Scope], names: dict[str, str], seen: frozenset[str] = frozenset()
) -> float | None:
    """Liczba sekund znana przed uruchomieniem: literał, ``+``, ``-``, ``*`` albo ``/`` na takich liczbach,
    ``float(...)`` albo ``int(...)`` z takiej liczby albo z napisu i nazwa, którą najbliższy zasięg wiąże tylko z takimi
    liczbami (najmniejsza z nich)."""

    if isinstance(expression, ast.Constant):
        value = expression.value
        return value if isinstance(value, (int, float)) and not isinstance(value, bool) else None
    if isinstance(expression, ast.BinOp) and type(expression.op) in ARITHMETIC:
        left = _seconds(expression.left, scopes, names, seen)
        right = _seconds(expression.right, scopes, names, seen)
        if left is None or right is None or (isinstance(expression.op, ast.Div) and right == 0):
            return None
        return float(ARITHMETIC[type(expression.op)](left, right))
    if (
        isinstance(expression, ast.Call)
        and dotted(expression.func, names, "") in {".float", ".int"}
        and len(expression.args) == 1
        and not expression.keywords
    ):
        (argument,) = expression.args
        if isinstance(argument, ast.Constant) and isinstance(argument.value, str):
            try:
                return float(argument.value)
            except ValueError:
                return None
        return _seconds(argument, scopes, names, seen)
    if isinstance(expression, ast.Name) and expression.id not in seen:
        found = [
            None if value is None else _seconds(value, scopes, names, seen | {expression.id})
            for value in _visible(expression.id, scopes)
        ]
        known = [seconds for seconds in found if seconds is not None]
        return min(known) if len(known) == len(found) else None
    return None


def _named(
    keywords: list[ast.keyword], scopes: list[Scope], names: dict[str, str], seen: frozenset[str] = frozenset()
) -> Iterator[tuple[str, ast.expr]]:
    """Argumenty nazwane, także rozpakowane ``**`` ze słownika: literału, ``dict(...)`` albo nazwy, którą najbliższy
    zasięg wiąże z jednym z nich."""

    for keyword in keywords:
        if keyword.arg is not None:
            yield keyword.arg, keyword.value
            continue
        unpacked = keyword.value
        if isinstance(unpacked, ast.Dict):
            for key, value in zip(unpacked.keys, unpacked.values, strict=True):
                if isinstance(key, ast.Constant) and isinstance(key.value, str):
                    yield key.value, value
        elif isinstance(unpacked, ast.Call) and dotted(unpacked.func, names, "") == ".dict":
            yield from _named(unpacked.keywords, scopes, names, seen)
        elif isinstance(unpacked, ast.Name) and unpacked.id not in seen:
            for binding in _visible(unpacked.id, scopes):
                if binding is not None:
                    yield from _named([ast.keyword(value=binding)], scopes, names, seen | {unpacked.id})


def _short_timeouts(tree: ast.Module) -> Iterator[tuple[ast.Call, float, str]]:
    """Wywołanie z limitem czasu krótszym niż ``SHORT_TIMEOUT_S`` w argumencie nazwanym ``timeout``, ``timeout_s``
    albo ``*_timeout*`` (bez względu na wielkość liter), z tym limitem i nazwą funkcji, w której jest.

    Limit to liczba, którą ``_seconds`` zna przed uruchomieniem, a argument nazwany przychodzi też z ``**`` (``_named``).
    Limit nie liczy się, gdy to samo wywołanie dostaje podróbkę zegara (``ManualClock(...)`` albo nazwę, którą zasięg
    wywołania wiąże z nią, także parametr z adnotacją), bo czas przesuwa wtedy test, i gdy stoi w pętli, która pyta
    zegar o termin, bo kończy wtedy tylko jedną próbę. Znana granica, bo wymaga analizy przepływu danych: limit z
    innego modułu, z atrybutu albo z wywołania innego niż ``float``/``int``, argument pozycyjny (``thread.join(2)``),
    wartość domyślna parametru pomocnika (``def _get(port, timeout=1)``), ``**`` z czegoś innego niż słownik z
    literału, ``dict(...)`` i nazwy oraz pętla, która woła zegar, ale nie porównuje go z terminem.
    """

    names = imports(tree)
    parents = {child: node for node in ast.walk(tree) for child in ast.iter_child_nodes(node)}
    bound: dict[ast.AST, Scope] = {}
    clocks: dict[ast.AST, set[str]] = {}
    for call in ast.walk(tree):
        if not (
            isinstance(call, ast.Call)
            and any(keyword.arg is None or "timeout" in keyword.arg.lower() for keyword in call.keywords)
            and dotted(call.func, names, "") != ".dict"
        ):
            continue
        enclosing = _enclosing(call, parents)
        within = [node for node in enclosing if isinstance(node, (*FUNCTION_SCOPES, ast.Module))]
        for scope in within:
            if scope not in bound:
                nodes = list(_scope(scope))
                bound[scope], clocks[scope] = _bindings(nodes), _manual_clocks(nodes, names)
        scopes = [bound[scope] for scope in within]
        named = list(_named(call.keywords, scopes, names))
        limits = [
            seconds
            for argument, value in named
            if "timeout" in argument.lower() and (seconds := _seconds(value, scopes, names)) is not None
        ]
        clocked = any(
            (isinstance(value, ast.Call) and dotted(value.func, names, "") == MANUAL_CLOCK)
            or (
                isinstance(value, ast.Name)
                and value.id in next((clocks[scope] for scope in within if value.id in bound[scope]), set())
            )
            for value in [*call.args, *(value for _, value in named)]
        )
        if limits and min(limits) < SHORT_TIMEOUT_S and not (clocked or _polling(enclosing, names)):
            yield call, min(limits), _function(enclosing)


def _short_timeout_findings(trees: dict[str, ast.Module], exceptions: dict[str, str]) -> list[str]:
    """Krótkie limity spoza ``exceptions`` i nieaktualne wpisy; wpis obejmuje jedno wywołanie, więc drugie takie samo
    w tej funkcji też jest trafieniem."""

    found, excepted = [], set()
    for name, tree in trees.items():
        for call, limit, function in _short_timeouts(tree):
            key = f"{name}::{function}::{ast.unparse(call)}"
            if key in exceptions and key not in excepted:
                excepted.add(key)
            else:
                found.append(f"tests/{name}:{call.lineno}: {ast.unparse(call)} czeka najwyżej {limit} s ({key})")
    return found + [
        f"SHORT_TIMEOUTS: {key} nie ma już krótkiego limitu, usuń wpis" for key in sorted(exceptions.keys() - excepted)
    ]


def test_odpowiedz_nie_ma_krotszego_limitu_czasu_niz_10_s() -> None:
    trees = {
        path.relative_to(TESTS).as_posix(): ast.parse(path.read_text(encoding="utf-8"))
        for path in sorted(TESTS.rglob("*.py"))
    }
    found = _short_timeout_findings(trees, SHORT_TIMEOUTS)

    assert not found, "\n".join(
        [
            *found,
            f"Na wolnym runnerze odpowiedź przychodzi po krótkim limicie. Gdy ktoś odpowie, daj limit co najmniej "
            f"{SHORT_TIMEOUT_S} s (dłuższy wydłuża tylko porażkę); gdy limit liczy zegar kodu pod testem, daj temu "
            "wywołaniu ManualClock z tests/fixtures/clock.py; gdy test sprawdza sam limit, bo nikt nie odpowie przed "
            "nim, wpisz wywołanie do SHORT_TIMEOUTS pod kluczem z nawiasu, z powodem.",
        ]
    )


ZEGAR = f"from {MANUAL_CLOCK.rpartition('.')[0]} import ManualClock\n"


@pytest.mark.parametrize(
    ("source", "flagged"),
    [
        ("releases_from(api, timeout_s=2)", ["releases_from(api, timeout_s=2)"]),
        ("urlopen(url, connect_timeout=0.3)", ["urlopen(url, connect_timeout=0.3)"]),
        ("connect(api, connectTimeout=2)", ["connect(api, connectTimeout=2)"]),
        ("functools.partial(urlopen, timeout=2)", ["functools.partial(urlopen, timeout=2)"]),
        ("run(command, timeout=30, read_timeout=2)", ["run(command, timeout=30, read_timeout=2)"]),
        (
            "a(timeout=2 * 1)\nb(timeout=0.5 + 0)\nc(timeout=12 - 5)\nd(timeout=20 / 4)",
            ["a(timeout=2 * 1)", "b(timeout=0.5 + 0)", "c(timeout=12 - 5)", "d(timeout=20 / 4)"],
        ),
        (
            "a(timeout=float('2'))\nb(timeout=int(2))\nc(timeout=float('dwa'))\nd(timeout=1 / 0)",
            ["a(timeout=float('2'))", "b(timeout=int(2))"],
        ),
        (
            "def test_a():\n    limit = 2\n    a(timeout_s=limit)\n"
            "def test_b():\n    limit = 30\n    limit = 3\n    b(timeout_s=limit)\n"
            "def test_c():\n    limit = 2\n    limit = wylicz()\n    c(timeout_s=limit)\n"
            "def test_d():\n    limit = 2\n    limit += 1\n    d(timeout_s=limit)",
            ["a(timeout_s=limit)", "b(timeout_s=limit)"],
        ),
        ("LIMIT = 2\ndef test_a():\n    ask(timeout_s=LIMIT)", ["ask(timeout_s=LIMIT)"]),
        (
            "limit = 2\ndef test_a(limit):\n    ask(timeout_s=limit)\ndef test_b():\n    limit = 30\n    ask(timeout_s=limit)",
            [],
        ),
        (
            "a(api, **{'timeout_s': 2})\nb(api, **dict(timeout=2))\noptions = {'timeout': 2}\nc(url, **options)",
            ["a(api, **{'timeout_s': 2})", "b(api, **dict(timeout=2))", "c(url, **options)"],
        ),
        ("def test_a(options):\n    a(url, **options)\ndef test_b():\n    options = options\n    b(url, **options)", []),
        ("releases_from(api, timeout_s=30)", []),
        ("run(command, timeout=True)", []),
        (f"{ZEGAR}watch(clock=ManualClock(), timeout_s=2)", []),
        (f"{ZEGAR}def test_a():\n    clock = ManualClock()\n    watch(clock, timeout_s=2)", []),
        (f"{ZEGAR}def test_a(clock: ManualClock) -> None:\n    watch(clock=clock, timeout_s=2)", []),
        (f"{ZEGAR}def test_a(clock: ManualClock, port: int) -> None:\n    watch(port, timeout_s=2)", ["watch(port, timeout_s=2)"]),
        (
            f"{ZEGAR}def test_a(clock: ManualClock) -> None:\n    watch(clock, timeout_s=2)\n"
            "def test_b(clock) -> None:\n    ask(clock, timeout_s=2)\n"
            "def test_c() -> None:\n    pytaj(clock, timeout_s=2)",
            ["ask(clock, timeout_s=2)", "pytaj(clock, timeout_s=2)"],
        ),
        (f"{ZEGAR}clock = ManualClock()\ndef test_a(clock) -> None:\n    ask(clock, timeout_s=2)", ["ask(clock, timeout_s=2)"]),
        ("import time\nwhile time.monotonic() < deadline:\n    urlopen(url, timeout=1)", []),
        ("import time\nfor _ in range(9):\n    if time.monotonic() > deadline:\n        break\n    urlopen(url, timeout=1)", []),
    ],
    ids=[
        "literal",
        "nazwa-z-timeout",
        "wielka-litera",
        "partial",
        "drugi-argument",
        "dzialania",
        "float-int",
        "zmienna",
        "stala-modulu",
        "parametr-i-inny-zasieg",
        "rozpakowanie",
        "rozpakowanie-parametru",
        "dlugi",
        "nie-liczba",
        "zegar",
        "zegar-z-nazwy",
        "zegar-z-parametru",
        "inny-parametr-z-adnotacja",
        "zegar-innego-testu",
        "zegar-przesloniety-parametrem",
        "petla-while",
        "petla-for",
    ],
)
def test_regula_krotkiego_limitu_czasu(source: str, flagged: list[str]) -> None:
    assert [ast.unparse(call) for call, _, _ in _short_timeouts(ast.parse(source))] == flagged


def test_wyjatek_krotkiego_limitu_obejmuje_jedno_wywolanie_w_funkcji_w_ktorej_stoi() -> None:
    source = (
        "def test_a():\n"
        "    def ask():\n"
        "        urlopen(url, timeout=1)\n"
        "        urlopen(url, timeout=1)\n"
        "    urlopen(url, timeout=2)\n"
    )
    exceptions = {"test_x.py::ask::urlopen(url, timeout=1)": "powód", "test_x.py::test_a::urlopen(url, timeout=5)": "powód"}

    assert _short_timeout_findings({"test_x.py": ast.parse(source)}, exceptions) == [
        "tests/test_x.py:5: urlopen(url, timeout=2) czeka najwyżej 2 s (test_x.py::test_a::urlopen(url, timeout=2))",
        "tests/test_x.py:4: urlopen(url, timeout=1) czeka najwyżej 1 s (test_x.py::ask::urlopen(url, timeout=1))",
        "SHORT_TIMEOUTS: test_x.py::test_a::urlopen(url, timeout=5) nie ma już krótkiego limitu, usuń wpis",
    ]

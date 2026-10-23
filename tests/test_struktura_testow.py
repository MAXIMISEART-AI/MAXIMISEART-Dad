"""Struktura testów: moduły niczego nie eksportują, a test czeka na stan, nie stałą liczbę sekund.

Wspólne dane i pomocniki są w ``tests.fixtures``.
"""

from __future__ import annotations

import ast
from collections.abc import Iterator
from pathlib import Path

from tests.fixtures.skladnia import dotted, imports

TESTS = Path(__file__).resolve().parent
CLOCKS = frozenset({"time.monotonic", "time.perf_counter"})
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

    assert imports == set()


Definition = ast.Lambda | ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef


def _is_sleep(call: ast.Call, names: dict[str, str]) -> bool:
    """``time.sleep`` pod każdą nazwą z importu i czekanie na nowe ``threading.Event``, którego nikt nie ustawi."""

    function = call.func
    return dotted(function, names, "") == "time.sleep" or (
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

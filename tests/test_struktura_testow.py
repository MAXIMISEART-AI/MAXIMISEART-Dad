"""Struktura testów: moduły niczego nie eksportują, a test czeka na stan, nie stałą liczbę sekund.

Wspólne dane i pomocniki są w ``tests.fixtures``.
"""

from __future__ import annotations

import ast
from collections.abc import Iterator
from pathlib import Path

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


def _fixed_sleeps(tree: ast.Module) -> Iterator[tuple[ast.Call, str]]:
    """Sen poza pętlą z terminem, lambdą i funkcją wewnętrzną, z nazwą funkcji, w której jest.

    Pętla ma termin, gdy jej warunek albo ciało pyta zegar (``time.monotonic()``). Lambda i funkcja
    wewnętrzna to podróbka, której sen udaje czas pracy kodu pod testem.
    """

    sleep = {"time.sleep"} | {
        alias.asname or alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module == "time"
        for alias in node.names
        if alias.name == "sleep"
    }
    parents = {child: node for node in ast.walk(tree) for child in ast.iter_child_nodes(node)}
    for call in ast.walk(tree):
        if not (isinstance(call, ast.Call) and ast.unparse(call.func) in sleep):
            continue
        enclosing: list[ast.AST] = []
        node: ast.AST = call
        while node in parents:
            node = parents[node]
            enclosing.append(node)
        functions = [node for node in enclosing if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))]
        polling = any(
            isinstance(loop, ast.While)
            and any(isinstance(asked, ast.Call) and ast.unparse(asked.func) in CLOCKS for asked in ast.walk(loop))
            for loop in enclosing
        )
        faked = len(functions) > 1 or any(isinstance(node, ast.Lambda) for node in enclosing)
        if not (polling or faked):
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
            "czas pracy podróbki śpi w lambdzie albo funkcji wewnętrznej, a czas symulowany w samym teście wpisz do "
            "SIMULATED_TIME z powodem.",
        ]
    )

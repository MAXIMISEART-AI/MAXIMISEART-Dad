"""Pełna nazwa wołanej funkcji po importach modułu, dla testów struktury: ``sp.run`` to ``subprocess.run``."""

from __future__ import annotations

import ast
from collections.abc import Mapping

__all__ = ["dotted", "imports"]


def imports(tree: ast.Module) -> dict[str, str]:
    """Nazwa, którą import wiąże w module, i pełna nazwa tego, co wskazuje."""

    names: dict[str, str] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                top = alias.name.partition(".")[0]
                names[alias.asname or top] = alias.name if alias.asname else top
        elif isinstance(node, ast.ImportFrom) and node.module is not None:
            names |= {alias.asname or alias.name: f"{node.module}.{alias.name}" for alias in node.names}
    return names


def dotted(expression: ast.expr, names: Mapping[str, str], module: str) -> str | None:
    """``a.b.c`` z ``a`` rozwiniętym przez import; nazwa spoza importów należy do ``module``."""

    if isinstance(expression, ast.Name):
        return names.get(expression.id, f"{module}.{expression.id}")
    if isinstance(expression, ast.Attribute):
        owner = dotted(expression.value, names, module)
        return None if owner is None else f"{owner}.{expression.attr}"
    return None

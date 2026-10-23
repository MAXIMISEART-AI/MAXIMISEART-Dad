"""Skoroszyt zapisują tylko moduły zapisu, więc obie drogi zapisu dają ten sam plik (#282).

``workbook_files`` zapisuje openpyxl, ``template_copy`` kopiuje Wzorzec, a ``row_look`` daje obu ten sam
Wygląd Wiersza danych. Reszta ``src`` przekazuje im Wiersze danych, ale sama nie pisze do komórek ani plików.
"""

from __future__ import annotations

import ast
from pathlib import Path

SRC = Path(__file__).resolve().parents[1] / "src"
WRITERS = frozenset({"rozliczenia/workbook_files.py", "rozliczenia/template_copy.py", "rozliczenia/row_look.py"})
CELL_WRITES = frozenset(
    {"value", "font", "fill", "border", "alignment", "number_format", "protection", "hyperlink", "auto_filter"}
)
NOT_WORKBOOK_SAVES = {"phases.save": "PhaseRunner.save to etap Zapisywanie procesu; skoroszyt zapisuje w nim workbook_files"}


def test_zapis_skoroszytu_ma_jedno_miejsce() -> None:
    found, saves = [], set()
    for path in sorted(SRC.rglob("*.py")):
        name = path.relative_to(SRC).as_posix()
        if name in WRITERS:
            continue
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if (
                isinstance(node, ast.Attribute)
                and isinstance(node.ctx, ast.Store)
                and node.attr in CELL_WRITES
                and not (isinstance(node.value, ast.Name) and node.value.id == "self")
            ):
                found.append(f"src/{name}:{node.lineno}: przypisanie {ast.unparse(node)} pisze do skoroszytu")
            elif isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "save":
                if (called := ast.unparse(node.func)) in NOT_WORKBOOK_SAVES:
                    saves.add(called)
                else:
                    found.append(f"src/{name}:{node.lineno}: {called}(...) zapisuje skoroszyt")
    found += [f"NOT_WORKBOOK_SAVES: nikt nie woła {called}, usuń wpis" for called in sorted(NOT_WORKBOOK_SAVES.keys() - saves)]

    assert not found, "\n".join(
        [
            *found,
            "Wiersze danych zapisuj przez TemplateFile.create z workbook_files.py, a wygląd komórki przez RowLook z "
            "row_look.py; wywołanie .save, które nie zapisuje skoroszytu, wpisz do NOT_WORKBOOK_SAVES z powodem.",
        ]
    )

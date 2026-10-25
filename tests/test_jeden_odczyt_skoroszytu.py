"""Bajty skoroszytu z dysku czyta tylko ``_file_bytes``, więc plik bez dostępu jest niedostępny, a nie uszkodzony.

``_file_bytes`` (``workbook_files``) zamienia błąd systemu plików na ``Problem.INACCESSIBLE``, a ``_open`` otwiera
skoroszyt w openpyxl tylko z bajtów. Odczyt z dysku poza nimi trafia w klasyfikację uszkodzeń openpyxl, dla której
``OSError`` to plik nieczytelny, i tata dostaje Komunikat o uszkodzonym pliku, który jest cały.
"""

from __future__ import annotations

import ast
from pathlib import Path

SRC = Path(__file__).resolve().parents[1] / "src"
READS = {
    "read_bytes": "rozliczenia/workbook_files.py::_file_bytes",
    "load_workbook": "rozliczenia/workbook_files.py::_open",
}
NOT_WORKBOOKS = {
    "rozliczenia/centrum/keyed_box.py::read_report_key": "klucz Zgłoszeń to plik tekstowy; bez dostępu jest brakiem klucza",
}


def test_bajty_skoroszytu_czyta_z_dysku_tylko_file_bytes() -> None:
    found, excepted = [], set()
    for path in sorted(SRC.rglob("*.py")):
        name = path.relative_to(SRC).as_posix()
        tree = ast.parse(path.read_text(encoding="utf-8"))
        aliases: dict[str, str] = {
            alias.asname: alias.name
            for node in ast.walk(tree)
            if isinstance(node, ast.ImportFrom)
            for alias in node.names
            if alias.asname and alias.name in READS
        }
        owner = {
            node: function.name
            for function in ast.walk(tree)
            if isinstance(function, (ast.FunctionDef, ast.AsyncFunctionDef))
            for node in ast.walk(function)
        }
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            called = node.func.attr if isinstance(node.func, ast.Attribute) else getattr(node.func, "id", None)
            if called in aliases:
                called = aliases[called]
            if called not in READS:
                continue
            where = f"{name}::{owner.get(node, '<moduł>')}"
            if where == READS[called]:
                continue
            if where in NOT_WORKBOOKS:
                excepted.add(where)
            else:
                found.append(f"src/{name}:{node.lineno}: {ast.unparse(node.func)}(...) czyta plik z dysku w {where}")
    found += [f"NOT_WORKBOOKS: {where} nic już nie czyta, usuń wpis" for where in sorted(NOT_WORKBOOKS.keys() - excepted)]

    assert not found, "\n".join(
        [
            *found,
            "Bajty skoroszytu czytaj przez _file_bytes, a skoroszyt otwieraj przez _open z tych bajtów "
            "(workbook_files.py); plik, który nie jest skoroszytem, wpisz do NOT_WORKBOOKS z powodem.",
        ]
    )

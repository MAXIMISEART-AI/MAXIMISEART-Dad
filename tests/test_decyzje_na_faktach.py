"""Silnik decyduje na faktach planu, nie na kodzie Komunikatu (``CODING_STANDARDS.md``, Error Ownership).

Plan procesu oddaje typowane fakty, a jedno miejsce na proces tłumaczy je na ostrzeżenia, Zatrzymania, wynik i
Decyzję taty. Decyzja to porównanie (``==``, ``in``…) albo ``match`` z ``.code`` w wyrażeniu; zapis kodu do
metryk albo tekstu wyjątku decyzją nie jest. Centrum rozliczeń jest poza testem, bo jego wyniki Aktualizacji
narzędzia też mają pole ``code``, a nie są Komunikatami.

Granica: decyzję przez ``getattr``, słownik po kodzie albo w Centrum rozliczeń łapie tylko przegląd.
"""

from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ENGINE = ROOT / "src" / "rozliczenia"


def _reads_code(node: ast.AST) -> bool:
    return any(isinstance(inner, ast.Attribute) and inner.attr == "code" for inner in ast.walk(node))


def _decisions_on_code(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    decisions = [
        node
        for node in ast.walk(tree)
        if (isinstance(node, ast.Compare) and _reads_code(node))
        or (isinstance(node, ast.Match) and _reads_code(node.subject))
    ]
    return [f"src/rozliczenia/{path.name}:{node.lineno}: {ast.unparse(node).splitlines()[0]}" for node in decisions]


def test_silnik_nie_decyduje_na_kodzie_komunikatu() -> None:
    found = [decision for path in sorted(ENGINE.glob("*.py")) for decision in _decisions_on_code(path)]

    assert not found, "\n".join(
        [
            *found,
            "Silnik nie decyduje na kodzie Komunikatu: niech plan odda fakt (dataclass), a decyzja procesu weźmie ten "
            "fakt.",
        ]
    )

"""GLOSSARY.md jako jedno źródło języka domeny: każde hasło ma jedną definicję.

Każdy agent wczytuje GLOSSARY.md przez ``AGENTS.md``, więc zdublowane hasło
(np. po merge'u) kosztuje kontekst i może rozjechać definicje jednego terminu.
"""

from __future__ import annotations

from collections import Counter
from pathlib import Path


GLOSSARY = Path(__file__).resolve().parents[1] / "GLOSSARY.md"


def test_kazde_haslo_glossary_ma_jedna_definicje() -> None:
    terms = [
        line.removeprefix("## ").strip()
        for line in GLOSSARY.read_text(encoding="utf-8").splitlines()
        if line.startswith("## ")
    ]
    repeated = sorted(term for term, count in Counter(terms).items() if count > 1)

    assert terms
    assert repeated == []

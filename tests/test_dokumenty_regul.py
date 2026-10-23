"""Dokumenty z regułami łamią linie tylko na końcu zdania: zmiana jednego słowa zmienia jedną linię, nie cały akapit."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]
DOCUMENTS = ("AGENTS.md", "CODING_STANDARDS.md")
FENCE = ("```", "~~~")
BLOCK_START = re.compile(r"\s*(?:#|\||```|~~~|[-*+]\s|\d+\.\s)")
SENTENCE_END = re.compile(r"[.!?][)”\"*]*$")


def _lines_broken_mid_sentence(text: str) -> Iterator[int]:
    """Numery linii prozy, które kończą się w środku zdania, choć następna linia ciągnie ten sam akapit."""

    lines = text.splitlines()
    fenced = False
    for number, (line, following) in enumerate(zip(lines, [*lines[1:], ""]), start=1):
        if line.lstrip().startswith(FENCE):
            fenced = not fenced
        elif (
            not fenced
            and line.strip()
            and not line.lstrip().startswith("#")
            and following.strip()
            and not BLOCK_START.match(following)
            and not SENTENCE_END.search(line.rstrip())
        ):
            yield number


def test_dokument_regul_lamie_linie_tylko_na_koncu_zdania() -> None:
    broken = [
        f"{name}:{number}: linia kończy się w środku zdania, a linia {number + 1} ciągnie ten sam akapit"
        for name in DOCUMENTS
        for number in _lines_broken_mid_sentence((ROOT / name).read_text(encoding="utf-8"))
    ]

    assert not broken, "\n".join(
        [
            *broken,
            "Jedno zdanie na linię: dołącz następną linię do tej, a nową linię zaczynaj tylko od nowego zdania. "
            "Kolejne zdanie elementu listy idzie w nowej linii z wcięciem kontynuacji (dwie spacje po „- ”).",
        ]
    )


def test_sprawdzenie_pomija_kod_i_tabele_a_wskazuje_kazde_lamanie_w_srodku_zdania() -> None:
    document = "\n".join(
        [
            "# Nagłówek bez kropki",
            "Akapit łamany",
            "w środku zdania.",
            "Lista:",
            "- Element listy łamany",
            "  w środku zdania.",
            "  Drugie zdanie w nowej linii.",
            "- Element bez kropki",
            "1. Element numerowany bez kropki",
            "",
            "```",
            "polecenie --flaga",
            "  --druga-flaga",
            "```",
            "",
            "| kolumna | bez kropki |",
            "| --- | --- |",
            "",
            "Komunikat brzmi „Plik jest niedostępny.”",
            "(Całe zdanie w nawiasie.)",
            "Zdanie z pytaniem?",
            "Ostatnia linia bez kropki",
        ]
    )

    assert list(_lines_broken_mid_sentence(document)) == [2, 5]

"""Instrukcja dla taty a katalogi Komunikatów.

Każdy katalog (Przygotowanie pliku zbiorczego, Przebieg rozliczeń, start
Centrum rozliczeń, Diagnoza) ma w ``docs/tata-instrukcja.md`` swoją sekcję z tabelą,
której wiersze cytują faktyczną treść „Co się stało”. Jeden zestaw sprawdzeń
obejmuje każdy katalog: nowy katalog dostaje wszystkie sprawdzenia, gdy tylko
trafi do ``CATALOGS``. Zmiana treści Komunikatu bez poprawki instrukcji psuje
test. Cytaty z punktów sekcji „Gdy pojawi się problem” Przebiegu rozliczeń
też muszą odpowiadać treści Komunikatu: „Co się stało” albo linii terminala.
"""

from __future__ import annotations

from dataclasses import dataclass
import inspect
from pathlib import Path
import re
from types import ModuleType

import pytest

from rozliczenia import preparation_messages as messages
from rozliczenia import settlement_messages
from rozliczenia.centrum import diagnosis_messages, start_problems
from rozliczenia.message import Message

from tests.fixtures.message_samples import (
    ABOVE_CONFIG,
    DIAGNOSIS_SAMPLES,
    PREPARATION_SAMPLES,
    SETTLEMENT_SAMPLES,
    START_SAMPLES,
    Samples,
)


INSTRUCTION = Path(__file__).resolve().parents[1] / "docs" / "tata-instrukcja.md"
QUOTED = re.compile(r"„([^”]+)”")
# Pełna ścieżka zaczyna się literą dysku (C:\Dane, C:/Dane) albo jest ścieżką sieciową
# (\\nas\Wspolne, //nas/Wspolne); „//” po dwukropku to adres, nie ścieżka.
FULL_PATH = re.compile(r"(?<![A-Za-z])[A-Za-z]:[\\/]|(?<![:\\/])(?:\\\\|//)[^\\/\s]")

@dataclass(frozen=True)
class Catalog:
    """Katalog Komunikatów, jego sekcja w instrukcji i próbki każdej fabryki.

    ``terminal_only`` to fabryki, których Komunikatu tata nie widzi poza
    terminalem, więc instrukcja ich nie cytuje. ``hidden_folders`` to foldery
    ze ścieżek próbek leżące wyżej niż folder nadrzędny wskazywanego pliku albo
    folderu; trzy części Komunikatu ich nie pokazują.
    """

    module: ModuleType
    section: str
    samples: Samples
    terminal_only: frozenset[str] = frozenset()
    hidden_folders: frozenset[str] = ABOVE_CONFIG

    def factories(self) -> set[str]:
        return {
            name
            for name, function in inspect.getmembers(self.module, inspect.isfunction)
            if function.__module__ == self.module.__name__ and not name.startswith("_")
        }

    def messages(self) -> list[Message]:
        return [sample() for samples in self.samples.values() for sample in samples]


CATALOGS = {
    # Folder Dane i folder okresów INEA legalnie widać jako folder nadrzędny Rejestru zleceń i folderu okresu.
    "przygotowanie-pliku-zbiorczego": Catalog(messages, "### Komunikat → co zrobić", PREPARATION_SAMPLES),
    "przebieg-rozliczen": Catalog(
        settlement_messages,
        "### Komunikat w Centrum rozliczeń → co zrobić",
        SETTLEMENT_SAMPLES,
        # Tylko terminal: w Centrum Plik zbiorczy wynika z okresu, więc okna wyboru pliku nie ma.
        terminal_only=frozenset(
            {"collective_file_not_selected", "period_not_entered", "invalid_period_token", "period_folder_lookup_problem"}
        ),
        # Przebieg wskazuje najwyżej folder okresu, więc folderów nad nim nie widać.
        hidden_folders=ABOVE_CONFIG | {"Dane", "INEA"},
    ),
    "start-centrum-rozliczen": Catalog(start_problems, "### Komunikaty startu Centrum rozliczeń", START_SAMPLES),
    # Diagnoza wskazuje najwyżej Folder okresu, więc folderów nad nim nie widać.
    "diagnoza": Catalog(
        diagnosis_messages,
        "### Wyjaśnienie Diagnozy → co zrobić",
        DIAGNOSIS_SAMPLES,
        hidden_folders=ABOVE_CONFIG | {"Dane", "INEA"},
    ),
}

each_catalog = pytest.mark.parametrize("catalog", CATALOGS.values(), ids=CATALOGS.keys())


def _settlement_problem_quotes() -> list[str]:
    """Cytaty „…” z punktów sekcji „Gdy pojawi się problem” w części Przebiegu rozliczeń."""

    lines = INSTRUCTION.read_text(encoding="utf-8").splitlines()
    start = lines.index("### Gdy pojawi się problem", lines.index("## Przebieg rozliczeń"))
    quotes: list[str] = []
    for line in lines[start + 1 :]:
        if line.startswith("#"):
            break
        if line.startswith("- "):
            quotes.extend(QUOTED.findall(line))
    return quotes


def _instruction_fragments(section: str) -> list[str]:
    """Cytaty „…” z pierwszej kolumny tabel w sekcji instrukcji, razem z jej podsekcjami."""

    lines = INSTRUCTION.read_text(encoding="utf-8").splitlines()
    start = lines.index(section)
    level = section.split(" ", 1)[0]
    fragments: list[str] = []
    for line in lines[start + 1 :]:
        if line.startswith("#") and len(line.split(" ", 1)[0]) <= len(level):
            break
        if not line.startswith("|") or set(line) <= {"|", "-", " ", ":"}:
            continue
        first_cell = line.strip("|").split("|", 1)[0]
        fragments.extend(QUOTED.findall(first_cell))
    return fragments


@each_catalog
def test_probki_pokrywaja_kazda_fabryke_katalogu(catalog: Catalog) -> None:
    assert set(catalog.samples) | catalog.terminal_only == catalog.factories()


@each_catalog
def test_instrukcja_taty_objasnia_kazdy_komunikat_katalogu(catalog: Catalog) -> None:
    fragments = _instruction_fragments(catalog.section)
    unexplained = sorted(
        {message.code for message in catalog.messages() if not any(f in message.what for f in fragments)}
    )

    assert unexplained == []


@each_catalog
def test_kazdy_cytat_instrukcji_wskazuje_dokladnie_jeden_kod(catalog: Catalog) -> None:
    codes_per_fragment = {
        fragment: {message.code for message in catalog.messages() if fragment in message.what}
        for fragment in _instruction_fragments(catalog.section)
    }

    assert {fragment: codes for fragment, codes in codes_per_fragment.items() if len(codes) != 1} == {}


@each_catalog
def test_kazdy_kod_katalogu_ma_dokladnie_jeden_cytat_instrukcji(catalog: Catalog) -> None:
    """Jeden kod to jeden Komunikat: jego warianty objaśnia ten sam, jedyny cytat instrukcji.

    Razem z ``test_kazdy_cytat_instrukcji_wskazuje_dokladnie_jeden_kod`` pilnuje,
    że dwie fabryki o różnej treści nie dzielą kodu w obrębie katalogu.
    """

    fragments = _instruction_fragments(catalog.section)
    fragments_per_code: dict[str, set[str]] = {}
    for message in catalog.messages():
        fragments_per_code.setdefault(message.code, set()).update(f for f in fragments if f in message.what)

    assert {code: found for code, found in fragments_per_code.items() if len(found) != 1} == {}


def test_cytaty_sekcji_gdy_pojawi_sie_problem_odpowiadaja_komunikatom_przebiegu_rozliczen() -> None:
    texts = [
        text
        for message in CATALOGS["przebieg-rozliczen"].messages()
        for text in (message.what, message.terminal_line)
        if text is not None
    ]
    quotes = _settlement_problem_quotes()

    assert quotes
    assert [quote for quote in quotes if not any(quote in text for text in texts)] == []


@each_catalog
def test_komunikaty_katalogu_nie_maja_pelnych_sciezek(catalog: Catalog) -> None:
    shown = {
        message.code: part
        for message in catalog.messages()
        for part in (message.what, message.where, message.action)
        if FULL_PATH.search(part) or any(folder in part for folder in catalog.hidden_folders)
    }

    assert shown == {}

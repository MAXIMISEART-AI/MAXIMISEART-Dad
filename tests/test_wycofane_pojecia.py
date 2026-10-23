"""Pojęcia wycofane przez ADR-y nie wracają do kodu, frontendu, skilli ani dokumentacji.

ADR, który wycofał pojęcie, jest zapisem historii, tak jak starszy ADR, którego Status prowadzi do niego
odnośnikami do późniejszych ADR-ów. ``AGENTS.md``, ``CODING_STANDARDS.md`` i ``GLOSSARY.md`` nazywają wycofane
pojęcia, żeby ich zabronić, więc test ich nie czyta. Kod generowany z ``src`` (kontrakt, klient API, build
Centrum) sprawdza się w ``src``.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]
ADRS = ROOT / "docs" / "adr"
SCANNED = ("src", "frontend/src", ".agents/skills", "docs", "README.md", "requirements.txt")
GENERATED = ("src/rozliczenia/centrum/static/", "frontend/src/api/generated/", "frontend/src/api/openapi.json")
TEXT = frozenset({".py", ".md", ".ts", ".tsx", ".txt", ".tla", ".cfg"})


@dataclass(frozen=True)
class Retired:
    pattern: re.Pattern[str]
    adr: str
    today: str


RETIRED = (
    Retired(
        re.compile(r"\bCLI\b"),
        "0011",
        "procesy uruchamia Centrum rozliczeń, a testy i pomiary skrypt dla maszyn tools/uruchom_proces.py",
    ),
    Retired(re.compile(r"(?<![\w/-])[Tt]erminal\w*"), "0011", "Komunikat ma trzy części i pokazuje go Centrum rozliczeń"),
    Retired(re.compile(r"\bRich\b|^\s*(?:from|import)\s+rich\b|^rich\b"), "0011", "postęp pokazuje tylko Centrum rozliczeń"),
    Retired(
        re.compile(r"(?<![\w/.-])run(?:_preparation)?\.py\b"),
        "0011",
        "procesy uruchamia Centrum rozliczeń, a testy i pomiary skrypt dla maszyn tools/uruchom_proces.py",
    ),
    Retired(
        re.compile(r"(?:Utwórz rozliczenia|Przygotuj plik zbiorczy|Centrum rozliczeń \(konsola\)|Zainstaluj skrót Centrum rozliczeń)\.cmd"),
        "0010",
        "tata pracuje tylko w Centrum rozliczeń; konsola to py -3 run_centrum.py, a skrót instaluje py -3 install_centrum_shortcut.py",
    ),
)
OLD_RUNS = "odznaka .cmd oznacza stare Uruchomienia z dawnych launcherów i CLI (ADR 0011, „Historia bez zmian”)"
HISTORY = {
    ("README.md", "z dawnych launcherów i CLI"): OLD_RUNS,
    ("src/rozliczenia/centrum/contract.py", "z dawnych launcherów ``.cmd`` i CLI"): OLD_RUNS,
    ("src/rozliczenia/centrum/run_origins.py", "z dawnych launcherów i CLI"): OLD_RUNS,
    ("src/rozliczenia/centrum/tool_update.py", "terminala, bez pomocnika logowania"): "Git biegnie bez terminala",
    ("src/rozliczenia/centrum/tool_update.py", '"terminal prompts disabled"'): "tekst błędu Gita",
}


def _later_in_status(adr: Path) -> set[str]:
    """Późniejsze ADR-y, do których prowadzą odnośniki z sekcji Status."""

    status = adr.read_text(encoding="utf-8").split("## Status", 1)[-1].split("\n## ", 1)[0]
    return {number for number in re.findall(r"\((\d{4})-[^)]*\.md\)", status) if number > adr.name[:4]}


def _history_of(retiring: str, links: dict[str, set[str]]) -> set[str]:
    """ADR, który wycofał pojęcie, i ADR-y, których Status prowadzi do niego."""

    reaching = {retiring}
    while grown := {number for number, later in links.items() if later & reaching} - reaching:
        reaching |= grown
    return reaching


def _scanned_files() -> list[Path]:
    paths = [ROOT / name for name in SCANNED]
    return sorted(
        file
        for path in paths
        for file in (path.rglob("*") if path.is_dir() else [path])
        if file.suffix in TEXT
        and not any(part.endswith(".egg-info") or part == "__pycache__" for part in file.parts)
        and not file.relative_to(ROOT).as_posix().startswith(GENERATED)
    )


def test_wycofane_pojecia_nie_wracaja() -> None:
    links = {adr.name[:4]: _later_in_status(adr) for adr in ADRS.glob("[0-9][0-9][0-9][0-9]-*.md")}
    history = {retired.adr: _history_of(retired.adr, links) for retired in RETIRED}
    found, used = [], set()
    for file in _scanned_files():
        name = file.relative_to(ROOT).as_posix()
        adr = file.name[:4] if file.parent == ADRS else None
        for number, line in enumerate(file.read_text(encoding="utf-8").splitlines(), 1):
            for retired in RETIRED:
                match = retired.pattern.search(line)
                if match is None or adr in history[retired.adr]:
                    continue
                allowed = {key for key in HISTORY if key[0] == name and key[1] in line}
                used |= allowed
                if not allowed:
                    found.append(f"{name}:{number}: „{match.group().strip()}” wycofał ADR {retired.adr}; dziś {retired.today}")
    found += [f"HISTORY: {name} nie ma już „{snippet}”, usuń wpis" for name, snippet in sorted(HISTORY.keys() - used)]

    assert not found, "\n".join(
        [
            *found,
            "Opisz to, co jest dziś; zdanie o historii wpisz do HISTORY z powodem, a starszy ADR połącz w Statusie "
            "odnośnikiem z ADR-em, który wycofał pojęcie.",
        ]
    )

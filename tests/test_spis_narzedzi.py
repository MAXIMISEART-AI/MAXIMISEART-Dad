"""Blok ``## Narzędzia`` w ``AGENTS.md`` to spis narzędzi agenta: każde narzędzie z ``tools/`` z pierwszym zdaniem docstringu.

Spis jest w kontekście agenta od początku sesji, więc agent nie musi wiedzieć, że narzędzie istnieje, zanim go szuka.
W ``tools/`` leżą tylko narzędzia, które agent albo człowiek uruchamia; skrypty, które uruchamia workflow, leżą
w ``tools/ci/``, a moduły bez własnego wywołania w ``tools/lib/``, więc spis ich nie ma, a ``AGENTS.md`` i skille nie
wskazują ``tools/ci/``. Skrypt, który agent uruchamia sam według ``docs/agents/``, ``README.md`` albo docstringu
narzędzia (plan runu, odtworzenie części nocnych mutacji), leży w ``tools/``, bo inaczej spis go nie ma, a agent bierze
najbliższą pozycję spisu: polecenie ``python … tools/ci/…`` w tych dokumentach to błąd. Pierwsze zdanie docstringu (zarazem pierwsza linia ``--help``) mówi w jednej linii
``MIN_CHARS``–``MAX_CHARS`` znaków, co narzędzie robi i kiedy go użyć, a pierwsze ``SAME_WORDS`` słów odróżnia je od
każdego innego narzędzia. Blok między ``START`` i ``END`` zapisuje ten test z ``ZAPISZ_EXPECT=1``, jak plik expect.

Granica: test nie ocenia, czy zdanie mówi „kiedy” słowami sytuacji agenta (czerwone CI, przed merge'em); to łapie
tylko przegląd.
"""

from __future__ import annotations

import ast
from pathlib import Path
import re

from tests.fixtures.expect import assert_expected

ROOT = Path(__file__).resolve().parents[1]
AGENTS_MD = ROOT / "AGENTS.md"
TOOLS = ROOT / "tools"
SKILLS = ROOT / ".agents" / "skills"
AGENT_DOCS = [ROOT / "README.md", *sorted((ROOT / "docs" / "agents").glob("*.md"))]
START = "<!-- spis narzędzi: generuje tests/test_spis_narzedzi.py z ZAPISZ_EXPECT=1, nie edytuj ręcznie -->"
END = "<!-- koniec spisu narzędzi -->"
MIN_CHARS = 80
MAX_CHARS = 160
SAME_WORDS = 3
CI_TOOLS = "tools/ci/"
# Polecenie, które uruchamia skrypt z tools/ci/: interpreter (python3, .venv/bin/python, py -3) albo `--` przed nim.
RUNS_CI_TOOL = re.compile(r"(?:python[\d.]*|py -3|--)\s+tools/ci/")


def _tools() -> list[Path]:
    return sorted(TOOLS.glob("*.py"))


def _first_paragraph(path: Path) -> list[str]:
    docstring = ast.get_docstring(ast.parse(path.read_text(encoding="utf-8"))) or ""
    return docstring.split("\n\n", 1)[0].splitlines()


def _index() -> str:
    return "".join(f"- `{path.relative_to(ROOT).as_posix()}`: {' '.join(_first_paragraph(path))}\n" for path in _tools())


def test_spis_narzedzi_w_agents_md_to_pierwsze_zdania_narzedzi_z_tools() -> None:
    text = AGENTS_MD.read_text(encoding="utf-8")
    assert text.count(START) == 1 and text.count(END) == 1, f"AGENTS.md ma mieć raz linię {START!r} i raz {END!r}"
    before, rest = text.split(START + "\n")
    _, after = rest.split(END)

    assert_expected(f"{before}{START}\n{_index()}{END}{after}", AGENTS_MD)


def test_pierwsze_zdanie_narzedzia_to_jedna_linia_o_dlugosci_spisu() -> None:
    problems = []
    for path in _tools():
        paragraph = _first_paragraph(path)
        name = path.relative_to(ROOT).as_posix()
        if len(paragraph) != 1:
            problems.append(f"{name}: pierwszy akapit docstringu ma {len(paragraph)} linii, a ma mieć jedno zdanie w jednej")
        elif not MIN_CHARS <= len(paragraph[0]) <= MAX_CHARS or not paragraph[0].endswith("."):
            problems.append(f"{name}: pierwsze zdanie ma {len(paragraph[0])} znaków albo nie kończy się kropką")

    assert problems == [], "\n".join(
        [
            *problems,
            f"Zacznij docstring jednym zdaniem {MIN_CHARS}–{MAX_CHARS} znaków zakończonym kropką: co narzędzie robi i kiedy "
            "go użyć, słowami sytuacji agenta; szczegóły daj w następnych akapitach.",
        ]
    )


def test_pierwsze_slowa_odrozniaja_narzedzie_od_innych() -> None:
    by_start: dict[str, list[str]] = {}
    for path in _tools():
        words = " ".join(re.findall(r"\w+", " ".join(_first_paragraph(path)).lower())[:SAME_WORDS])
        by_start.setdefault(words, []).append(path.name)

    same = {start: names for start, names in by_start.items() if len(names) > 1}

    assert same == {}, f"te narzędzia zaczynają pierwsze zdanie tymi samymi {SAME_WORDS} słowami; powiedz od razu, czym się różnią: {same}"


def test_agents_md_ani_skill_nie_wskazuja_agentowi_skryptow_ci() -> None:
    documents = [AGENTS_MD, *sorted(SKILLS.glob("*/**/*.md"))]
    found = [
        f"{path.relative_to(ROOT).as_posix()}:{number}: {line.strip()}"
        for path in documents
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1)
        if CI_TOOLS in line
    ]

    assert found == [], "\n".join(
        [
            *found,
            f"Skrypty {CI_TOOLS} uruchamia workflow; agent odtwarza ich zadanie według docs/agents/pr-i-ci.md, więc AGENTS.md i "
            "skille wskazują narzędzie z tools/ albo nazywają zadanie CI.",
        ]
    )


def test_dokument_agenta_nie_kaze_mu_uruchamiac_skryptu_ci() -> None:
    documents = {path: path.read_text(encoding="utf-8") for path in AGENT_DOCS}
    documents |= {path: ast.get_docstring(ast.parse(path.read_text(encoding="utf-8"))) or "" for path in _tools()}
    found = [
        f"{path.relative_to(ROOT).as_posix()}: {line.strip()}"
        for path, text in documents.items()
        for line in text.splitlines()
        if RUNS_CI_TOOL.search(line)
    ]

    assert found == [], "\n".join(
        [
            *found,
            f"Agent uruchamia ten skrypt sam, więc przenieś go z {CI_TOOLS} do tools/ (wtedy trafi do spisu) "
            "albo każ agentowi użyć narzędzia z tools/, które go uruchamia.",
        ]
    )

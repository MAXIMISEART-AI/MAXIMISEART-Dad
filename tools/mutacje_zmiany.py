"""Psuje zmienione linie ``src/`` i sprawdza, że któryś test to zauważa, jak zadanie CI ``Change mutations``.

Zmiana to linie plików ``src/**/*.py``, którymi checkout (z niezacommitowanymi i nieśledzonymi plikami) różni się
od ``merge-base`` HEAD z ``--baza`` (domyślnie ``origin/main``). Na każdej zmienionej linii narzędzie robi mutacje,
które przeglądy PR-ów robiły ręcznie i które przeżywały testy:

- bez jednego członu ``and``/``or``;
- wyrażenie ``a if w else b`` zastąpione jedną gałęzią;
- ``True`` zamienione na ``False`` i odwrotnie;
- warunek ``if`` zawsze prawdziwy i zawsze fałszywy;
- granica porównania (``<`` i ``<=``, ``>`` i ``>=``);
- ``return wartość`` zamienione na ``return None``;
- wywołanie w osobnej linii usunięte;
- bez jednego elementu krotki, która nie jest samymi stałymi;
- fragment zmiany (hunk) cofnięty do bazy: test poprawki, który przechodzi bez niej, tu przeżywa.

Mutacja, która zmienia tylko docstringi, komentarze, adnotacje argumentów i wyników funkcji, importy albo aliasy
typów (``Nazwa = Callable[...]``, ``A | B`` czytane tylko w adnotacjach), nie zmienia zachowania, więc jej nie ma.
Dekoratorów narzędzie nie psuje, a samo usunięcie linii (bez linii dodanej w tym miejscu) nie daje mutacji.
Kod, którego na tym systemie strzeże ``sys.platform ==``/``!=`` literał, dostaje linię ``POMINIĘTA``: gałąź ``if``
albo ``… if … else …`` innego systemu, kod po ``if`` z takim warunkiem, którego ciało kończy się ``return``/``raise``
na tym systemie, i sam warunek. Kod tylko dla innego systemu w innej postaci (stała czytana tylko w jego gałęzi,
warunek przez ``startswith`` albo zmienną) przeżywa i potrzebuje wyjątku.

Najpierw biegną raz testy dotknięte zmianą, wybrane jak w ``tools/szybko.py``, z pluginem
``tools/pokrycie_linii.py``. Zapisuje on, które testy wykonują które zmienione linie i jakikolwiek kod zmienionych
plików, także w procesach Pythona uruchomionych przez test, oraz linie wykonane dla wielu testów naraz: przy imporcie
modułu i w fixture o zasięgu szerszym niż test. Testy muszą przejść, inaczej wynik mutacji niczego nie dowodzi.

Potem każda mutacja biegnie przez silnik ``tools/mutacje.py`` (własna kopia checkoutu), najpierw z testami, które
wykonały jej linie. Pokrycie tylko przyspiesza wykrycie: mutacja, która je przeżyła, biegnie drugi raz, po jednej
naraz z ``--rownolegle`` workerami xdist, i dopiero ta porażka daje ``NIEWYKRYTA``. Drugi raz biegną testy, które
wykonały jakikolwiek kod jej pliku albo uruchomiły proces (jego kodu zapis nie widzi, gdy proces ma ``-I``), a wszystkie
testy dotknięte plikiem, gdy linię wykonano dla wielu testów naraz
albo leży w funkcji z ``@cache``, ``@lru_cache`` albo ``@cached_property`` (wynik pierwszego wywołania dostają też
inne testy). Linia ``CZAS`` mówi, ile trwała każda faza.

Mutacja, która przeżywa, to obietnica bez testu: dopisz test, który ją wykrywa. Mutacja równoważna (kod robi to samo)
dostaje wyjątek w linii mutacji albo w samodzielnym komentarzu tuż nad nią:
``# mutacje-zmiany: <powód> | do RRRR-MM-DD | zgoda <kto>``. Wyjątek obejmuje każdą mutację tej linii; cofnięcie
fragmentu ma linię początku fragmentu, więc obejmuje je komentarz nad nim albo w jego pierwszej linii. Wyjątek po
terminie nie obowiązuje, ale narzędzie widzi go dopiero przy
następnej zmianie jego pliku, a komentarz ``mutacje-zmiany:`` w innej postaci kończy narzędzie błędem.

Kończy się ``MUTACJE ZMIANY OK | …`` albo ``MUTACJE ZMIANY FAIL | …``. Nie zastępuje mutacji z opisu PR: zachowanie,
którego żadna z tych mutacji nie psuje (np. inny klucz wyszukiwania), dalej sprawdza przegląd.

Poza CI biegnie tylko do odtworzenia porażki zadania z runu Actions tej gałęzi (``tools/ciezkie_ci.py``):

    .venv/bin/python tools/mutacje_zmiany.py --odtwarzam <id albo URL runu>
    .venv/bin/python tools/mutacje_zmiany.py --baza feat/galaz-rodzica --odtwarzam <id albo URL runu>

Z ``--czesc K/N`` biegnie co N-ta mutacja od K-tej w kolejności skrótów sha256 mutacji, więc N zadań CI dzieli mutacje
bez listy w ``ci.yml``, a sąsiednie mutacje jednego pliku nie trafiają systematycznie do jednej części.
"""

from __future__ import annotations

import argparse
import ast
from collections import defaultdict
from collections.abc import Iterator, Sequence
from dataclasses import dataclass, field
import datetime
import hashlib
import itertools
import json
import os
from pathlib import Path, PurePosixPath
import re
import subprocess
import sys
import tempfile
import time

import ciezkie_ci
import mutacje
import pokrycie_procesu
import potomne
import szybko

ROOT = Path(__file__).resolve().parents[1]
BASE = "origin/main"
WORKERS = 4
# Linia poleceń Windows ma najwyżej 32 767 znaków; dłuższa lista testów idzie jako pliki testów.
COMMAND_LIMIT = 20_000
EXCEPTION = re.compile(r"#\s*mutacje-zmiany:(?P<rest>.*)$")
EXCEPTION_FORM = re.compile(r"\s*(?P<reason>[^|]*\S)\s*\|\s*do\s+(?P<until>\d{4}-\d{2}-\d{2})\s*\|\s*zgoda\s+(?P<who>\S.*?)\s*$")
Node = ast.expr | ast.stmt
_HUNK = re.compile(r"^@@ -(?P<old>\d+)(?:,(?P<old_count>\d+))? \+(?P<new>\d+)(?:,(?P<new_count>\d+))? @@")


@dataclass(frozen=True)
class Mutant:
    path: str
    line: int  # linia, w której wyjątek wyłącza mutację
    lines: frozenset[int]  # zmienione linie, które mutacja psuje
    description: str
    source: str  # cały plik po mutacji
    other_system: bool = False  # kod gałęzi innego systemu niż ten, na którym biegną testy
    shared_state: bool = False  # kod funkcji z ``@cache``: wynik pierwszego wywołania dostają następne testy


@dataclass(frozen=True)
class Allowance:
    reason: str
    until: datetime.date
    who: str


@dataclass(frozen=True)
class Hunk:
    start: int  # pierwsza linia po zmianie; przy samym usunięciu linia, po której stały usunięte
    count: int
    old: tuple[str, ...]


def _git(*arguments: str) -> str:
    return subprocess.run(
        ["git", *arguments], cwd=ROOT, capture_output=True, text=True, encoding="utf-8", check=True
    ).stdout


def _short(text: str, limit: int = 60) -> str:
    flat = " ".join(text.split())
    return flat if len(flat) <= limit else f"{flat[: limit - 1]}…"


def _is_source(path: str) -> bool:
    pure = PurePosixPath(path)
    return pure.parts[0] == "src" and pure.suffix == ".py"


def changes(fork: str) -> dict[str, list[Hunk]]:
    """Fragmenty zmiany każdego pliku ``src/**/*.py`` istniejącego w checkoucie; nowy plik to jeden fragment."""

    found: dict[str, list[Hunk]] = defaultdict(list)
    current: str | None = None
    old_left = new_left = 0  # linie fragmentu, których parser jeszcze nie przeczytał: nie są nagłówkiem
    # Przeniesiony plik (``-M``) psuje tylko linie, które przy przeniesieniu się zmieniły.
    for line in _git("diff", "-U0", "-M", "--no-color", fork, "--", "src").split("\n"):
        if old_left and line.startswith("-"):
            old_left -= 1
            if current is not None:
                hunk = found[current][-1]
                found[current][-1] = Hunk(hunk.start, hunk.count, (*hunk.old, line[1:]))
        elif new_left and line.startswith("+"):
            new_left -= 1
        elif line.startswith("+++ "):
            name = line[4:]
            current = name[2:] if name.startswith("b/") and _is_source(name[2:]) else None
        elif match := _HUNK.match(line):
            old_left, new_left = int(match["old_count"] or 1), int(match["new_count"] or 1)
            if current is not None:
                found[current].append(Hunk(int(match["new"]), new_left, ()))
    for name in _git("ls-files", "--others", "--exclude-standard", "--", "src").splitlines():
        if _is_source(name):
            found[name] = [Hunk(1, len(_rows((ROOT / name).read_text(encoding="utf-8"))), ())]
    return {path: hunks for path, hunks in found.items() if (ROOT / path).is_file()}


def _rows(text: str) -> list[str]:
    """Linie z końcami, jak liczy je git: tylko ``\n`` kończy linię (``str.splitlines`` dzieli też na U+2028)."""

    rows = [f"{row}\n" for row in text.split("\n")]
    rows[-1] = rows[-1][:-1]
    return rows if rows[-1] else rows[:-1]


def changed_lines(hunks: Sequence[Hunk]) -> frozenset[int]:
    return frozenset(line for hunk in hunks for line in range(hunk.start, hunk.start + hunk.count))


class _Source:
    """Tekst pliku z wymianą fragmentu wskazanego pozycjami węzła AST (kolumny w bajtach UTF-8)."""

    def __init__(self, text: str) -> None:
        self.text = text
        self.lines = text.encode("utf-8").splitlines(keepends=True)
        self.starts = [0]
        for line in self.lines:
            self.starts.append(self.starts[-1] + len(line))
        self.data = text.encode("utf-8")

    def segment(self, node: Node) -> str:
        start, end = self._span(node)
        return self.data[start:end].decode("utf-8")

    def replaced(self, node: Node, replacement: str) -> str:
        start, end = self._span(node)
        return (self.data[:start] + replacement.encode("utf-8") + self.data[end:]).decode("utf-8")

    def _span(self, node: Node) -> tuple[int, int]:
        end_lineno = node.lineno if node.end_lineno is None else node.end_lineno
        end_col = node.col_offset if node.end_col_offset is None else node.end_col_offset
        return self.starts[node.lineno - 1] + node.col_offset, self.starts[end_lineno - 1] + end_col


def _span_lines(node: Node) -> frozenset[int]:
    return frozenset(range(node.lineno, (node.end_lineno or node.lineno) + 1))


def _skipped(tree: ast.AST) -> set[int]:
    """Węzły, których nie warto psuć: adnotacje typów, dekoratory, docstringi i bloki ``TYPE_CHECKING`` i ``__main__``."""

    skipped: set[int] = set()

    def skip(node: ast.AST | None) -> None:
        if node is not None:
            skipped.update(id(inner) for inner in ast.walk(node))

    for node in ast.walk(tree):
        if isinstance(node, (ast.AnnAssign, ast.arg)):
            skip(node.annotation)
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            skip(node.returns)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            # ``@dataclass(frozen=True)`` bez zamrożenia działa tak samo, dopóki nikt nie zmienia pola.
            for decorator in node.decorator_list:
                skip(decorator)
        elif isinstance(node, ast.If) and ast.unparse(node.test) in {
            "TYPE_CHECKING",
            "typing.TYPE_CHECKING",
            "__name__ == '__main__'",
        }:
            skip(node)
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)) and node.body:
            first = node.body[0]
            if isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant) and isinstance(first.value.value, str):
                skip(first)
    return skipped


def _platform_test(test: ast.expr) -> tuple[str, bool] | None:
    """``sys.platform == "x"`` daje ``("x", True)``, ``!=`` daje ``("x", False)``, inny warunek ``None``."""

    if not (isinstance(test, ast.Compare) and len(test.ops) == 1 and isinstance(test.ops[0], (ast.Eq, ast.NotEq))):
        return None
    right = test.comparators[0]
    if ast.unparse(test.left) != "sys.platform" or not (isinstance(right, ast.Constant) and isinstance(right.value, str)):
        return None
    return right.value, isinstance(test.ops[0], ast.Eq)


def _ends(body: list[ast.stmt]) -> bool:
    return bool(body) and isinstance(body[-1], (ast.Return, ast.Raise, ast.Continue, ast.Break))


def _other_system(tree: ast.AST, platform: str) -> set[int]:
    """Węzły kodu, który na systemie ``platform`` nie biegnie, bo strzeże go ``sys.platform ==``/``!=`` literał.

    To gałąź ``if`` i wyrażenia ``… if … else …`` dla innego systemu, kod po ``if`` z takim warunkiem, którego ciało
    kończy się ``return``/``raise`` na tym systemie, i sam warunek.
    """

    other: set[int] = set()

    def mark(nodes: list[ast.stmt] | list[ast.expr]) -> None:
        other.update(id(inner) for node in nodes for inner in ast.walk(node))

    for node in ast.walk(tree):
        if isinstance(node, (ast.If, ast.IfExp)) and (found := _platform_test(node.test)) is not None:
            literal, equal = found
            here = (platform == literal) == equal
            mark([node.test])
            if isinstance(node, ast.If):
                mark(node.orelse if here else node.body)
            else:
                mark([node.orelse if here else node.body])
        for name in ("body", "orelse", "finalbody"):
            block = getattr(node, name, None)
            if not isinstance(block, list):
                continue
            for index, statement in enumerate(block):
                guard = _platform_test(statement.test) if isinstance(statement, ast.If) else None
                if guard is not None and isinstance(statement, ast.If) and not statement.orelse and _ends(statement.body):
                    literal, equal = guard
                    if (platform == literal) == equal:
                        mark(block[index + 1 :])
    return other


_CACHES = frozenset({"cache", "lru_cache", "cached_property"})


def _cached_lines(tree: ast.AST) -> set[int]:
    """Linie funkcji z ``@cache``, ``@lru_cache`` albo ``@cached_property``."""

    found: set[int] = set()
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for decorator in node.decorator_list:
            target = decorator.func if isinstance(decorator, ast.Call) else decorator
            name = target.attr if isinstance(target, ast.Attribute) else target.id if isinstance(target, ast.Name) else ""
            if name in _CACHES:
                found |= _span_lines(node)
    return found


_BOUNDARY: dict[type[ast.cmpop], str] = {ast.Lt: "<=", ast.LtE: "<", ast.Gt: ">=", ast.GtE: ">"}


def _candidates(node: ast.AST, source: _Source) -> Iterator[tuple[Node, Node, str, str]]:
    """(węzeł do zastąpienia, węzeł, którego linie psuje mutacja, zamiana, opis) dla jednego węzła."""

    if isinstance(node, ast.BoolOp):
        word = "and" if isinstance(node.op, ast.And) else "or"
        for dropped in node.values:
            rest = [source.segment(value) for value in node.values if value is not dropped]
            yield node, dropped, f"({f' {word} '.join(rest)})", f"bez `{_short(source.segment(dropped))}` w `{word}`"
    elif isinstance(node, ast.IfExp):
        for branch in (node.body, node.orelse):
            yield node, node, f"({source.segment(branch)})", f"`{_short(source.segment(node))}` zawsze `{_short(source.segment(branch), 30)}`"
    elif isinstance(node, ast.Constant) and isinstance(node.value, bool):
        yield node, node, str(not node.value), f"`{node.value}` → `{not node.value}`"
    elif isinstance(node, ast.If):
        for value in (True, False):
            yield node.test, node.test, str(value), f"warunek `{_short(source.segment(node.test))}` zawsze `{value}`"
    elif isinstance(node, ast.Compare) and len(node.ops) == 1 and type(node.ops[0]) in _BOUNDARY:
        left, right = source.segment(node.left), source.segment(node.comparators[0])
        swapped = _BOUNDARY[type(node.ops[0])]
        yield node, node, f"({left} {swapped} {right})", f"granica `{_short(source.segment(node))}` → `{swapped}`"
    elif isinstance(node, ast.Return) and node.value is not None and not (
        isinstance(node.value, ast.Constant) and node.value.value is None
    ):
        yield node.value, node, "None", f"`return {_short(source.segment(node.value))}` → `return None`"
    elif isinstance(node, ast.Expr) and isinstance(node.value, (ast.Call, ast.Await)):
        yield node, node, "pass", f"bez wywołania `{_short(source.segment(node.value))}`"
    elif (
        isinstance(node, ast.Tuple)
        and isinstance(node.ctx, ast.Load)
        and 2 <= len(node.elts) <= 6
        and not any(isinstance(element, ast.Starred) for element in node.elts)
        and not all(isinstance(element, ast.Constant) for element in node.elts)
    ):
        for dropped in node.elts:
            rest = [source.segment(element) for element in node.elts if element is not dropped]
            tail = "," if len(rest) == 1 else ""
            yield node, dropped, f"({', '.join(rest)}{tail})", f"krotka bez `{_short(source.segment(dropped))}`"


def _meaning(text: str) -> str:
    """Kod bez tego, czego test nie widzi: docstringów, adnotacji funkcji, importów i aliasów typów.

    Adnotacje argumentów i wyników (``from __future__ import annotations``) nie działają w czasie wykonania, a import
    nazwy, którą kod naprawdę wywołuje, psuje już mutacja linii z tym wywołaniem. W pliku z pydantic albo FastAPI
    adnotacje i aliasy decydują o walidacji i trasach, więc zostają; tam pomija się tylko docstringi i importy.
    Adnotacje pól zostają zawsze.
    """

    tree = ast.parse(text)
    if _runtime_annotations(tree):
        for node in ast.walk(tree):
            if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
                node.body = [statement for statement in node.body if not _invisible(statement, set(), module=False)]
        return ast.dump(tree)
    for node in ast.walk(tree):
        if isinstance(node, ast.arg):
            node.annotation = None
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            node.returns = None
    loaded = {node.id for node in ast.walk(tree) if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load)}
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            module = isinstance(node, ast.Module)
            node.body = [statement for statement in node.body if not _invisible(statement, loaded, module=module)]
    return ast.dump(tree)


def _runtime_annotations(tree: ast.AST) -> bool:
    """Plik importuje pydantic albo FastAPI, które czytają adnotacje i aliasy typów w czasie wykonania."""

    for node in ast.walk(tree):
        names = (
            [alias.name for alias in node.names] if isinstance(node, ast.Import) else [node.module or ""] if isinstance(node, ast.ImportFrom) else []
        )
        if any(name.split(".")[0] in {"pydantic", "fastapi"} for name in names):
            return True
    return False


_TYPE_FORMS = frozenset(
    {"Callable", "Literal", "Annotated", "Union", "Optional", "Mapping", "Sequence", "Iterable", "Iterator", "type"}
    | {"dict", "list", "tuple", "set", "frozenset"}
)


def _type_form(value: ast.expr) -> bool:
    if isinstance(value, ast.BinOp):
        return isinstance(value.op, ast.BitOr) and _type_form(value.left) and _type_form(value.right)
    if isinstance(value, ast.Constant):
        return value.value is None
    if isinstance(value, ast.Subscript):
        value = value.value
    name = value.attr if isinstance(value, ast.Attribute) else value.id if isinstance(value, ast.Name) else None
    # Klasa ma nazwę w CamelCase, a stała modułu (``OPCJE["nowa"]``) wielkimi literami.
    return name is not None and (name in _TYPE_FORMS or (name[:1].isupper() and not name.isupper()))


def _invisible(statement: ast.stmt, loaded: set[str], *, module: bool) -> bool:
    if isinstance(statement, (ast.Import, ast.ImportFrom)):
        return True
    if isinstance(statement, ast.Expr) and isinstance(statement.value, ast.Constant) and isinstance(statement.value.value, str):
        return True
    # Alias typu modułu (``Nazwa = Callable[...]`` albo ``A | B``) czytany tylko w adnotacjach.
    return (
        module
        and isinstance(statement, ast.Assign)
        and len(statement.targets) == 1
        and isinstance(statement.targets[0], ast.Name)
        and statement.targets[0].id not in loaded
        and isinstance(statement.value, (ast.Subscript, ast.BinOp))
        and _type_form(statement.value)
    )


def mutants(path: str, text: str, hunks: Sequence[Hunk], platform: str = sys.platform) -> list[Mutant]:
    """Mutacje zmienionych linii pliku ``path`` o treści ``text``; każda daje kod, który się kompiluje.

    Testy biegną na systemie ``platform``: mutacja kodu gałęzi innego systemu ma ``other_system``.
    """

    tree = ast.parse(text)
    source = _Source(text)
    changed = changed_lines(hunks)
    skipped = _skipped(tree)
    other = _other_system(tree, platform)
    other_lines = {
        line for node in ast.walk(tree) if id(node) in other and isinstance(node, (ast.expr, ast.stmt)) for line in _span_lines(node)
    }
    cached = _cached_lines(tree)
    found: dict[str, Mutant] = {}
    meaning = _meaning(text)

    def add(lines: frozenset[int], line: int, description: str, mutated: str, *, other_system: bool) -> None:
        if mutated == text or mutated in found:
            return
        try:
            compile(mutated, path, "exec", dont_inherit=True)
        except (SyntaxError, ValueError):
            return
        if _meaning(mutated) != meaning:
            found[mutated] = Mutant(path, line, lines, description, mutated, other_system, bool(lines & cached))

    for node in ast.walk(tree):
        if id(node) in skipped:
            continue
        for replaced, broken, replacement, description in _candidates(node, source):
            lines = _span_lines(broken) & changed
            if lines:
                mutated = source.replaced(replaced, replacement)
                add(lines, broken.lineno, description, mutated, other_system=id(broken) in other or id(node) in other)
    rows = _rows(text)
    for hunk in hunks:
        if not hunk.count or (not hunk.old and hunk.count == len(rows)):
            continue  # samo usunięcie nie ma linii do testu, a nowy plik nie ma bazy
        old = [f"{line}\n" for line in hunk.old]
        mutated = "".join([*rows[: hunk.start - 1], *old, *rows[hunk.start - 1 + hunk.count :]])
        last = hunk.start + hunk.count - 1
        span = f"{hunk.start}" if hunk.count == 1 else f"{hunk.start}–{last}"
        lines = changed_lines([hunk])
        # Komentarz i pusta linia nie biegną na żadnym systemie, więc nie decydują, czyj jest fragment.
        code = {line for line in lines if line <= len(rows) and rows[line - 1].strip() and not rows[line - 1].lstrip().startswith("#")}
        add(lines, hunk.start, f"zmiana linii {span} cofnięta do bazy", mutated, other_system=bool(code) and code <= other_lines)
    return sorted(found.values(), key=lambda mutant: (mutant.line, mutant.description))


def exceptions(text: str, path: str) -> dict[int, Allowance]:
    """Wyjątki ``# mutacje-zmiany:`` pliku według linii kodu, której dotyczą; zła postać rzuca ``ValueError``."""

    found: dict[int, Allowance] = {}
    for number, line in enumerate(_rows(text), start=1):
        line = line.rstrip("\n")  # noqa: PLW2901
        match = EXCEPTION.search(line)
        if match is None:
            continue
        form = EXCEPTION_FORM.fullmatch(match["rest"])
        if form is None:
            raise ValueError(f"{path}:{number}: wyjątek musi mieć postać `# mutacje-zmiany: <powód> | do RRRR-MM-DD | zgoda <kto>`")
        try:
            until = datetime.date.fromisoformat(form["until"])
        except ValueError as error:
            raise ValueError(f"{path}:{number}: zła data wyjątku {form['until']}") from error
        allowance = Allowance(form["reason"], until, form["who"])
        found[number] = allowance
        if line.lstrip().startswith("#"):
            found[number + 1] = allowance
    return found


@dataclass
class Coverage:
    lines: dict[str, dict[str, set[int]]] = field(default_factory=lambda: defaultdict(lambda: defaultdict(set)))  # test → plik → linie
    files: dict[str, set[str]] = field(default_factory=lambda: defaultdict(set))  # test → pliki, których kod wykonał
    shared: dict[str, set[int]] = field(default_factory=lambda: defaultdict(set))  # plik → linie wykonane dla wielu testów
    spawners: set[str] = field(default_factory=set)  # testy, które uruchomiły proces

    def covering(self, mutant: Mutant) -> list[str]:
        return sorted(test for test, files in self.lines.items() if files.get(mutant.path, set()) & mutant.lines)

    def touching(self, path: str) -> list[str]:
        """Testy, które wykonały kod pliku ``path`` albo uruchomiły proces, którego kodu zapis może nie widzieć."""

        return sorted({test for test, files in self.files.items() if path in files} | self.spawners)


def _coverage(tests: Sequence[str], lines: dict[str, frozenset[int]]) -> tuple[subprocess.CompletedProcess[str], Coverage]:
    """Uruchamia testy raz z pluginem ``pokrycie_linii``; zwraca wynik i pokrycie zmienionych plików."""

    with tempfile.TemporaryDirectory(prefix="mutacje-zmiany-") as folder:
        settings = {"linie": {str(ROOT / path): sorted(numbers) for path, numbers in lines.items()}, "wynik": folder}
        # ``sitecustomize`` włącza zapis w każdym procesie Pythona, który test uruchamia z tym ``PYTHONPATH``.
        site = Path(folder) / "site"
        site.mkdir()
        (site / "sitecustomize.py").write_text(pokrycie_procesu.SITECUSTOMIZE, encoding="utf-8")
        python_path = os.pathsep.join([str(site), str(ROOT / "tools"), str(ROOT / "src"), os.environ.get("PYTHONPATH", "")])
        inherited = {name: value for name, value in os.environ.items() if name != pokrycie_procesu.TEST}
        env = {
            **inherited,
            "PYTEST_XDIST_AUTO_NUM_WORKERS": os.environ.get("PYTEST_XDIST_AUTO_NUM_WORKERS", str(WORKERS)),
            "PYTHONPATH": python_path.rstrip(os.pathsep),
            "POKRYCIE_LINII": json.dumps(settings),
        }
        command = [sys.executable, "-m", "pytest", "-q", "-n", "auto", "-p", "pokrycie_linii", "-p", "no:cacheprovider", *tests]
        done = potomne.run(command, cwd=ROOT, env=env)
        coverage = Coverage()

        def relative(absolute: str) -> str:
            return Path(absolute).relative_to(ROOT).as_posix()

        for part in sorted(Path(folder).glob("*.json")):
            recorded = json.loads(part.read_text(encoding="utf-8"))
            for test, files in recorded["linie"].items():
                for absolute, numbers in files.items():
                    coverage.lines[test][relative(absolute)].update(numbers)
            for test, paths in recorded["pliki"].items():
                coverage.files[test].update(relative(path) for path in paths)
            for absolute, numbers in recorded["wspolne"].items():
                coverage.shared[relative(absolute)].update(numbers)
            coverage.spawners.update(recorded["procesy"])
    return done, coverage


def _command(tests: Sequence[str], workers: int = 0) -> tuple[str, ...]:
    if sum(len(test) + 1 for test in tests) > COMMAND_LIMIT:
        tests = sorted({test.split("::")[0] for test in tests})
    return ("-m", "pytest", "-q", "-x", "-n", str(workers), "-p", "no:cacheprovider", *tests)


def _allowance(allowed: dict[int, Allowance], mutant: Mutant, today: datetime.date) -> Allowance | None:
    """Ważny wyjątek z linii mutacji; cofnięcie fragmentu ma linię jego początku."""

    allowance = allowed.get(mutant.line)
    return allowance if allowance is not None and allowance.until >= today else None


def _part(text: str) -> tuple[int, int]:
    number, _, count = text.partition("/")
    if not (number.isdigit() and count.isdigit() and 1 <= int(number) <= int(count)):
        raise argparse.ArgumentTypeError(f"część K/N z 1 <= K <= N, nie {text!r}")
    return int(number), int(count)


def part_of(every: Sequence[Mutant], number: int, count: int) -> list[Mutant]:
    """K-ta z N części ``every`` w jej kolejności; skrót zależy tylko od mutacji, więc każde zadanie liczy ten sam podział."""

    chosen = sorted(range(len(every)), key=lambda index: _digest(every[index]))[number - 1 :: count]
    return [every[index] for index in sorted(chosen)]


def _digest(mutant: Mutant) -> bytes:
    return hashlib.sha256(f"{mutant.path}\0{mutant.line}\0{mutant.description}\0{mutant.source}".encode()).digest()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--baza", default=BASE, help=f"Gałąź, od której liczy się zmiana (domyślnie {BASE}).")
    parser.add_argument("--rownolegle", type=int, default=WORKERS, help="Ile mutacji biegnie naraz, każda w swojej kopii.")
    parser.add_argument("--limit-s", type=float, default=900, help="Limit czasu testów jednej mutacji w sekundach.")
    parser.add_argument("--czesc", metavar="K/N", type=_part, default=(1, 1), help="Tylko co N-ta mutacja po skrócie, od K-tej.")
    ciezkie_ci.argument(parser)
    args = parser.parse_args(argv)
    if refusal := ciezkie_ci.refusal({"change-mutations"}, args.odtwarzam, root=ROOT):
        print(refusal)
        return 2
    number, count = args.czesc
    try:
        fork = _git("merge-base", "HEAD", args.baza).strip()
    except subprocess.CalledProcessError:
        print(f"MUTACJE ZMIANY FAIL | nieznana baza {args.baza}")
        return 1
    hunks = changes(fork)
    texts = {path: (ROOT / path).read_text(encoding="utf-8") for path in hunks}
    try:
        allowed = {path: exceptions(text, path) for path, text in texts.items()}
    except ValueError as error:
        print(f"MUTACJE ZMIANY FAIL | {error}")
        return 1
    every = [mutant for path, text in texts.items() for mutant in mutants(path, text, hunks[path])]
    found = part_of(every, number, count)
    if not found:
        where = f" w części {number}/{count}" if every else ""
        print(f"MUTACJE ZMIANY OK | brak mutacji zmienionych linii src/ od {args.baza}{where}")
        return 0
    paths = {mutant.path for mutant in found}
    by_file = {path: sorted(szybko.select(ROOT, frozenset({path})).fingerprints) for path in paths}
    tests = sorted({test for selected in by_file.values() for test in selected})
    part = f" (część {number}/{count} z {len(every)})" if count > 1 else ""
    print(f"Mutacje: {len(found)}{part} w {len(paths)} plikach src/ od {args.baza}. Testy dotknięte zmianą: {len(tests)}.", flush=True)
    clock = [time.monotonic()]
    coverage = Coverage()
    if tests:
        done, coverage = _coverage(tests, {path: changed_lines(hunks[path]) for path in paths})
        if done.returncode != 0:
            print("\n".join((done.stdout + done.stderr).rstrip().splitlines()[-30:]))
            print("MUTACJE ZMIANY FAIL | testy dotknięte zmianą padają bez mutacji, więc mutacje niczego nie dowiodą")
            return 2
        print(f"Pokrycie: {len(coverage.lines)} testów wykonało zmienione linie, {len(coverage.spawners)} uruchomiło proces.", flush=True)
    today = datetime.datetime.now(datetime.UTC).date()
    narrow: list[tuple[Mutant, mutacje.Mutation, list[str]]] = []  # i testy drugiego przebiegu, gdy pierwszy przeżyje
    survived = excused = other_system = 0
    for mutant in found:
        name = f"{mutant.path}:{mutant.line} {mutant.description}"
        allowance = _allowance(allowed[mutant.path], mutant, today)
        if allowance is not None:
            excused += 1
            print(f"WYJĄTEK: {name} ({allowance.reason}, do {allowance.until}, zgoda {allowance.who})")
            continue
        if mutant.other_system:
            other_system += 1
            print(f"POMINIĘTA: {name} → kod innego systemu niż {sys.platform}")
            continue
        if not by_file[mutant.path]:
            survived += 1
            print(f"NIEWYKRYTA: {name} → żaden test nie zależy od {mutant.path}")
            continue
        # Kod, którego wynik dostają też testy, które go nie wykonały (import, fixture szersza niż test, ``@cache``),
        # sprawdzają wszystkie testy pliku; inny kod testy, które wykonały jakikolwiek kod jego pliku.
        shared = mutant.shared_state or bool(mutant.lines & coverage.shared.get(mutant.path, set()))
        candidates = set(by_file[mutant.path])
        touching = [test for test in coverage.touching(mutant.path) if test.split("::")[0] in candidates]
        second = by_file[mutant.path] if shared else touching or by_file[mutant.path]
        first = coverage.covering(mutant) or second
        edit = mutacje.Edit(Path(mutant.path), texts[mutant.path], mutant.source)
        narrow.append((mutant, mutacje.Mutation(name, (edit,), _command(first)), [] if first == second else second))
    clock.append(time.monotonic())
    # Pokrycie tylko przyspiesza: mutacja, która przeżyła testy swoich linii, biegnie ze wszystkimi testami pliku.
    # Takich jest kilka, a testów pliku tysiące, więc biegną po jednej, każda z workerami xdist.
    wide: list[mutacje.Mutation] = []
    for (_, mutation, second), (verdict, last) in zip(narrow, mutacje.verdicts([m for _, m, _ in narrow], workers=args.rownolegle, limit_s=args.limit_s), strict=True):
        if verdict == "WYKRYTA" or not second:
            survived += verdict != "WYKRYTA"
            print(f"{verdict}: {mutation.name} → {last}", flush=True)
        else:
            wide.append(mutacje.Mutation(mutation.name, mutation.edits, _command(second, args.rownolegle)))
    clock.append(time.monotonic())
    for mutation, (verdict, last) in zip(wide, mutacje.verdicts(wide, workers=1, limit_s=args.limit_s), strict=True):
        survived += verdict != "WYKRYTA"
        print(f"{verdict}: {mutation.name} → {last} (testy pliku)", flush=True)
    clock.append(time.monotonic())
    uncovered = sum(not second for _, _, second in narrow)
    coverage_s, narrow_s, wide_s = (later - earlier for earlier, later in itertools.pairwise(clock))
    print(
        f"CZAS | pokrycie {coverage_s:.0f} s | testy linii {narrow_s:.0f} s ({len(narrow)} mutacji, w tym {uncovered} bez drugiego)"
        f" | testy pliku {wide_s:.0f} s ({len(wide)} mutacji)",
        flush=True,
    )
    summary = f"mutacje={len(found)} | wyjątki={excused} | innego systemu={other_system}"
    if survived:
        print(f"MUTACJE ZMIANY FAIL | przeżyło {survived} | {summary}")
        return 1
    print(f"MUTACJE ZMIANY OK | {summary}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

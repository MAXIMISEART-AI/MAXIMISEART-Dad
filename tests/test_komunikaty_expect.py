"""Komunikaty, które widzi tata, jako tekst w ``tests/expected/komunikaty.txt``.

Plik ma próbkę każdej fabryki każdego katalogu z ``tests/fixtures/message_samples.py``, pogrupowaną po katalogu,
z kodem i trzema częściami. Zmiana tekstu Komunikatu zmienia ten plik w tym samym PR, więc diff PR pokazuje,
co tata zobaczy inaczej, obok zmiany kodu.

Katalog to moduł fabryk Komunikatów: ma wpis w ``CATALOGS``, a każda jego publiczna funkcja ma próbkę.
Moduł ``src/``, który tworzy Komunikat poza katalogiem, ma w ``OUTSIDE_CATALOGS`` próbkę każdej funkcji i stałej,
która go tworzy (co liczy się jako utworzenie, mówi ``_creating``), więc i jego tekst trafia do pliku.
"""

from __future__ import annotations

import ast
from collections.abc import Callable, Iterator, Mapping, Sequence
import inspect
from pathlib import Path
from types import ModuleType

import pytest

from rozliczenia import intermax_messages, settlement_messages
from rozliczenia import preparation_messages as messages
from rozliczenia.centrum import (
    contract,
    diagnosis_messages,
    fill_messages,
    notification_messages,
    report_messages,
    run_cards,
    runs,
    start_problems,
    update_messages,
)
from rozliczenia.message import Message

from tests.fixtures import message_samples
from tests.fixtures.expect import assert_expected
from tests.fixtures.message_samples import (
    DIAGNOSIS_SAMPLES,
    FILL_SAMPLES,
    INTERMAX_SAMPLES,
    NOTIFICATION_SAMPLES,
    PERIOD,
    PREPARATION_SAMPLES,
    REPORT_SAMPLES,
    SETTLEMENT_SAMPLES,
    START_SAMPLES,
    UPDATE_SAMPLES,
    Samples,
)

ROOT = Path(__file__).resolve().parents[1]
CATALOGS: dict[str, tuple[ModuleType, Samples]] = {
    "Przygotowanie pliku zbiorczego": (messages, PREPARATION_SAMPLES),
    "Przebieg rozliczeń": (settlement_messages, SETTLEMENT_SAMPLES),
    "Start Centrum rozliczeń": (start_problems, START_SAMPLES),
    "Diagnoza": (diagnosis_messages, DIAGNOSIS_SAMPLES),
    "Uzupełnienie pliku zbiorczego": (fill_messages, FILL_SAMPLES),
    "Zgłoszenie": (report_messages, REPORT_SAMPLES),
    "Powiadomienia": (notification_messages, NOTIFICATION_SAMPLES),
    "Aktualizacja narzędzia": (update_messages, UPDATE_SAMPLES),
    "Uporządkowanie INTERMAX": (intermax_messages, INTERMAX_SAMPLES),
}
# Komunikat karty Urwanego Uruchomienia (contract.Message) nie ma kodu; tytuł procesu jest syntetyczny.
OUTSIDE_CATALOGS: dict[str, tuple[ModuleType, Mapping[str, Sequence[Callable[[], Message | contract.Message]]]]] = {
    "Wynik Uruchomienia": (runs, {"_RESULT_NOT_SHOWN": [lambda: runs._RESULT_NOT_SHOWN]}),
    "Karta Urwanego Uruchomienia": (
        run_cards,
        {
            "_interrupted_advice": [
                lambda: run_cards._interrupted_advice("Przygotowanie pliku zbiorczego", PERIOD, dry_run=True),
                lambda: run_cards._interrupted_advice("Przygotowanie pliku zbiorczego", PERIOD, dry_run=False),
            ]
        },
    ),
}


def _source(module: ModuleType) -> str:
    return f"src/{module.__name__.replace('.', '/')}.py"


def _places(statements: list[ast.stmt], prefix: str = "") -> Iterator[tuple[str, ast.stmt]]:
    """Instrukcje modułu z nazwą miejsca: funkcja, ``Klasa.metoda``, stała albo numer wiersza."""

    for statement in statements:
        match statement:
            case ast.ClassDef(name=name, body=body):
                yield from _places(body, f"{prefix}{name}.")
            case ast.FunctionDef(name=name) | ast.AsyncFunctionDef(name=name):
                yield f"{prefix}{name}", statement
            case ast.Assign(targets=[ast.Name(id=name)]) | ast.AnnAssign(target=ast.Name(id=name)):
                yield f"{prefix}{name}", statement
            case _:
                yield f"{prefix}wiersz {statement.lineno}", statement


def _copies(call: ast.Call) -> bool:
    """``Message(what=message.what, where=message.where, …)``: każde pole z tego samego pola jednego obiektu."""

    owners = [
        keyword.value.value.id
        for keyword in call.keywords
        if isinstance(keyword.value, ast.Attribute)
        and isinstance(keyword.value.value, ast.Name)
        and keyword.value.attr == keyword.arg
    ]
    return not call.args and len(owners) == len(call.keywords) and len(set(owners)) == 1


def _creating(path: Path) -> set[str]:
    """Miejsca modułu (``_places``), które tworzą Komunikat.

    Tworzy go wywołanie, którego nazwa po rozwiązaniu importów (``Message as M``) albo atrybut (``message.Message``,
    ``contract.Message``) kończy się na ``Message``. Wywołanie, które tylko przepisuje pola innego Komunikatu
    (``_copies``), nowego tekstu nie tworzy.
    """

    tree = ast.parse(path.read_text(encoding="utf-8"))
    imported = {
        alias.asname or alias.name: alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.Import | ast.ImportFrom)
        for alias in node.names
    }

    def creates(node: ast.AST) -> bool:
        if not isinstance(node, ast.Call) or _copies(node):
            return False
        match node.func:
            case ast.Name(id=name):
                return imported.get(name, name).endswith("Message")
            case ast.Attribute(attr=attr):
                return attr.endswith("Message")
            case _:
                return False

    return {name for name, statement in _places(tree.body) if any(creates(node) for node in ast.walk(statement))}


def _entry(name: str, message: Message | contract.Message) -> list[str]:
    if isinstance(message, Message):
        return [f"{name} [{message.code}]", *(f"  {line}" for line in message.text.splitlines())]
    return [f"{name} [bez kodu]", f"  Co się stało: {message.what}", f"  Gdzie: {message.where}", f"  Co zrobić: {message.action}"]


def _rendered() -> str:
    lines = [
        "# Komunikaty, które widzi tata: próbka każdej fabryki każdego katalogu i każdego Komunikatu spoza katalogów.",
        "# Plik zapisuje tests/test_komunikaty_expect.py; ścieżki w próbkach są syntetyczne.",
    ]
    for catalog, (module, samples) in (CATALOGS | OUTSIDE_CATALOGS).items():
        lines += ["", f"=== {catalog} ({_source(module)}) ==="]
        for factory, factory_samples in samples.items():
            for number, sample in enumerate(factory_samples, start=1):
                variant = f" #{number}" if len(factory_samples) > 1 else ""
                lines += ["", *_entry(f"{factory}{variant}", sample())]
    return "\n".join(lines) + "\n"


def test_kazde_miejsce_tworzace_komunikat_ma_probke_w_pliku_expect() -> None:
    creating = {path.relative_to(ROOT).as_posix(): places for path in (ROOT / "src").rglob("*.py") if (places := _creating(path))}
    outside = {_source(module): set(samples) for module, samples in OUTSIDE_CATALOGS.values()}

    assert set(creating) == {_source(module) for module, _ in CATALOGS.values()} | set(outside)
    assert {path: creating[path] for path in outside} == outside


@pytest.mark.parametrize("catalog", CATALOGS)
def test_probki_pokrywaja_kazda_publiczna_funkcje_katalogu(catalog: str) -> None:
    module, samples = CATALOGS[catalog]
    public = {
        name
        for name, function in inspect.getmembers(module, inspect.isfunction)
        if function.__module__ == module.__name__ and not name.startswith("_")
    }

    assert set(samples) == public


def test_kazdy_katalog_probek_trafia_do_pliku_expect() -> None:
    sample_sets = {name for name, value in vars(message_samples).items() if name.endswith("_SAMPLES")}

    assert {id(getattr(message_samples, name)) for name in sample_sets} == {id(samples) for _, samples in CATALOGS.values()}


def test_komunikaty_ktore_widzi_tata_odpowiadaja_plikowi_expect() -> None:
    assert_expected(_rendered(), ROOT / "tests" / "expected" / "komunikaty.txt")

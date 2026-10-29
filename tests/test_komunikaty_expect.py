"""Komunikaty, które widzi tata, jako tekst w ``tests/expected/komunikaty.txt``.

Plik ma próbkę każdej fabryki każdego katalogu z ``tests/fixtures/message_samples.py``, pogrupowaną po katalogu,
z kodem i trzema częściami. Zmiana tekstu Komunikatu zmienia ten plik w tym samym PR, więc diff PR pokazuje,
co tata zobaczy inaczej, obok zmiany kodu.

Katalog to moduł ``src/``, który wywołuje ``Message(...)``. Każdy taki moduł ma wpis
w ``CATALOGS`` albo powód w ``OUTSIDE_CATALOGS``, a każda jego publiczna funkcja ma próbkę.
"""

from __future__ import annotations

import ast
import inspect
from pathlib import Path
from types import ModuleType

import pytest

from rozliczenia import intermax_messages, settlement_messages
from rozliczenia import preparation_messages as messages
from rozliczenia.centrum import (
    diagnosis_messages,
    fill_messages,
    notification_messages,
    report_messages,
    start_problems,
    update_messages,
)

from tests.fixtures import message_samples
from tests.fixtures.expect import assert_expected
from tests.fixtures.message_samples import (
    DIAGNOSIS_SAMPLES,
    FILL_SAMPLES,
    INTERMAX_SAMPLES,
    NOTIFICATION_SAMPLES,
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
# Moduły, które tworzą Message, ale nie są katalogiem z fabrykami, z powodem.
OUTSIDE_CATALOGS = {
    # Jedna prywatna stała BLAD_WYNIKU ostatniej siatki adaptera, bez fabryki do próbki; przeniesienie jej
    # do katalogu zmienia src/rozliczenia/centrum/, którym zajmują się teraz PR-y #626 i #512.
    "src/rozliczenia/centrum/runs.py",
}


def _source(module: ModuleType) -> str:
    return f"src/{module.__name__.replace('.', '/')}.py"


def _creates_message(path: Path) -> bool:
    return any(
        isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "Message"
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8")))
    )


def _rendered() -> str:
    lines = [
        "# Komunikaty, które widzi tata: próbka każdej fabryki każdego katalogu.",
        "# Plik zapisuje tests/test_komunikaty_expect.py; ścieżki w próbkach są syntetyczne.",
    ]
    for catalog, (module, samples) in CATALOGS.items():
        lines += ["", f"=== {catalog} ({_source(module)}) ==="]
        for factory, factory_samples in samples.items():
            for number, sample in enumerate(factory_samples, start=1):
                message = sample()
                variant = f" #{number}" if len(factory_samples) > 1 else ""
                lines += ["", f"{factory}{variant} [{message.code}]"]
                lines += [f"  {line}" for line in message.text.splitlines()]
    return "\n".join(lines) + "\n"


def test_kazdy_modul_tworzacy_komunikaty_ma_katalog_w_pliku_expect() -> None:
    creating = {path.relative_to(ROOT).as_posix() for path in (ROOT / "src").rglob("*.py") if _creates_message(path)}

    assert creating - OUTSIDE_CATALOGS == {_source(module) for module, _ in CATALOGS.values()}
    assert OUTSIDE_CATALOGS <= creating


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

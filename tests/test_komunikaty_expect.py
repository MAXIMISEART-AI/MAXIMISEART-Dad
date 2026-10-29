"""Komunikaty, które widzi tata, jako tekst w ``tests/expected/komunikaty.txt``.

Plik ma próbkę każdej fabryki każdego katalogu z ``tests/fixtures/message_samples.py``, pogrupowaną po katalogu,
z kodem i trzema częściami. Zmiana tekstu Komunikatu zmienia ten plik w tym samym PR, więc diff PR pokazuje,
co tata zobaczy inaczej, obok zmiany kodu.
"""

from __future__ import annotations

from pathlib import Path

from tests.fixtures import message_samples
from tests.fixtures.expect import assert_expected
from tests.fixtures.message_samples import (
    DIAGNOSIS_SAMPLES,
    FILL_SAMPLES,
    NOTIFICATION_SAMPLES,
    PREPARATION_SAMPLES,
    REPORT_SAMPLES,
    SETTLEMENT_SAMPLES,
    START_SAMPLES,
    UPDATE_SAMPLES,
    Samples,
)

ROOT = Path(__file__).resolve().parents[1]
CATALOGS: dict[str, Samples] = {
    "Przygotowanie pliku zbiorczego (src/rozliczenia/preparation_messages.py)": PREPARATION_SAMPLES,
    "Przebieg rozliczeń (src/rozliczenia/settlement_messages.py)": SETTLEMENT_SAMPLES,
    "Start Centrum rozliczeń (src/rozliczenia/centrum/start_problems.py)": START_SAMPLES,
    "Diagnoza (src/rozliczenia/centrum/diagnosis_messages.py)": DIAGNOSIS_SAMPLES,
    "Uzupełnienie pliku zbiorczego (src/rozliczenia/centrum/fill_messages.py)": FILL_SAMPLES,
    "Zgłoszenie (src/rozliczenia/centrum/report_messages.py)": REPORT_SAMPLES,
    "Powiadomienia (src/rozliczenia/centrum/notification_messages.py)": NOTIFICATION_SAMPLES,
    "Aktualizacja narzędzia (src/rozliczenia/centrum/update_messages.py)": UPDATE_SAMPLES,
}


def _rendered() -> str:
    lines = [
        "# Komunikaty, które widzi tata: próbka każdej fabryki każdego katalogu.",
        "# Plik zapisuje tests/test_komunikaty_expect.py; ścieżki w próbkach są syntetyczne.",
    ]
    for catalog, samples in CATALOGS.items():
        lines += ["", f"=== {catalog} ==="]
        for factory, factory_samples in samples.items():
            for number, sample in enumerate(factory_samples, start=1):
                message = sample()
                variant = f" #{number}" if len(factory_samples) > 1 else ""
                lines += ["", f"{factory}{variant} [{message.code}]"]
                lines += [f"  {line}" for line in message.text.splitlines()]
    return "\n".join(lines) + "\n"


def test_kazdy_katalog_probek_trafia_do_pliku_expect() -> None:
    sample_sets = {name for name, value in vars(message_samples).items() if name.endswith("_SAMPLES")}

    assert {id(getattr(message_samples, name)) for name in sample_sets} == {id(samples) for samples in CATALOGS.values()}


def test_komunikaty_ktore_widzi_tata_odpowiadaja_plikowi_expect() -> None:
    assert_expected(_rendered(), ROOT / "tests" / "expected" / "komunikaty.txt")

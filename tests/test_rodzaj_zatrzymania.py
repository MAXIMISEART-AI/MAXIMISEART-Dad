"""Rodzaj Zatrzymania z treści Komunikatu: „do Maksa” tylko przy bezwarunkowym przekazaniu Komunikatu.

Rodzaj wynika z „Co zrobić” w katalogu procesu, bez osobnej listy kodów; ten test
przypina wynik reguły dla każdej próbki obu katalogów procesów. Komunikat, który
przekazanie uzależnia od powtórki („Jeśli błąd wraca, przekaż…”) albo od innej
przyczyny („W innym wypadku przekaż…”), jest „dla taty”.
"""

from __future__ import annotations

import pytest

from tests.fixtures.message_samples import PREPARATION_SAMPLES, SETTLEMENT_SAMPLES, Samples

FOR_MAKS = {
    "przygotowanie-pliku-zbiorczego": {
        "ZLA_KONFIGURACJA_WYKONAWCOW",
        "BRAK_WZORCA",
        "USZKODZONY_WZORZEC",
        "ZLY_WZORZEC",
        "SCALONE_KOMORKI_WZORCA",
        "BLAD_PODSUMOWANIA",
        "BLAD_PLANU",
    },
    "przebieg-rozliczen": {
        "ZLA_KONFIGURACJA_WYKONAWCOW",
        "BLAD_PODSUMOWANIA",
        "BLAD_PLANU",
    },
}
SAMPLES: dict[str, Samples] = {
    "przygotowanie-pliku-zbiorczego": PREPARATION_SAMPLES,
    "przebieg-rozliczen": SETTLEMENT_SAMPLES,
}


@pytest.mark.parametrize("catalog", SAMPLES)
def test_do_maksa_sa_tylko_komunikaty_bezwarunkowo_przekazywane_osobie_utrzymujacej_narzedzie(catalog: str) -> None:
    messages = [sample() for samples in SAMPLES[catalog].values() for sample in samples]

    assert {message.code for message in messages if message.reports_to_maintainer} == FOR_MAKS[catalog]

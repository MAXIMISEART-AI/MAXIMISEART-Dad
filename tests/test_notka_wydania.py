"""Notka Wydania: to, co napisze narzędzie Wydań, Powiadomienie o nowej wersji odczyta bez straty."""

from __future__ import annotations

import pytest

from rozliczenia.centrum.release_notes import CASES_HEADING, DadCase, ReleaseNotes, parse, render

SUMMARY = "Przygotowanie pliku zbiorczego samo wpisuje ilości usług.\nCentrum pokazuje, co nowego."


@pytest.mark.parametrize(
    "cases",
    [
        (),
        (DadCase(3, "Zatrzymanie przy pustym ADRES", "zgloszenie"), DadCase(12, "Brakuje ilości: montaż #2", "uwaga-taty")),
    ],
)
def test_notka_wraca_z_tekstu_z_co_nowego_i_sprawami_taty(cases: tuple[DadCase, ...]) -> None:
    notes = ReleaseNotes(SUMMARY, cases)

    assert parse(render(notes)) == notes


def test_tytul_sprawy_w_notce_jest_jedna_linia() -> None:
    text = render(ReleaseNotes(SUMMARY, (DadCase(7, "Dwie\nlinie  tytułu", "uwaga-taty"),)))

    assert parse(text).cases == (DadCase(7, "Dwie linie tytułu", "uwaga-taty"),)


def test_notka_bez_spraw_nie_ma_naglowka_spraw() -> None:
    assert CASES_HEADING not in render(ReleaseNotes(SUMMARY, ()))


@pytest.mark.parametrize("summary", ["", "  \n", f"Co nowego.\n\n{CASES_HEADING}\n"])
def test_notka_wymaga_co_nowego_bez_naglowka_spraw(summary: str) -> None:
    with pytest.raises(ValueError, match="Co nowego"):
        render(ReleaseNotes(summary, ()))

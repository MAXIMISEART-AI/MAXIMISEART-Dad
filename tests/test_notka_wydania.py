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


CASES = (DadCase(3, "Zatrzymanie przy pustym ADRES", "zgloszenie"), DadCase(12, "Brakuje ilości", "uwaga-taty"))
LISTED = "- Zgłoszenie #3: Zatrzymanie przy pustym ADRES\n- Uwaga taty #12: Brakuje ilości\n"


@pytest.mark.parametrize(
    "text",
    [
        f"{SUMMARY}\n\n## Rozwiązane sprawy taty \n\n{LISTED}",
        f"{SUMMARY}\n\n### Rozwiązane sprawy taty\n\n{LISTED}",
        f"{SUMMARY}\n## Rozwiązane sprawy taty\n{LISTED}",
        f"{SUMMARY}\n\n## Rozwiązane sprawy taty\n\n{LISTED}".replace("\n", "\r\n"),
    ],
    ids=["spacja-na-koncu-naglowka", "naglowek-###", "bez-pustej-linii-przed-naglowkiem", "crlf"],
)
def test_notka_poprawiona_recznie_na_githubie_ma_co_nowego_bez_listy_i_sprawy(text: str) -> None:
    assert parse(text) == ReleaseNotes(SUMMARY, CASES)


def test_co_nowego_z_naglowkiem_spraw_innego_poziomu_jest_odrzucone() -> None:
    with pytest.raises(ValueError, match="Co nowego"):
        render(ReleaseNotes("Co nowego.\n### Rozwiązane sprawy taty\n- Zgłoszenie #3: Tytuł", ()))

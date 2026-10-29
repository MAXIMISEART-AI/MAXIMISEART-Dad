"""Test expect (``tests/fixtures/expect.py``): pada z diffem i poleceniem zapisu, zapisuje tylko poza CI."""

from __future__ import annotations

from pathlib import Path

import pytest

from tests.fixtures.expect import assert_expected


@pytest.fixture(autouse=True)
def _bez_zapisu(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("ZAPISZ_EXPECT", raising=False)
    monkeypatch.delenv("CI", raising=False)


def test_ten_sam_tekst_przechodzi(tmp_path: Path) -> None:
    expected = tmp_path / "wynik.txt"
    expected.write_bytes("Co się stało: coś\n".encode())

    assert_expected("Co się stało: coś\n", expected)


def test_inny_tekst_pada_z_diffem_i_poleceniem_zapisu(tmp_path: Path) -> None:
    expected = tmp_path / "wynik.txt"
    expected.write_bytes("Gdzie: plik A\nCo zrobić: zamknij\n".encode())

    with pytest.raises(pytest.fail.Exception) as failure:
        assert_expected("Gdzie: plik B\nCo zrobić: zamknij\n", expected)

    message = str(failure.value)
    assert "-Gdzie: plik A\n+Gdzie: plik B\n Co zrobić: zamknij\n" in message
    assert "ZAPISZ_EXPECT=1 .venv/bin/python -m pytest 'tests/test_expect.py::test_inny_tekst" in message
    assert expected.read_bytes() == "Gdzie: plik A\nCo zrobić: zamknij\n".encode()


def test_brak_pliku_pada_z_calym_tekstem_jako_dodanym(tmp_path: Path) -> None:
    with pytest.raises(pytest.fail.Exception, match=r"\+Co się stało: coś"):
        assert_expected("Co się stało: coś\n", tmp_path / "wynik.txt")


def test_zapis_tworzy_plik_w_utf8_z_koncami_linii_lf(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ZAPISZ_EXPECT", "1")
    expected = tmp_path / "expected" / "wynik.txt"

    assert_expected("Co się stało: coś\nGdzie: tu\n", expected)

    assert expected.read_bytes() == "Co się stało: coś\nGdzie: tu\n".encode()


def test_w_ci_zapis_pada_i_nie_zmienia_pliku(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ZAPISZ_EXPECT", "1")
    monkeypatch.setenv("CI", "true")
    expected = tmp_path / "wynik.txt"
    expected.write_bytes(b"stary\n")

    with pytest.raises(pytest.fail.Exception, match="w CI"):
        assert_expected("nowy\n", expected)

    assert expected.read_bytes() == b"stary\n"


def test_plik_z_koncami_linii_crlf_z_checkoutu_na_windows_porownuje_sie_jak_lf(tmp_path: Path) -> None:
    expected = tmp_path / "wynik.txt"
    expected.write_bytes(b"Gdzie: tu\r\nCo zrobi\xc4\x87: nic\r\n")

    assert_expected("Gdzie: tu\nCo zrobić: nic\n", expected)
    with pytest.raises(pytest.fail.Exception, match=r"-Co zrobić: nic\n\+Co zrobić: coś\n"):
        assert_expected("Gdzie: tu\nCo zrobić: coś\n", expected)

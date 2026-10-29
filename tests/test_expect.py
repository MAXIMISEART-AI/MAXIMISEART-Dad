"""Test expect (``tests/fixtures/expect.py``): pada z diffem i poleceniem zapisu, które działa, zapisuje tylko poza CI."""

from __future__ import annotations

import os
from pathlib import Path
import shlex
import subprocess
import sys

import pytest

from tests.fixtures.expect import assert_expected

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(autouse=True)
def _bez_zapisu(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("ZAPISZ_EXPECT", raising=False)
    monkeypatch.delenv("CI", raising=False)


def test_ten_sam_tekst_przechodzi(tmp_path: Path) -> None:
    expected = tmp_path / "wynik.txt"
    expected.write_bytes("Co się stało: coś\n".encode())

    assert_expected("Co się stało: coś\n", expected)


def test_inny_tekst_pada_z_diffem_i_nie_zmienia_pliku(tmp_path: Path) -> None:
    expected = tmp_path / "wynik.txt"
    expected.write_bytes("Gdzie: plik A\nCo zrobić: zamknij\n".encode())

    with pytest.raises(pytest.fail.Exception) as failure:
        assert_expected("Gdzie: plik B\nCo zrobić: zamknij\n", expected)

    assert "-Gdzie: plik A\n+Gdzie: plik B\n Co zrobić: zamknij\n" in str(failure.value)
    assert expected.read_bytes() == "Gdzie: plik A\nCo zrobić: zamknij\n".encode()


def test_polecenie_zapisu_z_porazki_zapisuje_plik_a_test_potem_przechodzi(tmp_path: Path) -> None:
    (tmp_path / "test_probka.py").write_text(
        "from pathlib import Path\n\nfrom tests.fixtures.expect import assert_expected\n\n\n"
        "def test_probka() -> None:\n"
        "    assert_expected('Co zrobić: zamknij\\n', Path(__file__).parent / 'wynik.txt')\n",
        encoding="utf-8",
    )
    env = {**os.environ, "PYTHONPATH": str(ROOT), "PYTHONUTF8": "1"}

    def pytest_run(*args: str, **extra: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", *args],
            cwd=tmp_path,
            env=env | extra,
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=120,
            check=False,
        )

    failed = pytest_run("test_probka.py")
    command = next(line.strip() for line in failed.stdout.splitlines() if line.strip().startswith("ZAPISZ_EXPECT=1 "))
    saving, python, *pytest_args = shlex.split(command)
    saved = pytest_run(*pytest_args[2:], ZAPISZ_EXPECT=saving.removeprefix("ZAPISZ_EXPECT="))

    assert (failed.returncode, python, pytest_args[:2]) == (1, ".venv/bin/python", ["-m", "pytest"])
    assert saved.returncode == 0, saved.stdout + saved.stderr
    assert (tmp_path / "wynik.txt").read_bytes() == "Co zrobić: zamknij\n".encode()
    assert pytest_run("test_probka.py").returncode == 0


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

"""Podstawa skilla z ``ci-czesci`` biegnie w CI w częściach ``MUTACJE_CZESC=k/n`` i żadna jej jednostka nie ginie:
części jednej liczby n składają się w kolejności na całość, a Centrum przejeżdża w nich każdą funkcję ``all`` raz."""

from __future__ import annotations

import importlib.util
from pathlib import Path
import sys
from types import ModuleType

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

import mutacje  # noqa: E402
import mutacje_skilli  # noqa: E402
import skrypt_skilla  # noqa: E402

CENTRUM = ROOT / ".agents" / "skills" / "verify-centrum-rozliczen"


@pytest.fixture
def runner(monkeypatch: pytest.MonkeyPatch) -> ModuleType:
    monkeypatch.syspath_prepend(str(CENTRUM / "scripts"))
    spec = importlib.util.spec_from_file_location("run_centrum_verification", CENTRUM / "scripts" / "run_centrum_verification.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_skrypt_skilla_czyta_czesc_z_tej_samej_zmiennej_co_silnik_mutacji_i_plan() -> None:
    assert skrypt_skilla.PART == mutacje.PART


@pytest.mark.parametrize("count", range(1, 8))
def test_n_czesci_bierze_kazda_jednostke_raz_w_jej_kolejnosci_i_zadna_czesc_nie_jest_pusta(count: int) -> None:
    units = tuple(f"j{number}" for number in range(7))

    parts = [skrypt_skilla.part(units, {mutacje.PART: f"{number}/{count}"}) for number in range(1, count + 1)]

    assert sum(parts, ()) == units
    assert all(parts)


@pytest.mark.parametrize("value", ["8/8", "0/3", "3/2", "1", "a/b"])
def test_czesc_spoza_jednostek_to_blad_a_nie_pusty_przebieg(value: str) -> None:
    with pytest.raises(ValueError, match="MUTACJE_CZESC to K/N z 1 <= K <= N <= 7"):
        skrypt_skilla.part(tuple(range(7)), {mutacje.PART: value})


def test_czesci_podstawy_centrum_przejezdzaja_kazda_funkcje_all_raz_w_kolejnosci_all(runner: ModuleType) -> None:
    count = mutacje_skilli.ci_parts(CENTRUM / "SKILL.md")
    every = runner.driven("all", {})

    assert count > 1 and count <= len(every)
    for parts in range(1, count + 1):
        driven = [runner.driven("all", {mutacje.PART: f"{number}/{parts}"}) for number in range(1, parts + 1)]
        assert sum(driven, ()) == every, parts
    assert set(every) == set(runner.REQUIRED_SCREENSHOTS) - set(importlib.import_module("drive").EXPLICIT_FEATURES)
    # Część nie zmienia przebiegu jednej funkcji (mutacje skilla), bo dzieli tylko all.
    assert runner.driven("zgloszenie", {mutacje.PART: "2/8"}) == ("zgloszenie",)


def test_zla_czesc_centrum_konczy_przebieg_porazka_zanim_cokolwiek_wystartuje(runner: ModuleType, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    monkeypatch.setenv(mutacje.PART, "30/30")

    code = runner.main(["--feature", "all", "--run-dir", "nie-powstanie"])

    assert code == 1
    assert capsys.readouterr().err.startswith("VERIFY FAIL | features=all | MUTACJE_CZESC to K/N z 1 <= K <= N <= 22")
    assert not Path("nie-powstanie").exists()

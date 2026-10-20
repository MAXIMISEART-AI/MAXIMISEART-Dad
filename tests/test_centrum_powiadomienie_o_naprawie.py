"""Powiadomienie o naprawie na stronie Okresy przez HTTP API, z fałszywą skrzynką Zgłoszeń i podstawionym zegarem."""

from __future__ import annotations

from pathlib import Path
import time

import pytest

from rozliczenia.centrum.report_box import Refused, Unreachable

from tests.fixtures.centrum_processes import PreparingCentrum, preparing_centrum, stopped_for_maks

KEY = "github_pat_SYNTETYCZNY_KLUCZ_ZGLOSZEN"


def sent_report(centrum: PreparingCentrum, monkeypatch: pytest.MonkeyPatch) -> None:
    """Zgłoszenie „do Maksa” wysłane z tego komputera, z kluczem wpisanym przez Maksa; skrzynka daje mu numer 1."""

    (centrum.tmp_path / "config" / "zgloszenia-klucz.txt").write_text(KEY + "\n", encoding="utf-8")
    run_id = stopped_for_maks(centrum, monkeypatch)
    assert centrum.client.post(f"/api/runs/{run_id}/diagnosis").status_code == 200
    assert centrum.client.post(f"/api/runs/{run_id}/report").json() == {"state": "sent"}


def repaired(centrum: PreparingCentrum) -> bool:
    response = centrum.client.get("/api/reports/repair")
    assert response.status_code == 200, response.json()
    answer = response.json()
    assert set(answer) == {"repaired"}
    return bool(answer["repaired"])


def test_zamkniete_zgloszenie_z_biezacej_wersji_daje_powiadomienie_a_otwarte_nie(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    centrum = preparing_centrum(tmp_path)
    sent_report(centrum, monkeypatch)
    box = centrum.surroundings.report_box

    assert repaired(centrum) is False

    box.close(1)
    centrum.surroundings.clock.advance(minutes=10)

    assert repaired(centrum) is True
    assert box.asked == [[1], [1]]


def test_skrzynka_jest_pytana_przy_starcie_i_najwyzej_raz_na_10_minut(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    centrum = preparing_centrum(tmp_path)
    sent_report(centrum, monkeypatch)
    box, clock = centrum.surroundings.report_box, centrum.surroundings.clock

    repaired(centrum)
    repaired(centrum)
    clock.advance(minutes=9.9)
    repaired(centrum)

    assert len(box.asked) == 1

    clock.advance(minutes=0.1)
    repaired(centrum)
    repaired(centrum)

    assert len(box.asked) == 2

    centrum.restart()
    repaired(centrum)

    assert len(box.asked) == 3


def test_zamkniete_zgloszenie_nie_jest_pytane_ponownie_a_powiadomienie_zostaje_po_restarcie(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    centrum = preparing_centrum(tmp_path)
    sent_report(centrum, monkeypatch)
    box = centrum.surroundings.report_box
    box.close(1)
    assert repaired(centrum) is True

    centrum.restart()
    box.states_failure = Unreachable()

    assert repaired(centrum) is True
    assert box.asked == [[1]]


def test_po_aktualizacji_narzedzia_powiadomienie_znika(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    centrum = preparing_centrum(tmp_path)
    sent_report(centrum, monkeypatch)
    centrum.surroundings.report_box.close(1)
    assert repaired(centrum) is True

    centrum.surroundings.github.tool_commit = "9f8e7d6c5b4a39281706f5e4d3c2b1a098765432"
    centrum.restart()

    assert repaired(centrum) is False


@pytest.mark.parametrize("failure", [Unreachable(), Refused()], ids=["brak-sieci", "odmowa"])
def test_porazka_zapytania_przechodzi_po_cichu_z_ostatnim_znanym_stanem(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, failure: Refused | Unreachable
) -> None:
    centrum = preparing_centrum(tmp_path)
    sent_report(centrum, monkeypatch)
    box = centrum.surroundings.report_box
    box.close(1)
    box.states_failure = failure
    log_before = centrum.log_path.read_text(encoding="utf-8")

    assert repaired(centrum) is False
    assert len(box.asked) == 1
    assert centrum.log_path.read_text(encoding="utf-8") == log_before


def test_bez_wyslanych_zgloszen_albo_klucza_skrzynka_nie_jest_pytana(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    centrum = preparing_centrum(tmp_path)
    box = centrum.surroundings.report_box

    assert repaired(centrum) is False
    assert box.asked == []

    sent_report(centrum, monkeypatch)
    (tmp_path / "config" / "zgloszenia-klucz.txt").unlink()

    assert repaired(centrum) is False
    assert box.asked == []


def test_przy_starcie_centrum_skrzynka_jest_pytana_w_tle_przed_wejsciem_na_okresy(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    centrum = preparing_centrum(tmp_path)
    sent_report(centrum, monkeypatch)
    box = centrum.surroundings.report_box
    box.close(1)
    centrum.restart()

    with centrum.client:  # start Centrum, jak po kliknięciu skrótu
        deadline = time.monotonic() + 5
        while not box.asked and time.monotonic() < deadline:
            time.sleep(0.01)
        asked_at_start = list(box.asked)

        assert repaired(centrum) is True

    assert asked_at_start == [[1]]
    assert box.asked == [[1]]

"""Rodzaj Zatrzymania, powtórka i Diagnoza w Centrum rozliczeń przez HTTP API, jak widzi je przeglądarka."""

from __future__ import annotations

from pathlib import Path
from typing import NoReturn

import pytest

from rozliczenia import preparation_register

from tests.fixtures.centrum_processes import PreparingCentrum, preparing_centrum, run_to_end


def lock(path: Path) -> Path:
    """Plik blokady Excela obok skoroszytu, jak przy otwartym albo źle zamkniętym Excelu."""

    lock_file = path.with_name(f"~${path.name}")
    lock_file.touch()
    return lock_file


def stop_of(centrum: PreparingCentrum, *, dry_run: bool = True) -> dict[str, object]:
    result = run_to_end(centrum, dry_run=dry_run)["result"]
    assert result["ending"] != "finished", result
    return dict(result)


def test_zatrzymanie_dla_taty_proponuje_uruchom_ponownie(tmp_path: Path) -> None:
    centrum = preparing_centrum(tmp_path)
    lock(centrum.fixture.register_path)

    result = stop_of(centrum)

    assert (result["stop_kind"], result["next_action"]) == ("for_tata", "rerun")


def test_zatrzymanie_ktore_kaze_przekazac_komunikat_jest_do_maksa(tmp_path: Path) -> None:
    centrum = preparing_centrum(tmp_path)
    centrum.fixture.internal_template_path.unlink()

    result = stop_of(centrum)

    assert result["stop_kind"] == "for_maks"


def test_nieoczekiwany_blad_jest_do_maksa(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    centrum = preparing_centrum(tmp_path)

    def fail_unexpectedly(*args: object, **kwargs: object) -> NoReturn:
        raise RuntimeError("nieprzewidziany błąd przy SYN-001")

    monkeypatch.setattr(preparation_register, "read_register", fail_unexpectedly)

    result = stop_of(centrum)

    assert (result["ending"], result["stop_kind"]) == ("unexpected", "for_maks")


def test_identyczny_komunikat_przy_ponownym_uruchomieniu_to_powtorka(tmp_path: Path) -> None:
    centrum = preparing_centrum(tmp_path)
    lock(centrum.fixture.register_path)
    stop_of(centrum)

    again = stop_of(centrum)

    assert again["stop_kind"] == "repeated"


def test_inny_komunikat_przy_ponownym_uruchomieniu_nie_jest_powtorka(tmp_path: Path) -> None:
    centrum = preparing_centrum(tmp_path)
    register_lock = lock(centrum.fixture.register_path)
    stop_of(centrum)
    register_lock.unlink()
    lock(centrum.fixture.internal_template_path)

    again = stop_of(centrum)

    assert again["stop_kind"] == "for_tata"


def test_uruchomienie_bez_zatrzymania_przerywa_powtorke(tmp_path: Path) -> None:
    centrum = preparing_centrum(tmp_path)
    register_lock = lock(centrum.fixture.register_path)
    stop_of(centrum)
    register_lock.unlink()
    assert run_to_end(centrum, dry_run=True)["result"]["stop_kind"] is None
    lock(centrum.fixture.register_path)

    again = stop_of(centrum)

    assert again["stop_kind"] == "for_tata"


def test_restart_centrum_zeruje_pamiec_powtorki(tmp_path: Path) -> None:
    centrum = preparing_centrum(tmp_path)
    lock(centrum.fixture.register_path)
    stop_of(centrum)

    centrum.restart()
    again = stop_of(centrum)

    assert again["stop_kind"] == "for_tata"

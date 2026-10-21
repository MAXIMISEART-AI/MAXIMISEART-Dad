"""Kto na kogo czeka na maszynie pomiarów i jak długo (``tools/quiet_machine.py``), na zegarze testu."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from tests.fixtures.cicha_maszyna import MachineBusy, QuietMachine, ZegarTestu, quiet_machine

# Pomiar wydajnosc trwa około 5 minut (features/wydajnosc.md); agent ma 10 minut na jedno polecenie.
POMIAR_S = 5 * 60
LIMIT_POLECENIA_S = 10 * 60


@pytest.fixture
def zegar(monkeypatch: pytest.MonkeyPatch) -> ZegarTestu:
    clock = ZegarTestu()
    monkeypatch.setattr(quiet_machine, "time", clock)
    return clock


def maszyna(directory: Path, busy: list[str] | None = None) -> QuietMachine:
    return QuietMachine(directory, busy_processes=lambda: busy or [], report_every_s=None)


def trwajacy_pomiar(directory: Path) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    lock = directory / "pomiar.lock"
    lock.write_text(str(os.getpid()), encoding="utf-8")
    return lock


def test_przebieg_czeka_na_caly_trwajacy_pomiar_z_zapasem(tmp_path: Path, zegar: ZegarTestu) -> None:
    lock = trwajacy_pomiar(tmp_path)
    zegar.at(2 * POMIAR_S, lambda: lock.unlink())

    with maszyna(tmp_path).run() as waited:
        assert waited >= 2 * POMIAR_S


def test_przebieg_w_koncu_przestaje_czekac_i_nazywa_pomiar_ktory_trzyma_maszyne(
    tmp_path: Path, zegar: ZegarTestu
) -> None:
    trwajacy_pomiar(tmp_path)

    with pytest.raises(MachineBusy, match=rf"pomiar \(pid {os.getpid()}\)"):
        with maszyna(tmp_path).run():
            pass
    assert zegar.now >= 2 * POMIAR_S


def test_pomiar_czeka_na_cichy_procesor_krotko_nic_nie_trzymajac(tmp_path: Path, zegar: ZegarTestu) -> None:
    runs_waited: list[float] = []

    def run_during_wait() -> None:
        with maszyna(tmp_path).run() as waited:
            runs_waited.append(waited)

    zegar.at(60, run_during_wait)

    with pytest.raises(MachineBusy, match="pytest"):
        with maszyna(tmp_path, ["pytest"]).measurement():
            pass
    assert zegar.now + POMIAR_S <= LIMIT_POLECENIA_S
    assert runs_waited == [0]

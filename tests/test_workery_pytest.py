"""``pytest -n auto`` dzieli CPU między agentów na jednym laptopie, a jawna liczba i Windows dostają liczbę xdist."""

from __future__ import annotations

import os
import sys

import pytest


@pytest.mark.parametrize(
    ("platform", "load", "override", "workers"),
    [
        pytest.param("darwin", 0.0, None, 8, id="wolny laptop: polowa rdzeni"),
        pytest.param("darwin", 10.4, None, 2, id="zajety laptop: polowa wolnych rdzeni"),
        pytest.param("darwin", 30.0, None, 1, id="przeciazony laptop: jeden worker"),
        pytest.param("darwin", 0.0, "3", 3, id="PYTEST_XDIST_AUTO_NUM_WORKERS wygrywa"),
        pytest.param("win32", 0.0, None, 16, id="Windows bez load average: wszystkie rdzenie"),
    ],
)
def test_n_auto_bierze_workery_wedlug_obciazenia(
    pytestconfig: pytest.Config,
    monkeypatch: pytest.MonkeyPatch,
    platform: str,
    load: float,
    override: str | None,
    workers: int,
) -> None:
    monkeypatch.setattr(sys, "platform", platform)
    monkeypatch.setattr(os, "cpu_count", lambda: 16)
    monkeypatch.setattr(os, "getloadavg", lambda: (load, load, load), raising=False)
    if override is None:
        monkeypatch.delenv("PYTEST_XDIST_AUTO_NUM_WORKERS", raising=False)
    else:
        monkeypatch.setenv("PYTEST_XDIST_AUTO_NUM_WORKERS", override)

    assert pytestconfig.hook.pytest_xdist_auto_num_workers(config=pytestconfig) == workers

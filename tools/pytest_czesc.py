"""Plugin pytest: zadanie CI bierze ze swojego udziału dużego pliku testów tylko jego testy, bez listy id.

    python -m pytest -n auto -p tools.pytest_czesc --czesci czesci.json tests/test_a.py tests/test_b.py

``czesci.json`` to ``{"tests/test_a.py": {"n": 3, "udzialy": [1, 3]}}``: z pliku zostają testy, których
``crc32(nodeid) % 3`` to 0 albo 2. Plik bez wpisu zostaje cały. Id testu ma ``/`` na każdym systemie, a crc32 nie zależy
od ``PYTHONHASHSEED``, więc udziały 1..n dzielą plik bez luk i bez powtórzeń na każdym systemie i w każdym procesie, także
z testami, których plan nie znał. Lista id w linii poleceń nie wchodzi w grę: 3620 id jednego pliku przekracza 32 767
znaków linii Windows. Pod xdist każdy worker odznacza to samo, więc kontroler widzi zgodne kolekcje.
"""

from __future__ import annotations

import json
from pathlib import Path
import zlib

import pytest


def w_udziale(nodeid: str, n: int, udzialy: list[int]) -> bool:
    return zlib.crc32(nodeid.encode("utf-8")) % n + 1 in udzialy


def pytest_addoption(parser: pytest.Parser) -> None:
    parser.addoption("--czesci", type=Path, help="JSON: plik testów -> n i udziały 1..n, które biegną w tym zadaniu.")


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    sciezka: Path | None = config.getoption("--czesci")
    if sciezka is None:
        return
    czesci = json.loads(sciezka.read_text(encoding="utf-8"))
    zostaja: list[pytest.Item] = []
    odznaczone: list[pytest.Item] = []
    for item in items:
        czesc = czesci.get(item.nodeid.split("::")[0])
        (zostaja if czesc is None or w_udziale(item.nodeid, czesc["n"], czesc["udzialy"]) else odznaczone).append(item)
    config.hook.pytest_deselected(items=odznaczone)
    items[:] = zostaja

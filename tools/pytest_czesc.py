"""Plugin pytest: zadanie CI bierze ze swojego udziału dużego pliku testów tylko jego testy.

    python -m pytest -n auto -p tools.pytest_czesc --czesci czesci.json tests/test_a.py tests/test_b.py

``czesci.json`` to ``{"tests/test_a.py": {"n": 3, "udzialy": [1, 3], "testy": [[id, ...], [id, ...], [id, ...]]}}``:
z pliku zostają testy udziałów 1 i 3. ``testy`` to id testów każdego udziału z planu (``tools/plan_ci.py``, LPT po
zmierzonych czasach), a test spoza tych list (nowy po pomiarze, plik bez czasów testów) należy do udziału
``crc32(id) % n + 1``. Plik bez wpisu zostaje cały. Id testu ma ``/`` na każdym systemie, a crc32 nie zależy od
``PYTHONHASHSEED``, więc udziały 1..n dzielą plik bez luk i bez powtórzeń na każdym systemie i w każdym procesie.
Lista id w linii poleceń nie wchodzi w grę: 3620 id jednego pliku przekracza 32 767 znaków linii Windows. Pod xdist każdy worker odznacza to samo, więc kontroler widzi zgodne kolekcje.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
import json
from pathlib import Path
import zlib

import pytest


def udzial(nodeid: str, n: int, testy: Mapping[str, int]) -> int:
    """Numer udziału testu: z listy planu, a test spoza niej z crc32 swojego id."""

    return testy.get(nodeid) or zlib.crc32(nodeid.encode("utf-8")) % n + 1


def _przydzial(listy: Sequence[Sequence[str]]) -> dict[str, int]:
    return {test: numer for numer, testy in enumerate(listy, start=1) for test in testy}


def pytest_addoption(parser: pytest.Parser) -> None:
    parser.addoption("--czesci", type=Path, help="JSON: plik testów -> n, udziały 1..n, które biegną w tym zadaniu, i id testów każdego udziału.")


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    sciezka: Path | None = config.getoption("--czesci")
    if sciezka is None:
        return
    czesci = json.loads(sciezka.read_text(encoding="utf-8"))
    przydzialy = {plik: _przydzial(czesc["testy"]) for plik, czesc in czesci.items()}
    zostaja: list[pytest.Item] = []
    odznaczone: list[pytest.Item] = []
    for item in items:
        plik = item.nodeid.split("::")[0]
        czesc = czesci.get(plik)
        (zostaja if czesc is None or udzial(item.nodeid, czesc["n"], przydzialy[plik]) in czesc["udzialy"] else odznaczone).append(item)
    config.hook.pytest_deselected(items=odznaczone)
    items[:] = zostaja

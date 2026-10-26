"""Kształt bramki PR (ADR 0020): plan dwóch wzorcowych PR-ów mieści się w limicie liczby zadań i prognozy ściany.

L to PR z samym plikiem testu (#416), C to zmiana Centrum (#461): ``src/``, frontend i drive skilla. Ich zmienione
ścieżki i czasy CI jednego runu ``main`` leżą zamrożone w ``tests/fixtures/ksztalt_bramki``, więc plan zmienia się
tylko z kodem planu i wyboru testów albo z grafem zależności testów repozytorium. Liczą się zadania runu bez Mutation
checks i Change mutations, a prognoza to najdłuższa ściana zadania z planu.

Limit to wartość z HEAD PR, który wprowadził bramkę, plus 20%. Gdy test padnie, bramka urosła: najpierw znajdź
przyczynę (test, który zaczął zależeć od wszystkiego, wybór szerszy niż zmiana) i napraw ją w kodzie. Podniesienie
limitu to decyzja Maksa.
"""

from __future__ import annotations

from dataclasses import dataclass
import math
from pathlib import Path
import shutil
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

import czasy_ci  # noqa: E402
import plan_ci  # noqa: E402

PRZYPADKI = ROOT / "tests" / "fixtures" / "ksztalt_bramki"


@dataclass(frozen=True)
class Limit:
    zadania: int
    sciana_s: float


# Na HEAD bramki: L 5 zadań i 56,9 s, C 10 zadań i 219,2 s.
LIMITY = {"L": Limit(6, 68.3), "C": Limit(12, 263.0)}


@pytest.fixture(scope="module")
def czasy(tmp_path_factory: pytest.TempPathFactory) -> czasy_ci.Czasy:
    katalog = tmp_path_factory.mktemp("czasy-ci")
    for plik in (PRZYPADKI / "czasy-ci").glob("*.json"):
        shutil.copy2(plik, katalog / plik.name)
    (katalog / "pobrane").touch()
    zamrozone = czasy_ci.z_mainu(katalog, odswiez_po_s=math.inf)
    assert zamrozone.blad is None and zamrozone.runy
    return zamrozone


@pytest.mark.parametrize("przypadek", sorted(LIMITY))
def test_plan_bramki_wzorcowego_pr_miesci_sie_w_limicie_zadan_i_prognozy_sciany(przypadek: str, czasy: czasy_ci.Czasy) -> None:
    zmiana = frozenset((PRZYPADKI / f"{przypadek}.txt").read_text(encoding="utf-8").split())
    zakres = plan_ci.zakres("pull_request", zmiana)
    plan = plan_ci.rozplanuj([plan_ci.wycen(tor, zakres.pliki, czasy) for tor in zakres.tory], "pull_request", 0, czasy.runy)
    zadania = plan_ci.STALE_ZADANIA + len(plan.zadania)
    sciana = max(zadanie.sciana_s for zadanie in plan.zadania)
    limit = LIMITY[przypadek]

    assert (zadania <= limit.zadania, sciana <= limit.sciana_s) == (True, True), (
        f"przypadek {przypadek}: {zadania} zadań runu (limit {limit.zadania}), prognoza ściany {sciana:.1f} s (limit {limit.sciana_s} s),"
        f" {zakres.zrodlo}; podniesienie limitu to decyzja Maksa"
    )

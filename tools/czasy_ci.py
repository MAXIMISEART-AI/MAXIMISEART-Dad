"""Czasy CI: ile trwała każda jednostka pracy zadań ``ci.yml``, zmierzone w runie, a nie wpisane ręcznie.

Zapis zadania. Zadania ``pytest`` i ``mutations`` kończą się poleceniem ``zadanie``, które zapisuje jeden plik JSON
(artefakt ``czasy-zadanie-<zadanie>-<indeks macierzy>-<próba>``, 7 dni), także gdy zadanie padło:

    {"wersja": 1, "run": 40259456807, "proba": 1, "szablon": "pytest", "zadanie": "pytest (Python 3.14, 1/2)",
     "tor": "windows-3.14", "zdarzenie": "push", "sha": "31bb7651...", "narzut_s": 17.0,
     "jednostki": [{"klucz": "pytest:tests/test_adr.py", "s": 0.412, "status": "ok"}, ...], "bledy": []}

Tor to system runnera i jego Python (``windows-3.11``, ``windows-3.14``, ``linux-3.14``). Klucz jednostki nie zależy od
podziału na zadania, więc para tor i klucz wskazuje tę samą pracę w każdym runie:

    pytest:<plik testów>     suma setup + call + teardown testów pliku (junit pytest, ``junit_family = "xunit1"`` w pyproject.toml)
    krok:pytest              ściana kroku pytest zadania; ``krok:mutacje`` to ściana kroku Mutation checks
    krok:e2e                 krok E2E (verify-rozliczenia --variant all)
    krok:timing              trzy kroki straży czasu razem
    skill:<skill>/ci         podstawa skilla, z linii ``OK``/``FAIL`` ``tools/mutacje_skilli.py`` (pełne sekundy)
    skill:<skill>/<skrypt>   skrypt mutacji skilla, z tej samej linii

Status jednostki to ``ok`` albo ``fail``; pominięty krok i pominięty skrypt nie są jednostką. Czasy kroków i start zadania
podaje API zadań runu (``$GITHUB_API_URL/repos/<repo>/actions/runs/<run>/attempts/<próba>/jobs``, token z ``GH_TOKEN``,
z dokładnością do sekundy), w którym zadanie znajduje się po nazwie swojego runnera. Narzut to sekundy od startu zadania do startu pierwszego kroku jednostki.

Scalenie. Na pushu do main ``Required CI status`` pobiera zapisy runu i poleceniem ``scal`` tworzy ``czasy-ci.json``
(artefakt ``czasy-ci``, 30 dni), jedyne źródło czasów CI:

    {"wersja": 1, "runy": [{"run": 40259456807, "proba": 1, "sha": "31bb7651...", "zdarzenie": "push"}],
     "tory": {"windows-3.14": {"narzut:pytest": [{"run": 40259456807, "proba": 1, "zadanie": "...", "s": 17.0, "status": "ok"}],
                               "pytest:tests/test_adr.py": [...]}}}

Obserwacje klucza idą po runie, próbie i zadaniu, więc te same zapisy dają ten sam plik bajt w bajt.

Wejście, którego brakuje albo którego nie da się odczytać, daje linię ``CZASY CI FAIL | ...`` i kod 1, a zapis powstaje
z reszty. Pomiar nie zmienia werdyktu CI: jego kroki w ``ci.yml`` mają ``continue-on-error``.

    python tools/czasy_ci.py zadanie --tor Windows-3.14.0 --junit junit.xml --wyjscie zapis.json
    python3 tools/czasy_ci.py scal --katalog zapisy --wyjscie czasy-ci.json
"""

from __future__ import annotations

import argparse
from collections import defaultdict
from dataclasses import asdict, dataclass
from datetime import datetime
import json
import os
from pathlib import Path
import re
from typing import Literal
import urllib.request
from xml.etree import ElementTree

WERSJA = 1
Status = Literal["ok", "fail"]
# Kroki ci.yml, których czas jest jednostką; czasy kroków jednego klucza się sumują.
KROKI = {
    "Run tests": "krok:pytest",
    "Run tests (Linux)": "krok:pytest",
    "E2E (verify-rozliczenia --variant all)": "krok:e2e",
    "Timing guard: generate synthetic Wzorce": "krok:timing",
    "Timing guard: measure Przebieg rozliczeń (typowy tydzień)": "krok:timing",
    "Timing guard: report timings and enforce the budget": "krok:timing",
    "Run each verify skill's baseline check and prove it fails on broken variants": "krok:mutacje",
}
# Linia końca kroku ``tools/mutacje_skilli.py``; echo skryptów mutacji jej nie podrobi, bo nazwa kroku ma stałą postać.
KONIEC_KROKU = re.compile(
    r"(?P<wynik>OK {3}|FAIL )"
    r"(?:PODSTAWA (?P<podstawa>[\w.-]+)|\.agents/skills/(?P<skill>[\w.-]+)/scripts/(?P<skrypt>check_\w+_mutations\.py))"
    r" \((?P<s>\d+) s\)(?::|$)"
)
KONIEC_MUTACJI = "MUTACJE SKILLI "


@dataclass(frozen=True)
class Jednostka:
    klucz: str
    s: float
    status: Status


@dataclass(frozen=True)
class Zapis:
    run: int
    proba: int
    szablon: str  # id zadania w ci.yml
    zadanie: str  # nazwa zadania w runie
    tor: str
    zdarzenie: str
    sha: str
    narzut_s: float | None
    jednostki: tuple[Jednostka, ...]
    bledy: tuple[str, ...]


def _tor(runner: str) -> str:
    """``Windows-3.14.0`` → ``windows-3.14``."""

    system, _, wersja = runner.lower().partition("-")
    return f"{system}-{'.'.join(wersja.split('.')[:2])}"


def _junit(plik: Path) -> list[Jednostka]:
    try:
        korzen = ElementTree.parse(plik).getroot()
    except ElementTree.ParseError as error:
        raise ValueError(f"to nie jest XML ({error})") from None
    sekundy: dict[str, float] = defaultdict(float)
    porazki = set()
    for test in korzen.iter("testcase"):
        nazwa = test.get("file")
        if nazwa is None:
            raise ValueError(f"test {test.get('name')} bez atrybutu file (pytest bez junit_family = xunit1)")
        nazwa = nazwa.replace("\\", "/")
        sekundy[nazwa] += float(test.get("time", "0"))
        if test.find("failure") is not None or test.find("error") is not None:
            porazki.add(nazwa)
    if not sekundy:
        raise ValueError("brak testów")
    return [Jednostka(f"pytest:{nazwa}", round(s, 3), "fail" if nazwa in porazki else "ok") for nazwa, s in sorted(sekundy.items())]


def _mutacje(plik: Path) -> list[Jednostka]:
    linie = plik.read_text(encoding="utf-8", errors="replace").splitlines()
    if not any(linia.startswith(KONIEC_MUTACJI) for linia in linie):
        raise ValueError(f"brak linii {KONIEC_MUTACJI.strip()} OK/FAIL, więc Mutation checks nie skończyły się")
    jednostki = []
    for linia in linie:
        if koniec := KONIEC_KROKU.match(linia):
            krok = f"{koniec['podstawa']}/ci" if koniec["podstawa"] else f"{koniec['skill']}/{koniec['skrypt']}"
            jednostki.append(Jednostka(f"skill:{krok}", float(koniec["s"]), "ok" if koniec["wynik"].startswith("OK") else "fail"))
    return jednostki


def _chwila(tekst: str) -> float:
    return datetime.fromisoformat(tekst.replace("Z", "+00:00")).timestamp()


def _kroki(runner: str) -> tuple[str, float | None, list[Jednostka]]:
    """Nazwa zadania, narzut i jednostki-kroki zadania na runnerze ``runner`` z API zadań tej próby runu."""

    adres = (
        f"{os.environ['GITHUB_API_URL']}/repos/{os.environ['GITHUB_REPOSITORY']}/actions/runs/{os.environ['GITHUB_RUN_ID']}"
        f"/attempts/{os.environ['GITHUB_RUN_ATTEMPT']}/jobs?per_page=100"
    )
    prosba = urllib.request.Request(adres, headers={"Authorization": f"Bearer {os.environ['GH_TOKEN']}"})
    with urllib.request.urlopen(prosba, timeout=20) as odpowiedz:
        dane = json.load(odpowiedz)
    zadania = [zadanie for zadanie in dane["jobs"] if zadanie["runner_name"] == runner]
    if len(zadania) != 1:
        raise ValueError(f"{len(zadania)} zadań na runnerze {runner!r} zamiast jednego")
    zadanie = zadania[0]
    sekundy: dict[str, float] = defaultdict(float)
    porazki = set()
    pierwszy = None
    for krok in zadanie["steps"]:
        klucz = KROKI.get(krok["name"])
        if klucz is None or krok["conclusion"] not in ("success", "failure"):
            continue
        if pierwszy is None:
            pierwszy = _chwila(krok["started_at"])
        sekundy[klucz] += _chwila(krok["completed_at"]) - _chwila(krok["started_at"])
        if krok["conclusion"] == "failure":
            porazki.add(klucz)
    narzut = None if pierwszy is None else pierwszy - _chwila(zadanie["started_at"])
    jednostki = [Jednostka(klucz, s, "fail" if klucz in porazki else "ok") for klucz, s in sorted(sekundy.items())]
    return zadanie["name"], narzut, jednostki


def _zadanie(args: argparse.Namespace) -> int:
    bledy = []
    jednostki: list[Jednostka] = []
    nazwa, narzut = os.environ["GITHUB_JOB"], None
    try:
        nazwa, narzut, kroki = _kroki(os.environ["RUNNER_NAME"])
        jednostki += kroki
    except (OSError, ValueError, KeyError, TypeError) as error:
        bledy.append(f"API zadań runu: {error!r}")
    for plik, czytaj in ((args.junit, _junit), (args.mutacje, _mutacje)):
        if plik:
            try:
                jednostki += czytaj(plik)
            except (OSError, ValueError) as error:
                bledy.append(f"{plik.name}: {error!r}")
    zapis = Zapis(
        run=int(os.environ["GITHUB_RUN_ID"]),
        proba=int(os.environ["GITHUB_RUN_ATTEMPT"]),
        szablon=os.environ["GITHUB_JOB"],
        zadanie=nazwa,
        tor=_tor(args.tor),
        zdarzenie=os.environ["GITHUB_EVENT_NAME"],
        sha=os.environ["GITHUB_SHA"],
        narzut_s=narzut,
        jednostki=tuple(jednostki),
        bledy=tuple(bledy),
    )
    args.wyjscie.parent.mkdir(parents=True, exist_ok=True)
    args.wyjscie.write_text(json.dumps({"wersja": WERSJA, **asdict(zapis)}, indent=1), encoding="utf-8")
    for blad in bledy:
        print(f"CZASY CI FAIL | {blad}")
    print(f"CZASY CI | {zapis.zadanie} | {zapis.tor} | {len(jednostki)} jednostek | narzut {'?' if narzut is None else f'{narzut:.0f}'} s | {args.wyjscie.name}")
    return 1 if bledy else 0


def _wczytaj(plik: Path) -> Zapis:
    dane = json.loads(plik.read_text(encoding="utf-8"))
    if dane.pop("wersja") != WERSJA:
        raise ValueError(f"wersja zapisu inna niż {WERSJA}")
    return Zapis(**{**dane, "jednostki": tuple(Jednostka(**jednostka) for jednostka in dane["jednostki"])})


def _scal(args: argparse.Namespace) -> int:
    bledy = []
    tory: dict[str, dict[str, list[dict[str, object]]]] = defaultdict(lambda: defaultdict(list))
    runy = set()
    pliki = sorted(args.katalog.rglob("*.json"))
    for plik in pliki:
        try:
            zapis = _wczytaj(plik)
        except (OSError, ValueError, KeyError, TypeError) as error:
            bledy.append(f"{plik.name}: {error!r}")
            continue
        runy.add((zapis.run, zapis.proba, zapis.sha, zapis.zdarzenie))
        narzut = () if zapis.narzut_s is None else (Jednostka(f"narzut:{zapis.szablon}", zapis.narzut_s, "ok"),)
        for jednostka in (*zapis.jednostki, *narzut):
            obserwacja = {"run": zapis.run, "proba": zapis.proba, "zadanie": zapis.zadanie, "s": jednostka.s, "status": jednostka.status}
            tory[zapis.tor][jednostka.klucz].append(obserwacja)
    if not pliki:
        bledy.append(f"brak zapisów zadań w {args.katalog}")
    for blad in bledy:
        print(f"CZASY CI FAIL | {blad}")
    if not runy:
        return 1
    czasy = {
        "wersja": WERSJA,
        "runy": [{"run": run, "proba": proba, "sha": sha, "zdarzenie": zdarzenie} for run, proba, sha, zdarzenie in sorted(runy)],
        "tory": {
            tor: {klucz: sorted(obserwacje, key=lambda o: (o["run"], o["proba"], o["zadanie"])) for klucz, obserwacje in sorted(klucze.items())}
            for tor, klucze in sorted(tory.items())
        },
    }
    args.wyjscie.write_text(json.dumps(czasy, indent=1), encoding="utf-8")
    for tor, klucze in sorted(tory.items()):
        pliki_testow = sum(klucz.startswith("pytest:") for klucz in klucze)
        print(f"CZASY CI | {tor} | {len(klucze)} kluczy, w tym {pliki_testow} plików testów")
    print(f"CZASY CI SCALONE | {len(pliki) - len(bledy)} zapisów zadań | {args.wyjscie.name}")
    return 1 if bledy else 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    polecenia = parser.add_subparsers(dest="polecenie", required=True)
    zadanie = polecenia.add_parser("zadanie", help="Zapis czasów jednego zadania runu (w zadaniu CI).")
    zadanie.add_argument("--tor", required=True, help="System runnera i wersja Pythona, np. Windows-3.14.0.")
    zadanie.add_argument("--junit", type=Path, help="Junit pytest (junit_family = xunit1 w pyproject.toml).")
    zadanie.add_argument("--mutacje", type=Path, help="Wyjście tools/mutacje_skilli.py.")
    zadanie.add_argument("--wyjscie", type=Path, required=True)
    scal = polecenia.add_parser("scal", help="Scalenie zapisów zadań runu w czasy-ci.json (w Required na main).")
    scal.add_argument("--katalog", type=Path, required=True)
    scal.add_argument("--wyjscie", type=Path, required=True)
    args = parser.parse_args(argv)
    return _zadanie(args) if args.polecenie == "zadanie" else _scal(args)


if __name__ == "__main__":
    raise SystemExit(main())

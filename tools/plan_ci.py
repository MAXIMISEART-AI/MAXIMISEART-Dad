"""Plan CI: ile zadań pytest startuje w runie ``ci.yml``, co biegnie w każdym i czy biegną Change mutations.

Praca pytest to jednostki trzech torów (``TORY``: Windows 3.11, Windows 3.14, Linux 3.14): każdy plik testów
``tests/`` na każdym torze oraz kroki CI (``KROKI``) na swoich torach: E2E na obu Windows, straż czasu na Windows 3.14.
Koszt jednostki to ściana, którą dodaje do zadania: plik waży sumę czasów swoich testów przez ``WORKERY`` workerów
xdist, krok swój czas. Czasy to mediany z ostatnich runów main (``tools/czasy_ci.py``). Plik bez pomiaru waży medianę
plików toru, a bez żadnych pomiarów każdy plik waży ``DOMYSLNIE.plik_s``: plan to wypisuje i biegnie dalej, bo brak
czasów psuje tylko równowagę zadań, nie zbiór pracy.

Ściana zadania to narzut (od startu zadania do pracy), start pytest, suma kosztów jego jednostek i koniec zadania;
narzut i start też są z pomiarów. Plan dzieli każdy tor na najmniej zadań o ścianie najwyżej ``cel_s`` (LPT: najdłuższa jednostka do
zadania o najmniejszej sumie). Plik dłuższy niż zadanie dzieli się na k udziałów o tej samej wadze: udział k biegnie
z ``-p tools.pytest_czesc`` (crc32 id testu modulo k). Gdy run (``STALE_ZADANIA``, zadania pytest i
``ZADANIA_ZMIANY``, jeśli są mutacje zmiany) przekroczyłby ``ZADANIA_RUNU``, cel rośnie co ``KROK_CELU_S``.

Change mutations startują tylko na pull request, który ma mutacje zmiany albo wyjątek ``# mutacje-zmiany:`` w złej
postaci: plan liczy je tak samo jak ``tools/mutacje_zmiany.py``, bez testów i bez instalacji.

Plan ma ``digest``: zadanie wykonuje tylko plan, którego treść się z nim zgadza, i zapisuje go w swoim zapisie czasów,
a ``Required CI status`` (``werdykt``) przyjmuje tylko zapisy tego planu. Werdykt przepuszcza run, gdy każde zadanie
przeszło, zadanie pominięte to tylko takie, któremu plan nie dał pracy, a każde zadanie planu zgłosiło w ostatniej
próbie każdą swoją jednostkę (plik testów, krok) bez porażki. Plan, którego nie ma, jest czerwonym werdyktem z przyczyną.

    python3 tools/plan_ci.py plan --zdarzenie pull_request --baza HEAD^1 --czasy .ci-plan/czasy --wyjscie .ci-plan/plan.json
    python tools/plan_ci.py wykonaj --plan .ci-plan/plan.json --zadanie windows-3.14-2
    python3 tools/plan_ci.py werdykt --plan .ci-plan/plan.json --zapisy .ci-czasy/zapisy      # NEEDS: toJSON(needs)

Lokalnie plan na czasach z ``.git/czasy-ci`` (wspólnych z ``tools/szybko.py``) drukuje zadania i ich prognozę:

    .venv/bin/python tools/plan_ci.py plan --baza origin/main
"""

from __future__ import annotations

import argparse
from collections import defaultdict
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import asdict, dataclass
import hashlib
import json
import math
import os
from pathlib import Path
import statistics
import subprocess
import sys
import tempfile
import time

import czasy_ci
import mutacje_zmiany
import potomne

ROOT = Path(__file__).resolve().parents[1]
WERSJA = 1
WORKERY = 4  # pytest -n auto na runnerze 4 vCPU
JUNIT = Path(".ci-czasy", "junit.xml")
WYKONANIE = Path(".ci-czasy", "wykonanie.json")
CZESCI = Path(".ci-plan", "czesci.json")
# Domyślne python_files pytest: pyproject.toml go nie zmienia.
PLIKI_TESTOW = ("test_*.py", "*_test.py")
CEL_S = 225.0
KROK_CELU_S = 5.0
# Limit konta to 20 zadań naraz ze wszystkich workflowów; 20. slot zostaje dla scalenia.yml.
ZADANIA_RUNU = 19
# Zadania ci.yml o stałej liczbie (plan, szybkie, Mutation checks 3, Required) i części Change mutations.
STALE_ZADANIA = 6
ZADANIA_ZMIANY = 3
# Zadania ci.yml, które startują tylko z pracą od planu.
Z_PLANU = ("pytest", "change-mutations")


@dataclass(frozen=True)
class Domyslnie:
    """Wagi bez pomiaru, z runów 40276834805 i 40288016668 w zaokrągleniu."""

    plik_s: float = 20.0
    narzut_s: float = 15.0
    start_s: float = 25.0
    # Zapis czasów, wysłanie artefaktów i koniec zadania po pracy: 4–8 s w runie 40288016668. Zapis czasów go nie mierzy.
    koniec_s: float = 6.0


DOMYSLNIE = Domyslnie()


@dataclass(frozen=True)
class Krok:
    """Krok CI spoza pytest: polecenia po kolei, każde z limitem; ``{python}``, ``{temp}``, ``{podsumowanie}``.

    Polecenie to jeden napis z argumentami po spacji, bo ``tools/skille_dla_zmiany.py`` czyta z tego pliku, które
    polecenia skilli liczy CI, tak jak z ``ci.yml``.
    """

    nazwa: str
    polecenia: tuple[str, ...]
    limity_s: tuple[float, ...]
    domyslnie_s: float


E2E = Krok("e2e", ("{python} .agents/skills/verify-rozliczenia/scripts/run_verification.py --variant all",), (15 * 60,), 60.0)
# Straż czasu Przebiegu rozliczeń (spec #141, #145): benchmark „typowy tydzień” na syntetycznych Wzorcach kształtu
# Wzorców taty (tools/syntetyczne_wzorce.py), bo prawdziwych nie ma w repozytorium. Budżet 180 000 ms to mediana
# czasu ściany typowego tygodnia na runnerze; krok pada tylko powyżej niego. Docelowo 3 × cel twardy po przeliczeniu
# na runner: 3 × 18 s (Mac M4 Max) × ~3,3 ≈ 180 000 ms (Mac → komputer taty, i7-10875H; windows-latest ma podobną
# wydajność jednego rdzenia). Po #147 (ADR 0008) Przebieg trwa ~3 s na Macu, czyli ~10 s na runnerze: budżet
# przepuszcza szum współdzielonych runnerów, a łapie powrót do pełnego zapisu przez openpyxl (~240 s). To jedyne
# miejsce budżetu. Najdłuższy pomiar trwał 13 min (CI 20.10–25.10), mediana 1 min.
TIMING = Krok(
    "timing",
    (
        "{python} tools/syntetyczne_wzorce.py {temp}/syntetyczne-wzorce",
        "{python} tools/benchmark_przebiegu.py measure --scenario typowy-tydzien --templates-dir {temp}/syntetyczne-wzorce"
        " --config {temp}/syntetyczne-wzorce/worker_mapping.yaml --mirror-dir {temp}/lustro --journal {temp}/przebieg.jsonl"
        " --machine github-windows-latest",
        "{python} tools/benchmark_przebiegu.py guard --journal {temp}/przebieg.jsonl --budget-ms 180000 --summary {podsumowanie}",
    ),
    (10 * 60, 30 * 60, 10 * 60),
    25.0,
)
KROKI = {krok.nazwa: krok for krok in (E2E, TIMING)}


@dataclass(frozen=True)
class Tor:
    nazwa: str
    os: str
    python: str
    kroki: tuple[str, ...]
    etykieta: str  # w nazwie zadania, jak przed planem: "pytest (Python 3.14, Linux, 1/3)"


TORY = (
    Tor("windows-3.11", "windows-latest", "3.11", ("e2e",), "Python 3.11"),
    Tor("windows-3.14", "windows-latest", "3.14", ("e2e", "timing"), "Python 3.14"),
    Tor("linux-3.14", "ubuntu-latest", "3.14", (), "Python 3.14, Linux"),
)


@dataclass(frozen=True)
class Jednostka:
    """Praca, którą plan daje zadaniu: ``pytest:<plik>``, udział ``pytest:<plik>#k/n`` albo ``krok:<nazwa>``."""

    klucz: str
    s: float  # ściana, którą dodaje do zadania


@dataclass(frozen=True)
class Zadanie:
    id: str
    tor: str
    nazwa: str
    jednostki: tuple[str, ...]
    sciana_s: float


@dataclass(frozen=True)
class Plan:
    zdarzenie: str
    cel_s: float
    runy: tuple[int, ...]  # runy main, z których są czasy
    mutacje_zmiany: int
    zadania: tuple[Zadanie, ...]

    @property
    def digest(self) -> str:
        tresc = json.dumps(asdict(self), sort_keys=True, ensure_ascii=False)
        return hashlib.sha256(tresc.encode("utf-8")).hexdigest()

    def do_json(self) -> str:
        return json.dumps({"wersja": WERSJA, "digest": self.digest, **asdict(self)}, indent=1, ensure_ascii=False)

    @classmethod
    def z_json(cls, tekst: str) -> Plan:
        """Plan z pliku; treść niezgodna z ``digest`` to ``ValueError``, bo zadania biegłyby z innego planu."""

        dane = json.loads(tekst)
        if dane.pop("wersja", None) != WERSJA:
            raise ValueError(f"plan w wersji innej niż {WERSJA}")
        digest = dane.pop("digest")
        zadania = tuple(Zadanie(**{**zadanie, "jednostki": tuple(zadanie["jednostki"])}) for zadanie in dane.pop("zadania"))
        plan = cls(**{**dane, "runy": tuple(dane["runy"]), "zadania": zadania})
        if plan.digest != digest:
            raise ValueError(f"treść planu nie zgadza się z jego digest {digest[:12]}")
        return plan

    def macierz(self) -> list[dict[str, str]]:
        """``include`` macierzy zadania ``pytest`` w ci.yml (``[]``, gdy plan nie ma zadań: zadanie jest pominięte)."""

        tory = {tor.nazwa: tor for tor in TORY}
        return [{"id": z.id, "nazwa": z.nazwa, "os": tory[z.tor].os, "python": tory[z.tor].python} for z in self.zadania]


# --- plan ---


@dataclass(frozen=True)
class Wycena:
    """Koszty jednego toru: jednostki bez podziału plików, narzut i start pytest zadania."""

    tor: Tor
    pliki: Mapping[str, float]  # plik -> ściana całego pliku
    kroki: Mapping[str, float]
    narzut_s: float
    start_s: float

    def jednostki(self, pojemnosc_s: float) -> list[Jednostka]:
        """Pliki dłuższe niż ``pojemnosc_s`` w udziałach, które się w niej mieszczą, i kroki."""

        wynik = [Jednostka(f"krok:{nazwa}", s) for nazwa, s in self.kroki.items()]
        for plik, s in self.pliki.items():
            k = max(1, math.ceil(s / pojemnosc_s)) if pojemnosc_s > 0 else 1
            wynik += [Jednostka(f"pytest:{plik}", s)] if k == 1 else [Jednostka(f"pytest:{plik}#{i}/{k}", s / k) for i in range(1, k + 1)]
        return wynik


def pliki_testow(root: Path = ROOT) -> list[str]:
    return sorted({sciezka.relative_to(root).as_posix() for wzorzec in PLIKI_TESTOW for sciezka in (root / "tests").rglob(wzorzec)})


def wycen(tor: Tor, pliki: Sequence[str], czasy: czasy_ci.Czasy) -> Wycena:
    zmierzone = czasy.pliki(tor.nazwa)
    domyslny = statistics.median(zmierzone.values()) if zmierzone else DOMYSLNIE.plik_s
    kroki = {nazwa: czasy.praca(tor.nazwa, f"krok:{nazwa}") or KROKI[nazwa].domyslnie_s for nazwa in tor.kroki}
    zadania = [z for z in czasy.zadania(tor.nazwa) if "narzut:pytest" in z]
    narzuty = [z["narzut:pytest"] for z in zadania]
    # Start pytest: ściana pytest zadania ponad sumę jego testów na workerach (start, kolekcja, ogon workerów).
    starty = [z["krok:pytest"] - sum(s for k, s in z.items() if k.startswith("pytest:")) / WORKERY for z in zadania if "krok:pytest" in z]
    return Wycena(
        tor,
        {plik: zmierzone.get(plik, domyslny) / WORKERY for plik in pliki},
        kroki,
        statistics.median(narzuty) if narzuty else DOMYSLNIE.narzut_s,
        max(0.0, statistics.median(starty)) if starty else DOMYSLNIE.start_s,
    )


def _lpt(jednostki: Iterable[Jednostka], n: int) -> list[list[Jednostka]]:
    """Najdłuższa jednostka do zadania o najmniejszej sumie, remis po kluczu i numerze zadania."""

    zadania: list[list[Jednostka]] = [[] for _ in range(n)]
    sumy = [0.0] * n
    for jednostka in sorted(jednostki, key=lambda j: (-j.s, j.klucz)):
        najlzejsze = sumy.index(min(sumy))
        zadania[najlzejsze].append(jednostka)
        sumy[najlzejsze] += jednostka.s
    return zadania


def _upakuj(wycena: Wycena, cel_s: float) -> list[list[Jednostka]]:
    """Najmniej zadań toru, z których każde mieści się w ``cel_s``; jednostka dłuższa od celu stoi sama."""

    pojemnosc = cel_s - wycena.narzut_s - wycena.start_s - DOMYSLNIE.koniec_s
    jednostki = wycena.jednostki(pojemnosc)
    n = max(1, math.ceil(sum(j.s for j in jednostki) / pojemnosc)) if pojemnosc > 0 else len(jednostki)
    while True:
        zadania = _lpt(jednostki, n)
        if n >= len(jednostki) or max(sum(j.s for j in zadanie) for zadanie in zadania) <= pojemnosc:
            return [zadanie for zadanie in zadania if zadanie]
        n += 1


def rozplanuj(wyceny: Sequence[Wycena], zdarzenie: str, mutacje_zmiany: int, runy: tuple[int, ...] = ()) -> Plan:
    """Najmniej zadań na tor przy celu ``CEL_S``; gdy run przekroczyłby ``ZADANIA_RUNU``, cel rośnie o ``KROK_CELU_S``."""

    limit = ZADANIA_RUNU - STALE_ZADANIA - (ZADANIA_ZMIANY if mutacje_zmiany else 0)
    if limit < len(wyceny):
        raise ValueError(f"limit {ZADANIA_RUNU} zadań runu nie mieści po jednym zadaniu pytest na tor")
    cel = CEL_S
    podzial = [_upakuj(wycena, cel) for wycena in wyceny]
    while sum(map(len, podzial)) > limit:
        cel += KROK_CELU_S
        podzial = [_upakuj(wycena, cel) for wycena in wyceny]
    zadania = []
    for wycena, tor in zip(wyceny, podzial, strict=True):
        for numer, jednostki in enumerate(tor, start=1):
            # Najdłuższe pliki pierwsze: xdist zaczyna od nich, a kroki biegną po pytest.
            kolejne = sorted(jednostki, key=lambda j: (j.klucz.startswith("krok:"), -j.s, j.klucz))
            zadania.append(
                Zadanie(
                    id=f"{wycena.tor.nazwa}-{numer}",
                    tor=wycena.tor.nazwa,
                    nazwa=f"pytest ({wycena.tor.etykieta}, {numer}/{len(tor)})",
                    jednostki=tuple(j.klucz for j in kolejne),
                    sciana_s=round(wycena.narzut_s + wycena.start_s + sum(j.s for j in jednostki) + DOMYSLNIE.koniec_s, 1),
                )
            )
    return Plan(zdarzenie, cel, runy, mutacje_zmiany, tuple(zadania))


def _git(*argumenty: str) -> str:
    return subprocess.run(["git", *argumenty], cwd=ROOT, capture_output=True, text=True, encoding="utf-8", check=True).stdout


def liczba_mutacji_zmiany(baza: str) -> int:
    """Mutacje zmiany od ``merge-base`` HEAD z ``baza``, policzone jak w ``tools/mutacje_zmiany.py``, bez testów.

    Wyjątek ``# mutacje-zmiany:`` w złej postaci w zmienionym pliku to praca Change mutations także bez mutacji (np.
    przy zmianie samego komentarza): ich zadanie zgłasza go jako ``MUTACJE ZMIANY FAIL``, jak przed planem.
    """

    fragmenty = mutacje_zmiany.changes(_git("merge-base", "HEAD", baza).strip())
    teksty = {sciezka: (ROOT / sciezka).read_text(encoding="utf-8") for sciezka in fragmenty}
    liczba = sum(len(mutacje_zmiany.mutants(sciezka, tekst, fragmenty[sciezka])) for sciezka, tekst in teksty.items())
    try:
        for sciezka, tekst in teksty.items():
            mutacje_zmiany.exceptions(tekst, sciezka)
    except ValueError as error:
        print(f"MUTACJE ZMIANY | {error}; Change mutations startują, żeby to zgłosić")
        return max(liczba, 1)
    return liczba


def _katalog_czasow() -> Path:
    return (ROOT / _git("rev-parse", "--git-common-dir").strip() / "czasy-ci").resolve()


def _wypisz(plan: Plan, wyceny: Sequence[Wycena]) -> None:
    run = STALE_ZADANIA + len(plan.zadania) + (ZADANIA_ZMIANY if plan.mutacje_zmiany else 0)
    zrodlo = ", ".join(map(str, plan.runy)) or "brak (wagi domyślne)"
    print(f"PLAN CI | {plan.zdarzenie} | cel {plan.cel_s:.0f} s | {run} zadań runu (limit {ZADANIA_RUNU}) | mutacje zmiany {plan.mutacje_zmiany} | czasy z runów main: {zrodlo}")
    for wycena in wyceny:
        print(f"{wycena.tor.nazwa}: narzut {wycena.narzut_s:.0f} s, start pytest {wycena.start_s:.0f} s")
        for zadanie in (z for z in plan.zadania if z.tor == wycena.tor.nazwa):
            pliki = sum(klucz.startswith("pytest:") for klucz in zadanie.jednostki)
            reszta = [klucz for klucz in zadanie.jednostki if "#" in klucz or klucz.startswith("krok:")]
            print(f"  {zadanie.nazwa}: {zadanie.sciana_s:.0f} s | {pliki} plików {' '.join(reszta)}".rstrip())
    print(f"PLAN CI DIGEST | {plan.digest}")


def _plan(args: argparse.Namespace) -> int:
    katalog = args.czasy or _katalog_czasow()
    czasy = czasy_ci.z_mainu(katalog, odswiez_po_s=0 if args.czasy else czasy_ci.ODSWIEZ_S)
    if czasy.blad:
        print(f"CZASY CI | {czasy.blad}; plan waży pracę bez pomiaru domyślnie")
    pliki = pliki_testow()
    wyceny = [wycen(tor, pliki, czasy) for tor in TORY]
    mutacje = liczba_mutacji_zmiany(args.baza) if args.zdarzenie == "pull_request" else 0
    plan = rozplanuj(wyceny, args.zdarzenie, mutacje, czasy.runy)
    _wypisz(plan, wyceny)
    if args.wyjscie:
        args.wyjscie.parent.mkdir(parents=True, exist_ok=True)
        args.wyjscie.write_text(plan.do_json(), encoding="utf-8")
    if wyjscie := os.environ.get("GITHUB_OUTPUT"):
        with open(wyjscie, "a", encoding="utf-8") as plik:
            plik.write(f"pytest={json.dumps(plan.macierz(), ensure_ascii=False)}\nmutacje-zmiany={plan.mutacje_zmiany}\n")
    return 0


# --- wykonanie ---


def _pytest(pliki: Mapping[str, list[tuple[int, int]]]) -> tuple[str, ...]:
    czesci = {plik: {"n": udzialy[0][1], "udzialy": sorted(k for k, _ in udzialy)} for plik, udzialy in pliki.items() if udzialy}
    CZESCI.parent.mkdir(parents=True, exist_ok=True)
    CZESCI.write_text(json.dumps(czesci, indent=1), encoding="utf-8")
    # Bez '=' w argumentach: shim py (cmd) dzieli argument na '='.
    return (sys.executable, "-m", "pytest", "-n", "auto", "-p", "tools.pytest_czesc", "--czesci", str(CZESCI), *pliki, "--junitxml", str(JUNIT))


def _polecenia(krok: Krok) -> list[tuple[tuple[str, ...], float]]:
    wartosci = {
        "{python}": sys.executable,
        "{temp}": os.environ.get("RUNNER_TEMP", tempfile.gettempdir()),
        "{podsumowanie}": os.environ.get("GITHUB_STEP_SUMMARY", os.devnull),
    }

    def wstaw(argument: str) -> str:
        for znacznik, wartosc in wartosci.items():
            argument = argument.replace(znacznik, wartosc)
        return argument

    return [(tuple(map(wstaw, polecenie.split())), limit) for polecenie, limit in zip(krok.polecenia, krok.limity_s, strict=True)]


def _uruchom(nazwa: str, polecenia: Sequence[tuple[tuple[str, ...], float | None]]) -> dict[str, object]:
    """Polecenia po kolei do pierwszej porażki; wyjście na bieżąco, a drzewo procesów ginie z limitem."""

    print(f"== {nazwa}", flush=True)
    start, status = time.monotonic(), "ok"
    for polecenie, limit in polecenia:
        try:
            kod = potomne.run(polecenie, cwd=ROOT, timeout=limit, echo=True).returncode
        except subprocess.TimeoutExpired:
            print(f"{nazwa}: {polecenie[1]} przekroczył limit {limit:.0f} s", flush=True)
            kod = None
        if kod != 0:
            status = "fail"
            break
    s = round(time.monotonic() - start, 1)
    print(f"{'OK  ' if status == 'ok' else 'FAIL'} {nazwa} ({s:.0f} s)", flush=True)
    return {"klucz": nazwa, "s": s, "status": status}


def wykonaj(plan: Plan, zadanie_id: str) -> int:
    """Pytest z plikami i udziałami zadania, potem jego kroki, także po czerwonym pytest. Kod 1, gdy coś padło."""

    zadanie = next((z for z in plan.zadania if z.id == zadanie_id), None)
    if zadanie is None:
        print(f"WYKONANIE FAIL | plan {plan.digest[:12]} nie ma zadania {zadanie_id}")
        return 1
    pliki: dict[str, list[tuple[int, int]]] = defaultdict(list)
    kroki = []
    for klucz in zadanie.jednostki:
        nazwa, _, udzial = klucz.partition("#")
        if nazwa.startswith("pytest:"):
            k, _, n = udzial.partition("/")
            pliki[nazwa.removeprefix("pytest:")] += [(int(k), int(n))] if udzial else []
        else:
            kroki.append(KROKI[nazwa.removeprefix("krok:")])
    wyniki = [_uruchom("krok:pytest", [(_pytest(pliki), None)])] if pliki else []
    wyniki += [_uruchom(f"krok:{krok.nazwa}", _polecenia(krok)) for krok in kroki]
    WYKONANIE.parent.mkdir(parents=True, exist_ok=True)
    WYKONANIE.write_text(json.dumps({"plan": plan.digest, "zadanie": zadanie.id, "jednostki": wyniki}, indent=1), encoding="utf-8")
    padly = [str(wynik["klucz"]) for wynik in wyniki if wynik["status"] != "ok"]
    print(f"WYKONANIE FAIL | {', '.join(padly)}" if padly else f"WYKONANIE OK | {zadanie.nazwa}")
    return 1 if padly else 0


# --- Required ---


def werdykt(plan: Plan | None, wyniki_zadan: Mapping[str, str], zapisy: Sequence[czasy_ci.Zapis], *, brak_planu: str = "") -> list[str]:
    """Przyczyny czerwonego Required; pusta lista to zielony."""

    przyczyny = []
    if plan is None:
        przyczyny.append(f"plan CI: {brak_planu or 'brak planu'}; zadania pytest i Change mutations nie miały pracy")
    uruchomione = {} if plan is None else {"pytest": bool(plan.zadania), "change-mutations": plan.mutacje_zmiany > 0}
    for nazwa, wynik in wyniki_zadan.items():
        if wynik != "success" and not (wynik == "skipped" and uruchomione.get(nazwa) is False):
            przyczyny.append(f"{nazwa}={wynik}")
    if plan is None:
        return przyczyny
    ostatnie: dict[str, czasy_ci.Zapis] = {}
    for zapis in zapisy:
        if zapis.plan == plan.digest and zapis.zadanie_planu is not None:
            if zapis.zadanie_planu not in ostatnie or zapis.proba > ostatnie[zapis.zadanie_planu].proba:
                ostatnie[zapis.zadanie_planu] = zapis
    for zadanie in plan.zadania:
        if (ostatni := ostatnie.get(zadanie.id)) is None:
            przyczyny.append(f"{zadanie.nazwa}: brak zapisu czasów z tego planu, więc nic nie dowodzi, że jego jednostki biegły")
            continue
        # Udział pliku zapis czasów zgłasza jako cały plik (junit nie zna udziałów).
        zaplanowane = {klucz.partition("#")[0] for klucz in zadanie.jednostki}
        if brak := sorted(zaplanowane - {jednostka.klucz for jednostka in ostatni.jednostki}):
            przyczyny.append(f"{zadanie.nazwa}: jednostki bez wyniku: {', '.join(brak)}")
        # Druga linia obrony, gdyby zadanie z porażką skończyło się sukcesem.
        if padly := sorted(zaplanowane & {jednostka.klucz for jednostka in ostatni.jednostki if jednostka.status != "ok"}):
            przyczyny.append(f"{zadanie.nazwa}: jednostki z porażką: {', '.join(padly)}")
    return przyczyny


def _werdykt(args: argparse.Namespace) -> int:
    plan, brak = None, ""
    try:
        plan = Plan.z_json(args.plan.read_text(encoding="utf-8"))
    except (OSError, ValueError, KeyError, TypeError) as error:
        brak = f"{args.plan.as_posix()} nieczytelny ({error})"
    zapisy = []
    for sciezka in sorted(args.zapisy.rglob("*.json")) if args.zapisy.is_dir() else []:
        try:
            zapisy.append(czasy_ci.wczytaj(sciezka))
        except (OSError, ValueError, KeyError, TypeError) as error:
            print(f"CZASY CI FAIL | {sciezka.name}: {error!r}")
    wyniki = {zadanie: need["result"] for zadanie, need in json.loads(os.environ["NEEDS"]).items()}
    if przyczyny := werdykt(plan, wyniki, zapisy, brak_planu=brak):
        print("\n".join(f"REQUIRED FAIL | {przyczyna}" for przyczyna in przyczyny))
        return 1
    assert plan is not None
    jednostki = sum(len(zadanie.jednostki) for zadanie in plan.zadania)
    print(f"REQUIRED OK | {len(wyniki)} zadań, {len(plan.zadania)} zadań pytest z planu {plan.digest[:12]}, {jednostki} jednostek")
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    polecenia = parser.add_subparsers(dest="polecenie", required=True)
    plan = polecenia.add_parser("plan", help="Plan runu: zadania pytest i Change mutations (zadanie plan albo lokalnie).")
    plan.add_argument("--zdarzenie", choices=("pull_request", "push"), default="pull_request")
    plan.add_argument("--baza", default="origin/main", help="Od czego liczą się mutacje zmiany (w CI HEAD^1).")
    plan.add_argument("--czasy", type=Path, help="Katalog artefaktów czasy-ci, pobieranych od nowa (domyślnie .git/czasy-ci).")
    plan.add_argument("--wyjscie", type=Path)
    wykonanie = polecenia.add_parser("wykonaj", help="Jednostki jednego zadania planu (w zadaniu pytest).")
    wykonanie.add_argument("--plan", type=Path, required=True)
    wykonanie.add_argument("--zadanie", required=True)
    sad = polecenia.add_parser("werdykt", help="Required CI status: zadania i jednostki wobec planu (env NEEDS).")
    sad.add_argument("--plan", type=Path, required=True)
    sad.add_argument("--zapisy", type=Path, required=True)
    args = parser.parse_args(argv)
    if args.polecenie == "plan":
        return _plan(args)
    if args.polecenie == "werdykt":
        return _werdykt(args)
    try:
        wczytany = Plan.z_json(args.plan.read_text(encoding="utf-8"))
    except (OSError, ValueError, KeyError, TypeError) as error:
        print(f"WYKONANIE FAIL | plan {args.plan.as_posix()}: {error}")
        return 1
    return wykonaj(wczytany, args.zadanie)


if __name__ == "__main__":
    raise SystemExit(main())

"""Mutacje nocne (ADR 0021): mutacje linii zmienionych na ``main`` od ostatniej nocy i issue dla przeżytych.

Workflow ``mutacje-nocne.yml`` biegnie raz na dobę na ``main`` i ręcznie (``workflow_dispatch`` z opcjonalnym ``od``).

- ``plan`` ustala bazę: ``--od``, gdy jest, inaczej ``headSha`` ostatniego udanego runu tego workflow na ``main``,
  a bez niego (albo gdy ten commit nie jest przodkiem HEAD) ostatni commit linii pierwszych rodziców HEAD sprzed 24 h.
  Mutacje od bazy liczy jak ``tools/mutacje_zmiany.py`` (``selected``, bez testów), a zły wyjątek ``# mutacje-zmiany:``
  liczy jako jedną mutację, żeby część go zgłosiła. Dzieli je na części po najwyżej ``NA_CZESC`` mutacji, ale na
  najwyżej ``NAJWIECEJ_CZESCI`` części, i pisze do ``GITHUB_OUTPUT`` ``baza``, ``czesci`` (macierz numerów) i ``liczba``.
- Część k z n to ``tools/mutacje_zmiany.py --baza <baza> --czesc k/n --zapis …``: kolejne mutacje z listy
  posortowanej po plikach, więc pokrycie biegnie na testach kilku plików, nie całej zmiany dnia.
- ``zglos`` czyta zapisy części. Każdą przeżytą mutację przypisuje PR-owi, który ostatni zmienił jej linię: ``git blame``
  linii na HEAD daje commit, a numer PR podaje temat commitu linii pierwszych rodziców HEAD, który go wniósł
  (``Merge pull request #N`` albo squash ``… (#N)``); gałąź zbudowana na innej wnosi swoje commity do kilku PR-ów, a
  temat scalenia mówi, który z nich je scalił. Bez numeru w temacie PR podaje ``gh api …/commits/<sha>/pulls``. Na PR
  przypada jedno issue ``Przeżyte mutacje z #N`` z etykietami ``ETYKIETY``, a w nim linie ``MUTACJA <plik>:<linia> <opis>``
  (id jak w ``NIEWYKRYTA``). Linii, którą issue już ma w treści albo komentarzu, nie dostaje drugi raz; nowe linie idą
  do istniejącego issue komentarzem, a zamknięte issue z nowymi liniami wraca otwarte z ``ready-for-agent``.
  Część bez zapisu albo z porażką inną niż przeżyte mutacje (testy padają bez mutacji, zły wyjątek) czerwieni run po
  zgłoszeniu reszty, więc następna noc liczy od tej samej bazy, a zgłoszone linie się nie powtórzą.

Bazę i liczbę części nocy drukuje lokalnie bez testów:

    .venv/bin/python tools/mutacje_nocne.py plan
"""

from __future__ import annotations

import argparse
from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
import itertools
import json
import math
import os
from pathlib import Path
import re
import subprocess
import sys
from typing import Any

import mutacje_zmiany
from zgloszenia_ci import MERGE, REPO, SQUASH, GhApi, GitHub, blok_kodu

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = "mutacje-nocne.yml"
# Część Change mutations na PR liczyła pokrycie 6–10 min i ok. 10 s na mutację (runy 40543912115–40612759981 z 27–28.10),
# więc 25 mutacji to część na 10–15 min.
NA_CZESC = 25
# Nocą runnery są wolne, ale 60 zadań organizacji dzielą też inne workflowy.
NAJWIECEJ_CZESCI = 20
OKNO = timedelta(hours=24)
ETYKIETY = ("ready-for-agent", "przezyte-mutacje")
# Artefakt części k w mutacje-nocne.yml: ``mutacje-nocne-<k>`` z plikiem ``--zapis`` narzędzia mutacji.
ARTEFAKT = "mutacje-nocne-"
ZAPIS = "czesc.json"
STRONA = 100
_ID = re.compile(r"(?P<plik>[^:\s]+):(?P<linia>[1-9][0-9]*) \S.*")


def _git(root: Path, *argumenty: str) -> str:
    return subprocess.run(["git", *argumenty], cwd=root, capture_output=True, text=True, encoding="utf-8", check=True).stdout.strip()


def _przodek(root: Path, przodek: str, commit: str) -> bool:
    return subprocess.run(["git", "merge-base", "--is-ancestor", przodek, commit], cwd=root, capture_output=True, check=False).returncode == 0


# --- plan ---


def baza(github: GitHub, root: Path, od: str, teraz: datetime) -> tuple[str, str]:
    """SHA, od którego noc mutuje zmiany, i skąd go wzięła."""

    if od:
        return _git(root, "rev-parse", "--verify", f"{od}^{{commit}}"), f"--od {od}"
    runy = github.json(f"{REPO}/actions/workflows/{WORKFLOW}/runs?branch=main&status=success&per_page=1")["workflow_runs"]
    if runy and _przodek(root, runy[0]["head_sha"], "HEAD"):
        return runy[0]["head_sha"], f"ostatni udany run {runy[0]['id']}"
    przed = _git(root, "rev-list", "-1", "--first-parent", f"--before={(teraz - OKNO).isoformat()}", "HEAD")
    if not przed:
        raise ValueError("HEAD nie ma commitu sprzed 24 h; podaj --od")
    return przed, "24 h wstecz, bez udanego runu przodka HEAD"


def liczba_mutacji(od: str) -> int:
    """Mutacje zmiany od ``od`` do checkoutu, policzone jak w ``tools/mutacje_zmiany.py``, bez testów."""

    fragmenty = mutacje_zmiany.changes(od)
    teksty = {sciezka: (mutacje_zmiany.ROOT / sciezka).read_text(encoding="utf-8") for sciezka in fragmenty}
    liczba = sum(len(mutacje_zmiany.selected(sciezka, tekst, fragmenty[sciezka])) for sciezka, tekst in teksty.items())
    try:
        for sciezka, tekst in teksty.items():
            mutacje_zmiany.exceptions(tekst, sciezka)
    except ValueError as blad:
        print(f"MUTACJE NOCNE | {blad}; część mutacji to zgłosi")
        return max(liczba, 1)
    return liczba


def czesci(liczba: int) -> int:
    return min(NAJWIECEJ_CZESCI, math.ceil(liczba / NA_CZESC))


def _plan(od: str) -> int:
    od_sha, skad = baza(GhApi(), ROOT, od, datetime.now(UTC))
    liczba = liczba_mutacji(od_sha)
    n = czesci(liczba)
    print(f"MUTACJE NOCNE PLAN | baza {od_sha} ({skad}) | mutacje {liczba} | części {n}")
    if wyjscie := os.environ.get("GITHUB_OUTPUT"):
        with open(wyjscie, "a", encoding="utf-8") as plik:
            plik.write(f"baza={od_sha}\nczesci={json.dumps(list(range(1, n + 1)))}\nliczba={n}\n")
    return 0


# --- zgłoszenie ---


def zapisy(katalog: Path, liczba: int) -> tuple[list[str], list[str]]:
    """Przeżyte mutacje wszystkich części i przyczyny porażki części, które nie dały wyniku."""

    przezyte, problemy = [], []
    for numer in range(1, liczba + 1):
        try:
            zapis = json.loads((katalog / f"{ARTEFAKT}{numer}" / ZAPIS).read_text(encoding="utf-8"))
        except (OSError, ValueError) as blad:
            problemy.append(f"część {numer}/{liczba} bez zapisu: {blad}")
            continue
        if zapis.get("przezyte"):
            przezyte += zapis["przezyte"]
        elif not str(zapis.get("wynik")).startswith("MUTACJE ZMIANY OK"):
            problemy.append(f"część {numer}/{liczba}: {zapis.get('wynik')}")
    return przezyte, problemy


@dataclass(frozen=True)
class Autor:
    """PR (``numer``) albo, bez PR, commit, który ostatni zmienił linię mutacji: commity jednego PR to jeden autor."""

    numer: int | None
    commit: str | None = None

    @property
    def tytul(self) -> str:
        return f"Przeżyte mutacje z #{self.numer}" if self.numer else f"Przeżyte mutacje z commitu {str(self.commit)[:9]}"

    @property
    def nazwa(self) -> str:
        return f"#{self.numer}" if self.numer else f"commit {self.commit}"


def _pr_z_tematu(temat: str) -> int | None:
    znalezione = MERGE.fullmatch(temat) or SQUASH.fullmatch(temat)
    return int(znalezione["numer"]) if znalezione else None


def autor(github: GitHub, root: Path, od: str, commit: str) -> Autor:
    """PR, który wniósł ``commit`` na linię pierwszych rodziców HEAD po ``od``."""

    linia_main = _git(root, "rev-list", "--first-parent", "--reverse", f"{od}..HEAD").split()
    potomkowie = {commit, *_git(root, "rev-list", "--ancestry-path", f"{commit}..HEAD").split()}
    scalenie = next((kandydat for kandydat in linia_main if kandydat in potomkowie), None)
    if scalenie is not None and (numer := _pr_z_tematu(_git(root, "log", "-1", "--format=%s", scalenie))):
        return Autor(numer)
    scalone = [pr for pr in github.json(f"{REPO}/commits/{commit}/pulls") if pr.get("merged_at")]
    return Autor(int(scalone[0]["number"])) if scalone else Autor(None, commit)


def przypisz(github: GitHub, root: Path, od: str, przezyte: Sequence[str]) -> dict[Autor, list[str]]:
    """Przeżyte mutacje według PR-u, który ostatni zmienił ich linię."""

    commity: dict[str, Autor] = {}
    wynik: dict[Autor, list[str]] = {}
    for mutacja in przezyte:
        znalezione = _ID.fullmatch(mutacja)
        if znalezione is None:
            raise ValueError(f"przeżyta mutacja bez postaci <plik>:<linia> <opis>: {mutacja}")
        linia = znalezione["linia"]
        blame = _git(root, "blame", "--porcelain", "-L", f"{linia},{linia}", "HEAD", "--", znalezione["plik"])
        commit = blame.split(maxsplit=1)[0]
        if commit not in commity:
            commity[commit] = autor(github, root, od, commit)
        wynik.setdefault(commity[commit], []).append(mutacja)
    return wynik


@dataclass(frozen=True)
class Zaloz:
    tytul: str
    tresc: str


@dataclass(frozen=True)
class Uzupelnij:
    issue: int
    tresc: str
    otworz: bool  # issue jest zamknięte


Akcja = Zaloz | Uzupelnij


def _strony(github: GitHub, sciezka: str) -> Iterator[dict[str, Any]]:
    laczenie = "&" if "?" in sciezka else "?"
    for strona in itertools.count(1):
        partia = github.json(f"{sciezka}{laczenie}per_page={STRONA}&page={strona}")
        yield from partia
        if len(partia) < STRONA:
            return


def _ma(tekst: str, linia: str) -> bool:
    return any(obecna.strip() == linia or obecna.strip().startswith(f"{linia} |") for obecna in tekst.splitlines())


def akcje(github: GitHub, przypisane: dict[Autor, list[str]], run: str) -> list[Akcja]:
    """Nowe issue dla PR bez issue, a komentarz z nowymi liniami dla PR, którego issue ich jeszcze nie ma."""

    istniejace: dict[str, dict[str, Any]] = {}
    for znalezione in _strony(github, f"{REPO}/issues?labels={ETYKIETY[1]}&state=all"):
        if "pull_request" not in znalezione:
            istniejace.setdefault(znalezione["title"], znalezione)
    wynik: list[Akcja] = []
    for kto, mutacje in przypisane.items():
        linie = [f"MUTACJA {mutacja}" for mutacja in mutacje]
        issue = istniejace.get(kto.tytul)
        if issue is None:
            tresc = [
                f"Nocne mutacje `main` ([run]({run})) przeżyły testy na liniach, które ostatnio zmienił {kto.nazwa}:",
                "",
                *blok_kodu(linie),
                "",
                "Dla każdej linii `MUTACJA` dodaj test, który zabija tę mutację (dowód: `tools/mutacje.py`), albo napisz w komentarzu "
                "`MUTACJA <plik>:<linia> <opis> | nie warto, bo <powód>`.",
                "Gdy każda linia ma test albo powód, zamknij issue (ADR 0021).",
            ]
            wynik.append(Zaloz(kto.tytul, "\n".join(tresc)))
            continue
        znane = "\n".join([issue.get("body") or "", *(komentarz["body"] or "" for komentarz in _strony(github, f"{REPO}/issues/{issue['number']}/comments"))])
        if nowe := [linia for linia in linie if not _ma(znane, linia)]:
            tresc = [f"Nowe przeżyte mutacje z [runu]({run}):", "", *blok_kodu(nowe)]
            wynik.append(Uzupelnij(issue["number"], "\n".join(tresc), issue["state"] == "closed"))
    return wynik


def wykonaj(github: GitHub, wykonane: Sequence[Akcja]) -> list[str]:
    linie = []
    for akcja in wykonane:
        match akcja:
            case Zaloz(tytul, tresc):
                numer = github.wyslij("POST", f"{REPO}/issues", {"title": tytul, "body": tresc, "labels": list(ETYKIETY)})["number"]
                linie.append(f"MUTACJE NOCNE | założone #{numer} „{tytul}”")
            case Uzupelnij(issue, tresc, otworz):
                github.wyslij("POST", f"{REPO}/issues/{issue}/comments", {"body": tresc})
                if otworz:
                    github.wyslij("PATCH", f"{REPO}/issues/{issue}", {"state": "open"})
                    github.wyslij("POST", f"{REPO}/issues/{issue}/labels", {"labels": [ETYKIETY[0]]})
                linie.append(f"MUTACJE NOCNE | {'otwarte ponownie' if otworz else 'komentarz w'} #{issue}")
    return linie


def zglos(github: GitHub, root: Path, od: str, katalog: Path, liczba: int, run: str) -> int:
    przezyte, problemy = zapisy(katalog, liczba)
    linie = wykonaj(github, akcje(github, przypisz(github, root, od, przezyte), run))
    print("\n".join(linie) or "MUTACJE NOCNE | nic nowego do zgłoszenia")
    if problemy:
        print(f"MUTACJE NOCNE FAIL | {'; '.join(problemy)}")
        return 1
    print(f"MUTACJE NOCNE OK | części {liczba} | przeżyło {len(przezyte)}")
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    polecenia = parser.add_subparsers(dest="polecenie", required=True)
    plan = polecenia.add_parser("plan", help="Baza nocy, liczba mutacji i części (GITHUB_OUTPUT).")
    plan.add_argument("--od", default="", help="Commit, od którego liczyć zmiany (domyślnie ostatni udany run albo 24 h wstecz).")
    zgloszenie = polecenia.add_parser("zglos", help="Issue dla przeżytych mutacji ze wszystkich części.")
    zgloszenie.add_argument("--baza", required=True, help="Baza nocy z planu.")
    zgloszenie.add_argument("--zapisy", type=Path, required=True, help=f"Katalog z podkatalogami artefaktów {ARTEFAKT}<k>.")
    zgloszenie.add_argument("--czesci", type=int, required=True, help="Liczba części z planu.")
    zgloszenie.add_argument("--run", required=True, help="URL runu workflow.")
    args = parser.parse_args(argv)
    try:
        if args.polecenie == "plan":
            return _plan(args.od)
        return zglos(GhApi(), ROOT, args.baza, args.zapisy, args.czesci, args.run)
    except (RuntimeError, ValueError, KeyError, OSError, subprocess.CalledProcessError) as blad:
        szczegol = blad.stderr.strip() if isinstance(blad, subprocess.CalledProcessError) else blad
        print(f"MUTACJE NOCNE FAIL | {szczegol}")
        return 1


if __name__ == "__main__":
    sys.exit(main())

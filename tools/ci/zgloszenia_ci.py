"""Zgłoszenia CI (ADR 0020): issue dla flaky testów i dla czerwonego `main`, z workflow ``zgloszenia.yml`` po każdym runie CI.

Wejście to jeden zakończony run workflow ``CI``. Narzędzie najpierw ustala akcje (``Zaloz``, ``Skomentuj``, ``Zamknij``),
potem je wykonuje; z ``--bez-zapisu`` tylko je drukuje.

- **Flaky test.** Każdy test z artefaktów ``flaky-testy-*`` runu (``tools/lib/niestabilne_testy.py``) dostaje jedno
  otwarte issue ``Flaky test: <test>`` z etykietą ``flaky-test``: nowe albo komentarz do otwartego. Runu PR z forka
  narzędzie nie czyta, bo fork pisze własny ``ci.yml``. Z artefaktu bierze tylko id testu, które da się zgłosić (``niestabilne_testy.zgloszalny``),
  a wpis z innym odrzuca z linią w logu, nie ruszając reszty; id trafia do treści issue tylko w bloku kodu, przycięte.
  Commit, run i PR bierze z API runu.
- **Czerwony `main`.** Push na `main` z ``Required CI status`` ``failure`` zakłada issue ``CzerwonyMain`` z etykietą
  ``czerwony-main``, gdy żadne nie jest otwarte, a inaczej dopisuje komentarz do otwartego: jedno na raz. Issue ma
  ostatni zielony commit linii pierwszych rodziców `main`, PR-y scalone pomiędzy, przyczyny z linii ``REQUIRED FAIL``
  i polecenie ``git bisect``. Push na `main` z zielonym Required zamyka komentarzem z linkiem do runu otwarte issue,
  którego czerwony commit jest jego przodkiem.
- **Zderzenie** (Q26). Gdy scalenie PR B czerwieni `main` nową porażką, B ma zielone Required na swoim HEAD, a po
  utworzeniu runu tej bramki weszły do `main` PR-y A (także z zielonym Required na HEAD), których bramka B nie widziała,
  issue dostaje etykietę ``zderzenie`` z numerami A i B i liczbą zderzeń z ostatnich 7 dni. Porażka jest nowa, gdy
  `main` był zielony tuż przed scaleniem albo gdy czerwony rodzic nie miał tej porażki (test z linii ``FAILED``/``ERROR``
  pytest, a zadanie bez takiej linii po nazwie toru, bez numeru kawałka). Zderzenie na już czerwonym `main` zakłada
  własne issue obok otwartego.

Historię `main` narzędzie czyta z Gita checkoutu (w workflow pełna historia `main`), a resztę z ``gh api`` (w workflow
z ``GH_TOKEN``, lokalnie z logowaniem Maksa).

    .venv/bin/python tools/ci/zgloszenia_ci.py --run 40380584486 --bez-zapisu
"""

from __future__ import annotations

import argparse
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
import io
import json
from pathlib import Path
import re
import subprocess
import sys
from typing import Any, Protocol
import urllib.parse
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools/lib"))

import niestabilne_testy

ROOT = Path(__file__).resolve().parents[2]
REPO = "repos/{owner}/{repo}"
MAIN = "main"
REQUIRED = "Required CI status"
FLAKY_TEST, CZERWONY_MAIN, ZDERZENIE = "flaky-test", "czerwony-main", "zderzenie"
# Początek nazwy artefaktu, w którym każde zadanie pytest z ``ci.yml`` wysyła ``niestabilne_testy.FLAKY_TESTY``.
ARTEFAKT_FLAKY_TESTOW = "flaky-testy-"
# Tyle flaky testów jednego runu trafia do issue; reszta to znak awarii, a nie flaky testów.
NAJWIECEJ_FLAKY_TESTOW = 10
# Tyle nowych porażek zderzenia wymienia issue.
NAJWIECEJ_NOWYCH = 20
# Id testu w tytule i w treści issue (GitHub przyjmuje tytuł do 256 znaków).
DLUGOSC_W_TYTULE, DLUGOSC_W_TRESCI = 200, 2000
# Tyle commitów `main` wstecz szuka ostatniego zielonego.
HISTORIA = 50
OKNO_ZDERZEN = timedelta(days=7)
MERGE = re.compile(r"Merge pull request #(?P<numer>[1-9][0-9]*) from \S+")
SQUASH = re.compile(r"(?P<tytul>.+) \(#(?P<numer>[1-9][0-9]*)\)")
_ZNACZNIK = re.compile(r"<!-- czerwony-main (?P<sha>[0-9a-f]{40}) -->")
_RUN = re.compile(r"/actions/runs/(?P<run>[0-9]+)")
_PLIK_PYTEST = re.compile(r"pytest:(tests/[\w/]+\.py)")
# Linia podsumowania pytest w logu zadania, po znaczniku czasu GitHuba i kolorach terminala.
# Numer kawałka toru w nazwie zadania pytest (``pytest (Python 3.11, 2/3)``): plan dzieli tor na inną liczbę zadań w
# każdym runie, więc zadanie bez linii pytest porównuje się z rodzicem po torze.
_KAWALEK = re.compile(r", \d+/\d+(?=\)$)")
_PORAZKA = re.compile(r"(?:\S+Z )?(?:FAILED|ERROR) (?P<test>tests/[^\s\[]+(?:\[.*?\])?)(?: - .*)?")
_KOLOR = re.compile(r"\x1b\[[0-9;]*m")


class GitHub(Protocol):
    def json(self, sciezka: str) -> Any: ...

    def bajty(self, sciezka: str) -> bytes: ...

    def wyslij(self, metoda: str, sciezka: str, tresc: Mapping[str, object]) -> Any: ...


class GhApi:
    """``gh api`` z ``{owner}/{repo}`` repozytorium checkoutu."""

    def _gh(self, *argumenty: str, wejscie: bytes | None = None) -> bytes:
        odpowiedz = subprocess.run(["gh", "api", *argumenty], cwd=ROOT, input=wejscie, capture_output=True, timeout=120, check=False)
        if odpowiedz.returncode != 0:
            raise RuntimeError(f"gh api {' '.join(argumenty)}: {odpowiedz.stderr.decode('utf-8', errors='replace').strip()}")
        return odpowiedz.stdout

    def json(self, sciezka: str) -> Any:
        return json.loads(self._gh(sciezka))

    def bajty(self, sciezka: str) -> bytes:
        # Zip artefaktu i log zadania mają bajty sekwencji terminala, których gh bez tej flagi nie wypisze.
        return self._gh(sciezka, "--allow-escape-sequences")

    def wyslij(self, metoda: str, sciezka: str, tresc: Mapping[str, object]) -> Any:
        return json.loads(self._gh("--method", metoda, sciezka, "--input", "-", wejscie=json.dumps(tresc).encode("utf-8")))


@dataclass(frozen=True)
class Run:
    id: int
    url: str
    zdarzenie: str
    galaz: str
    sha: str
    wynik: str | None
    pr: tuple[int, ...]  # PR-y runu z tego repozytorium; run PR z forka ich nie ma
    z_forka: bool

    @classmethod
    def z_api(cls, dane: Mapping[str, Any]) -> Run:
        pr = tuple(int(pr["number"]) for pr in dane.get("pull_requests") or ())
        z_forka = (dane.get("head_repository") or {}).get("full_name") != (dane.get("repository") or {}).get("full_name")
        return cls(int(dane["id"]), dane["html_url"], dane["event"], dane["head_branch"], dane["head_sha"], dane["conclusion"], pr, z_forka)


@dataclass(frozen=True)
class PR:
    numer: int
    tytul: str


@dataclass(frozen=True)
class Zderzenie:
    niewidziane: tuple[PR, ...]  # PR-y scalone po utworzeniu runu zielonej bramki PR ``scalony``
    scalony: PR
    w_oknie: int  # zderzenia z ostatnich 7 dni, z tym
    nowe: tuple[str, ...]  # porażki, których nie miał czerwony rodzic; pusta, gdy rodzic był zielony


@dataclass(frozen=True)
class CzerwonyMain:
    commit: str
    run: str
    zielony: str | None
    zielony_run: str | None
    pr: tuple[PR, ...]
    przyczyny: tuple[str, ...]
    zderzenie: Zderzenie | None
    otwarte: int | None = None  # issue czerwonego `main`, który był czerwony już przed tym scaleniem

    @property
    def tytul(self) -> str:
        return f"Czerwony main od {self.commit[:9]}" + (f" (zderzenie {_numery(self.zderzenie.niewidziane)} i #{self.zderzenie.scalony.numer})" if self.zderzenie else "")

    @property
    def etykiety(self) -> tuple[str, ...]:
        return (CZERWONY_MAIN, *((ZDERZENIE,) if self.zderzenie else ()))

    @property
    def tresc(self) -> str:
        linie = [f"`main` jest czerwony od commitu {self.commit} ([run]({self.run})).", ""]
        if self.otwarte is not None:
            linie += [f"`main` był czerwony już przed tym scaleniem (#{self.otwarte}); to issue dotyczy nowych porażek.", ""]
        if self.zielony is None:
            linie += [f"Ostatniego zielonego commitu nie ma w {HISTORIA} commitach `main` wstecz.", ""]
        else:
            linie += [f"Ostatni zielony commit: {self.zielony} ([run]({self.zielony_run})).", "", f"PR-y scalone pomiędzy ({len(self.pr)}):"]
            linie += [f"- #{pr.numer} {pr.tytul}" for pr in self.pr] + [""]
        if self.zderzenie is not None:
            a, b = _numery(self.zderzenie.niewidziane), f"#{self.zderzenie.scalony.numer}"
            linie += [
                f"**Zderzenie:** {a} i {b} były zielone osobno, a zielona bramka {b} testowała `main` sprzed scalenia {a}.",
                f"To {self.zderzenie.w_oknie}. zderzenie w ostatnich 7 dniach; gdy się powtarzają, wraca decyzja o merge queue (ADR 0020).",
                "",
            ]
            if self.zderzenie.nowe:
                nowe = self.zderzenie.nowe
                reszta = [f"… i {len(nowe) - NAJWIECEJ_NOWYCH} więcej"] if len(nowe) > NAJWIECEJ_NOWYCH else []
                linie += ["Porażki, których nie było na czerwonym rodzicu:", "", *blok_kodu([*nowe[:NAJWIECEJ_NOWYCH], *reszta]), ""]
        if self.przyczyny:
            linie += ["Przyczyny z `Required CI status`:", "", "```", *self.przyczyny, "```", ""]
        if self.zielony is not None:
            pliki = sorted({plik for przyczyna in self.przyczyny for plik in _PLIK_PYTEST.findall(przyczyna)})
            test = f".venv/bin/python -m pytest {' '.join(pliki)}" if pliki else "<polecenie, które odtwarza porażkę>"
            linie += ["Winnego wskazuje bisect:", "", "```", f"git bisect start {self.commit} {self.zielony}", f"git bisect run {test}", "```", ""]
        linie += ["Naprawia osobny PR (`docs/agents/pr-i-ci.md`); następny zielony `main` zamyka to issue.", f"<!-- czerwony-main {self.commit} -->"]
        return "\n".join(linie)


def _numery(pr: Sequence[PR]) -> str:
    return ", ".join(f"#{p.numer}" for p in pr)


def blok_kodu(linie: Sequence[str]) -> list[str]:
    """Blok kodu z ``linie``: płot dłuższy od każdego ciągu backticków w nich, więc treść nie wyjdzie z bloku."""

    plot = "`" * max([3, *(len(ciag) + 1 for linia in linie for ciag in re.findall("`+", linia))])
    return [plot, *linie, plot]


def _przytnij(tekst: str, dlugosc: int) -> str:
    return tekst if len(tekst) <= dlugosc else f"{tekst[: dlugosc - 1]}…"


@dataclass(frozen=True)
class Zaloz:
    tytul: str
    tresc: str
    etykiety: tuple[str, ...]


@dataclass(frozen=True)
class Skomentuj:
    issue: int
    tresc: str


@dataclass(frozen=True)
class Zamknij:
    issue: int
    tresc: str


Akcja = Zaloz | Skomentuj | Zamknij


def akcje(github: GitHub, root: Path, run_id: int, teraz: datetime) -> list[Akcja]:
    run = Run.z_api(github.json(f"{REPO}/actions/runs/{run_id}"))
    return [*_flaky_testy(github, run), *_main(github, root, run, teraz)]


def wykonaj(github: GitHub, wykonane: Sequence[Akcja], *, bez_zapisu: bool) -> list[str]:
    linie = []
    for akcja in wykonane:
        if bez_zapisu:
            linie.append(f"ZGŁOSZENIA BEZ ZAPISU | {_opis(akcja)}\n" + "\n".join(f"    {linia}" for linia in akcja.tresc.splitlines()))
            continue
        match akcja:
            case Zaloz(tytul, tresc, etykiety):
                numer = github.wyslij("POST", f"{REPO}/issues", {"title": tytul, "body": tresc, "labels": list(etykiety)})["number"]
                linie.append(f"ZGŁOSZENIA | założone #{numer} „{tytul}”")
            case Skomentuj(issue, tresc):
                github.wyslij("POST", f"{REPO}/issues/{issue}/comments", {"body": tresc})
                linie.append(f"ZGŁOSZENIA | komentarz w #{issue}")
            case Zamknij(issue, tresc):
                github.wyslij("POST", f"{REPO}/issues/{issue}/comments", {"body": tresc})
                github.wyslij("PATCH", f"{REPO}/issues/{issue}", {"state": "closed", "state_reason": "completed"})
                linie.append(f"ZGŁOSZENIA | zamknięte #{issue}")
    return linie


def _opis(akcja: Akcja) -> str:
    match akcja:
        case Zaloz(tytul, _, etykiety):
            return f"załóż issue „{tytul}” z etykietami {', '.join(etykiety)}"
        case Skomentuj(issue, _):
            return f"skomentuj #{issue}"
        case Zamknij(issue, _):
            return f"zamknij #{issue} z komentarzem"


# --- flaky testy ---


def _artefakty(github: GitHub, run_id: int, poczatek: str) -> list[tuple[str, bytes]]:
    """Pliki JSON z niewygasłych artefaktów runu, których nazwa zaczyna się od ``poczatek``."""

    znalezione = github.json(f"{REPO}/actions/runs/{run_id}/artifacts?per_page=100")["artifacts"]
    pliki = []
    for artefakt in znalezione:
        if not artefakt["name"].startswith(poczatek) or artefakt["expired"]:
            continue
        with zipfile.ZipFile(io.BytesIO(github.bajty(f"{REPO}/actions/artifacts/{artefakt['id']}/zip"))) as archiwum:
            pliki += [(artefakt["name"], archiwum.read(nazwa)) for nazwa in archiwum.namelist() if nazwa.endswith(".json")]
    return pliki


def _flaky_testy(github: GitHub, run: Run) -> list[Akcja]:
    if run.z_forka:
        print(f"ZGŁOSZENIA | run {run.id} z forka: flaky testów nie zgłaszam")
        return []
    testy: dict[str, None] = {}
    for nazwa, plik in _artefakty(github, run.id, ARTEFAKT_FLAKY_TESTOW):
        try:
            flaky_testy, odrzucone = niestabilne_testy.flaky_testy_z_json(plik.decode("utf-8"))
        except (ValueError, UnicodeDecodeError) as blad:
            print(f"ZGŁOSZENIA | pominięty artefakt {nazwa}: {blad}")
            continue
        for powod in odrzucone:
            print(f"ZGŁOSZENIA | odrzucony wpis artefaktu {nazwa}: {powod}")
        testy |= dict.fromkeys(flaky.test for flaky in flaky_testy)
    if len(testy) > NAJWIECEJ_FLAKY_TESTOW:
        print(f"ZGŁOSZENIA | {len(testy)} flaky testów w runie, zgłaszam pierwsze {NAJWIECEJ_FLAKY_TESTOW}")
    if not testy:
        return []
    otwarte = {issue["title"]: issue["number"] for issue in _issues(github, FLAKY_TEST, "open")}
    pr = f", PR {', '.join(f'#{numer}' for numer in run.pr)}" if run.pr else ""
    wynik: list[Akcja] = []
    for test in list(testy)[:NAJWIECEJ_FLAKY_TESTOW]:
        opis = f"padł w [runie {run.id}]({run.url}) ({run.zdarzenie}, commit {run.sha}{pr}) i przeszedł po jednym ponowieniu."
        izolacja = "Ponowienie uruchamia same testy, które padły, więc przechodzi też test, który pada tylko po innym teście."
        tresc = "\n".join(["Test", "", *blok_kodu([_przytnij(test, DLUGOSC_W_TRESCI)]), "", opis, izolacja])
        tytul = f"Flaky test: {_przytnij(test, DLUGOSC_W_TYTULE)}"
        if tytul in otwarte:
            wynik.append(Skomentuj(otwarte[tytul], tresc))
        else:
            rada = "Napraw przyczynę albo wpisz test do `tests/fixtures/kwarantanna.py` z numerem tego issue, najwyżej na 7 dni (ADR 0020)."
            wynik.append(Zaloz(tytul, f"{tresc}\n\n{rada}", (FLAKY_TEST,)))
    return wynik


def _issues(github: GitHub, etykieta: str, stan: str, od: datetime | None = None) -> list[dict[str, Any]]:
    zapytanie = {"labels": etykieta, "state": stan, "per_page": "100", **({"since": od.strftime("%Y-%m-%dT%H:%M:%SZ")} if od else {})}
    return [issue for issue in github.json(f"{REPO}/issues?{urllib.parse.urlencode(zapytanie)}") if "pull_request" not in issue]


# --- czerwony main ---


def _main(github: GitHub, root: Path, run: Run, teraz: datetime) -> list[Akcja]:
    if run.zdarzenie != "push" or run.galaz != MAIN or run.wynik in (None, "cancelled", "skipped"):
        return []
    zadania = github.json(f"{REPO}/actions/runs/{run.id}/jobs?per_page=100")["jobs"]
    required = next((zadanie for zadanie in zadania if zadanie["name"] == REQUIRED), None)
    if required is None or required["conclusion"] not in ("success", "failure"):
        return []
    otwarte = _issues(github, CZERWONY_MAIN, "open")
    if required["conclusion"] == "success":
        zamkniecie = f"Zielony `main` na commicie {run.sha} ([run]({run.url}))."
        return [Zamknij(issue["number"], zamkniecie) for issue in otwarte if (znak := _ZNACZNIK.search(issue.get("body") or "")) and _przodek(root, znak["sha"], run.sha)]
    przyczyny = tuple(_przyczyny(github, required["id"]))
    nowe = _nowe_porazki(github, run, _git(root, "rev-parse", f"{run.sha}^1"))
    zderzenie = None if nowe is None else _zderzenie(github, root, run.sha, teraz, nowe)
    if otwarte and zderzenie is None:
        linie = [f"Nadal czerwony na commicie {run.sha} ([run]({run.url})).", *(["", "```", *przyczyny, "```"] if przyczyny else [])]
        return [Skomentuj(otwarte[0]["number"], "\n".join(linie))]
    zielony = _ostatni_zielony(github, root, run.sha)
    pr = _pr(root, zielony[0], run.sha) if zielony else ()
    poprzednie = otwarte[0]["number"] if otwarte else None
    czerwony = CzerwonyMain(run.sha, run.url, zielony[0] if zielony else None, zielony[1] if zielony else None, pr, przyczyny, zderzenie, poprzednie)
    return [Zaloz(czerwony.tytul, czerwony.tresc, czerwony.etykiety)]


def _nowe_porazki(github: GitHub, run: Run, rodzic: str) -> tuple[str, ...] | None:
    """Porażki runu, których nie miał rodzic: pusta krotka, gdy rodzic był zielony, a ``None``, gdy żadnej nowej nie ma
    albo stanu rodzica nie da się porównać (CI w toku, anulowane, bez logów)."""

    check = _required(github, rodzic)
    if check is None or check["status"] != "completed":
        return None
    if check["conclusion"] == "success":
        return ()
    run_rodzica = _RUN.search(check.get("details_url") or "")
    if check["conclusion"] != "failure" or run_rodzica is None:
        return None
    przed = _porazki(github, int(run_rodzica["run"]))
    nowe = tuple(sorted(_porazki(github, run.id) - przed))
    return nowe if przed and nowe else None


def _porazki(github: GitHub, run_id: int) -> frozenset[str]:
    """Testy z porażką w zadaniach runu, które padły (z linii ``FAILED``/``ERROR`` podsumowania pytest), a zadanie bez
    takiej linii po nazwie bez numeru kawałka toru."""

    porazki: set[str] = set()
    for zadanie in github.json(f"{REPO}/actions/runs/{run_id}/jobs?per_page=100")["jobs"]:
        if zadanie["conclusion"] != "failure" or zadanie["name"] == REQUIRED:
            continue
        log = _KOLOR.sub("", github.bajty(f"{REPO}/actions/jobs/{zadanie['id']}/logs").decode("utf-8", errors="replace"))
        testy = {znalezione["test"] for linia in log.splitlines() if (znalezione := _PORAZKA.fullmatch(linia.strip()))}
        porazki |= testy or {f"zadanie {_KAWALEK.sub('', zadanie['name'])}"}
    return frozenset(porazki)


def _git(root: Path, *argumenty: str) -> str:
    return subprocess.run(["git", *argumenty], cwd=root, capture_output=True, text=True, encoding="utf-8", check=True).stdout.strip()


def _przodek(root: Path, przodek: str, commit: str) -> bool:
    return subprocess.run(["git", "merge-base", "--is-ancestor", przodek, commit], cwd=root, capture_output=True, check=False).returncode == 0


def _required(github: GitHub, commit: str) -> dict[str, Any] | None:
    """Ostatni ``Required CI status`` commitu."""

    znalezione = github.json(f"{REPO}/commits/{commit}/check-runs?check_name={urllib.parse.quote(REQUIRED)}&per_page=100")["check_runs"]
    return max(znalezione, key=lambda check: check.get("started_at") or "", default=None)


def _ostatni_zielony(github: GitHub, root: Path, czerwony: str) -> tuple[str, str] | None:
    """Najnowszy commit linii pierwszych rodziców przed ``czerwony`` z zielonym Required i link do jego runu."""

    for commit in _git(root, "rev-list", "--first-parent", f"--max-count={HISTORIA}", czerwony).split()[1:]:
        check = _required(github, commit)
        if check is not None and check["status"] == "completed" and check["conclusion"] == "success":
            return commit, check.get("details_url") or ""
    return None


def _scalenia(root: Path, *zakres: str) -> list[tuple[datetime, PR]]:
    """PR-y scalone na linii pierwszych rodziców w ``zakres`` (merge albo squash), od najstarszego, z chwilą scalenia."""

    # Rekord kończy NUL: separatory \x1c-\x1f to dla str.strip() białe znaki.
    zapisy = _git(root, "log", "--first-parent", "--format=%cI%x1f%s%x1f%b%x00", *zakres).split("\x00")[:-1]
    znalezione = []
    for zapis in reversed(zapisy):
        czas, temat, tresc = zapis.lstrip("\n").split("\x1f", 2)
        if (scalenie := MERGE.fullmatch(temat)) is not None:
            tytul = next((linia.strip() for linia in tresc.splitlines() if linia.strip()), temat)
            znalezione.append((_chwila(czas), PR(int(scalenie["numer"]), tytul)))
        elif (squash := SQUASH.fullmatch(temat)) is not None:
            znalezione.append((_chwila(czas), PR(int(squash["numer"]), squash["tytul"])))
    return znalezione


def _pr(root: Path, zielony: str, czerwony: str) -> tuple[PR, ...]:
    return tuple(pr for _, pr in _scalenia(root, f"{zielony}..{czerwony}"))


def _zderzenie(github: GitHub, root: Path, czerwony: str, teraz: datetime, nowe: tuple[str, ...]) -> Zderzenie | None:
    """Zderzenie PR B, którego scalenie to ``czerwony``, z PR-ami scalonymi po utworzeniu runu jego zielonej bramki."""

    scalony = _scalenia(root, "-1", czerwony)
    if not scalony:
        return None
    b = scalony[0][1]
    check_b = _required(github, github.json(f"{REPO}/pulls/{b.numer}")["head"]["sha"])
    if check_b is None or check_b["conclusion"] != "success":
        return None
    # Bramka testuje scalenie PR z `main` z chwili utworzenia runu (także w ponowionej próbie), nie ze startu Required.
    run_b = _RUN.search(check_b.get("details_url") or "")
    start_b = _chwila(github.json(f"{REPO}/actions/runs/{run_b['run']}")["created_at"] if run_b else check_b["started_at"])
    niewidziane = [pr for czas, pr in _scalenia(root, f"--max-count={HISTORIA}", f"{czerwony}^1") if czas > start_b]
    zielone = [pr for pr in niewidziane if (check := _required(github, github.json(f"{REPO}/pulls/{pr.numer}")["head"]["sha"])) and check["conclusion"] == "success"]
    if not niewidziane or zielone != niewidziane:
        return None
    od = teraz - OKNO_ZDERZEN
    wczesniejsze = [issue for issue in _issues(github, ZDERZENIE, "all", od) if _chwila(issue["created_at"]) >= od]
    return Zderzenie(tuple(zielone), b, len(wczesniejsze) + 1, nowe)


def _chwila(tekst: str) -> datetime:
    return datetime.fromisoformat(tekst.replace("Z", "+00:00"))


def _przyczyny(github: GitHub, zadanie: int) -> list[str]:
    log = github.bajty(f"{REPO}/actions/jobs/{zadanie}/logs").decode("utf-8", errors="replace")
    return [linia[linia.index("REQUIRED FAIL") :].strip() for linia in log.splitlines() if "REQUIRED FAIL |" in linia][:20]


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--run", type=int, required=True, help="Id zakończonego runu workflow CI.")
    parser.add_argument("--bez-zapisu", action="store_true", help="Tylko drukuje akcje; niczego nie zakłada, nie komentuje i nie zamyka.")
    args = parser.parse_args(argv)
    github = GhApi()
    try:
        linie = wykonaj(github, akcje(github, ROOT, args.run, datetime.now(UTC)), bez_zapisu=args.bez_zapisu)
    except (RuntimeError, OSError, ValueError, KeyError, subprocess.SubprocessError, zipfile.BadZipFile) as blad:
        print(f"ZGŁOSZENIA FAIL | run {args.run}: {blad}")
        return 1
    print("\n".join(linie) or f"ZGŁOSZENIA | run {args.run}: nic do zgłoszenia")
    return 0


if __name__ == "__main__":
    sys.exit(main())

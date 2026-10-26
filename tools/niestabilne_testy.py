"""Niestabilne testy (ADR 0020): ponowienie testu, który padł w bramce PR, zapis flaka i zapis testów z kwarantanny.

Zadanie pytest (``tools/plan_ci.py wykonaj``) zapisuje dwa pliki, a dwa narzędzia je czytają z artefaktów runu:

- ``Flak``: test, który w zadaniu pytest bramki padł, a po jednym ponowieniu przeszedł. Lista trafia do ``FLAKI``
  (artefakt ``flaki-<zadanie>-<próba>``), a ``tools/zgloszenia_ci.py`` zakłada z niej issue ``Flak: <test>``.
- ``ZapisKwarantanny``: wynik każdego testu z kwarantanny, który biegł w zadaniu (artefakt ``kwarantanna-<zadanie>-<próba>``
  na pushu do `main`). Test z kwarantanny ma w junit własność ``WLASNOSC`` (``tests/conftest.py``). ``stan_kwarantanny``
  mówi ``tools/wydanie.py``, czy na commicie testy z kwarantanny przeszły.

Id testu to id pytest (``tests/test_x.py::Klasa::test_y[parametry]``), odtworzone z junit (``junit_family = "xunit1"``):
plik z atrybutu ``file``, klasy z ``classname`` za modułem tego pliku i nazwa z parametrami z ``name``.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import asdict, dataclass
import json
from pathlib import Path
import re
from typing import Literal
from xml.etree import ElementTree

FLAKI = Path(".ci-niestabilne", "flaki.json")
KWARANTANNA = Path(".ci-niestabilne", "kwarantanna.json")
# Id testu, które zgłoszenia przepisują do issue: artefakt runu z forka podaje je bez kontroli.
ID_TESTU = re.compile(r"tests/[\w/]+\.py(::\w+)+(\[[\w.,:=/+ -]*\])?")
DLUGOSC_ID = 300
# Własność junit testu z kwarantanny (``tests/conftest.py``), z powodem kwarantanny jako wartością.
WLASNOSC = "kwarantanna"

Wynik = Literal["przeszedł", "padł", "pominięty"]
StanKwarantanny = Literal["przeszła", "padła", "bez zapisu"]


@dataclass(frozen=True)
class Flak:
    test: str
    zadanie: str  # nazwa zadania w runie
    sha: str
    run: int
    proba: int


@dataclass(frozen=True)
class ZapisKwarantanny:
    zadanie: str  # id zadania planu
    proba: int
    sha: str
    wyniki: Mapping[str, Wynik]  # testy z kwarantanny, które biegły w zadaniu


def zapisz_flaki(flaki: Sequence[Flak], plik: Path = FLAKI) -> None:
    plik.parent.mkdir(parents=True, exist_ok=True)
    plik.write_text(json.dumps([asdict(flak) for flak in flaki], indent=1, ensure_ascii=False), encoding="utf-8")


def flaki_z_json(tekst: str) -> list[Flak]:
    """Flaki z artefaktu; ``ValueError``, gdy kształt albo id testu się nie zgadza (artefakt z forka to dane obce)."""

    dane = json.loads(tekst)
    if not isinstance(dane, list):
        raise ValueError("flaki to nie lista")
    flaki = []
    for wpis in dane:
        flak = Flak(**wpis)
        if not isinstance(flak.test, str) or len(flak.test) > DLUGOSC_ID or ID_TESTU.fullmatch(flak.test) is None:
            raise ValueError(f"id testu poza wzorcem {ID_TESTU.pattern}: {str(flak.test)[:80]!r}")
        flaki.append(flak)
    return flaki


def zapisz_kwarantanne(zapis: ZapisKwarantanny, plik: Path = KWARANTANNA) -> None:
    plik.parent.mkdir(parents=True, exist_ok=True)
    plik.write_text(json.dumps(asdict(zapis), indent=1, ensure_ascii=False), encoding="utf-8")


def kwarantanna_z_json(tekst: str) -> ZapisKwarantanny:
    return ZapisKwarantanny(**json.loads(tekst))


def stan_kwarantanny(zapisy: Iterable[ZapisKwarantanny]) -> StanKwarantanny:
    """Ostatnia próba każdego zadania runu: ``padła``, gdy test z kwarantanny gdzieś padł, ``bez zapisu``, gdy run nie
    ma zapisów albo test z kwarantanny nigdzie nie przeszedł (np. wszędzie pominięty), inaczej ``przeszła``."""

    ostatnie: dict[str, ZapisKwarantanny] = {}
    for zapis in zapisy:
        if zapis.zadanie not in ostatnie or zapis.proba > ostatnie[zapis.zadanie].proba:
            ostatnie[zapis.zadanie] = zapis
    if not ostatnie:
        return "bez zapisu"
    wyniki = [zapis.wyniki for zapis in ostatnie.values()]
    wpisy = {wpis for wynik in wyniki for wpis in wynik}
    if any(wynik.get(wpis) == "padł" for wynik in wyniki for wpis in wpisy):
        return "padła"
    if any(all(wynik.get(wpis) != "przeszedł" for wynik in wyniki) for wpis in wpisy):
        return "bez zapisu"
    return "przeszła"


def _id(test: ElementTree.Element) -> str | None:
    plik = (test.get("file") or "").replace("\\", "/")
    modul = plik.removesuffix(".py").replace("/", ".")
    klasy, nazwa = test.get("classname", ""), test.get("name")
    if not plik.endswith(".py") or nazwa is None or not (klasy == modul or klasy.startswith(f"{modul}.")):
        return None
    return "::".join([plik, *klasy[len(modul) :].split(".")[1:], nazwa])


def _testy(junit: Path) -> list[tuple[str | None, ElementTree.Element]]:
    return [(_id(test), test) for test in ElementTree.parse(junit).getroot().iter("testcase")]


def _wynik(test: ElementTree.Element) -> Wynik:
    if test.find("failure") is not None or test.find("error") is not None:
        return "padł"
    pominiety = test.find("skipped")
    if pominiety is None:
        return "przeszedł"
    return "padł" if pominiety.get("type") == "pytest.xfail" else "pominięty"


def padniete(junit: Path) -> tuple[str, ...] | None:
    """Id testów z porażką albo błędem; ``None``, gdy junit nie da się odczytać albo porażka nie ma id testu (błąd
    kolekcji): wtedy nie ma czego ponowić."""

    try:
        testy = _testy(junit)
    except (OSError, ElementTree.ParseError):
        return None
    padly = [(id_testu, test) for id_testu, test in testy if test.find("failure") is not None or test.find("error") is not None]
    if any(id_testu is None for id_testu, _ in padly):
        return None
    return tuple(dict.fromkeys(id_testu for id_testu, _ in padly if id_testu is not None))


def po_ponowieniu(junit: Path, ponowienie: Path, testy: Sequence[str]) -> bool:
    """Czy każdy z ``testy`` przeszedł w junit ``ponowienie``. Gdy tak, ``junit`` traci ich porażki, bo z niego zapis
    czasów zgłasza wynik pliku testów, który sprawdza ``Required CI status``."""

    try:
        wyniki = {id_testu: _wynik(test) for id_testu, test in _testy(ponowienie)}
    except (OSError, ElementTree.ParseError):
        return False
    if any(wyniki.get(test) != "przeszedł" for test in testy):
        return False
    drzewo = ElementTree.parse(junit)
    for test in drzewo.getroot().iter("testcase"):
        if _id(test) in testy:
            for porazka in [*test.findall("failure"), *test.findall("error")]:
                test.remove(porazka)
    drzewo.write(junit, encoding="utf-8", xml_declaration=True)
    return True


def wyniki_kwarantanny(junit: Path) -> dict[str, Wynik]:
    """Wynik każdego testu z kwarantanny w junit; jego xfail to porażka, a xpass przejście."""

    try:
        testy = _testy(junit)
    except (OSError, ElementTree.ParseError):
        return {}
    return {id_testu: _wynik(test) for id_testu, test in testy if id_testu and any(w.get("name") == WLASNOSC for w in test.iter("property"))}

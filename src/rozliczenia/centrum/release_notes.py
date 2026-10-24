"""Notka Wydania: tekst GitHub Release, który czyta też Powiadomienie o nowej wersji (ADR 0015).

Notka to „Co nowego” dla taty (2-5 zdań jego językiem), a pod nią, gdy są, rozwiązane sprawy taty ze Skrzynki
Zgłoszeń, każda w jednej linii z rodzajem, numerem i tytułem::

    Przygotowanie pliku zbiorczego samo wpisuje ilości usług.

    ## Rozwiązane sprawy taty

    - Uwaga taty #12: Brakuje ilości przy montażu
    - Zgłoszenie #7: Zatrzymanie przy pustym ADRES

Release jest publiczny, a Skrzynka prywatna, więc sprawa ma tylko numer i tytuł, nigdy treść. Ten moduł jest
jedynym miejscem formatu: notkę pisze ``render`` (narzędzie Wydań), a czyta ``parse`` (Centrum).
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
import re
from typing import Final

from rozliczenia.centrum import report_box

# Etykieta sprawy w Skrzynce Zgłoszeń → jej rodzaj w notce.
CASE_KINDS: Final[Mapping[str, str]] = {report_box.REPORT_LABEL: "Zgłoszenie", report_box.NOTE_LABEL: "Uwaga taty"}
CASES_HEADING: Final = "## Rozwiązane sprawy taty"
# Maks poprawia notkę ręcznie na GitHubie, więc nagłówek spraw może mieć inny poziom i spacje na końcu.
_CASES_HEADING_LINE: Final = re.compile(rf"^#+[ \t]+{re.escape(CASES_HEADING.lstrip('# '))}[ \t]*$", re.MULTILINE)

_CASE_LINE: Final = re.compile(r"- (?P<kind>.+?) #(?P<number>[1-9][0-9]*): (?P<title>.+)")


@dataclass(frozen=True)
class DadCase:
    """Sprawa taty ze Skrzynki Zgłoszeń, zamknięta jako rozwiązana: numer issue, tytuł i etykieta rodzaju."""

    number: int
    title: str
    label: str


@dataclass(frozen=True)
class ReleaseNotes:
    """Notka Wydania: „Co nowego” i rozwiązane sprawy taty."""

    summary: str
    cases: tuple[DadCase, ...]


def render(notes: ReleaseNotes) -> str:
    """Tekst notki; ``ValueError``, gdy „Co nowego” jest puste albo zawiera nagłówek spraw."""

    summary = notes.summary.strip()
    if not summary:
        raise ValueError("notka nie ma „Co nowego”")
    if _CASES_HEADING_LINE.search(summary):
        raise ValueError(f"„Co nowego” nie może zawierać nagłówka {CASES_HEADING!r}")
    if not notes.cases:
        return summary + "\n"
    lines = [f"- {CASE_KINDS[case.label]} #{case.number}: {' '.join(case.title.split())}" for case in notes.cases]
    return "\n".join([summary, "", CASES_HEADING, "", *lines]) + "\n"


def parse(text: str) -> ReleaseNotes:
    """Notka z tekstu ``render``; linia listy spraw, której nie da się odczytać, jest pomijana."""

    summary, *listed = _CASES_HEADING_LINE.split(text.replace("\r\n", "\n"), maxsplit=1)
    labels = {kind: label for label, kind in CASE_KINDS.items()}
    cases = tuple(
        DadCase(int(found["number"]), found["title"].strip(), labels[found["kind"]])
        for line in "".join(listed).splitlines()
        if (found := _CASE_LINE.fullmatch(line.strip())) is not None and found["kind"] in labels
    )
    return ReleaseNotes(summary.strip(), cases)

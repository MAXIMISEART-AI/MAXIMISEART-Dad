"""Skrzynka Zgłoszeń: adapter, przez który Centrum rozliczeń wysyła Zgłoszenia do Maksa.

Skrzynka jest wstrzykiwana do ``create_app`` obok platformy (ADR 0007). U taty
to prywatne repozytorium Zgłoszeń na GitHubie (``GitHubReportBox``), w
``verify-centrum-rozliczen`` katalog plików, a w testach API fałszywa skrzynka.
Skrzynka nie zna Centrum: dostaje gotowe Zgłoszenie i klucz taty, a zwraca
wynik bez wyjątków. Klucz nie trafia do wyniku, dziennika ani Zgłoszenia.

Każda operacja zwraca jeden z wyników: ``Sent`` (numer issue), ``Refused``
(skrzynka odmówiła: klucz wygasł albo jest nieważny) albo ``Unreachable``
(brak sieci albo skrzynka nie odpowiedziała jak zwykle). Kolejne operacje
(znajdź otwarte Zgłoszenie po odcisku problemu, stan wysłanych Zgłoszeń)
dostają ten sam kształt: metoda z kluczem i wynik z tych samych porażek.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Final, Literal, Protocol


@dataclass(frozen=True)
class Report:
    """Zgłoszenie: tytuł (kod i „Co się stało”), treść Markdown i odcisk problemu, po którym je rozpoznać."""

    title: str
    body: str
    fingerprint: str


@dataclass(frozen=True)
class Sent:
    """Skrzynka przyjęła Zgłoszenie jako issue o numerze ``number``."""

    number: int


@dataclass(frozen=True)
class Refused:
    """Skrzynka odmówiła: klucz wygasł, jest nieważny albo nie ma dostępu do repozytorium Zgłoszeń."""


@dataclass(frozen=True)
class Unreachable:
    """Skrzynka nie odpowiedziała jak zwykle: brak sieci, przekroczony czas albo awaria po stronie GitHuba."""


SendOutcome = Sent | Refused | Unreachable

# Stan Zgłoszenia w skrzynce: ``open`` czeka na naprawę, ``closed`` Maks zamknął po naprawie.
IssueState = Literal["open", "closed"]
# Stan każdego z pytanych numerów albo porażka całego zapytania.
StatesOutcome = Mapping[int, IssueState] | Refused | Unreachable


class ReportBox(Protocol):
    def send(self, report: Report, *, key: str) -> SendOutcome:
        """Zakłada Zgłoszenie w skrzynce z kluczem taty; nigdy nie rzuca wyjątku sieci."""
        ...

    def states(self, numbers: Sequence[int], *, key: str) -> StatesOutcome:
        """Stan wysłanych Zgłoszeń o numerach ``numbers``; nigdy nie rzuca wyjątku sieci."""
        ...


@dataclass(frozen=True)
class HttpRequest:
    method: str
    url: str
    headers: Mapping[str, str]
    body: bytes | None


@dataclass(frozen=True)
class HttpResponse:
    status: int
    body: bytes


# Transport HTTP skrzynki GitHuba; brak sieci to ``OSError``. Testy podstawiają własny, bez prawdziwego GitHuba.
Transport = Callable[[HttpRequest], HttpResponse]

REPOSITORY: Final = "MAXIMISEART-AI/MAXIMISEART-Dad-zgloszenia"
LABEL: Final = "zgloszenie"
_API: Final = "https://api.github.com"
_TIMEOUT_S: Final = 15.0
_REFUSALS: Final = frozenset({401, 403, 404})


def urllib_transport(request: HttpRequest) -> HttpResponse:
    """Żądanie HTTPS przez bibliotekę standardową; odpowiedź z kodem błędu HTTP to też odpowiedź."""

    sent = urllib.request.Request(request.url, data=request.body, headers=dict(request.headers), method=request.method)
    try:
        with urllib.request.urlopen(sent, timeout=_TIMEOUT_S) as response:
            return HttpResponse(response.status, response.read())
    except urllib.error.HTTPError as error:
        with error:
            return HttpResponse(error.code, error.read())


class GitHubReportBox:
    """Prywatne repozytorium Zgłoszeń na GitHubie przez REST API, z kluczem taty (token fine-grained Maksa)."""

    def __init__(self, repository: str = REPOSITORY, transport: Transport | None = None) -> None:
        self._repository = repository
        self._transport = transport

    def send(self, report: Report, *, key: str) -> SendOutcome:
        payload = {"title": report.title, "body": report.body, "labels": [LABEL]}
        transport = self._transport or urllib_transport  # odczyt przy wysyłce: testy blokują go w conftest
        try:
            response = transport(
                HttpRequest(
                    method="POST",
                    url=f"{_API}/repos/{self._repository}/issues",
                    headers={**_headers(key), "Content-Type": "application/json"},
                    body=json.dumps(payload).encode("utf-8"),
                )
            )
        except OSError:
            return Unreachable()
        if response.status in _REFUSALS:
            return Refused()
        number = _json_field(response.body, "number") if response.status == 201 else None
        return Sent(number) if isinstance(number, int) else Unreachable()

    def states(self, numbers: Sequence[int], *, key: str) -> StatesOutcome:
        transport = self._transport or urllib_transport  # odczyt przy zapytaniu: testy blokują go w conftest
        states: dict[int, IssueState] = {}
        for number in numbers:
            url = f"{_API}/repos/{self._repository}/issues/{number}"
            try:
                response = transport(HttpRequest(method="GET", url=url, headers=_headers(key), body=None))
            except OSError:
                return Unreachable()
            if response.status in _REFUSALS:
                return Refused()
            state = _json_field(response.body, "state") if response.status == 200 else None
            if state not in ("open", "closed"):
                return Unreachable()
            states[number] = "open" if state == "open" else "closed"
        return states


def _headers(key: str) -> dict[str, str]:
    return {
        "Accept": "application/vnd.github+json",
        "Authorization": f"Bearer {key}",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "centrum-rozliczen",
    }


def _json_field(body: bytes, name: str) -> object:
    try:
        document = json.loads(body)
    except ValueError:
        return None
    return document.get(name) if isinstance(document, dict) else None

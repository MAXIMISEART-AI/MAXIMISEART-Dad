"""Skrzynka Zgłoszeń: adapter, przez który Centrum rozliczeń wysyła Zgłoszenia do Maksa.

Skrzynka jest wstrzykiwana do ``create_app`` obok platformy (ADR 0007). U taty
to prywatne repozytorium Zgłoszeń na GitHubie (``GitHubReportBox``), w
``verify-centrum-rozliczen`` katalog plików, a w testach API fałszywa skrzynka.
Skrzynka nie zna Centrum: dostaje gotowe Zgłoszenie i klucz taty, a zwraca
wynik bez wyjątków. Klucz nie trafia do wyniku, dziennika ani Zgłoszenia.

Każda operacja zwraca jeden z wyników: ``Sent`` (numer issue), ``Refused``
(skrzynka odmówiła: klucz wygasł albo jest nieważny) albo ``Unreachable``
(brak sieci albo skrzynka nie odpowiedziała jak zwykle). Znalezienie otwartego
Zgłoszenia po odcisku problemu (``find_open``) daje numer issue albo ``None``
z tymi samymi porażkami; kolejne operacje dostają ten sam kształt.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
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
# Numer otwartego Zgłoszenia problemu albo ``None``, gdy otwartego nie ma (nigdy nie było albo Maks je zamknął).
FindOutcome = int | None | Refused | Unreachable

# Stan Zgłoszenia w skrzynce: ``open`` czeka na naprawę, ``closed`` Maks zamknął po naprawie.
IssueState = Literal["open", "closed"]
# Stan każdego z pytanych numerów albo porażka całego zapytania.
StatesOutcome = Mapping[int, IssueState] | Refused | Unreachable


class ReportBox(Protocol):
    def send(self, report: Report, *, key: str) -> SendOutcome:
        """Zakłada Zgłoszenie w skrzynce z kluczem taty; nigdy nie rzuca wyjątku sieci."""
        ...

    def find_open(self, fingerprint: str, *, key: str) -> FindOutcome:
        """Otwarte Zgłoszenie z odciskiem problemu ``fingerprint``; nigdy nie rzuca wyjątku sieci."""
        ...

    def states(self, numbers: Sequence[int], *, key: str) -> StatesOutcome:
        """Stan wysłanych Zgłoszeń o numerach ``numbers``; nigdy nie rzuca wyjątku sieci."""
        ...


@dataclass(frozen=True)
class HttpRequest:
    method: str
    url: str
    headers: Mapping[str, str] = field(repr=False)  # nagłówki niosą klucz taty
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
# Otwarte Zgłoszenia przegląda się stronami po 100; dziesięć stron to więcej, niż Maks kiedykolwiek będzie miał otwartych.
_PAGE_SIZE: Final = 100
_MAX_PAGES: Final = 10


def fingerprint_line(fingerprint: str) -> str:
    """Wiersz treści Zgłoszenia z odciskiem problemu, po którym skrzynka znajduje otwarte Zgłoszenie."""

    return f"- Odcisk problemu: {fingerprint}"


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

    def __init__(self, transport: Transport | None = None) -> None:
        self._transport = transport

    def send(self, report: Report, *, key: str) -> SendOutcome:
        payload = {"title": report.title, "body": report.body, "labels": [LABEL]}
        answer = self._exchange(
            HttpRequest(
                method="POST",
                url=f"{_API}/repos/{REPOSITORY}/issues",
                headers={**_headers(key), "Content-Type": "application/json"},
                body=json.dumps(payload).encode("utf-8"),
            )
        )
        if not isinstance(answer, HttpResponse):
            return answer
        number = _json_field(answer.body, "number") if answer.status == 201 else None
        return Sent(number) if isinstance(number, int) else Unreachable()

    def find_open(self, fingerprint: str, *, key: str) -> FindOutcome:
        """Przegląda otwarte issue z etykietą Zgłoszeń strona po stronie i szuka wiersza z odciskiem problemu."""

        line = fingerprint_line(fingerprint)
        for page in range(1, _MAX_PAGES + 1):
            url = f"{_API}/repos/{REPOSITORY}/issues?state=open&labels={LABEL}&per_page={_PAGE_SIZE}&page={page}"
            answer = self._exchange(HttpRequest(method="GET", url=url, headers=_headers(key), body=None))
            if not isinstance(answer, HttpResponse):
                return answer
            issues = _json(answer.body) if answer.status == 200 else None
            if not isinstance(issues, list):
                return Unreachable()
            for issue in issues:
                body = issue.get("body") if isinstance(issue, dict) else None
                if isinstance(body, str) and line in body.splitlines() and isinstance(issue.get("number"), int):
                    return int(issue["number"])
            if len(issues) < _PAGE_SIZE:
                break
        return None

    def states(self, numbers: Sequence[int], *, key: str) -> StatesOutcome:
        states: dict[int, IssueState] = {}
        for number in numbers:
            url = f"{_API}/repos/{REPOSITORY}/issues/{number}"
            answer = self._exchange(HttpRequest(method="GET", url=url, headers=_headers(key), body=None))
            if not isinstance(answer, HttpResponse):
                return answer
            state = _json_field(answer.body, "state") if answer.status == 200 else None
            if state not in ("open", "closed"):
                return Unreachable()
            states[number] = "open" if state == "open" else "closed"
        return states

    def _exchange(self, request: HttpRequest) -> HttpResponse | Refused | Unreachable:
        """Odpowiedź skrzynki na ``request``; brak sieci to ``Unreachable``, odmowa autoryzacji ``Refused``."""

        transport = self._transport or urllib_transport  # odczyt przy każdym żądaniu: testy blokują go w conftest
        try:
            response = transport(request)
        except OSError:
            return Unreachable()
        return Refused() if response.status in _REFUSALS else response


def _headers(key: str) -> dict[str, str]:
    return {
        "Accept": "application/vnd.github+json",
        "Authorization": f"Bearer {key}",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "centrum-rozliczen",
    }


def _json_field(body: bytes, name: str) -> object:
    document = _json(body)
    return document.get(name) if isinstance(document, dict) else None


def _json(body: bytes) -> object:
    try:
        return json.loads(body)
    except ValueError:
        return None

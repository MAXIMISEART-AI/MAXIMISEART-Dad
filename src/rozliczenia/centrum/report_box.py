"""Skrzynka Zgłoszeń: adapter, przez który Centrum rozliczeń pisze do Maksa.

Skrzynka jest wstrzykiwana do ``create_app`` obok platformy (ADR 0007). U taty
to prywatne repozytorium Zgłoszeń na GitHubie (``GitHubReportBox``), w
``verify-centrum-rozliczen`` katalog plików, a w testach API fałszywa skrzynka.
Skrzynka nie zna Centrum ani rodzajów treści: dostaje etykietę issue
(``zgloszenie``, ``kontrola-ilosci``, ``logi-uruchomienia``, ``uwaga-taty``),
gotowy tekst i klucz taty, a zwraca wynik bez wyjątków. Klucz nie trafia do
wyniku, dziennika ani issue.

Każda operacja zwraca wynik albo jedną z dwóch porażek: ``Refused`` (skrzynka
odmówiła: klucz wygasł albo jest nieważny) albo ``Unreachable`` (brak sieci
albo skrzynka nie odpowiedziała jak zwykle). Klucz, którego nie da się wysłać
w nagłówku HTTP (np. z BOM albo znakiem spoza ASCII), to ``Refused`` bez
zapytania: taki klucz nie może być ważny. Nowe issue to ``Sent`` z numerem,
komentarz ``Commented`` z identyfikatorem i adresem, a pytanie o issue z
etykietą (``labelled_issues``) daje ich numery i treści. ``find_issue`` wybiera z nich
najnowsze issue z wierszem rozpoznawczym: odciskiem problemu Zgłoszenia albo
tokenem okresu Kontroli ilości.
"""

from __future__ import annotations

import http.client
import json
import urllib.error
import urllib.request
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Final, Literal, Protocol


Label = Literal["zgloszenie", "kontrola-ilosci", "logi-uruchomienia", "uwaga-taty"]
"""Etykieta issue w Skrzynce Zgłoszeń; etykiety zakłada Maks w repozytorium Zgłoszeń, kod ich nie tworzy."""
REPORT_LABEL: Final[Label] = "zgloszenie"
# GitHub odrzuca treść issue i komentarza dłuższą niż tyle znaków.
COMMENT_LIMIT: Final = 65_536


@dataclass(frozen=True)
class Sent:
    """Skrzynka założyła issue o numerze ``number``."""

    number: int


@dataclass(frozen=True)
class Commented:
    """Skrzynka przyjęła komentarz: ``id`` z API i ``url`` do niego."""

    id: int
    url: str


@dataclass(frozen=True)
class Issue:
    """Issue z etykietą w skrzynce: numer i treść (pusta, gdy issue jej nie ma)."""

    number: int
    body: str


@dataclass(frozen=True)
class Refused:
    """Skrzynka odmówiła: klucz wygasł, jest nieważny albo nie ma dostępu do repozytorium Zgłoszeń."""


@dataclass(frozen=True)
class Unreachable:
    """Skrzynka nie odpowiedziała jak zwykle: brak sieci, przekroczony czas albo awaria po stronie GitHuba."""


SendOutcome = Sent | Refused | Unreachable
CommentOutcome = Commented | Refused | Unreachable
IssuesOutcome = tuple[Issue, ...] | Refused | Unreachable
# Numer znalezionego issue albo ``None``, gdy issue z tym wierszem nie ma (nigdy nie było albo Maks je zamknął).
FindOutcome = int | None | Refused | Unreachable

# Stan Zgłoszenia w skrzynce: ``open`` czeka na naprawę, ``closed`` Maks zamknął po naprawie.
IssueState = Literal["open", "closed"]
# Stan każdego z pytanych numerów albo porażka całego zapytania.
StatesOutcome = Mapping[int, IssueState] | Refused | Unreachable


class ReportBox(Protocol):
    def open_issue(self, label: Label, title: str, body: str, *, key: str) -> SendOutcome:
        """Zakłada issue z etykietą ``label`` kluczem taty; nigdy nie rzuca wyjątku sieci."""
        ...

    def comment(self, number: int, body: str, *, key: str) -> CommentOutcome:
        """Dopisuje komentarz do issue ``number``; nigdy nie rzuca wyjątku sieci."""
        ...

    def labelled_issues(self, label: Label, *, include_closed: bool, key: str) -> IssuesOutcome:
        """Otwarte issue z etykietą ``label``, z ``include_closed`` także zamknięte; nigdy nie rzuca wyjątku sieci."""
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


# Transport HTTP skrzynki GitHuba; brak sieci to ``OSError``, urwana albo nieczytelna odpowiedź ``HTTPException``. Testy podstawiają własny, bez prawdziwego GitHuba.
Transport = Callable[[HttpRequest], HttpResponse]

REPOSITORY: Final = "MAXIMISEART-AI/MAXIMISEART-Dad-zgloszenia"
_API: Final = "https://api.github.com"
_TIMEOUT_S: Final = 15.0
_REFUSALS: Final = frozenset({401, 403, 404})
# Issue z etykietą przegląda się stronami po 100; dziesięć stron to więcej, niż jedna etykieta kiedykolwiek będzie miała.
_PAGE_SIZE: Final = 100
_MAX_PAGES: Final = 10


def find_issue(box: ReportBox, label: Label, line: str, *, include_closed: bool, key: str) -> FindOutcome:
    """Najnowsze (o najwyższym numerze) issue z etykietą ``label`` i dokładnie wierszem ``line`` w treści."""

    issues = box.labelled_issues(label, include_closed=include_closed, key=key)
    if isinstance(issues, Refused | Unreachable):
        return issues
    return max((issue.number for issue in issues if line in issue.body.splitlines()), default=None)


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

    def open_issue(self, label: Label, title: str, body: str, *, key: str) -> SendOutcome:
        if not _sendable(key):
            return Refused()
        answer = self._post(f"{_API}/repos/{REPOSITORY}/issues", {"title": title, "body": body, "labels": [label]}, key)
        if not isinstance(answer, HttpResponse):
            return answer
        number = _json_field(answer.body, "number") if answer.status == 201 else None
        return Sent(number) if isinstance(number, int) else Unreachable()

    def comment(self, number: int, body: str, *, key: str) -> CommentOutcome:
        if not _sendable(key):
            return Refused()
        answer = self._post(f"{_API}/repos/{REPOSITORY}/issues/{number}/comments", {"body": body}, key)
        if not isinstance(answer, HttpResponse):
            return answer
        document = _json(answer.body) if answer.status == 201 else None
        if not isinstance(document, dict):
            return Unreachable()
        comment_id, url = document.get("id"), document.get("html_url")
        return Commented(comment_id, url) if isinstance(comment_id, int) and isinstance(url, str) else Unreachable()

    def labelled_issues(self, label: Label, *, include_closed: bool, key: str) -> IssuesOutcome:
        """Issue z etykietą strona po stronie; wpis bez numeru (nie issue) pomija, a porażka strony to porażka całości."""

        if not _sendable(key):
            return Refused()
        state = "all" if include_closed else "open"
        found: list[Issue] = []
        for page in range(1, _MAX_PAGES + 1):
            url = f"{_API}/repos/{REPOSITORY}/issues?state={state}&labels={label}&per_page={_PAGE_SIZE}&page={page}"
            answer = self._exchange(HttpRequest(method="GET", url=url, headers=_headers(key), body=None))
            if not isinstance(answer, HttpResponse):
                return answer
            entries = _json(answer.body) if answer.status == 200 else None
            if not isinstance(entries, list):
                return Unreachable()
            found.extend(issue for issue in map(_issue, entries) if issue is not None)
            if len(entries) < _PAGE_SIZE:
                break
        return tuple(found)

    def states(self, numbers: Sequence[int], *, key: str) -> StatesOutcome:
        if not _sendable(key):
            return Refused()
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

    def _post(self, url: str, payload: Mapping[str, object], key: str) -> HttpResponse | Refused | Unreachable:
        return self._exchange(
            HttpRequest(
                method="POST",
                url=url,
                headers={**_headers(key), "Content-Type": "application/json"},
                body=json.dumps(payload).encode("utf-8"),
            )
        )

    def _exchange(self, request: HttpRequest) -> HttpResponse | Refused | Unreachable:
        """Odpowiedź skrzynki na ``request``; brak sieci to ``Unreachable``, odmowa autoryzacji ``Refused``."""

        transport = self._transport or urllib_transport  # odczyt przy każdym żądaniu: testy blokują go w conftest
        try:
            response = transport(request)
        except (OSError, http.client.HTTPException):
            return Unreachable()
        return Refused() if response.status in _REFUSALS else response


def _sendable(key: str) -> bool:
    """Klucz da się wysłać w nagłówku ``Authorization``: widoczne znaki ASCII bez spacji, jak każdy token GitHuba."""

    return key.isascii() and key.isprintable() and " " not in key


def _headers(key: str) -> dict[str, str]:
    return {
        "Accept": "application/vnd.github+json",
        "Authorization": f"Bearer {key}",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "centrum-rozliczen",
    }


def _issue(entry: object) -> Issue | None:
    if not isinstance(entry, dict) or not isinstance(entry.get("number"), int):
        return None
    body = entry.get("body")
    return Issue(entry["number"], body if isinstance(body, str) else "")


def _json_field(body: bytes, name: str) -> object:
    document = _json(body)
    return document.get(name) if isinstance(document, dict) else None


def _json(body: bytes) -> object:
    try:
        return json.loads(body)
    except ValueError:
        return None

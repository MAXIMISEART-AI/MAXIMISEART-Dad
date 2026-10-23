"""Skrzynka Zgłoszeń na GitHubie: odpowiedzi REST zamienione na wyniki skrzynki, z podstawionym transportem HTTP.

Żaden test nie łączy się z prawdziwym GitHubem.
"""

from __future__ import annotations

import http.client
import json
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field

import pytest

from rozliczenia.centrum.report_box import (
    FindOutcome,
    GitHubReportBox,
    HttpRequest,
    HttpResponse,
    Label,
    Refused,
    SendOutcome,
    Sent,
    StatesOutcome,
    Unreachable,
)

TITLE = "BRAK_WZORCA: Nie znaleziono wzorca."
BODY = "## Komunikat\n"
FINGERPRINT = "0123456789abcdef"
KEY = "github_pat_SYNTETYCZNY"


@dataclass
class ScriptedTransport:
    """Transport HTTP, który zapisuje żądania i odpowiada przygotowaną odpowiedzią albo brakiem sieci."""

    answer: Callable[[], HttpResponse]
    requests: list[HttpRequest] = field(default_factory=list)

    def __call__(self, request: HttpRequest) -> HttpResponse:
        self.requests.append(request)
        return self.answer()


def send_with(
    answer: Callable[[], HttpResponse], label: Label = "zgloszenie"
) -> tuple[SendOutcome, ScriptedTransport]:
    transport = ScriptedTransport(answer)
    return GitHubReportBox(transport=transport).open_issue(label, TITLE, BODY, key=KEY), transport


def no_network() -> HttpResponse:
    raise OSError("brak sieci")


def cut_off() -> HttpResponse:
    raise http.client.IncompleteRead(b"{")


def test_utworzone_issue_to_wyslane_zgloszenie_z_numerem() -> None:
    outcome, transport = send_with(lambda: HttpResponse(201, json.dumps({"number": 42, "title": "x"}).encode()))

    assert outcome == Sent(42)
    [request] = transport.requests
    assert (request.method, request.url) == (
        "POST",
        "https://api.github.com/repos/MAXIMISEART-AI/MAXIMISEART-Dad-zgloszenia/issues",
    )
    assert request.headers["Authorization"] == f"Bearer {KEY}"
    assert request.body is not None
    assert json.loads(request.body) == {"title": TITLE, "body": BODY, "labels": ["zgloszenie"]}
    assert KEY not in repr(request)


@pytest.mark.parametrize("label", ["kontrola-ilosci", "logi-uruchomienia"])
def test_issue_dostaje_etykiete_swojego_rodzaju(label: Label) -> None:
    outcome, transport = send_with(lambda: HttpResponse(201, json.dumps({"number": 7}).encode()), label)

    assert outcome == Sent(7)
    [request] = transport.requests
    assert request.body is not None
    assert json.loads(request.body)["labels"] == [label]


@pytest.mark.parametrize("status", [401, 403, 404])
def test_odmowa_autoryzacji_to_odmowa_skrzynki(status: int) -> None:
    outcome, _ = send_with(lambda: HttpResponse(status, b'{"message": "Bad credentials"}'))

    assert outcome == Refused()


@pytest.mark.parametrize(
    "answer",
    [
        no_network,
        cut_off,
        lambda: HttpResponse(502, b"<html>Bad gateway</html>"),
        lambda: HttpResponse(201, b"to nie jest JSON"),
    ],
    ids=["brak-sieci", "urwana-odpowiedz", "awaria-githuba", "nieczytelna-odpowiedz"],
)
def test_brak_sieci_albo_niezwykla_odpowiedz_to_skrzynka_nieosiagalna(answer: Callable[[], HttpResponse]) -> None:
    outcome, _ = send_with(answer)

    assert outcome == Unreachable()


ISSUES = "https://api.github.com/repos/MAXIMISEART-AI/MAXIMISEART-Dad-zgloszenia/issues"
OTHER_FINGERPRINT = "fedcba9876543210"


def issue(number: int, fingerprint: str) -> dict[str, object]:
    return {"number": number, "body": f"## Narzędzie\n\n- Odcisk problemu: {fingerprint}\n- Commit: abc\n"}


def pages(*answers: list[dict[str, object]]) -> Callable[[], HttpResponse]:
    remaining: Iterator[list[dict[str, object]]] = iter(answers)
    return lambda: HttpResponse(200, json.dumps(next(remaining)).encode())


def find_with(answer: Callable[[], HttpResponse]) -> tuple[FindOutcome, ScriptedTransport]:
    transport = ScriptedTransport(answer)
    return GitHubReportBox(transport=transport).find_open(FINGERPRINT, key=KEY), transport


def test_otwarte_issue_z_odciskiem_problemu_to_znalezione_zgloszenie() -> None:
    outcome, transport = find_with(
        pages([issue(3, OTHER_FINGERPRINT), issue(7, FINGERPRINT), {"number": 8, "body": None}])
    )

    assert outcome == 7
    [request] = transport.requests
    assert (request.method, request.url, request.body) == (
        "GET",
        f"{ISSUES}?state=open&labels=zgloszenie&per_page=100&page=1",
        None,
    )
    assert request.headers["Authorization"] == f"Bearer {KEY}"


def test_bez_otwartego_issue_z_odciskiem_nie_ma_zgloszenia_takze_po_przejrzeniu_kolejnych_stron() -> None:
    full_page = [issue(number, OTHER_FINGERPRINT) for number in range(100, 200)]
    outcome, transport = find_with(pages(full_page, [issue(5, OTHER_FINGERPRINT)]))

    assert outcome is None
    assert [request.url.rsplit("=", 1)[1] for request in transport.requests] == ["1", "2"]


def test_otwarte_issue_z_odciskiem_na_drugiej_stronie_to_znalezione_zgloszenie() -> None:
    full_page = [issue(number, OTHER_FINGERPRINT) for number in range(100, 200)]
    outcome, _ = find_with(pages(full_page, [issue(42, FINGERPRINT)]))

    assert outcome == 42


@pytest.mark.parametrize("status", [401, 403, 404])
def test_odmowa_autoryzacji_przy_szukaniu_to_odmowa_skrzynki(status: int) -> None:
    outcome, _ = find_with(lambda: HttpResponse(status, b'{"message": "Bad credentials"}'))

    assert outcome == Refused()


@pytest.mark.parametrize(
    "answer",
    [
        no_network,
        lambda: HttpResponse(502, b"<html>Bad gateway</html>"),
        lambda: HttpResponse(200, b'{"message": "to nie jest lista"}'),
    ],
    ids=["brak-sieci", "awaria-githuba", "nieczytelna-odpowiedz"],
)
def test_brak_sieci_albo_niezwykla_odpowiedz_przy_szukaniu_to_skrzynka_nieosiagalna(
    answer: Callable[[], HttpResponse],
) -> None:
    outcome, _ = find_with(answer)

    assert outcome == Unreachable()


def issue_in(state: str) -> HttpResponse:
    return HttpResponse(200, json.dumps({"number": 1, "state": state, "title": "x"}).encode())


def states_with(*answers: Callable[[], HttpResponse]) -> tuple[StatesOutcome, ScriptedTransport]:
    queued = iter(answers)
    transport = ScriptedTransport(lambda: next(queued)())
    return GitHubReportBox(transport=transport).states([7, 9], key=KEY), transport


def test_stan_wyslanych_zgloszen_to_stan_ich_issue() -> None:
    outcome, transport = states_with(lambda: issue_in("closed"), lambda: issue_in("open"))

    assert outcome == {7: "closed", 9: "open"}
    assert [(request.method, request.url) for request in transport.requests] == [
        ("GET", "https://api.github.com/repos/MAXIMISEART-AI/MAXIMISEART-Dad-zgloszenia/issues/7"),
        ("GET", "https://api.github.com/repos/MAXIMISEART-AI/MAXIMISEART-Dad-zgloszenia/issues/9"),
    ]
    assert all(request.headers["Authorization"] == f"Bearer {KEY}" for request in transport.requests)
    assert all(request.body is None for request in transport.requests)


@pytest.mark.parametrize("status", [401, 403, 404])
def test_odmowa_przy_stanie_zgloszen_to_odmowa_skrzynki(status: int) -> None:
    outcome, _ = states_with(lambda: issue_in("open"), lambda: HttpResponse(status, b'{"message": "Not Found"}'))

    assert outcome == Refused()


@pytest.mark.parametrize(
    "answer",
    [
        no_network,
        lambda: HttpResponse(502, b"<html>Bad gateway</html>"),
        lambda: HttpResponse(200, b"to nie jest JSON"),
        lambda: issue_in("zablokowane"),
    ],
    ids=["brak-sieci", "awaria-githuba", "nieczytelna-odpowiedz", "nieznany-stan"],
)
def test_brak_sieci_albo_niezwykla_odpowiedz_przy_stanie_to_skrzynka_nieosiagalna(
    answer: Callable[[], HttpResponse],
) -> None:
    outcome, _ = states_with(lambda: issue_in("closed"), answer)

    assert outcome == Unreachable()


OPERATIONS: dict[str, Callable[[GitHubReportBox, str], object]] = {
    "open_issue": lambda box, key: box.open_issue("kontrola-ilosci", TITLE, BODY, key=key),
    "find_open": lambda box, key: box.find_open(FINGERPRINT, key=key),
    "states": lambda box, key: box.states([7], key=key),
}


@pytest.mark.parametrize("key", ["\ufeffgithub_pat_SYNTETYCZNY", "github_pat_SYNTETYCZNY\nX-Inny: 1", "kluczóś"])
@pytest.mark.parametrize("operation", OPERATIONS)
def test_klucz_ktorego_nie_da_sie_wyslac_w_naglowku_to_odmowa_skrzynki_bez_zapytania(key: str, operation: str) -> None:
    transport = ScriptedTransport(lambda: HttpResponse(201, json.dumps({"number": 42}).encode()))

    outcome = OPERATIONS[operation](GitHubReportBox(transport=transport), key)

    assert (outcome, transport.requests) == (Refused(), [])

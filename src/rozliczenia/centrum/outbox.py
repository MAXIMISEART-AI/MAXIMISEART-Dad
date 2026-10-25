"""Kolejka Skrzynki Zgłoszeń: Kontrole ilości, Logi Uruchomienia, Uwagi taty i Zgłoszenia, które Centrum wysyła w tle.

Każda wysyłka (``Post``) to gotowy tekst skierowany do issue okresu (``PeriodThread``: etykieta, wiersz rozpoznawczy
na początku treści issue, tytuł i co z issue, które Maks zamknął), do nowego issue (``NewIssue``: etykieta i tytuł,
jak Uwaga taty), do issue o znanym numerze (``KnownIssue``) albo do jednego otwartego Zgłoszenia problemu
(``ReportIssue``: wiersz odcisku problemu w treści i tytuł). Najpierw trafia do własnego pliku JSON w
``config/zgloszenia/kolejka/`` (poza Gitem), potem jeden wątek w tle wysyła wszystkie pliki po kolei i usuwa
wysłane. Porażka (brak klucza, odmowa, brak sieci) zostawia plik bez Komunikatu; wątek rusza znów sam po
``RETRY_S``, przy starcie Centrum (``resume``) i po każdej nowej wysyłce. Plik do ``KnownIssue``, którego skrzynka
już nie ma, kolejka porzuca z linią dziennika (#402). Wysłany plik dostaje znacznik dostarczenia, zanim zniknie,
więc plik, którego nie da się usunąć, nie idzie drugi raz. Przerwanie między wysłaniem a znacznikiem powtarza
wysyłkę (co najmniej raz, decyzja 12). Treść nigdy nie trafia do dziennika Centrum: tylko etykieta, okres, numer
issue i przyczyna czekania (decyzja 13).

Issue okresu kolejka znajduje po wierszu rozpoznawczym przy każdej próbie wysyłki i dopisuje do niego części jako
komentarze. Bez niego zakłada nowe issue: pierwsza część (albo nagłówek) jest jego treścią, kolejne komentarzami.
``NewIssue`` zawsze zakłada nowe issue tak samo, bez wiersza rozpoznawczego. Kto czeka na wynik (Uwaga taty),
dostaje numer issue przez ``on_delivered`` i może poczekać na dostarczenie przez ``wait_delivered``.

Adres pierwszego komentarza każdej dostarczonej wysyłki (np. Logów Uruchomienia, do których prowadzi przypięta
Uwaga taty) kolejka dopisuje do pliku ``addresses`` i wczytuje przy następnym starcie Centrum, więc ``delivered``
zna też wysyłki poprzednich prac Centrum. Tuż przed wysłaniem wysyłka przechodzi przez ``prepare``: Uwaga taty
uzupełnia w nim odnośnik do Logów, które skrzynka przyjęła po jej zapisaniu, a wysyłka, która czeka na inną
(odnośnik do Logów odrzuconych w tej pracy Centrum), zostaje w kolejce do następnego przejścia.
"""

from __future__ import annotations

import itertools
import json
import threading
from collections.abc import Callable, Sequence
from contextlib import suppress
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Final, Literal, assert_never, get_args

from rozliczenia.centrum.atomic_file import replace_atomically
from rozliczenia.centrum.clock import Clock
from rozliczenia.centrum.keyed_box import KeyedBox, NoKey
from rozliczenia.centrum.log import CentrumLog, WaitingCause
from rozliczenia.centrum.report_box import (
    COMMENT_LIMIT,
    Commented,
    Label,
    Refused,
    Rejected,
    Sent,
    Unreachable,
)

QUEUE_DIRECTORY: Final = "kolejka"
# Poza ``config/zgloszenia``: weryfikacja Kontroli ilości sprawdza, że jest tam tylko kolejka.
ADDRESSES_FILE: Final = "skrzynka-adresy.jsonl"
SCHEMA_VERSION: Final = 2
# Pliki kolejki sprzed ``NewIssue`` (#273) mają cel w kluczu ``thread`` i zawsze jest nim issue okresu.
_PERIOD_THREAD_SCHEMA: Final = 1
# Miejsce w komentarzu na nagłówek części i wiersz rozpoznawczy, ponad tekst bloków.
_FRAME_RESERVE: Final = 2_000
# Etykieta Zgłoszenia jak ``dad_cases.REPORT``, który sam zależy od kolejki.
_REPORT_LABEL: Final[Label] = "zgloszenie"
# Po przejściu, które stanęło na przyczynie dla całej kolejki (brak sieci, brak klucza, odmowa klucza), kolejka
# próbuje znowu po minucie. Odrzucony klucz nie kosztuje przy tym zapytania: ``KeyedBox`` odpowiada ``Refused`` bez
# sieci przez kwadrans, a brak klucza to odczyt pliku. Nieudana próba DNS raz na minutę nic nie kosztuje, a dłuższa
# przerwa opóźniłaby wysyłkę po powrocie sieci.
RETRY_S: Final = 60.0
# Tyle „Wyślij” Uwagi taty i „Wyślij do Maksa” czekają na skrzynkę, zanim powiedzą, że wysyłka czeka w kolejce.
DELIVERY_WAIT_S: Final = 5.0

Frame = Callable[[int, int, str], str]
"""Komentarz części ``k`` z ``n`` z jej tekstu."""
Closed = Literal["new_issue", "reuse"]
_LABELS: Final = frozenset(get_args(Label))
_CLOSED: Final = frozenset(get_args(Closed))


@dataclass(frozen=True)
class PeriodThread:
    """Issue okresu w Skrzynce Zgłoszeń: etykieta, wiersz rozpoznawczy i co z issue, które Maks zamknął."""

    label: Label
    line: str
    """Dokładny wiersz treści, po którym znaleźć issue; kolejka stawia go na początku każdego issue, które zakłada."""
    closed: Closed
    """Kontrola ilości: zamknięte issue to nowe issue okresu; Logi Uruchomienia: dalej to samo."""
    title: str
    """Tytuł, gdy issue trzeba założyć."""


@dataclass(frozen=True)
class NewIssue:
    """Nowe issue przy każdej wysyłce, bez wiersza rozpoznawczego (Uwaga taty: każda to osobna sprawa)."""

    label: Label
    title: str


@dataclass(frozen=True)
class KnownIssue:
    """Komentarze do issue o znanym numerze (odnośnik do Logów dopisany do issue Uwagi taty)."""

    label: Label
    number: int


@dataclass(frozen=True)
class ReportIssue:
    """Zgłoszenie: jedno otwarte issue z etykietą ``zgloszenie`` na odcisk problemu (``line``: jego wiersz w treści).

    Dostarczenie szuka otwartego Zgłoszenia z tym wierszem. Gdy jest (założyła je przerwana próba tej wysyłki, inny
    komputer albo wcześniejsze Zgłoszenie, którego Centrum jeszcze nie znało), wysyłka je przejmuje bez nowego issue i
    bez komentarza. Bez niego zakłada issue z ``title`` i częścią 1, a resztę części dopisuje komentarzami.
    """

    line: str
    title: str

    @property
    def label(self) -> Label:
        return _REPORT_LABEL


Target = PeriodThread | NewIssue | KnownIssue | ReportIssue
"""Dokąd w Skrzynce Zgłoszeń idzie wysyłka; dostarczenie rozróżnia cele przez ``match``."""


@dataclass(frozen=True)
class Post:
    """Gotowa wysyłka do Skrzynki Zgłoszeń, wyrenderowana przez wersję narzędzia, która ją utworzyła.

    ``header``: treść nowego issue; ``None``: nowe issue otwiera pierwsza część (Kontrola ilości, Uwaga taty).
    ``run_id`` to Uruchomienie, a dla Uwagi taty jej identyfikator.
    """

    target: Target
    period: str | None
    """Token okresu do dziennika Centrum; ``None``: Uruchomienie bez okresu."""
    run_id: str
    header: str | None
    parts: tuple[str, ...]

    def __post_init__(self) -> None:
        body, comments = self.opening()
        if not self.parts or any(len(text) > COMMENT_LIMIT for text in (body, *comments)):
            raise ValueError("Wysyłka musi mieć części mieszczące się w komentarzu Skrzynki Zgłoszeń.")
        # Przerwaną wysyłkę Zgłoszenia następna próba znajduje po tym wierszu; bez niego założyłaby drugie issue.
        if isinstance(self.target, ReportIssue) and self.target.line not in body.splitlines():
            raise ValueError("Treść nowego issue Zgłoszenia musi mieć wiersz odcisku problemu.")

    @classmethod
    def of(
        cls,
        target: Target,
        *,
        period: str | None,
        run_id: str,
        blocks: Sequence[str],
        frame: Frame,
        header: str | None = None,
    ) -> Post:
        """Dzieli ``blocks`` na części mieszczące się w komentarzu i opisuje każdą przez ``frame``.

        Bloki są sklejane w kolejności; blok dłuższy niż część jest cięty. Część ponad limit to ``ValueError``.
        """

        texts = _pack(blocks, COMMENT_LIMIT - _FRAME_RESERVE)
        parts = tuple(frame(number, len(texts), text) for number, text in enumerate(texts, start=1))
        return cls(target, period, run_id, header, parts)

    def opening(self) -> tuple[str, tuple[str, ...]]:
        """Treść nowego issue (nagłówek albo część 1, w issue okresu po wierszu rozpoznawczym) i komentarze po nim.

        ``KnownIssue`` nie zakłada issue: pusta treść, a wszystkie części to komentarze.
        """

        if self.header is None:
            first, comments = (self.parts[0], self.parts[1:]) if self.parts else ("", ())
        else:
            first, comments = self.header, self.parts
        match self.target:
            case PeriodThread(line=line):
                return f"{line}\n\n{first}", comments
            case NewIssue() | ReportIssue():
                return first, comments
            case KnownIssue():
                return "", self.parts
            case _:
                assert_never(self.target)

    def to_json(self) -> str:
        return _queue_text(self, delivered_parts=0)


@dataclass(frozen=True)
class _Queued:
    """Plik kolejki: wysyłka i ile jej części skrzynka już przyjęła (wszystkie: plik czeka tylko na usunięcie)."""

    post: Post
    delivered_parts: int

    @property
    def delivered(self) -> bool:
        return self.delivered_parts == len(self.post.parts)


def _queue_text(post: Post, *, delivered_parts: int) -> str:
    return json.dumps(
        {
            "schema_version": SCHEMA_VERSION,
            "target": _target_json(post.target),
            "period": post.period,
            "run_id": post.run_id,
            "header": post.header,
            "parts": list(post.parts),
            "delivered_parts": delivered_parts,
        },
        ensure_ascii=False,
        indent=2,
    )


def _target_json(target: Target) -> dict[str, str | int]:
    match target:
        case PeriodThread():
            return {
                "kind": "period_thread",
                "label": target.label,
                "line": target.line,
                "closed": target.closed,
                "title": target.title,
            }
        case NewIssue():
            return {"kind": "new_issue", "label": target.label, "title": target.title}
        case KnownIssue():
            return {"kind": "known_issue", "label": target.label, "number": target.number}
        case ReportIssue():
            return {"kind": "report_issue", "label": target.label, "line": target.line, "title": target.title}
        case _:
            assert_never(target)


def _target(entry: dict[str, Any], kind: object) -> Target | None:
    """Cel wysyłki z pliku kolejki; nieznany rodzaj celu albo etykieta to ``None``."""

    if entry["label"] not in _LABELS:
        return None
    if kind == "new_issue":
        return NewIssue(entry["label"], _string(entry["title"]))
    if kind == "known_issue":
        return KnownIssue(entry["label"], entry["number"]) if type(entry["number"]) is int else None
    if kind == "report_issue":
        return ReportIssue(_string(entry["line"]), _string(entry["title"]))
    if kind != "period_thread" or entry["closed"] not in _CLOSED:
        return None
    return PeriodThread(entry["label"], _string(entry["line"]), entry["closed"], _string(entry["title"]))


def _parse(text: str) -> _Queued | None:
    """Granica plików kolejki. ``delivered_parts`` jest opcjonalne: pliki z #273 go nie mają i nic nie dostarczyły."""

    try:
        document = json.loads(text)
        schema = document["schema_version"]
        if schema == SCHEMA_VERSION:
            target = _target(document["target"], document["target"]["kind"])
        elif schema == _PERIOD_THREAD_SCHEMA:
            target = _target(document["thread"], "period_thread")
        else:
            return None
        if target is None:
            return None
        post = Post(
            target,
            _optional_string(document["period"]),
            _string(document["run_id"]),
            _optional_string(document["header"]),
            tuple(_string(part) for part in document["parts"]),
        )
        delivered_parts = document.get("delivered_parts", 0)
    except (ValueError, KeyError, TypeError):
        return None
    if type(delivered_parts) is not int or not 0 <= delivered_parts <= len(post.parts):
        return None
    return _Queued(post, delivered_parts)


def _queued(path: Path) -> _Queued | None:
    """Plik kolejki; pliku, którego nie da się odczytać, nie ma w tym przejściu."""

    try:
        return _parse(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError):
        return None


def _string(value: object) -> str:
    if not isinstance(value, str):
        raise TypeError("napis")
    return value


def _optional_string(value: object) -> str | None:
    return None if value is None else _string(value)


def _pack(blocks: Sequence[str], budget: int) -> tuple[str, ...]:
    """Bloki sklejone w kolejności w części najwyżej ``budget`` znaków; blok, który się mieści, nie jest dzielony."""

    parts: list[str] = []
    current = ""
    for block in blocks:
        if len(block) <= budget:
            if len(current) + len(block) > budget:
                parts.append(current)
                current = ""
            current += block
            continue
        rest = current + block  # blok i tak jest cięty, więc dopełnia bieżącą część
        while len(rest) > budget:
            parts.append(rest[:budget])
            rest = rest[budget:]
        current = rest
    if current:
        parts.append(current)
    return tuple(parts)


def _read_addresses(path: Path) -> dict[tuple[str, Label], str | None]:
    """Adresy pierwszych komentarzy z poprzednich prac Centrum; brak albo nieczytelny plik lub linia to brak adresu."""

    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeError):
        return {}
    found: dict[tuple[str, Label], str | None] = {}
    for line in text.splitlines():
        try:
            entry = json.loads(line)
            run_id, label, url = entry["run_id"], entry["label"], entry["url"]
        except (ValueError, KeyError, TypeError):
            continue
        if isinstance(run_id, str) and label in _LABELS and isinstance(url, str):
            found[run_id, label] = url
    return found


@dataclass(frozen=True)
class Delivered:
    number: int
    comments: tuple[Commented, ...]


@dataclass(frozen=True)
class Gone:
    """Skrzynka działa, ale nie ma już issue ``number`` (Maks je usunął): wysyłka do niego nigdy nie przejdzie."""

    number: int


Failure = Refused | Rejected | Unreachable | NoKey
"""Porażka wysyłki: odmowa klucza, odmowa treści, brak sieci albo brak klucza."""


def _deliver(post: Post, box: KeyedBox) -> Delivered | Gone | Failure:
    match post.target:
        case PeriodThread() as thread:
            return _deliver_to_period(post, thread, box)
        case NewIssue() as issue:
            return _deliver_new_issue(post, issue, box)
        case KnownIssue() as known:
            return _deliver_to_known(post, known, box)
        case ReportIssue() as report:
            return _deliver_report(post, report, box)
        case _:
            assert_never(post.target)


def _deliver_new_issue(post: Post, issue: NewIssue, box: KeyedBox) -> Delivered | Failure:
    """Nowe issue z pierwszą częścią (albo nagłówkiem) i komentarze z resztą; porażka kończy wysyłkę."""

    body, comments = post.opening()
    opened = box.open_issue(issue.label, issue.title, body)
    if not isinstance(opened, Sent):
        return opened
    return _comment_all(opened.number, comments, box)


def _deliver_report(post: Post, report: ReportIssue, box: KeyedBox) -> Delivered | Failure:
    """Otwarte Zgłoszenie z tym odciskiem albo nowe issue z częścią 1 i komentarze z resztą.

    Ponowna próba po przerwaniu między założeniem issue a znacznikiem dostarczenia znajduje issue założone przez
    pierwszą i je przejmuje, więc jeden problem ma jedno otwarte Zgłoszenie także wtedy.
    """

    found = box.find_issue(report.label, report.line, include_closed=False)
    if isinstance(found, Refused | Unreachable | NoKey):
        return found
    if found is not None:
        return Delivered(found, ())
    body, comments = post.opening()
    opened = box.open_issue(report.label, report.title, body)
    if not isinstance(opened, Sent):
        return opened
    return _comment_all(opened.number, comments, box)


def _deliver_to_known(post: Post, known: KnownIssue, box: KeyedBox) -> Delivered | Gone | Failure:
    """Każda część jako komentarz do issue ``known.number``, jeśli skrzynka je ma (otwarte albo zamknięte).

    Komentarz do issue, które Maks usunął, to 404, czyli odmowa, która zatrzymałaby całą kolejkę, więc kolejka
    najpierw pyta o issue z etykietą. Gdy lista przyszła bez tego numeru, issue nie ma (``Gone``).
    """

    found = box.labelled_issues(known.label, include_closed=True)
    if isinstance(found, Refused | Unreachable | NoKey):
        return found
    if all(issue.number != known.number for issue in found):
        return Gone(known.number)
    return _comment_all(known.number, post.parts, box)


def _deliver_to_period(post: Post, thread: PeriodThread, box: KeyedBox) -> Delivered | Failure:
    """Każda część jako komentarz do issue okresu, a bez niego nowe issue z pierwszą częścią i komentarze z resztą.

    Issue okresu jest szukane przy każdej próbie, więc usunięte albo zamknięte issue nie blokuje kolejki. Pierwsza
    porażka kończy wysyłkę; następna próba zaczyna od nowa.
    """

    found = box.find_issue(thread.label, thread.line, include_closed=thread.closed == "reuse")
    if isinstance(found, Refused | Unreachable | NoKey):
        return found
    if found is None:
        body, comments = post.opening()
        opened = box.open_issue(thread.label, thread.title, body)
        if not isinstance(opened, Sent):
            return opened
        number = opened.number
    else:
        number, comments = found, post.parts
    return _comment_all(number, comments, box)


def _comment_all(number: int, comments: Sequence[str], box: KeyedBox) -> Delivered | Failure:
    delivered: list[Commented] = []
    for comment in comments:
        answer = box.comment(number, comment)
        if not isinstance(answer, Commented):
            return answer
        delivered.append(answer)
    return Delivered(number, tuple(delivered))


def _waiting(outcome: Failure) -> tuple[WaitingCause, Literal["stop", "next"]]:
    """Przyczyna w dzienniku i co dalej w przejściu kolejki po porażce wysyłki.

    Brak klucza, brak sieci (także limit zapytań) i odmowa (401/403/404: klucz albo dostęp) spotkałyby każdy następny plik,
    więc przejście staje z jedną linią dziennika. Odmowa treści dotyczy tylko tego pliku: zostaje do następnego
    startu Centrum, a przejście idzie dalej.
    """

    match outcome:
        case NoKey():
            return "brak-klucza", "stop"
        case Unreachable():
            return "brak-sieci", "stop"
        case Refused():
            return "odmowa", "stop"
        case Rejected():
            return "odmowa-tresci", "next"
        case _:
            assert_never(outcome)


class Outbox:
    """Pliki kolejki w ``directory`` i jedyny wątek, który je wysyła, także sam po porażce skrzynki.

    Każdy plik ma jednego autora (``post``, nowa nazwa) i jednego czytelnika, który go oznacza i usuwa (wątek
    ``skrzynka-kolejka``), więc pliki nie potrzebują blokady. Blokada chroni tylko to, czy wątek już biegnie, i
    adresy dostarczonych wysyłek; zbiory nazw plików i plik ``addresses`` zna tylko ten jeden wątek.
    ``on_delivered`` dostaje każdą wysyłkę przyjętą przez skrzynkę i numer jej issue, w wątku wysyłki, zanim plik
    dostanie znacznik. ``prepare`` dostaje wysyłkę z pliku tuż przed wysłaniem i zwraca tę, która pójdzie, albo
    ``None``: wysyłka czeka na inną i zostaje w kolejce do następnego przejścia.

    Przejście, które stanęło na przyczynie dla całej kolejki, nastawia jedno budzenie ``clock`` za ``RETRY_S``, chyba
    że już jest nastawione; budzenie rusza wysyłkę w tle. Odrzucona treść i wysyłka czekająca w ``prepare`` budzenia
    nie nastawiają: ponowienie im nie pomoże. Linia „skrzynka-czeka” trafia do dziennika tylko przy zmianie przyczyny
    (każde dostarczenie ją zeruje), bo budzenie co minutę zapełniłoby ostatnie wpisy, które niesie Diagnoza.
    """

    def __init__(
        self,
        directory: Path,
        box: KeyedBox,
        log: CentrumLog,
        *,
        clock: Clock,
        on_delivered: Callable[[Post, int], None] = lambda _post, _number: None,
        prepare: Callable[[Post], Post | None] = lambda post: post,
        addresses: Path | None = None,
    ) -> None:
        self._directory = directory
        self._box = box
        self._log = log
        self._clock = clock
        self._on_delivered = on_delivered
        self._prepare = prepare
        self._addresses = addresses
        self._sequence = itertools.count(1)
        self._lock = threading.Lock()  # _draining, _again, _retry_armed, _first_comments, _rejected_posts
        self._changed = threading.Condition(self._lock)
        self._draining = False
        self._again = False
        self._retry_armed = False
        self._waiting_logged: WaitingCause | None = None  # tylko wątek kolejki
        self._first_comments: dict[tuple[str, Label], str | None] = {} if addresses is None else _read_addresses(addresses)
        self._undeleted: set[str] = set()  # wysłane w tej pracy Centrum, usunięcie się nie udało i jest w dzienniku
        self._unreadable: set[str] = set()  # nieczytelne, już w dzienniku tej pracy Centrum
        self._rejected: set[str] = set()  # treść odrzucona przez skrzynkę, w dzienniku; następna próba po starcie
        self._rejected_posts: set[tuple[str, Label]] = set()  # run_id i etykieta plików z _rejected

    def resume(self) -> None:
        """Przy starcie Centrum: usuwa pozostałości urwanego zapisu i wysyła w tle wszystko, co czeka.

        Woła go ``lifespan`` przed przyjęciem pierwszego zapytania HTTP. Wysyłkę tworzy tylko zapytanie HTTP
        (Uruchomienie albo „Wyślij” Uwagi taty), a wątek wysyłki rusza dopiero tutaj, więc żaden ``*.tmp`` nie ma
        teraz autora: każdy został po zapisie przerwanym w poprzedniej pracy Centrum (np. utrata zasilania). Plik
        ``.json`` obok niego, jeśli jest, ma pełną treść sprzed tego zapisu. Start nie czeka na skrzynkę: pyta ją tylko wątek w tle.
        """

        with suppress(OSError):
            for leftover in self._directory.glob("*.tmp"):
                with suppress(OSError):
                    leftover.unlink()
        self.send_in_background()

    @property
    def directory(self) -> Path:
        return self._directory

    def delivered(self, run_id: str, label: Label) -> str | None:
        """Adres pierwszego komentarza wysyłki ``label`` z Uruchomienia ``run_id``, przyjętej przez skrzynkę.

        Zna wysyłki z tej pracy Centrum i z pliku ``addresses``. ``None``: wysyłka czeka w kolejce, nie powstała,
        cała zmieściła się w treści nowego issue albo jej adresu nie dało się zapamiętać.
        """

        with self._lock:
            return self._first_comments.get((run_id, label))

    def rejected(self, run_id: str, label: Label) -> bool:
        """Skrzynka odrzuciła w tej pracy Centrum treść wysyłki ``label`` z ``run_id``; plik czeka na następny start."""

        with self._lock:
            return (run_id, label) in self._rejected_posts

    def wait_delivered(self, run_id: str, label: Label, *, timeout_s: float) -> bool:
        """Czeka najwyżej ``timeout_s``, aż skrzynka przyjmie wysyłkę ``label`` z ``run_id`` w tej pracy Centrum.

        ``False`` od razu, gdy wątek wysyłki skończył przejście kolejki bez niej (brak klucza, sieci, odmowa).
        """

        def settled() -> bool:
            return (run_id, label) in self._first_comments or not self._draining

        with self._changed:
            self._changed.wait_for(settled, timeout_s)
            return (run_id, label) in self._first_comments

    def post(self, post: Post) -> bool:
        """Zapisuje ``post`` w nowym pliku kolejki i budzi wysyłkę w tle; nie pyta skrzynki i nie czeka na sieć.

        ``False``: pliku nie udało się zapisać (typ wyjątku jest w dzienniku) i wysyłka przepadła.
        """

        moment = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
        name = f"{moment}-{next(self._sequence):04d}-{post.target.label}-{post.run_id[:8]}.json"
        try:
            replace_atomically(self._directory / name, post.to_json())
        except OSError as failure:
            self._log.unexpected_failure(failure, where="zapis wysyłki do Skrzynki Zgłoszeń")
            return False
        self._log.box_post_queued(label=post.target.label, period=post.period)
        self.send_in_background()
        return True

    def send_in_background(self) -> None:
        """Jeden wątek wysyłki naraz; wywołanie w trakcie wysyłki każe jej przejść kolejkę jeszcze raz."""

        with self._lock:
            if self._draining:
                self._again = True
                return
            self._draining = True
        threading.Thread(target=self._drain, name="skrzynka-kolejka", daemon=True).start()

    def _drain(self) -> None:
        while True:
            stopped: WaitingCause | None = None
            try:
                stopped = self._send_all()
            except Exception as failure:
                self._log.unexpected_failure(failure, where="wysyłka do Skrzynki Zgłoszeń")
            with self._changed:
                if not self._again:
                    self._draining = False
                    if stopped is not None and not self._retry_armed:
                        self._retry_armed = True
                        self._clock.after(RETRY_S, self._woken)
                    self._changed.notify_all()
                    return
                self._again = False

    def _woken(self) -> None:
        with self._lock:
            self._retry_armed = False
        self.send_in_background()

    def _send_all(self) -> WaitingCause | None:
        """Pliki kolejki po nazwie (czas utworzenia); porażka skrzynki zatrzymuje przejście albo pomija plik (``_waiting``).

        Zwraca przyczynę, na której przejście stanęło, albo ``None``.
        """

        for path in sorted(self._directory.glob("*.json")):
            if path.name in self._undeleted:
                self._remove(path)
                continue
            if path.name in self._rejected:
                continue
            queued = _queued(path)
            if queued is None:
                self._skip_unreadable(path)
                continue
            if queued.delivered:
                self._remove(path)
                continue
            post = self._prepare(queued.post)
            if post is None:
                continue
            label, period = post.target.label, post.period
            outcome = _deliver(post, self._box)
            if isinstance(outcome, Gone):
                self._log.box_post_dropped(label=label, file=path.name, number=outcome.number)
                self._remove(path)
                continue
            if not isinstance(outcome, Delivered):
                cause, then = _waiting(outcome)
                if then == "stop":
                    if cause != self._waiting_logged:
                        self._waiting_logged = cause
                        self._log.box_post_waiting(label=label, period=period, cause=cause)
                    return cause
                self._rejected.add(path.name)
                with self._lock:
                    self._rejected_posts.add((post.run_id, label))
                self._log.box_post_waiting(label=label, period=period, cause=cause, file=path.name)
                continue
            self._waiting_logged = None
            self._log.box_post_sent(label=label, period=period, number=outcome.number)
            self._on_delivered(post, outcome.number)
            with self._changed:
                self._first_comments[post.run_id, label] = outcome.comments[0].url if outcome.comments else None
                self._changed.notify_all()
            self._remember_address(post, outcome)
            with suppress(OSError):  # bez znacznika chroni już tylko _undeleted, do końca tej pracy Centrum
                replace_atomically(path, _queue_text(post, delivered_parts=len(post.parts)))
            self._remove(path)
        return None

    def _remember_address(self, post: Post, outcome: Delivered) -> None:
        """Dopisuje adres pierwszego komentarza do pliku ``addresses``; nieudany zapis to tylko wpis w dzienniku."""

        if self._addresses is None or not outcome.comments:
            return
        line = json.dumps({"run_id": post.run_id, "label": post.target.label, "url": outcome.comments[0].url})
        try:
            with self._addresses.open("a", encoding="utf-8") as addresses:
                addresses.write(line + "\n")
        except OSError as failure:
            self._log.unexpected_failure(failure, where="adres wysyłki do Skrzynki Zgłoszeń")

    def _remove(self, path: Path) -> None:
        """Usuwa dostarczony plik; gdy się nie da (np. plik otwarty w Windows), pierwszy raz zapisuje to w dzienniku."""

        try:
            path.unlink(missing_ok=True)
        except OSError as failure:
            if path.name not in self._undeleted:
                self._undeleted.add(path.name)
                self._log.unexpected_failure(failure, where="usunięcie wysłanej wysyłki do Skrzynki Zgłoszeń")
            return
        self._undeleted.discard(path.name)

    def _skip_unreadable(self, path: Path) -> None:
        """Uszkodzony plik albo nieznany schemat (np. z nowszej wersji narzędzia) zostaje; dziennik raz na pracę."""

        if path.name not in self._unreadable:
            self._unreadable.add(path.name)
            self._log.box_post_unreadable(file=path.name)

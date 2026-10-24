"""Kolejka Skrzynki Zgłoszeń: Kontrole ilości, Logi Uruchomienia (#320) i Uwagi taty, które Centrum wysyła w tle.

Każda wysyłka (``Post``) to gotowy tekst skierowany do issue okresu (``PeriodThread``: etykieta, wiersz
rozpoznawczy na początku treści issue, tytuł i co z issue, które Maks zamknął) albo do nowego issue (``NewIssue``:
etykieta i tytuł, jak Uwaga taty). Najpierw trafia do własnego pliku
JSON w ``config/zgloszenia/kolejka/`` (poza Gitem, poza plikami ``Zgłoszenie *.md``, które tata może przesłać
Maksowi), potem jeden wątek w tle wysyła wszystkie pliki po kolei i usuwa wysłane. Porażka (brak klucza, odmowa,
brak sieci) zostawia plik bez Komunikatu; wątek rusza znów przy starcie Centrum (``resume``) i po każdej nowej
wysyłce. Wysłany plik dostaje znacznik dostarczenia, zanim zniknie, więc plik, którego nie da się usunąć, nie idzie
drugi raz. Przerwanie między wysłaniem a znacznikiem powtarza wysyłkę (co najmniej raz, decyzja 12). Treść nigdy
nie trafia do dziennika Centrum: tylko etykieta, okres, numer issue i przyczyna czekania (decyzja 13).

Issue okresu kolejka znajduje po wierszu rozpoznawczym przy każdej próbie wysyłki i dopisuje do niego części jako
komentarze. Bez niego zakłada nowe issue: pierwsza część (albo nagłówek) jest jego treścią, kolejne komentarzami.
``NewIssue`` zawsze zakłada nowe issue tak samo, bez wiersza rozpoznawczego. Kto czeka na wynik (Uwaga taty),
dostaje numer issue przez ``on_delivered`` i może poczekać na dostarczenie przez ``wait_delivered``.

Adres pierwszego komentarza każdej dostarczonej wysyłki (np. Logów Uruchomienia, do których prowadzi przypięta
Uwaga taty) kolejka dopisuje do pliku ``addresses`` i wczytuje przy następnym starcie Centrum, więc ``delivered``
zna też wysyłki poprzednich prac Centrum. Tuż przed wysłaniem wysyłka przechodzi przez ``prepare``: Uwaga taty
uzupełnia w nim odnośnik do Logów, które skrzynka przyjęła po jej zapisaniu.
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
from rozliczenia.centrum.log import CentrumLog
from rozliczenia.centrum.report_box import (
    COMMENT_LIMIT,
    Commented,
    Label,
    Refused,
    ReportBox,
    Sent,
    Unreachable,
    find_issue,
)

QUEUE_DIRECTORY: Final = "kolejka"
# Adresy pierwszych komentarzy dostarczonych wysyłek, poza ``config/zgloszenia``, które ma tylko kolejkę.
ADDRESSES_FILE: Final = "skrzynka-adresy.jsonl"
SCHEMA_VERSION: Final = 2
# Pliki kolejki sprzed ``NewIssue`` (#273) mają cel w kluczu ``thread`` i zawsze jest nim issue okresu.
_PERIOD_THREAD_SCHEMA: Final = 1
# Miejsce w komentarzu na nagłówek części i wiersz rozpoznawczy, ponad tekst bloków.
_FRAME_RESERVE: Final = 2_000

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


Target = PeriodThread | NewIssue
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
        """Treść nowego issue (nagłówek albo część 1, w issue okresu po wierszu rozpoznawczym) i komentarze po nim."""

        if self.header is None:
            first, comments = (self.parts[0], self.parts[1:]) if self.parts else ("", ())
        else:
            first, comments = self.header, self.parts
        match self.target:
            case PeriodThread(line=line):
                return f"{line}\n\n{first}", comments
            case NewIssue():
                return first, comments
            case _:
                assert_never(self.target)

    def to_json(self) -> str:
        return _queue_text(self, delivered_parts=0)

    @classmethod
    def from_json(cls, text: str) -> Post | None:
        """Plik kolejki; nieznana wersja schematu albo etykieta lub plik uszkodzony to ``None`` (plik zostaje)."""

        queued = _parse(text)
        return None if queued is None else queued.post


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


def _target_json(target: Target) -> dict[str, str]:
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
        case _:
            assert_never(target)


def _target(entry: dict[str, Any], kind: object) -> Target | None:
    """Cel wysyłki z pliku kolejki; nieznany rodzaj celu albo etykieta to ``None``."""

    if entry["label"] not in _LABELS:
        return None
    if kind == "new_issue":
        return NewIssue(entry["label"], _string(entry["title"]))
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


def _deliver(post: Post, box: ReportBox, key: str) -> Delivered | Refused | Unreachable:
    match post.target:
        case PeriodThread() as thread:
            return _deliver_to_period(post, thread, box, key)
        case NewIssue() as issue:
            return _deliver_new_issue(post, issue, box, key)
        case _:
            assert_never(post.target)


def _deliver_new_issue(post: Post, issue: NewIssue, box: ReportBox, key: str) -> Delivered | Refused | Unreachable:
    """Nowe issue z pierwszą częścią (albo nagłówkiem) i komentarze z resztą; porażka kończy wysyłkę."""

    body, comments = post.opening()
    opened = box.open_issue(issue.label, issue.title, body, key=key)
    if not isinstance(opened, Sent):
        return opened
    return _comment_all(opened.number, comments, box, key)


def _deliver_to_period(post: Post, thread: PeriodThread, box: ReportBox, key: str) -> Delivered | Refused | Unreachable:
    """Każda część jako komentarz do issue okresu, a bez niego nowe issue z pierwszą częścią i komentarze z resztą.

    Issue okresu jest szukane przy każdej próbie, więc usunięte albo zamknięte issue nie blokuje kolejki. Pierwsza
    porażka kończy wysyłkę; następna próba zaczyna od nowa.
    """

    found = find_issue(box, thread.label, thread.line, include_closed=thread.closed == "reuse", key=key)
    if isinstance(found, Refused | Unreachable):
        return found
    if found is None:
        body, comments = post.opening()
        opened = box.open_issue(thread.label, thread.title, body, key=key)
        if not isinstance(opened, Sent):
            return opened
        number = opened.number
    else:
        number, comments = found, post.parts
    return _comment_all(number, comments, box, key)


def _comment_all(number: int, comments: Sequence[str], box: ReportBox, key: str) -> Delivered | Refused | Unreachable:
    delivered: list[Commented] = []
    for comment in comments:
        answer = box.comment(number, comment, key=key)
        if not isinstance(answer, Commented):
            return answer
        delivered.append(answer)
    return Delivered(number, tuple(delivered))


class Outbox:
    """Pliki kolejki w ``directory`` i jedyny wątek, który je wysyła.

    Każdy plik ma jednego autora (``post``, nowa nazwa) i jednego czytelnika, który go oznacza i usuwa (wątek
    ``skrzynka-kolejka``), więc pliki nie potrzebują blokady. Blokada chroni tylko to, czy wątek już biegnie, i
    adresy dostarczonych wysyłek; zbiory nazw plików i plik ``addresses`` zna tylko ten jeden wątek.
    ``on_delivered`` dostaje każdą wysyłkę przyjętą przez skrzynkę i numer jej issue, w wątku wysyłki, zanim plik
    dostanie znacznik. ``prepare`` dostaje wysyłkę z pliku tuż przed wysłaniem i zwraca tę, która pójdzie.
    """

    def __init__(
        self,
        directory: Path,
        box: ReportBox,
        key: Callable[[], str | None],
        log: CentrumLog,
        *,
        on_delivered: Callable[[Post, int], None] = lambda _post, _number: None,
        prepare: Callable[[Post], Post] = lambda post: post,
        addresses: Path | None = None,
    ) -> None:
        self._directory = directory
        self._box = box
        self._key = key
        self._log = log
        self._on_delivered = on_delivered
        self._prepare = prepare
        self._addresses = addresses
        self._sequence = itertools.count(1)
        self._lock = threading.Lock()  # tylko _draining, _again i _first_comments; nigdy na czas skrzynki ani pliku
        self._changed = threading.Condition(self._lock)
        self._draining = False
        self._again = False
        self._first_comments: dict[tuple[str, Label], str | None] = {} if addresses is None else _read_addresses(addresses)
        self._undeleted: set[str] = set()  # wysłane w tej pracy Centrum, usunięcie się nie udało i jest w dzienniku
        self._unreadable: set[str] = set()  # nieczytelne, już w dzienniku tej pracy Centrum

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

    def delivered(self, run_id: str, label: Label) -> str | None:
        """Adres pierwszego komentarza wysyłki ``label`` z Uruchomienia ``run_id``, przyjętej przez skrzynkę.

        Zna wysyłki z tej pracy Centrum i z pliku ``addresses``. ``None``: wysyłka czeka w kolejce, nie powstała,
        cała zmieściła się w treści nowego issue albo jej adresu nie dało się zapamiętać.
        """

        with self._lock:
            return self._first_comments.get((run_id, label))

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
            try:
                self._send_all()
            except Exception as failure:  # noqa: BLE001 - granica wątku wysyłki: typ wyjątku trafia do dziennika Centrum
                self._log.unexpected_failure(failure, where="wysyłka do Skrzynki Zgłoszeń")
            with self._changed:
                if not self._again:
                    self._draining = False
                    self._changed.notify_all()
                    return
                self._again = False

    def _send_all(self) -> None:
        """Pliki kolejki po nazwie (czas utworzenia), aż do pierwszej porażki skrzynki."""

        paths = sorted(self._directory.glob("*.json"))
        if not paths:
            return
        key = self._key()
        for path in paths:
            if path.name in self._undeleted:
                self._remove(path)
                continue
            queued = _queued(path)
            if queued is None:
                self._skip_unreadable(path)
                continue
            if queued.delivered:
                self._remove(path)
                continue
            post = self._prepare(queued.post)
            label, period = post.target.label, post.period
            if key is None:
                self._log.box_post_waiting(label=label, period=period, cause="brak-klucza")
                continue
            outcome = _deliver(post, self._box, key)
            if not isinstance(outcome, Delivered):
                self._log.box_post_waiting(
                    label=label, period=period, cause="odmowa" if isinstance(outcome, Refused) else "brak-sieci"
                )
                return
            self._log.box_post_sent(label=label, period=period, number=outcome.number)
            self._on_delivered(post, outcome.number)
            with self._changed:
                self._first_comments[post.run_id, label] = outcome.comments[0].url if outcome.comments else None
                self._changed.notify_all()
            self._remember_address(post, outcome)
            with suppress(OSError):  # bez znacznika chroni już tylko _undeleted, do końca tej pracy Centrum
                replace_atomically(path, _queue_text(post, delivered_parts=len(post.parts)))
            self._remove(path)

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

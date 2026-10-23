"""Kolejka Skrzynki Zgłoszeń: Kontrole ilości (a od #320 Logi Uruchomienia), które Centrum wysyła samo i po cichu.

Każda wysyłka (``Post``) to gotowy tekst skierowany do issue okresu (``PeriodThread``): etykieta, wiersz
rozpoznawczy na początku treści issue, tytuł i co z issue, które Maks zamknął. Najpierw trafia do własnego pliku
JSON w ``config/zgloszenia/kolejka/`` (poza Gitem, poza plikami ``Zgłoszenie *.md``, które tata może przesłać
Maksowi), potem jeden wątek w tle wysyła wszystkie pliki po kolei i usuwa wysłane. Porażka (brak klucza, odmowa,
brak sieci) zostawia plik bez Komunikatu; wątek rusza znów po każdej nowej wysyłce. Przerwanie między wysłaniem a
usunięciem pliku powtarza wysyłkę (co najmniej raz, decyzja 12). Treść nigdy nie trafia do dziennika Centrum:
tylko etykieta, okres, numer issue i przyczyna czekania (decyzja 13).

Treść dłuższa niż komentarz GitHuba idzie w częściach: pierwsza zakłada issue, kolejne są komentarzami.
"""

from __future__ import annotations

import itertools
import json
import threading
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Final, Literal, get_args

from rozliczenia.centrum.log import CentrumLog
from rozliczenia.centrum.report_box import (
    COMMENT_LIMIT,
    Commented,
    Label,
    Refused,
    ReportBox,
    Sent,
    Unreachable,
)
from rozliczenia.centrum.reports import replace_atomically

QUEUE_DIRECTORY: Final = "kolejka"
SCHEMA_VERSION: Final = 1
# Miejsce w komentarzu na nagłówek części i wiersz rozpoznawczy, ponad tekst bloków.
_FRAME_RESERVE: Final = 2_000
_LABELS: Final = frozenset(get_args(Label))

Frame = Callable[[int, int, str], str]
"""Komentarz części ``k`` z ``n`` z jej tekstu."""
Closed = Literal["new_issue", "reuse"]


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
class Post:
    """Gotowa wysyłka do issue okresu, wyrenderowana przez wersję narzędzia, która ją utworzyła.

    ``header``: treść nowego issue; ``None``: nowe issue otwiera pierwsza część (Kontrola ilości).
    """

    thread: PeriodThread
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
        thread: PeriodThread,
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
        return cls(thread, period, run_id, header, parts)

    def opening(self) -> tuple[str, tuple[str, ...]]:
        """Treść nowego issue (wiersz rozpoznawczy i nagłówek albo część 1) i komentarze po jego założeniu."""

        if self.header is None:
            first, comments = (self.parts[0], self.parts[1:]) if self.parts else ("", ())
        else:
            first, comments = self.header, self.parts
        return f"{self.thread.line}\n\n{first}", comments

    def to_json(self) -> str:
        thread = self.thread
        return json.dumps(
            {
                "schema_version": SCHEMA_VERSION,
                "thread": {"label": thread.label, "line": thread.line, "closed": thread.closed, "title": thread.title},
                "period": self.period,
                "run_id": self.run_id,
                "header": self.header,
                "parts": list(self.parts),
            },
            ensure_ascii=False,
            indent=2,
        )

    @classmethod
    def from_json(cls, text: str) -> Post | None:
        """Plik kolejki; nieznana wersja schematu albo etykieta lub plik uszkodzony to ``None`` (plik zostaje)."""

        try:
            document = json.loads(text)
            thread = document["thread"]
            if document["schema_version"] != SCHEMA_VERSION or thread["label"] not in _LABELS:
                return None
            if thread["closed"] not in ("new_issue", "reuse"):
                return None
            post = cls(
                PeriodThread(thread["label"], _string(thread["line"]), thread["closed"], _string(thread["title"])),
                _optional_string(document["period"]),
                _string(document["run_id"]),
                _optional_string(document["header"]),
                tuple(_string(part) for part in document["parts"]),
            )
        except (ValueError, KeyError, TypeError):
            return None
        return post


def _queued(path: Path) -> Post | None:
    """Wysyłka z pliku kolejki; pliku, którego nie da się odczytać, nie ma w tym przejściu."""

    try:
        return Post.from_json(path.read_text(encoding="utf-8"))
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


@dataclass(frozen=True)
class Delivered:
    number: int
    comments: tuple[Commented, ...]


def _deliver(post: Post, box: ReportBox, key: str) -> Delivered | Refused | Unreachable:
    """Nowe issue okresu z pierwszą częścią, potem komentarz z każdą kolejną; pierwsza porażka kończy wysyłkę."""

    body, comments = post.opening()
    opened = box.open_issue(post.thread.label, post.thread.title, body, key=key)
    if not isinstance(opened, Sent):
        return opened
    delivered: list[Commented] = []
    for comment in comments:
        answer = box.comment(opened.number, comment, key=key)
        if not isinstance(answer, Commented):
            return answer
        delivered.append(answer)
    return Delivered(opened.number, tuple(delivered))


class Outbox:
    """Pliki kolejki w ``directory`` i jedyny wątek, który je wysyła.

    Każdy plik ma jednego autora (``post``, nowa nazwa) i jednego czytelnika, który go usuwa (wątek
    ``skrzynka-kolejka``), więc pliki nie potrzebują blokady. Blokada chroni tylko to, czy wątek już biegnie.
    """

    def __init__(self, directory: Path, box: ReportBox, key: Callable[[], str | None], log: CentrumLog) -> None:
        self._directory = directory
        self._box = box
        self._key = key
        self._log = log
        self._sequence = itertools.count(1)
        self._lock = threading.Lock()  # tylko _draining i _again; nigdy na czas pytania skrzynki ani pliku
        self._draining = False
        self._again = False

    def post(self, post: Post) -> None:
        """Zapisuje ``post`` w nowym pliku kolejki i budzi wysyłkę w tle; nie pyta skrzynki i nie czeka na sieć.

        Nieudany zapis pliku trafia do dziennika jako typ wyjątku; wysyłka przepada bez Komunikatu.
        """

        moment = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
        name = f"{moment}-{next(self._sequence):04d}-{post.thread.label}-{post.run_id[:8]}.json"
        try:
            replace_atomically(self._directory / name, post.to_json())
        except OSError as failure:
            self._log.unexpected_failure(failure, where="zapis wysyłki do Skrzynki Zgłoszeń")
            return
        self._log.box_post_queued(label=post.thread.label, period=post.period)
        self.send_in_background()

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
            with self._lock:
                if not self._again:
                    self._draining = False
                    return
                self._again = False

    def _send_all(self) -> None:
        """Pliki kolejki po nazwie (czas utworzenia), aż do pierwszej porażki skrzynki."""

        paths = sorted(self._directory.glob("*.json"))
        if not paths:
            return
        key = self._key()
        for path in paths:
            post = _queued(path)
            if post is None:
                continue
            label, period = post.thread.label, post.period
            if key is None:
                self._log.box_post_waiting(label=label, period=period, cause="brak-klucza")
                continue
            outcome = _deliver(post, self._box, key)
            if not isinstance(outcome, Delivered):
                cause: Literal["odmowa", "brak-sieci"] = "odmowa" if isinstance(outcome, Refused) else "brak-sieci"
                self._log.box_post_waiting(label=label, period=period, cause=cause)
                return
            self._log.box_post_sent(label=label, period=period, number=outcome.number)
            try:
                path.unlink(missing_ok=True)
            except OSError as failure:  # np. plik otwarty w Windows: wysyłka i tak przyjęta
                self._log.unexpected_failure(failure, where="usunięcie wysłanej wysyłki do Skrzynki Zgłoszeń")

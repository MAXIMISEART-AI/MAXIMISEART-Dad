"""Aktualność narzędzia: commit narzędzia u taty względem najnowszego Wydania na publicznym GitHubie.

Diagnoza i Konfiguracja oceniają ją przez ``ToolFreshness.judge`` z trzech źródeł:
commitu narzędzia, z którego działa Centrum (``version.tool_commit`` odczytany
przy starcie), odpowiedzi GitHuba o najnowszym Wydaniu na `main` (ADR 0014; ten
sam wybór co w Aktualizacji narzędzia, ``tool_update.newest_on_main``) i
sprawdzenia w klonie, czy commit narzędzia zawiera commit Wydania. Źródła są
wstrzykiwane do aplikacji Centrum, więc testy i weryfikacja w przeglądarce nigdy
nie łączą się z GitHubem. Brak sieci to ``None`` w krótkim limicie czasu, nigdy
wyjątek ani Komunikat. Diagnoza pyta GitHuba przy każdym sprawdzeniu;
Konfiguracja, odczytywana przy każdym wejściu na stronę, pamięta jego odpowiedź
(``RememberedRelease``), także tę z Diagnozy. Czy z oceny wynika propozycja
Aktualizacji narzędzia, mówi jedna reguła: ``offers_update``. Powiadomienie o
nowej wersji czyta stąd też opublikowane Wydania z ich notkami
(``PublishedRelease``, lista GitHub Releases).
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date, datetime
from functools import partial
import json
from pathlib import Path
import re
import threading
from typing import Final, Literal
import urllib.request

from rozliczenia import TOOL_ROOT
from rozliczenia.centrum.deadline import within
from rozliczenia.centrum.tool_update import Release, contains_commit, find_git, newest_on_main, release_at
from rozliczenia.centrum.version import commit_since, is_commit, tool_commit

CommitSource = Callable[[], str | None]


@dataclass(frozen=True)
class GitHubReleases:
    """Odpowiedź GitHuba: commit i tag najnowszego Wydania na `main`; ``None``, gdy na `main` nie ma żadnego Wydania."""

    newest: str | None
    tag: str | None


# ``None``: GitHub nie odpowiedział (brak sieci, odmowa, limit czasu, niepełna odpowiedź).
ReleaseSource = Callable[[], GitHubReleases | None]


@dataclass(frozen=True)
class PublishedRelease:
    """Wydanie opublikowane jako GitHub Release: numer z tagu, notka (``release_notes``) i czas publikacji."""

    release: Release
    notes: str
    at: datetime


# ``None``: GitHub nie odpowiedział; pusta krotka: nie ma żadnego opublikowanego Wydania.
PublishedSource = Callable[[], tuple[PublishedRelease, ...] | None]
Judgement = Literal["current", "newer", "no_release", "no_answer", "no_commit"]


def offers_update(judgement: Judgement) -> bool:
    """Czy Centrum proponuje tacie Aktualizację narzędzia przy Aktualności ``judgement``.

    Tylko przy Wydaniu nowszym od wersji taty (ADR 0014), nigdy bez odpowiedzi
    GitHuba. Pytają o to Konfiguracja, Diagnoza i Powiadomienie o nowej wersji
    (#324).
    """

    return judgement == "newer"


REPOSITORY_API: Final = "https://api.github.com/repos/MAXIMISEART-AI/MAXIMISEART-Dad"
# 1000 tagów: przy Wydaniu na tydzień na lata. Strona 100 tagów to kilkadziesiąt kB.
_PAGES: Final = 10
# Tyle najwyższych Wydań sprawdza się po kolei, zanim jedno leży na `main`; dalej wynik jest nieznany.
_CANDIDATES: Final = 5
_PAGE_BYTES: Final = 1_000_000
_TIMEOUT_S: Final = 3.0


@dataclass(frozen=True)
class ToolFreshness:
    """Źródła Aktualności narzędzia; ``None`` = nie wiadomo.

    ``local`` to commit narzędzia, z którego działa Centrum, ``since`` dzień, od
    którego narzędzie jest na tym commicie, ``release`` odpowiedź GitHuba o
    najnowszym Wydaniu, ``published`` opublikowane Wydania z notkami,
    ``contains(release, local)`` mówi, czy commit narzędzia zawiera commit Wydania, a
    ``wydanie(local)`` to Wydanie, którego tag w klonie wskazuje dokładnie commit narzędzia.
    """

    local: CommitSource
    since: Callable[[], date | None]
    release: ReleaseSource
    published: PublishedSource
    contains: Callable[[str, str], bool] = field(default=lambda release, local: release == local)
    wydanie: Callable[[str], Release | None] = field(default=lambda local: None)

    @classmethod
    def of_system(cls) -> ToolFreshness:
        return cls.of_clone(TOOL_ROOT, github_releases, github_published)

    @classmethod
    def of_clone(
        cls,
        root: Path,
        release: ReleaseSource,
        published: PublishedSource,
        *,
        find_git: Callable[[], Path | None] = find_git,
    ) -> ToolFreshness:
        """Wersja narzędzia w ``root`` odczytana teraz, przy starcie Centrum.

        Klon przesunięty później (ręcznie albo przez aktualizację przed ponownym startem) nie zmienia kodu, który
        już działa, więc nie zmienia też wersji tego Centrum.
        """

        running = tool_commit(root)
        since = None if running is None else commit_since(running, root)
        return cls(
            local=lambda: running,
            since=lambda: since,
            release=release,
            published=published,
            contains=partial(contains_commit, root),
            wydanie=partial(release_at, root, find_git=find_git),
        )

    def judge(self, release: ReleaseSource | None = None) -> Judgement:
        """Aktualność narzędzia według ``release`` (domyślnie ``self.release``).

        ``current``, gdy commit narzędzia zawiera commit najnowszego Wydania:
        także narzędzie na nowszym commicie `main` niż Wydanie jest aktualne.
        """

        local = self.local()
        if local is None:
            return "no_commit"
        answer = (release or self.release)()
        if answer is None:
            return "no_answer"
        if answer.newest is None:
            return "no_release"
        return "current" if self.contains(answer.newest, local) else "newer"


# API GitHuba bez logowania odpowiada na 60 pytań na godzinę z jednego adresu, a bez sieci każde pytanie czeka do
# 3 s: Konfiguracja pamięta odpowiedź przez 10 minut, także „brak Wydań”, a brak odpowiedzi przez minutę
# (internet może zaraz wrócić).
ANSWER_KEPT_S: Final = 10 * 60
NO_ANSWER_KEPT_S: Final = 60


class RememberedRelease:
    """Odpowiedź ``release`` pamiętana przez ``ANSWER_KEPT_S`` na zegarze ``clock``; brak odpowiedzi krócej."""

    def __init__(self, release: ReleaseSource, *, clock: Callable[[], float]) -> None:
        self._release = release
        self._clock = clock
        self._lock = threading.Lock()
        self._answer: GitHubReleases | None = None
        self._asked_at: float | None = None

    def __call__(self) -> GitHubReleases | None:
        with self._lock:
            if self._asked_at is not None:
                kept = ANSWER_KEPT_S if self._answer is not None else NO_ANSWER_KEPT_S
                if self._clock() - self._asked_at < kept:
                    return self._answer
        answer = self._release()
        with self._lock:
            self._answer, self._asked_at = answer, self._clock()
        return answer

    def fresh(self) -> GitHubReleases | None:
        """Odpowiedź ``release`` teraz, bez pamięci (Diagnoza); odpowiedź, która przyszła, zostaje w pamięci."""

        answer = self._release()
        if answer is not None:
            with self._lock:
                self._answer, self._asked_at = answer, self._clock()
        return answer


def github_releases() -> GitHubReleases | None:
    """Najnowsze Wydanie na `main` publicznego repozytorium; ``None`` bez sieci, po limicie czasu, przy odmowie."""

    return releases_from(REPOSITORY_API, timeout_s=_TIMEOUT_S)


def releases_from(api: str, *, timeout_s: float) -> GitHubReleases | None:
    """Najnowsze Wydanie na `main` z API GitHuba repozytorium ``api``, najpóźniej po ``timeout_s`` sekundach.

    Lista tagów (``tags``) przychodzi stronami (nagłówek ``Link``); bez
    wszystkich stron nie wiadomo, które Wydanie jest najnowsze, więc więcej niż
    ``_PAGES`` stron to ``None``. Czy commit Wydania leży na `main`, mówi
    porównanie (``compare``) ze stroną bez commitów i plików. Diagnoza czeka na
    odpowiedź najwyżej ``timeout_s`` (``deadline.within``). Połączenie idzie
    wprost, bez serwera proxy z ustawień systemu.
    """

    def fetch() -> GitHubReleases | None:
        commits = _tag_commits(f"{api}/tags?per_page=100", timeout_s)
        if commits is None:
            return None
        asked = 0

        def on_main(commit: str) -> bool:
            nonlocal asked
            asked += 1
            if asked > _CANDIDATES:
                raise _NoAnswer
            compared = _json(f"{api}/compare/{commit}...main?per_page=1&page=2", timeout_s)
            if not isinstance(compared, dict) or not isinstance(compared.get("status"), str):
                raise _NoAnswer
            return compared["status"] in ("ahead", "identical")

        try:
            newest = newest_on_main(commits, on_main)
        except _NoAnswer:
            return None
        return GitHubReleases(newest.commit, None if newest.release is None else newest.release.tag)

    return within(timeout_s, fetch, name="github-wydania")


# Tyle ostatnio opublikowanych Wydań (jedna strona listy) pokazują Powiadomienia; starsze nie wracają do historii.
PUBLISHED_PAGE: Final = 30


def github_published() -> tuple[PublishedRelease, ...] | None:
    """Opublikowane Wydania publicznego repozytorium; ``None`` bez sieci, po limicie czasu, przy odmowie."""

    return published_from(REPOSITORY_API, timeout_s=_TIMEOUT_S)


def published_from(api: str, *, timeout_s: float) -> tuple[PublishedRelease, ...] | None:
    """Ostatnie ``PUBLISHED_PAGE`` Wydań z listy GitHub Releases repozytorium ``api``, jednym pytaniem bez klucza."""

    def fetch() -> tuple[PublishedRelease, ...] | None:
        try:
            return parse_published(_json(f"{api}/releases?per_page={PUBLISHED_PAGE}", timeout_s))
        except _NoAnswer:
            return None

    return within(timeout_s, fetch, name="github-notki-wydan")


def parse_published(document: object) -> tuple[PublishedRelease, ...] | None:
    """Wydania z odpowiedzi listy GitHub Releases; ``None``, gdy odpowiedź nie jest listą.

    Szkic, wersja przedpremierowa, tag, który nie jest Wydaniem, i wpis w innym kształcie się nie liczą; Release bez
    treści ma pustą notkę.
    """

    if not isinstance(document, list):
        return None
    return tuple(published for entry in document if (published := _published(entry)) is not None)


def _published(entry: object) -> PublishedRelease | None:
    if not isinstance(entry, dict) or entry.get("draft") is not False or entry.get("prerelease") is not False:
        return None
    tag, notes, at = entry.get("tag_name"), entry.get("body"), entry.get("published_at")
    release = Release.of_tag(tag) if isinstance(tag, str) else None
    if release is None or not isinstance(notes, str | None) or not isinstance(at, str):
        return None
    try:
        published_at = datetime.fromisoformat(at)
    except ValueError:
        return None
    return PublishedRelease(release, notes or "", published_at) if published_at.tzinfo is not None else None


class _NoAnswer(Exception):
    """GitHub nie dał pełnej odpowiedzi; Aktualność to wtedy ``None``."""


def _tag_commits(url: str, timeout_s: float) -> dict[str, str] | None:
    """Tagi i ich commity ze wszystkich stron listy tagów; ``None`` bez pełnej listy."""

    commits: dict[str, str] = {}
    page = url
    for _ in range(_PAGES):
        try:
            tags, following = _page(page, timeout_s)
        except _NoAnswer:
            return None
        if not isinstance(tags, list):
            return None
        for tag in tags:
            named = _tag_commit(tag)
            if named is not None:
                commits[named[0]] = named[1]
        if following is None:
            return commits
        page = following
    return None


def _json(url: str, timeout_s: float) -> object:
    return _page(url, timeout_s)[0]


def _page(url: str, timeout_s: float) -> tuple[object, str | None]:
    """Treść JSON odpowiedzi ``url`` i adres następnej strony z nagłówka ``Link``; ``_NoAnswer`` przy porażce."""

    request = urllib.request.Request(url, headers={"Accept": "application/vnd.github+json", "User-Agent": "centrum-rozliczen"})
    direct = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    try:
        with direct.open(request, timeout=timeout_s) as response:
            return json.loads(response.read(_PAGE_BYTES)), _next_page(response.headers.get("Link"))
    except (OSError, ValueError) as failure:  # brak sieci, odmowa GitHuba (HTTPError), zerwane połączenie, nie JSON
        raise _NoAnswer from failure


def _tag_commit(tag: object) -> tuple[str, str] | None:
    """Nazwa tagu i jego commit z jednego wpisu listy tagów; ``None`` dla wpisu w innym kształcie."""

    if not isinstance(tag, dict):
        return None
    name, commit = tag.get("name"), tag.get("commit")
    sha = commit.get("sha") if isinstance(commit, dict) else None
    return (name, sha) if isinstance(name, str) and isinstance(sha, str) and is_commit(sha) else None


def _next_page(link: str | None) -> str | None:
    found = None if link is None else _NEXT_PAGE.search(link)
    return None if found is None else found[1]


_NEXT_PAGE: Final = re.compile(r'<([^>]+)>;\s*rel="next"')

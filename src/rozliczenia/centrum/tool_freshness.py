"""Aktualność narzędzia: commit narzędzia u taty względem najnowszego Wydania na publicznym GitHubie.

Diagnoza i Konfiguracja porównują dwa źródła z ``ToolFreshness``: commit
narzędzia, z którego działa Centrum (``version.tool_commit`` odczytany przy
starcie), i commit najnowszego Wydania publicznego repozytorium narzędzia
(ADR 0014; ten sam wybór tagu co w Aktualizacji narzędzia,
``tool_update.newest_release``). Oba są wstrzykiwane do aplikacji Centrum, więc testy i
weryfikacja w przeglądarce nigdy nie łączą się z GitHubem. Brak sieci to
``None`` w krótkim limicie czasu, nigdy wyjątek ani Komunikat. Diagnoza pyta
GitHuba przy każdym sprawdzeniu; Konfiguracja, odczytywana przy każdym wejściu
na stronę, pamięta jego odpowiedź (``RememberedMain``).
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import date
import json
from pathlib import Path
import re
import threading
from typing import Final
import urllib.request

from rozliczenia import TOOL_ROOT
from rozliczenia.centrum.deadline import within
from rozliczenia.centrum.tool_update import newest_release
from rozliczenia.centrum.version import commit_since, is_commit, tool_commit

CommitSource = Callable[[], str | None]

RELEASES_URL: Final = "https://api.github.com/repos/MAXIMISEART-AI/MAXIMISEART-Dad/tags?per_page=100"
# 1000 tagów: przy Wydaniu na tydzień na lata. Strona 100 tagów to kilkadziesiąt kB.
_PAGES: Final = 10
_PAGE_BYTES: Final = 1_000_000
_TIMEOUT_S: Final = 3.0


@dataclass(frozen=True)
class ToolFreshness:
    """Źródła wersji narzędzia u taty i najnowszego Wydania na GitHubie; ``None`` = nie wiadomo.

    ``local`` to commit narzędzia, z którego działa Centrum, ``since`` dzień, od
    którego narzędzie jest na tym commicie, a ``main`` commit najnowszego
    Wydania na GitHubie; nazwa pola pochodzi sprzed ADR 0014.
    """

    local: CommitSource
    since: Callable[[], date | None]
    main: CommitSource

    @classmethod
    def of_system(cls) -> ToolFreshness:
        return cls.of_clone(TOOL_ROOT, github_release_commit)

    @classmethod
    def of_clone(cls, root: Path, main: CommitSource) -> ToolFreshness:
        """Wersja narzędzia w ``root`` odczytana teraz, przy starcie Centrum.

        Klon przesunięty później (ręcznie albo przez aktualizację przed ponownym startem) nie zmienia kodu, który
        już działa, więc nie zmienia też wersji tego Centrum.
        """

        running = tool_commit(root)
        since = None if running is None else commit_since(running, root)
        return cls(local=lambda: running, since=lambda: since, main=main)



# API GitHuba bez logowania odpowiada na 60 pytań na godzinę z jednego adresu, a bez sieci każde pytanie czeka do
# 3 s: Konfiguracja pamięta odpowiedź przez 10 minut, a brak odpowiedzi przez minutę (internet może zaraz wrócić).
MAIN_KEPT_S: Final = 10 * 60
NO_ANSWER_KEPT_S: Final = 60


class RememberedMain:
    """Commit najnowszego Wydania z ``main``, pamiętany przez ``MAIN_KEPT_S`` na zegarze ``clock``; brak odpowiedzi krócej."""

    def __init__(self, main: CommitSource, *, clock: Callable[[], float]) -> None:
        self._main = main
        self._clock = clock
        self._lock = threading.Lock()
        self._answer: str | None = None
        self._asked_at: float | None = None

    def __call__(self) -> str | None:
        with self._lock:
            if self._asked_at is not None:
                kept = MAIN_KEPT_S if self._answer is not None else NO_ANSWER_KEPT_S
                if self._clock() - self._asked_at < kept:
                    return self._answer
        answer = self._main()
        with self._lock:
            self._answer, self._asked_at = answer, self._clock()
        return answer


def github_release_commit() -> str | None:
    """Commit najnowszego Wydania publicznego repozytorium; ``None`` bez sieci, bez Wydania, po limicie czasu, przy odmowie."""

    return release_commit_from(RELEASES_URL, timeout_s=_TIMEOUT_S)


def release_commit_from(url: str, *, timeout_s: float) -> str | None:
    """Commit najnowszego Wydania z listy tagów API GitHuba pod ``url``, najpóźniej po ``timeout_s`` sekundach.

    Lista przychodzi stronami (nagłówek ``Link``); bez wszystkich stron nie
    wiadomo, które Wydanie jest najnowsze, więc więcej niż ``_PAGES`` stron to
    ``None``. Diagnoza czeka na odpowiedź najwyżej ``timeout_s``
    (``deadline.within``). Połączenie idzie wprost, bez serwera proxy z
    ustawień systemu.
    """

    def fetch() -> str | None:
        direct = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        commits: dict[str, str] = {}
        page = url
        for _ in range(_PAGES):
            request = urllib.request.Request(
                page, headers={"Accept": "application/vnd.github+json", "User-Agent": "centrum-rozliczen"}
            )
            try:
                with direct.open(request, timeout=timeout_s) as response:
                    tags = json.loads(response.read(_PAGE_BYTES))
                    following = _next_page(response.headers.get("Link"))
            except (OSError, ValueError):  # brak sieci, odmowa GitHuba (HTTPError), zerwane połączenie, nie JSON
                return None
            if not isinstance(tags, list):
                return None
            for tag in tags:
                named = _tag_commit(tag)
                if named is not None:
                    commits[named[0]] = named[1]
            if following is None:
                newest = newest_release(commits)
                return None if newest is None else commits[newest.tag]
            page = following
        return None

    return within(timeout_s, fetch, name="github-wydania")


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

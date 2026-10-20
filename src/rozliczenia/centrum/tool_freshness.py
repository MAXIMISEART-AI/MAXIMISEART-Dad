"""Aktualność narzędzia: commit narzędzia u taty względem `main` na publicznym GitHubie.

Diagnoza porównuje dwa źródła z ``ToolFreshness``: commit klonu narzędzia
(``version.tool_commit``) i commit `main` publicznego repozytorium narzędzia.
Oba są wstrzykiwane do aplikacji Centrum, więc testy i weryfikacja w
przeglądarce nigdy nie łączą się z GitHubem. Brak sieci to ``None`` w krótkim
limicie czasu, nigdy wyjątek ani Komunikat.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
import re
import threading
from typing import Final
import urllib.request

from rozliczenia.centrum.version import tool_commit

CommitSource = Callable[[], str | None]

MAIN_COMMIT_URL: Final = "https://api.github.com/repos/MAXIMISEART-AI/MAXIMISEART-Dad/commits/main"
_TIMEOUT_S: Final = 3.0
_COMMIT = re.compile(r"[0-9a-f]{40}")


@dataclass(frozen=True)
class ToolFreshness:
    """Źródła commitu narzędzia u taty (``local``) i `main` na GitHubie (``main``); ``None`` = nie wiadomo."""

    local: CommitSource
    main: CommitSource

    @classmethod
    def of_system(cls) -> ToolFreshness:
        return cls(local=tool_commit, main=github_main_commit)


def github_main_commit() -> str | None:
    """Commit `main` publicznego repozytorium narzędzia; ``None`` bez sieci, po limicie czasu albo przy odmowie."""

    return main_commit_from(MAIN_COMMIT_URL, timeout_s=_TIMEOUT_S)


def main_commit_from(url: str, *, timeout_s: float) -> str | None:
    """Commit z odpowiedzi ``url`` API GitHuba w postaci samego SHA, najpóźniej po ``timeout_s`` sekundach.

    Limit gniazda nie obejmuje rozwiązywania nazwy, więc zapytanie biegnie w
    osobnym wątku, a Diagnoza czeka na nie najwyżej ``timeout_s``. Połączenie
    idzie wprost, bez serwera proxy z ustawień systemu.
    """

    answer: list[str | None] = [None]

    def fetch() -> None:
        request = urllib.request.Request(
            url, headers={"Accept": "application/vnd.github.sha", "User-Agent": "centrum-rozliczen"}
        )
        direct = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        try:
            with direct.open(request, timeout=timeout_s) as response:
                body = response.read(100).decode("ascii", errors="replace").strip()
        except (OSError, ValueError):  # brak sieci, odmowa GitHuba (HTTPError) albo zerwane połączenie
            return
        answer[0] = body if _COMMIT.fullmatch(body) else None

    worker = threading.Thread(target=fetch, name="github-main", daemon=True)
    worker.start()
    worker.join(timeout_s)
    return None if worker.is_alive() else answer[0]

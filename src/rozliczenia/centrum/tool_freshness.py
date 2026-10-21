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
from typing import Final, Literal
import urllib.request

from rozliczenia.centrum.deadline import within
from rozliczenia.centrum.version import is_commit, tool_commit

CommitSource = Callable[[], str | None]

MAIN_COMMIT_URL: Final = "https://api.github.com/repos/MAXIMISEART-AI/MAXIMISEART-Dad/commits/main"
_TIMEOUT_S: Final = 3.0


@dataclass(frozen=True)
class ToolFreshness:
    """Źródła commitu narzędzia u taty (``local``) i `main` na GitHubie (``main``); ``None`` = nie wiadomo."""

    local: CommitSource
    main: CommitSource

    @classmethod
    def of_system(cls) -> ToolFreshness:
        return cls(local=tool_commit, main=github_main_commit)

    def state(self) -> Literal["current", "newer", "not_checked"]:
        """Czy commit narzędzia to `main`; ``not_checked`` bez commitu Gita albo bez odpowiedzi GitHuba."""

        local = self.local()
        main = None if local is None else self.main()
        if local is None or main is None:
            return "not_checked"
        return "current" if main == local else "newer"


def github_main_commit() -> str | None:
    """Commit `main` publicznego repozytorium narzędzia; ``None`` bez sieci, po limicie czasu albo przy odmowie."""

    return main_commit_from(MAIN_COMMIT_URL, timeout_s=_TIMEOUT_S)


def main_commit_from(url: str, *, timeout_s: float) -> str | None:
    """Commit z odpowiedzi ``url`` API GitHuba w postaci samego SHA, najpóźniej po ``timeout_s`` sekundach.

    Diagnoza czeka na odpowiedź najwyżej ``timeout_s`` (``deadline.within``).
    Połączenie idzie wprost, bez serwera proxy z ustawień systemu.
    """

    def fetch() -> str | None:
        request = urllib.request.Request(
            url, headers={"Accept": "application/vnd.github.sha", "User-Agent": "centrum-rozliczen"}
        )
        direct = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        try:
            with direct.open(request, timeout=timeout_s) as response:
                body = response.read(100).decode("ascii", errors="replace").strip()
        except (OSError, ValueError):  # brak sieci, odmowa GitHuba (HTTPError) albo zerwane połączenie
            return None
        return body if is_commit(body) else None

    return within(timeout_s, fetch, name="github-main")

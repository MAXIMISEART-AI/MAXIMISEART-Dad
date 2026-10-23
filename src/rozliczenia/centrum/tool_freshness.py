"""Aktualność narzędzia: commit narzędzia u taty względem Stabilnej wersji na publicznym GitHubie.

Diagnoza i Konfiguracja porównują dwa źródła z ``ToolFreshness``: commit
narzędzia, z którego działa Centrum (``version.tool_commit`` odczytany przy
starcie), i commit gałęzi `stabilna` publicznego repozytorium narzędzia, tej
samej, z której pobiera Aktualizacja narzędzia (ADR 0014). Oba są wstrzykiwane do aplikacji Centrum, więc testy i
weryfikacja w przeglądarce nigdy nie łączą się z GitHubem. Brak sieci to
``None`` w krótkim limicie czasu, nigdy wyjątek ani Komunikat. Diagnoza pyta
GitHuba przy każdym sprawdzeniu; Konfiguracja, odczytywana przy każdym wejściu
na stronę, pamięta jego odpowiedź (``RememberedMain``).
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import date
from pathlib import Path
import threading
from typing import Final
import urllib.request

from rozliczenia import TOOL_ROOT
from rozliczenia.centrum.deadline import within
from rozliczenia.centrum.tool_update import STABLE_BRANCH
from rozliczenia.centrum.version import commit_since, is_commit, tool_commit

CommitSource = Callable[[], str | None]

STABLE_COMMIT_URL: Final = f"https://api.github.com/repos/MAXIMISEART-AI/MAXIMISEART-Dad/commits/{STABLE_BRANCH}"
_TIMEOUT_S: Final = 3.0


@dataclass(frozen=True)
class ToolFreshness:
    """Źródła wersji narzędzia u taty i Stabilnej wersji na GitHubie; ``None`` = nie wiadomo.

    ``local`` to commit narzędzia, z którego działa Centrum, ``since`` dzień, od
    którego narzędzie jest na tym commicie, a ``main`` commit Stabilnej wersji (gałąź `stabilna`)
    na GitHubie; nazwa pola pochodzi sprzed ADR 0014.
    """

    local: CommitSource
    since: Callable[[], date | None]
    main: CommitSource

    @classmethod
    def of_system(cls) -> ToolFreshness:
        return cls.of_clone(TOOL_ROOT, github_stable_commit)

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
    """Commit Stabilnej wersji z ``main``, pamiętany przez ``MAIN_KEPT_S`` na zegarze ``clock``; brak odpowiedzi krócej."""

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


def github_stable_commit() -> str | None:
    """Commit gałęzi `stabilna` publicznego repozytorium; ``None`` bez sieci i bez tej gałęzi, po limicie czasu, przy odmowie."""

    return commit_from(STABLE_COMMIT_URL, timeout_s=_TIMEOUT_S)


def commit_from(url: str, *, timeout_s: float) -> str | None:
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

    return within(timeout_s, fetch, name="github-stabilna")

"""Zamknięcie Centrum rozliczeń przyciskiem „Zamknij Centrum rozliczeń”.

Zamknięcie karty przeglądarki nie wyłącza serwera; robi to tylko ta prośba
(albo wylogowanie z Windows). ``serve`` czeka na prośbę i kończy pracę po
wysłaniu odpowiedzi. Inna część serwera może odmówić zamknięcia przez
``refuse_while``, np. trwające Uruchomienie procesu.
"""

from __future__ import annotations

from collections.abc import Callable
import threading

from fastapi import APIRouter

from rozliczenia.centrum import contract
from rozliczenia.centrum.log import CentrumLog

Refusal = Callable[[], str | None]
"""Bezpieczny komunikat, dlaczego teraz nie można zamknąć Centrum, albo ``None``, gdy można."""


class Shutdown:
    def __init__(self, log: CentrumLog) -> None:
        self._log = log
        self._requested = threading.Event()
        self._refusals: list[Refusal] = []

    def refuse_while(self, refusal: Refusal) -> None:
        """Dokłada warunek odmowy; sprawdzany przy każdej prośbie o zamknięcie, w kolejności dodania."""

        self._refusals.append(refusal)

    def request(self) -> None:
        for refusal in self._refusals:
            message = refusal()
            if message is not None:
                raise contract.Refusal(409, message)
        self._log.shutdown_requested()
        self._requested.set()

    def wait(self) -> None:
        self._requested.wait()


def shutdown_router(shutdown: Shutdown) -> APIRouter:
    router = APIRouter(prefix="/api/shutdown", tags=["centrum"])

    @router.post("", operation_id="closeCentrum", status_code=202, responses={409: {"model": contract.Problem}})
    def close() -> contract.Closing:
        shutdown.request()
        return contract.Closing(state="closing")

    return router

"""Zatrzymanie Uruchomienia procesu w Centrum: rodzaj, odcisk problemu i pamięć powtórki.

Rodzaj Zatrzymania wynika z treści Komunikatu z katalogu procesu, bez osobnej
listy (``Message.reports_to_maintainer``): Komunikat, który bezwarunkowo każe
przekazać go osobie utrzymującej narzędzie, jest „do Maksa”, tak jak każde
zakończenie inne niż własne zatrzymanie procesu (nieoczekiwany wyjątek, błąd po
silniku). Każdy inny jest „dla taty”, aż wróci identyczny: ten sam odcisk
problemu w następnym Uruchomieniu tego samego procesu to powtórka. Przy
Zatrzymaniu „do Maksa” i powtórce Centrum proponuje Diagnozę
(``diagnosis_offer``); przy nieoczekiwanym wyjątku zaczyna ją od razu.

Pamięć ostatniego Zatrzymania każdego procesu jest tylko w pamięci serwera,
więc restart Centrum ją zeruje.
"""

from __future__ import annotations

from dataclasses import astuple, dataclass
import hashlib
import threading
from typing import Literal

from rozliczenia.centrum import contract
from rozliczenia.message import Message
from rozliczenia.process_run import Stop


@dataclass(frozen=True)
class ProblemFingerprint:
    """Odcisk problemu: proces (albo Aktualizacja narzędzia), kod Komunikatu i jego trzy części.

    Kody są unikalne tylko w katalogu procesu, więc odcisk zawiera proces.
    """

    process: contract.ProcessKey | Literal["tool_update"]  # albo Aktualizacja narzędzia
    code: str
    what: str
    where: str
    action: str

    @classmethod
    def of(cls, process: contract.ProcessKey, message: Message) -> ProblemFingerprint:
        return cls(process, message.code, message.what, message.where, message.action)

    @classmethod
    def of_tool_update(cls, message: Message) -> ProblemFingerprint:
        """Odcisk problemu nieudanej Aktualizacji narzędzia: jej kody są unikalne w jej własnym katalogu."""

        return cls("tool_update", message.code, message.what, message.where, message.action)

    @property
    def digest(self) -> str:
        """Stały skrót odcisku do Zgłoszenia i lokalnego stanu wysłanych; bez treści Komunikatu."""

        return hashlib.sha256("\x1f".join(astuple(self)).encode("utf-8")).hexdigest()[:16]


def diagnosis_offer(stop: Stop | None, kind: contract.StopKind | None) -> contract.DiagnosisOffer | None:
    """Diagnoza przy Zatrzymaniu „do Maksa” i powtórce; przy nieoczekiwanym wyjątku zaczyna się sama."""

    if stop is None or kind is None or kind == "for_tata":
        return None
    return "on_request" if stop.kind == "stop" else "automatic"


class StopMemory:
    """Ostatnie Zatrzymanie każdego procesu od startu Centrum; Uruchomienie bez Zatrzymania je kasuje."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._last: dict[contract.ProcessKey, ProblemFingerprint] = {}

    def kind(self, process: contract.ProcessKey, stop: Stop | None) -> contract.StopKind | None:
        """Rodzaj Zatrzymania ``stop`` względem poprzedniego Uruchomienia procesu; niczego nie zapamiętuje."""

        if stop is None:
            return None
        if stop.kind != "stop" or stop.message.reports_to_maintainer:
            return "for_maks"
        with self._lock:
            previous = self._last.get(process)
        return "repeated" if previous == ProblemFingerprint.of(process, stop.message) else "for_tata"

    def remember(self, process: contract.ProcessKey, stop: Stop | None) -> None:
        with self._lock:
            if stop is None:
                self._last.pop(process, None)
            else:
                self._last[process] = ProblemFingerprint.of(process, stop.message)

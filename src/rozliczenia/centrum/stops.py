"""Zatrzymanie Uruchomienia procesu w Centrum: rodzaj, Powtórka, Diagnoza i Zgłoszenie do Maksa.

``RunHost`` oddaje tu każde zakończone Uruchomienie (``Stops.ended``) i dostaje
``StoppedRun`` albo ``None``. Rodzaj Zatrzymania „dla taty” albo „do Maksa”
rozstrzyga ``Stop.stop_kind``, ta sama reguła co w rekordzie metryk. Centrum
dokłada do niej Powtórkę: Zatrzymanie „dla taty” z tym samym odciskiem problemu
w następnym Uruchomieniu tego samego procesu. Odcisk problemu Zatrzymania
powstaje tylko tutaj, raz. Pamięć ostatniego Zatrzymania każdego procesu jest
tylko w pamięci serwera, więc restart Centrum ją zeruje.

Przy Zatrzymaniu „do Maksa” i Powtórce Centrum proponuje Diagnozę; przy
nieoczekiwanym wyjątku zaczyna ją od razu. ``Stops`` prowadzi Diagnozę
Zatrzymania (Diagnoza, wpis w dzienniku, podgląd Zgłoszenia, pytanie skrzynki)
i wysyłkę Zgłoszenia. Każda z nich zwraca nowy stan Zgłoszenia, a ``RunHost``
pokazuje go na karcie Uruchomienia.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
import threading
from typing import Final, overload

from rozliczenia.centrum import contract
from rozliczenia.centrum.diagnosis import Diagnosis
from rozliczenia.centrum.log import CentrumLog
from rozliczenia.centrum.reports import Draft, ProblemFingerprint, Reports, StopReport
from rozliczenia.process_run import Stop

NO_DIAGNOSIS: Final = "Diagnoza jest przy Zatrzymaniu do Maksa albo przy powtórce tego samego Komunikatu."
_NO_DRAFT: Final = "Zgłoszenie powstaje z Diagnozy. Najpierw kliknij „Diagnoza”."

Diagnose = Callable[[contract.ProcessKey, str], Diagnosis]
"""Diagnoza procesu dla tokenu okresu Zatrzymania, z Ustawieniami taty z chwili kliknięcia."""


class Stops:
    def __init__(self, reports: Reports, diagnosis_of: Diagnose, log: CentrumLog) -> None:
        self._reports = reports
        self._diagnosis_of = diagnosis_of
        self._log = log
        self._lock = threading.Lock()
        self._last: dict[contract.ProcessKey, ProblemFingerprint] = {}

    @overload
    def ended(self, info: contract.RunInfo, stop: Stop) -> StoppedRun: ...

    @overload
    def ended(self, info: contract.RunInfo, stop: None) -> None: ...

    def ended(self, info: contract.RunInfo, stop: Stop | None) -> StoppedRun | None:
        if stop is None:
            with self._lock:
                self._last.pop(info.process, None)
            return None
        fingerprint = ProblemFingerprint.of(info.process, stop.message)
        with self._lock:
            repeated = self._last.get(info.process) == fingerprint
            self._last[info.process] = fingerprint
        kind: contract.StopKind = "repeated" if repeated and stop.stop_kind == "for_tata" else stop.stop_kind
        offer: contract.DiagnosisOffer | None = (
            None if kind == "for_tata" else "on_request" if stop.kind == "stop" else "automatic"
        )
        report = None if offer is None else self._reports.state(fingerprint)
        return StoppedRun(info, stop, fingerprint, kind, offer, report)

    def diagnose(self, stopped: StoppedRun) -> tuple[contract.Diagnosis, contract.ReportState]:
        if stopped.offer is None:
            raise contract.Refusal(409, NO_DIAGNOSIS)
        info = stopped.info
        diagnosis = self._diagnosis_of(info.process, info.period)
        self._log.diagnosed(process=info.process, period=info.period, cause=diagnosis.explanation.code)
        draft = self._reports.draft(info.id, StopReport(info, stopped.stop, stopped.fingerprint, diagnosis))
        state = self._reports.ask(draft)
        stopped.draft = draft
        return diagnosis.view(stopped.stop.message, draft.view), state

    def send(self, stopped: StoppedRun) -> contract.ReportState:
        if stopped.offer is None:
            raise contract.Refusal(409, NO_DIAGNOSIS)
        draft = stopped.draft
        if draft is None:
            raise contract.Refusal(409, _NO_DRAFT)
        return self._reports.send(draft)


@dataclass(eq=False)
class StoppedRun:
    info: contract.RunInfo
    stop: Stop
    fingerprint: ProblemFingerprint
    kind: contract.StopKind
    offer: contract.DiagnosisOffer | None
    report: contract.ReportState | None
    draft: Draft | None = field(default=None, init=False, repr=False)

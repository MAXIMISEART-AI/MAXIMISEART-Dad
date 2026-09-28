"""Pojęcia i wyniki procesu rozliczeń."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import Callable


class ProgressPhase(StrEnum):
    """Typed phase values while retaining the existing Polish strings."""

    CHECKING = "Sprawdzanie"
    READING = "Odczyt danych"
    PLANNING = "Planowanie"
    SAVING = "Zapisywanie"


class ProgressState(StrEnum):
    """States allowed on the settlement observer seam."""

    START = "START"
    END = "END"
    ISSUE_COUNT = "ISSUE_COUNT"
    PLAN_READY = "PLAN_READY"
    WORKER_START = "WORKER_START"
    WORKER_END = "WORKER_END"
    FAILED = "FAILED"


class ProgressProtocolError(ValueError):
    """Controlled error for an invalid progress event combination."""


def _coerce_phase(value: ProgressPhase | str) -> ProgressPhase:
    try:
        return ProgressPhase(value)
    except (TypeError, ValueError) as exc:
        raise ProgressProtocolError(f"Nieznana faza zdarzenia: {value!r}.") from exc


PHASES = tuple(phase.value for phase in ProgressPhase)
SKIPPED_STATUSES = frozenset({"ZABLOKOWANY", "ZLY_SZABLON", "POMINIĘTO"})
ProgressObserver = Callable[["ProgressEvent"], None]


@dataclass(frozen=True)
class Issue:
    """Problem możliwy do pokazania bez ujawniania danych klientów."""

    code: str
    message: str


@dataclass(frozen=True)
class WorkerResult:
    """Bezpieczny wynik dla jednego szablonu."""

    worker_name: str
    output_file: Path
    rows: int
    status: str
    issues: tuple[Issue, ...] = ()


@dataclass(frozen=True)
class ProgressEvent:
    """Bezpieczne zdarzenie postępu dla terminala lub innego adaptera."""

    phase: ProgressPhase
    state: ProgressState
    template_index: int = 0
    template_total: int = 0
    worker_name: str | None = None
    status: str | None = None
    rows: int = 0
    elapsed_ms: int | None = None
    phase_elapsed_ms: int | None = None
    worker_elapsed_ms: int | None = None
    issue_count: int = 0

    def __post_init__(self) -> None:
        phase = _coerce_phase(self.phase)
        try:
            state = ProgressState(self.state)
        except (TypeError, ValueError) as exc:
            raise ProgressProtocolError(f"Nieznany stan zdarzenia: {self.state!r}.") from exc
        object.__setattr__(self, "phase", phase)
        object.__setattr__(self, "state", state)

        for name in ("template_index", "template_total", "rows", "issue_count"):
            value = getattr(self, name)
            if type(value) is not int or value < 0:
                raise ProgressProtocolError(f"Pole {name} musi być nieujemną liczbą całkowitą.")
        for name in ("elapsed_ms", "phase_elapsed_ms", "worker_elapsed_ms"):
            value = getattr(self, name)
            if value is not None and (type(value) is not int or value < 0):
                raise ProgressProtocolError(f"Pole {name} musi być nieujemnym czasem albo None.")
        if (
            self.elapsed_ms is not None
            and self.phase_elapsed_ms is not None
            and self.phase_elapsed_ms > self.elapsed_ms
        ):
            raise ProgressProtocolError("Czas fazy nie może przekraczać czasu uruchomienia.")
        if (
            self.elapsed_ms is not None
            and self.worker_elapsed_ms is not None
            and self.worker_elapsed_ms > self.elapsed_ms
        ):
            raise ProgressProtocolError("Czas wykonawcy nie może przekraczać czasu uruchomienia.")
        if self.template_index > self.template_total:
            raise ProgressProtocolError("template_index nie może przekraczać template_total.")
        if self.worker_name is not None:
            if not isinstance(self.worker_name, str) or not self.worker_name.strip():
                raise ProgressProtocolError("worker_name musi być niepustym tekstem albo None.")
            if any(character in self.worker_name for character in "\r\n\x00"):
                raise ProgressProtocolError("worker_name zawiera niedozwolone znaki.")
        if self.status is not None:
            if not isinstance(self.status, str) or not self.status.strip():
                raise ProgressProtocolError("status musi być niepustym tekstem albo None.")
            if any(character in self.status for character in "\r\n\x00"):
                raise ProgressProtocolError("status zawiera niedozwolone znaki.")

        if state is ProgressState.START:
            self._require_empty_context(allow_template_total=False, allow_phase_elapsed=False)
        elif state is ProgressState.END:
            self._require_empty_context(allow_template_total=True, allow_phase_elapsed=True)
            if phase is not ProgressPhase.SAVING and self.template_total:
                raise ProgressProtocolError("template_total jest dozwolone na END tylko dla Zapisywanie.")
            if phase is ProgressPhase.SAVING and self.template_index != self.template_total:
                raise ProgressProtocolError("END dla Zapisywanie wymaga końcowej pozycji szablonu.")
        elif state is ProgressState.ISSUE_COUNT:
            self._require_empty_context(
                allow_template_total=False,
                allow_issue_count=True,
                allow_phase_elapsed=False,
            )
            if phase is not ProgressPhase.READING:
                raise ProgressProtocolError("ISSUE_COUNT jest dozwolone tylko dla Odczyt danych.")
        elif state is ProgressState.PLAN_READY:
            self._require_empty_context(
                allow_template_total=True,
                allow_issue_count=True,
                allow_phase_elapsed=False,
            )
            if phase is not ProgressPhase.PLANNING:
                raise ProgressProtocolError("PLAN_READY jest dozwolone tylko dla Planowanie.")
            if self.template_index:
                raise ProgressProtocolError("PLAN_READY nie może zawierać bieżącej pozycji szablonu.")
        elif state is ProgressState.WORKER_START:
            self._require_worker_context(
                require_status=False,
                require_rows=False,
                allow_worker_elapsed=False,
                allow_phase_elapsed=False,
            )
        elif state is ProgressState.WORKER_END:
            self._require_worker_context(
                require_status=True,
                require_rows=True,
                allow_worker_elapsed=True,
                allow_phase_elapsed=False,
            )
        elif state is ProgressState.FAILED:
            if self.status is not None or self.rows or self.issue_count:
                raise ProgressProtocolError("FAILED nie może zawierać statusu, wierszy ani liczby problemów.")
            if self.worker_name is not None:
                if phase is not ProgressPhase.SAVING:
                    raise ProgressProtocolError("FAILED z wykonawcą jest dozwolone tylko dla Zapisywanie.")
                self._require_worker_context(
                    require_status=False,
                    require_rows=False,
                    allow_worker_elapsed=True,
                    allow_phase_elapsed=True,
                )
            else:
                if self.worker_elapsed_ms is not None:
                    raise ProgressProtocolError("FAILED bez wykonawcy nie może zawierać czasu wykonawcy.")
                if self.template_index or self.template_total:
                    raise ProgressProtocolError("FAILED bez wykonawcy nie może zawierać pozycji szablonu.")

    def _require_empty_context(
        self,
        *,
        allow_template_total: bool,
        allow_issue_count: bool = False,
        allow_phase_elapsed: bool,
    ) -> None:
        if self.worker_name is not None or self.status is not None or self.rows:
            raise ProgressProtocolError("Zdarzenie fazy zawiera kontekst wykonawcy lub wierszy.")
        if not allow_phase_elapsed and self.phase_elapsed_ms is not None:
            raise ProgressProtocolError("To zdarzenie nie może zawierać czasu fazy.")
        if self.worker_elapsed_ms is not None:
            raise ProgressProtocolError("Zdarzenie fazy nie może zawierać czasu wykonawcy.")
        if not allow_template_total and (self.template_index or self.template_total):
            raise ProgressProtocolError("To zdarzenie nie może zawierać pozycji szablonu.")
        if not allow_issue_count and self.issue_count:
            raise ProgressProtocolError("To zdarzenie nie może zawierać liczby problemów.")

    def _require_worker_context(
        self,
        *,
        require_status: bool,
        require_rows: bool,
        allow_worker_elapsed: bool,
        allow_phase_elapsed: bool,
    ) -> None:
        if self.phase is not ProgressPhase.SAVING:
            raise ProgressProtocolError("Zdarzenie wykonawcy jest dozwolone tylko dla Zapisywanie.")
        if self.worker_name is None:
            raise ProgressProtocolError("Zdarzenie wykonawcy wymaga worker_name.")
        if not self.template_total or not self.template_index:
            raise ProgressProtocolError("Zdarzenie wykonawcy wymaga pozycji wśród szablonów.")
        if not allow_phase_elapsed and self.phase_elapsed_ms is not None:
            raise ProgressProtocolError("Zdarzenie wykonawcy nie może zawierać czasu fazy.")
        if require_status and self.status is None:
            raise ProgressProtocolError("WORKER_END wymaga statusu.")
        if not require_status and self.status is not None:
            raise ProgressProtocolError("WORKER_START nie może zawierać statusu.")
        if not require_rows and self.rows:
            raise ProgressProtocolError("WORKER_START nie może zawierać liczby wierszy.")
        if not require_rows and self.issue_count:
            raise ProgressProtocolError("WORKER_START nie może zawierać liczby problemów.")
        if not allow_worker_elapsed and self.worker_elapsed_ms is not None:
            raise ProgressProtocolError("WORKER_START nie może zawierać czasu wykonawcy.")


class ProgressEventFactory:
    """Centralne fabryki kompatybilnych i walidowanych zdarzeń przebiegu."""

    @staticmethod
    def phase_started(phase: ProgressPhase | str, *, elapsed_ms: int | None = None) -> ProgressEvent:
        return ProgressEvent(_coerce_phase(phase), ProgressState.START, elapsed_ms=elapsed_ms)

    @staticmethod
    def phase_ended(
        phase: ProgressPhase | str,
        *,
        elapsed_ms: int | None = None,
        phase_elapsed_ms: int | None = None,
        template_index: int = 0,
        template_total: int = 0,
    ) -> ProgressEvent:
        return ProgressEvent(
            _coerce_phase(phase),
            ProgressState.END,
            template_index=template_index,
            template_total=template_total,
            elapsed_ms=elapsed_ms,
            phase_elapsed_ms=phase_elapsed_ms,
        )

    @staticmethod
    def phase_failed(
        phase: ProgressPhase | str,
        *,
        elapsed_ms: int | None = None,
        phase_elapsed_ms: int | None = None,
    ) -> ProgressEvent:
        return ProgressEvent(
            _coerce_phase(phase),
            ProgressState.FAILED,
            elapsed_ms=elapsed_ms,
            phase_elapsed_ms=phase_elapsed_ms,
        )

    @staticmethod
    def issue_count(*, elapsed_ms: int | None = None, issue_count: int = 0) -> ProgressEvent:
        return ProgressEvent(
            ProgressPhase.READING,
            ProgressState.ISSUE_COUNT,
            elapsed_ms=elapsed_ms,
            issue_count=issue_count,
        )

    @staticmethod
    def plan_ready(
        *,
        elapsed_ms: int | None = None,
        template_total: int = 0,
        issue_count: int = 0,
    ) -> ProgressEvent:
        return ProgressEvent(
            ProgressPhase.PLANNING,
            ProgressState.PLAN_READY,
            elapsed_ms=elapsed_ms,
            template_total=template_total,
            issue_count=issue_count,
        )

    @staticmethod
    def worker_started(
        worker_name: str,
        *,
        elapsed_ms: int | None = None,
        template_index: int,
        template_total: int,
    ) -> ProgressEvent:
        return ProgressEvent(
            ProgressPhase.SAVING,
            ProgressState.WORKER_START,
            template_index=template_index,
            template_total=template_total,
            worker_name=worker_name,
            elapsed_ms=elapsed_ms,
        )

    @staticmethod
    def worker_ended(
        worker_name: str,
        *,
        status: str,
        rows: int,
        elapsed_ms: int | None = None,
        worker_elapsed_ms: int | None = None,
        template_index: int,
        template_total: int,
        issue_count: int = 0,
    ) -> ProgressEvent:
        return ProgressEvent(
            ProgressPhase.SAVING,
            ProgressState.WORKER_END,
            template_index=template_index,
            template_total=template_total,
            worker_name=worker_name,
            status=status,
            rows=rows,
            elapsed_ms=elapsed_ms,
            worker_elapsed_ms=worker_elapsed_ms,
            issue_count=issue_count,
        )

    @staticmethod
    def worker_failed(
        worker_name: str,
        *,
        elapsed_ms: int | None = None,
        phase_elapsed_ms: int | None = None,
        worker_elapsed_ms: int | None = None,
        template_index: int,
        template_total: int,
    ) -> ProgressEvent:
        return ProgressEvent(
            ProgressPhase.SAVING,
            ProgressState.FAILED,
            template_index=template_index,
            template_total=template_total,
            worker_name=worker_name,
            elapsed_ms=elapsed_ms,
            phase_elapsed_ms=phase_elapsed_ms,
            worker_elapsed_ms=worker_elapsed_ms,
        )


@dataclass
class SettlementSummary:
    """Podsumowanie operacyjne bez zawartości wierszy klientów."""

    period: str
    source_file: Path
    target_directory: Path
    results: list[WorkerResult] = field(default_factory=list)
    issues: list[Issue] = field(default_factory=list)

    @property
    def written_count(self) -> int:
        return sum(result.status == "ZAPISANO" for result in self.results)

    @property
    def planned_count(self) -> int:
        return sum(result.status == "PLAN" for result in self.results)

    @property
    def empty_count(self) -> int:
        return sum(result.status == "PUSTY_SZABLON" for result in self.results)

    @property
    def total_rows(self) -> int:
        return sum(result.rows for result in self.results)

    @property
    def skipped_count(self) -> int:
        return sum(result.status in SKIPPED_STATUSES for result in self.results)

    @property
    def template_count(self) -> int:
        return len(self.results)

    @property
    def ok(self) -> bool:
        return not self.issues

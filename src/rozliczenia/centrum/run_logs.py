"""Logi Uruchomienia na komputerze taty (ADR 0015): jeden plik JSON na Uruchomienie procesu z Centrum.

Działanie po wyniku Uruchomienia (``runs.AfterRun``), w każdej drodze zakończenia i w obu trybach. Logi powstają
z tego, co ma karta Uruchomienia (``EndedRun``): wynik, Komunikaty z kodami, podsumowanie, etapy, ślad wywołań
Zatrzymania, a z ostatniego snapshotu projekcji postępu (``Outcome.progress``) Przetworzenia Szablonów pracownika
i liczba problemów. Środowisko to system, Python i pliki procesu z Diagnozy z rozmiarem i atrybutem OneDrive.
Logi nie mają treści komórek: żadne pole nie niesie Wiersza danych, a pliki mają tylko nazwę, nigdy pełną ścieżkę.
Skrypt dla maszyn nie ma działań po wyniku, więc Logów nie tworzy.

Plik leży w katalogu Logów obok dziennika Centrum, poza Gitem i OneDrive, bez rotacji. Nazwa to czas startu (UTC),
klucz procesu i identyfikator Uruchomienia, więc jest jedna na Uruchomienie i układa się chronologicznie. Zapis jest
atomowy; nieudany wychodzi z ``run_ended``, a ``RunHost.after`` zapisuje w dzienniku tylko jego typ, bez zmiany
wyniku i bez Komunikatu.

Te same Logi idą przez kolejkę Skrzynki Zgłoszeń (``Outbox``) do issue okresu z etykietą ``logi-uruchomienia``,
także zamkniętego: każde Uruchomienie to komentarz z podsumowaniem w Markdown (``summary_markdown``) i pełnym JSON
w zwijanym bloku, a JSON ponad limit komentarza idzie w kolejnych częściach, które sklejone dają tekst pliku.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Callable, Sequence
from datetime import datetime
from functools import cache
from pathlib import Path
import platform
from typing import Final, Literal, assert_never

from pydantic import BaseModel, ConfigDict

from rozliczenia.call_trace import CallTrace
from rozliczenia.centrum import contract
from rozliczenia.centrum.atomic_file import replace_atomically
from rozliczenia.centrum.cloud_files import CloudFiles
from rozliczenia.centrum.outbox import Outbox, PeriodThread, Post
from rozliczenia.centrum.report_box import Label
from rozliczenia.centrum.runs import EndedRun
from rozliczenia.centrum.tool_freshness import CommitSource
from rozliczenia.centrum.version import short_commit
from rozliczenia.domain import WorkerStatus
from rozliczenia.message import Message
from rozliczenia.period_folder import PeriodFolderInaccessible

RUN_LOGS_DIRECTORY: Final = "uruchomienia"
LABEL: Final[Label] = "logi-uruchomienia"

ProcessFiles = Callable[[contract.ProcessKey, str], Sequence[Path]]
"""Pliki taty Uruchomienia procesu dla tokenu okresu, z Ustawieniami taty z chwili końca Uruchomienia."""


class _Record(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class LoggedMessage(_Record):
    """Komunikat karty w trzech częściach z kodem; ``stop`` to Zatrzymanie, ``warning`` ostrzeżenie wyniku."""

    kind: Literal["stop", "warning"]
    code: str
    what: str
    where: str
    action: str

    @classmethod
    def of(cls, kind: Literal["stop", "warning"], message: Message) -> LoggedMessage:
        return cls(kind=kind, code=message.code, what=message.what, where=message.where, action=message.action)


class LoggedTemplate(_Record):
    """Przetworzenie Szablonu pracownika: Wykonawca, wynik, Wiersze danych i czas."""

    wykonawca: str
    outcome: WorkerStatus | Literal["failed"]
    rows: int
    duration_ms: int


class LoggedFile(_Record):
    """Plik taty procesu: sama nazwa, rozmiar i atrybut OneDrive „tylko online”.

    ``size`` ``None``: pliku nie ma albo nie da się go odczytać. ``online_only`` ``None``: poza Windows albo bez pliku.
    """

    name: str
    size: int | None
    online_only: bool | None


class Environment(_Record):
    system: str
    python: str
    files: list[LoggedFile] | None
    """``None``: plików procesu nie dało się wyliczyć (np. Folder okresu niedostępny)."""


class Tool(_Record):
    wydanie: None
    """Wydań (ADR 0014) jeszcze nie ma."""
    commit: str | None


class RunLog(_Record):
    """Logi jednego Uruchomienia procesu z Centrum; kształt tego modelu to schemat pliku JSON.

    ``duration_ms`` to Czas uruchomienia bez czekania na Decyzję taty; ``started_at`` i ``ended_at`` to zegar ścienny.
    ``issue_count``, ``templates`` i ``duration_ms`` są puste tylko wtedy, gdy sam rdzeń (``run_process``) rzucił wyjątek.
    """

    schema_version: Literal[1]
    run_id: str
    process: contract.ProcessKey
    mode: Literal["podgląd", "zapis"]
    period: str
    started_at: datetime
    ended_at: datetime
    duration_ms: int | None
    tool: Tool
    result: contract.RunResult
    ending: Literal["finished", "stop", "unexpected", "after_engine"]
    stop_kind: contract.StopKind | None
    issue_count: int | None
    messages: list[LoggedMessage]
    notices: list[str]
    summary: contract.RunSummary | None
    phases: list[contract.PhaseProgress]
    templates: list[LoggedTemplate]
    environment: Environment
    trace: CallTrace | None
    diagnosis: None
    """Diagnoza dopisze się w osobnej zmianie (nowa wersja schematu)."""

    @classmethod
    def of(cls, run: EndedRun, *, tool: Tool, environment: Environment) -> RunLog:
        info, result, outcome = run.info, run.result, run.outcome
        stop = None if run.stopped is None else run.stopped.stop
        messages = [] if stop is None else [LoggedMessage.of("stop", stop.message)]
        if result.ending == "finished" and outcome is not None and outcome.view is not None:
            messages += [LoggedMessage.of("warning", warning) for warning in outcome.view.shown.warnings]
        progress = None if outcome is None else outcome.progress
        return cls(
            schema_version=1,
            run_id=info.id,
            process=info.process,
            mode="podgląd" if info.dry_run else "zapis",
            period=info.period,
            started_at=run.started_at,
            ended_at=run.ended_at,
            duration_ms=None if outcome is None else outcome.total_duration_ms,
            tool=tool,
            result=result.result,
            ending=result.ending,
            stop_kind=result.stop_kind,
            issue_count=None if progress is None else progress.issue_count,
            messages=messages,
            notices=result.notices,
            summary=result.summary,
            phases=run.progress.phases,
            templates=[]
            if progress is None
            else [
                LoggedTemplate(
                    wykonawca=template.worker_name,
                    outcome=template.outcome,
                    rows=template.rows,
                    duration_ms=template.duration_ms,
                )
                for template in progress.templates
            ],
            environment=environment,
            trace=None if stop is None else stop.trace,
            diagnosis=None,
        )

    @property
    def file_name(self) -> str:
        """``20261023T140507Z-settlement-<run_id>.json``: start w UTC, klucz procesu, identyfikator Uruchomienia."""

        return f"{self.started_at:%Y%m%dT%H%M%SZ}-{self.process}-{self.run_id}.json"

    @property
    def text(self) -> str:
        """Treść pliku Logów; te same znaki idą do Skrzynki Zgłoszeń."""

        return self.model_dump_json(indent=2) + "\n"


def logi_post(record: RunLog) -> Post:
    """Logi do issue okresu w Skrzynce Zgłoszeń: podsumowanie, pod nim JSON w ``<details>``, w razie potrzeby w częściach."""

    period, run_id = record.period, record.run_id

    def frame(number: int, count: int, chunk: str) -> str:
        part = "" if count == 1 else f", część {number}/{count}"
        top = summary_markdown(record) if number == 1 else f"**Logi Uruchomienia** {run_id}{part}"
        return f"{top}\n\n<details><summary>Logi JSON{part}</summary>\n\n````json\n{chunk}\n````\n\n</details>\n"

    return Post.of(
        PeriodThread(
            label=LABEL,
            line=f"- Logi Uruchomienia okresu: {period}",
            closed="reuse",
            title=f"Logi Uruchomienia {period}",
        ),
        period=period,
        run_id=run_id,
        header=(
            f"Logi Uruchomień okresu {period} z Centrum rozliczeń taty. Każde Uruchomienie to komentarz: "
            "podsumowanie, a pod nim pełny JSON Logów. Długie Logi idą w kolejnych komentarzach „część k/n”."
        ),
        blocks=[record.text],
        frame=frame,
    )


def summary_markdown(record: RunLog) -> str:
    """Podsumowanie na górze komentarza Logów: proces, tryb, okres, wynik, czas, kody Komunikatów i Wydanie."""

    commit = "nieznany" if record.tool.commit is None else short_commit(record.tool.commit)
    return (
        f"**Logi Uruchomienia**: {_process(record.process)}, {record.mode}, okres {record.period}\n"
        "\n"
        f"- Wynik: {_result(record)}\n"
        f"- Czas: {_duration(record.duration_ms)}\n"
        f"- Komunikaty: {_codes(record.messages)}\n"
        f"- Wydanie: {record.tool.wydanie or 'brak'}, commit {commit}\n"
        f"- Uruchomienie: {record.run_id}, start {record.started_at:%Y-%m-%d %H:%M:%S} UTC"
    )


def _process(key: contract.ProcessKey) -> str:
    match key:
        case "preparation":
            return "Przygotowanie pliku zbiorczego"
        case "settlement":
            return "Przebieg rozliczeń"
        case _:
            assert_never(key)


def _result(record: RunLog) -> str:
    match record.ending:
        case "finished":
            return record.result
        case "stop":
            return f"{record.result}, {_stop(record.stop_kind)}"
        case "unexpected":
            return f"{record.result}, nieoczekiwany wyjątek"
        case "after_engine":
            return f"{record.result}, błąd po zakończeniu silnika"
        case _:
            assert_never(record.ending)


def _stop(kind: contract.StopKind | None) -> str:
    match kind:
        case "for_tata":
            return "Zatrzymanie dla taty"
        case "for_maks":
            return "Zatrzymanie do Maksa"
        case "repeated":
            return "powtórzone Zatrzymanie dla taty"
        case None:
            return "Zatrzymanie"
        case _:
            assert_never(kind)


def _duration(milliseconds: int | None) -> str:
    if milliseconds is None:
        return "nieznany"
    if milliseconds < 1000:
        return f"{milliseconds} ms"
    return f"{milliseconds / 1000:.1f} s".replace(".", ",")


def _codes(messages: Sequence[LoggedMessage]) -> str:
    """Kody w kolejności karty, każdy raz, z liczbą powtórzeń i rodzajem."""

    counted = Counter((message.kind, message.code) for message in messages)
    if not counted:
        return "brak"
    kinds = {"stop": "Zatrzymanie", "warning": "ostrzeżenie"}
    return ", ".join(
        f"`{code}`{f' ×{count}' if count > 1 else ''} ({kinds[kind]})" for (kind, code), count in counted.items()
    )


class RunLogs:
    """Logi Uruchomienia każdego Uruchomienia procesu z Centrum (``runs.AfterRun``) w katalogu ``directory``."""

    def __init__(
        self,
        directory: Path,
        outbox: Outbox,
        *,
        commit: CommitSource,
        files: ProcessFiles,
        cloud_files: CloudFiles,
    ) -> None:
        self._directory = directory
        self._outbox = outbox
        self._commit = commit
        self._files = files
        self._cloud = cloud_files

    def run_ended(self, run: EndedRun) -> None:
        record = RunLog.of(run, tool=Tool(wydanie=None, commit=self._commit()), environment=self._environment(run))
        try:
            replace_atomically(self._directory / record.file_name, record.text)
        finally:
            # Katalog Logów, który nie przyjął pliku, nie zatrzymuje Logów w drodze do Maksa.
            self._outbox.post(logi_post(record))

    def _environment(self, run: EndedRun) -> Environment:
        try:
            paths = self._files(run.info.process, run.info.period)
        except (OSError, PeriodFolderInaccessible):
            # Niedostępny folder to stan komputera taty, nie nieoczekiwany wyjątek: bez wpisu, który Diagnoza by zgłosiła.
            files = None
        else:
            files = [self._file(path) for path in paths]
        return Environment(system=_system(), python=platform.python_version(), files=files)

    def _file(self, path: Path) -> LoggedFile:
        try:
            size: int | None = path.stat().st_size
        except OSError:
            size = None
        online_only = self._cloud.online_only(path) if self._cloud.checked and size is not None else None
        return LoggedFile(name=path.name, size=size, online_only=online_only)


@cache
def _system() -> str:
    """System raz na pracę Centrum, przy pierwszych Logach, nie przy starcie; nigdy ``platform.node()`` (nazwa komputera)."""

    return platform.platform()

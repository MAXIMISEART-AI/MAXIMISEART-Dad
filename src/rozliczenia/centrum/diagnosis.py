"""Diagnoza Zatrzymania: sprawdzenia komputera taty tylko do odczytu i wyjaśnienie w trzech częściach.

Diagnozę tata uruchamia przy Zatrzymaniu „do Maksa” albo przy powtórce
(``stops``). Każde sprawdzenie używa istniejącej reguły procesu albo
Konfiguracji (odczyt Rejestru zleceń, Sprawdzanie wzorców, wczytanie
konfiguracji wykonawców, odszukanie Folderu okresu, plik blokady Excela) i
gotowego Komunikatu z katalogu procesu; tylko przyczyny bez Komunikatu procesu
mają własny katalog (``diagnosis_messages``). Wyjaśnienie to Komunikat
pierwszego sprawdzenia, które nie przeszło, a gdy przeszły wszystkie:
„Nie znalazłem przyczyny na tym komputerze”. Rodzaj wyjaśnienia (tata usuwa
przyczynę sam albo nie) liczy ta sama reguła co rodzaj Zatrzymania.

Nowe sprawdzenie to funkcja ``(_Computer) -> list[CheckResult]`` dopisana do
``_CHECKS`` procesu, w kolejności, w jakiej ma wyjaśniać. Diagnoza niczego nie
zapisuje ani nie naprawia; jej wynik i ostatnie wpisy dziennika zostają
w ``Diagnosis`` po stronie serwera, np. dla Zgłoszenia.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from functools import cached_property
from pathlib import Path
from typing import Final, Literal

from fastapi import APIRouter

from rozliczenia import preparation_messages, settlement_messages, workbook_files
from rozliczenia.centrum import contract, diagnosis_messages
from rozliczenia.centrum.cloud_files import CloudFiles
from rozliczenia.centrum.configuration import ConfigurationFiles, workers_problem
from rozliczenia.centrum.log import CentrumLog, event_of
from rozliczenia.centrum.runs import RunHost, StoppedRun
from rozliczenia.centrum.tool_freshness import ToolFreshness
from rozliczenia.message import Message, StopError
from rozliczenia.period_folder import PeriodFolder, PeriodFolderLookupError, locate_period_folder
from rozliczenia.preparation_register import ensure_register_available, read_register
from rozliczenia.settings import Settings, SettingsStore
from rozliczenia.settlement_period import SettlementPeriod, parse_period_token

CheckState = Literal["passed", "failed", "not_checked"]

_LOG_ENTRIES: Final = 20
_UNEXPECTED_EVENTS: Final = frozenset({"nieoczekiwany-wyjatek"})


@dataclass(frozen=True)
class CheckResult:
    """Wynik jednego sprawdzenia; ``message`` tylko przy ``failed``, ``detail`` to krótki bezpieczny fakt."""

    label: str
    state: CheckState
    detail: str
    message: Message | None = None

    @classmethod
    def passed(cls, label: str, detail: str) -> CheckResult:
        return cls(label, "passed", detail)

    @classmethod
    def failed(cls, label: str, message: Message) -> CheckResult:
        return cls(label, "failed", message.what, message)

    @classmethod
    def not_checked(cls, label: str, detail: str) -> CheckResult:
        return cls(label, "not_checked", detail)


@dataclass(frozen=True)
class Diagnosis:
    """Wynik Diagnozy: sprawdzenia po kolei i ostatnie wpisy dziennika Centrum od jego startu."""

    stopped: StoppedRun
    checks: tuple[CheckResult, ...]
    log_entries: tuple[str, ...]

    @property
    def cause(self) -> Message | None:
        return next((check.message for check in self.checks if check.message is not None), None)

    @property
    def explanation(self) -> Message:
        return self.cause or diagnosis_messages.cause_not_found()

    @property
    def fixable_by_tata(self) -> bool:
        cause = self.cause
        return cause is not None and not cause.reports_to_maintainer

    def view(self) -> contract.Diagnosis:
        return contract.Diagnosis(
            explanation=contract.Message.of(self.explanation),
            next_action="rerun" if self.fixable_by_tata else "report",
            checks=[contract.DiagnosisCheck(label=check.label, state=check.state, detail=check.detail) for check in self.checks],
        )


@dataclass(frozen=True)
class Surroundings:
    """Granice komputera taty poza jego plikami: commit `main` na GitHubie i atrybuty plików OneDrive."""

    tool_freshness: ToolFreshness
    cloud_files: CloudFiles


@dataclass(frozen=True)
class _Computer:
    """Komputer taty w chwili Diagnozy: Ustawienia taty, Konfiguracja, dziennik i okres Zatrzymania."""

    process: contract.ProcessKey
    period: SettlementPeriod
    settings: Settings
    configuration: ConfigurationFiles
    log: CentrumLog
    surroundings: Surroundings

    @cached_property
    def period_folder(self) -> PeriodFolder | PeriodFolderLookupError | None:
        """Folder okresu odszukany jak w procesie; ``None`` bez folderu okresów."""

        periods_directory = self.settings.existing_periods_directory
        if periods_directory is None:
            return None
        try:
            return locate_period_folder(periods_directory, self.period)
        except PeriodFolderLookupError as error:
            return error

    @cached_property
    def log_entries(self) -> tuple[str, ...]:
        return tuple(self.log.recent(_LOG_ENTRIES))


_Check = Callable[[_Computer], list[CheckResult]]


def _tool_freshness(computer: _Computer) -> list[CheckResult]:
    label = "Aktualność narzędzia"
    freshness = computer.surroundings.tool_freshness
    local = freshness.local()
    if local is None:
        return [CheckResult.not_checked(label, "Nie sprawdzono: narzędzie na tym komputerze nie ma commitu Gita.")]
    main = freshness.main()
    if main is None:
        return [CheckResult.not_checked(label, "Nie sprawdzono: brak połączenia z GitHubem.")]
    if main != local:
        return [CheckResult.failed(label, diagnosis_messages.newer_tool_version())]
    return [CheckResult.passed(label, f"Najnowsza wersja z GitHuba, commit {local[:7]}.")]


def _tata_settings(computer: _Computer) -> list[CheckResult]:
    label = "Ustawienia taty"
    settings = computer.settings
    needed = [("folder okresów", settings.periods_directory, settings.existing_periods_directory)]
    if computer.process == "preparation":
        needed.insert(0, ("Rejestr zleceń", settings.register, settings.existing_register))
    for name, chosen, existing in needed:
        if chosen is None:
            return [CheckResult.not_checked(label, f"Nie wskazano: {name}.")]
        if existing is None:
            missing = (
                preparation_messages.register_missing(chosen)
                if name == "Rejestr zleceń"
                else preparation_messages.periods_directory_missing(chosen)
            )
            return [CheckResult.failed(label, missing)]
    return [CheckResult.passed(label, " i ".join(name for name, _, _ in needed).capitalize() + " są na miejscu.")]


def _register(computer: _Computer) -> list[CheckResult]:
    label = "Rejestr zleceń"
    register = computer.settings.existing_register
    if register is None:
        return [CheckResult.not_checked(label, "Rejestru zleceń nie ma na miejscu.")]
    try:
        ensure_register_available(register)
        read_register(register)
    except StopError as stop:
        return [CheckResult.failed(label, stop.message)]
    return [CheckResult.passed(label, "Nie jest otwarty w Excelu, otwiera się i ma wymagane nagłówki.")]


def _templates(computer: _Computer) -> list[CheckResult]:
    results = []
    for template in computer.configuration.templates():
        if template.used_by != computer.process:
            continue
        problem = template.problem()
        results.append(
            CheckResult.passed(template.label, f"{template.path.name} przechodzi Sprawdzanie.")
            if problem is None
            else CheckResult.failed(template.label, problem)
        )
    problem = workers_problem(computer.configuration.worker_config)
    label = "Konfiguracja wykonawców"
    results.append(
        CheckResult.passed(label, "Wczytuje się.") if problem is None else CheckResult.failed(label, problem)
    )
    return results


_PERIOD_FILE_LABELS: Final[Mapping[str, str]] = {
    "internal_settlement": "Rozliczenie wewnętrzne",
    "collective_file": "Plik zbiorczy",
    "worker_settlements": "Folder rozliczeń pracowników",
}


def _period_folder(computer: _Computer) -> list[CheckResult]:
    label = "Folder okresu"
    folder = computer.period_folder
    if folder is None:
        return [CheckResult.not_checked(label, "Folderu okresów nie ma na miejscu.")]
    if isinstance(folder, PeriodFolderLookupError):
        # Komunikat Przebiegu rozliczeń o odszukaniu jest tylko terminalowy (w Centrum start wymaga Folderu okresu),
        # więc oba procesy wyjaśniają Komunikatem Przygotowania: założyć albo zostawić jeden Folder okresu.
        return [CheckResult.failed(label, preparation_messages.period_folder_lookup_problem(folder))]
    if computer.process == "settlement" and not folder.collective_file.is_file():
        return [CheckResult.failed(label, settlement_messages.collective_file_missing(folder.collective_file))]
    observed = folder.observe()
    present = [
        _PERIOD_FILE_LABELS[name]
        for name, exists in (
            ("internal_settlement", observed.internal_settlement_exists),
            ("collective_file", observed.collective_file_exists),
            ("worker_settlements", observed.worker_settlements_folder_exists),
        )
        if exists
    ]
    if not observed.period_folder_exists:
        return [CheckResult.passed(label, f"Folderu {computer.period.token} jeszcze nie ma.")]
    return [CheckResult.passed(label, f"Pliki okresu: {', '.join(present) if present else 'brak'}.")]


def _period_files_in_excel(computer: _Computer) -> list[CheckResult]:
    label = "Pliki okresu w Excelu"
    folder = computer.period_folder
    if not isinstance(folder, PeriodFolder):
        return [CheckResult.not_checked(label, "Nie odszukano Folderu okresu.")]
    for path in (folder.internal_settlement, folder.collective_file):
        if workbook_files.is_open_in_excel(path):
            return [CheckResult.failed(label, diagnosis_messages.period_file_open(path))]
    return [CheckResult.passed(label, "Żaden plik okresu nie jest otwarty w Excelu.")]


def _files_in_onedrive(computer: _Computer) -> list[CheckResult]:
    label = "Pliki w OneDrive"
    cloud = computer.surroundings.cloud_files
    if not cloud.checked:
        return [CheckResult.not_checked(label, "Nie sprawdzono: tylko w Windows.")]
    files = [path for path in _files_of_process(computer) if path.is_file()]
    for path in files:
        if cloud.online_only(path):
            return [CheckResult.failed(label, diagnosis_messages.file_only_in_cloud(path))]
    return [CheckResult.passed(label, f"Sprawdzone pliki są na tym komputerze: {len(files)}.")]


def _files_of_process(computer: _Computer) -> list[Path]:
    """Rejestr zleceń, wzorce i pliki Folderu okresu, które czyta proces Zatrzymania."""

    files = []
    register = computer.settings.existing_register
    if computer.process == "preparation" and register is not None:
        files.append(register)
    files += [template.path for template in computer.configuration.templates() if template.used_by == computer.process]
    folder = computer.period_folder
    if isinstance(folder, PeriodFolder):
        files += [folder.internal_settlement, folder.collective_file]
        if folder.worker_settlements.is_dir():
            files += sorted(folder.worker_settlements.iterdir())
    return files


def _centrum_log(computer: _Computer) -> list[CheckResult]:
    label = "Dziennik Centrum rozliczeń"
    entries = computer.log_entries
    if any(event_of(entry) in _UNEXPECTED_EVENTS for entry in entries):
        return [CheckResult.failed(label, diagnosis_messages.unexpected_failure_logged())]
    return [CheckResult.passed(label, f"Ostatnie wpisy od startu Centrum: {len(entries)}, bez nieoczekiwanego wyjątku.")]


# Sprawdzenia każdego procesu w kolejności wyjaśniania: pierwsze, które nie przeszło, jest wyjaśnieniem.
_CHECKS: Final[Mapping[contract.ProcessKey, Sequence[_Check]]] = {
    "preparation": (
        _tool_freshness,
        _tata_settings,
        _register,
        _templates,
        _period_folder,
        _period_files_in_excel,
        _files_in_onedrive,
        _centrum_log,
    ),
    "settlement": (
        _tool_freshness,
        _tata_settings,
        _templates,
        _period_folder,
        _period_files_in_excel,
        _files_in_onedrive,
        _centrum_log,
    ),
}


def diagnose(
    stopped: StoppedRun,
    *,
    settings: Settings,
    configuration: ConfigurationFiles,
    log: CentrumLog,
    surroundings: Surroundings,
) -> Diagnosis:
    """Wszystkie sprawdzenia procesu Zatrzymania, tylko do odczytu."""

    info = stopped.info
    period = parse_period_token(info.period)
    computer = _Computer(info.process, period, settings, configuration, log, surroundings)
    checks: list[CheckResult] = []
    for check in _CHECKS[info.process]:
        checks.extend(check(computer))
    return Diagnosis(stopped, tuple(checks), computer.log_entries)


_PROBLEMS: dict[int | str, dict[str, object]] = {404: {"model": contract.Problem}, 409: {"model": contract.Problem}}


def diagnosis_router(
    host: RunHost, store: SettingsStore, configuration: ConfigurationFiles, log: CentrumLog, surroundings: Surroundings
) -> APIRouter:
    router = APIRouter(prefix="/api/runs", tags=["uruchomienia"])

    @router.post("/{run_id}/diagnosis", operation_id="diagnoseRun", responses=_PROBLEMS)
    def run_diagnosis(run_id: str) -> contract.Diagnosis:
        stopped = host.stopped(run_id)
        diagnosis = diagnose(
            stopped, settings=store.load(), configuration=configuration, log=log, surroundings=surroundings
        )
        log.diagnosed(process=stopped.info.process, period=stopped.info.period, cause=diagnosis.explanation.code)
        return diagnosis.view()

    return router

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

Nowe sprawdzenie to funkcja ``(_Computer, label) -> list[CheckResult]`` z
nazwą w ``@_check(label)``, dopisana do ``_CHECKS`` procesu w kolejności, w
jakiej ma wyjaśniać. Sprawdzenie, które samo się nie uda (nieoczekiwany
wyjątek), jest „nie sprawdzono” na swoim miejscu, a typ wyjątku trafia do
dziennika Centrum, nigdy jego treść; reszta sprawdzeń idzie dalej, więc
Diagnoza zawsze kończy się wyjaśnieniem i podglądem Zgłoszenia. Diagnoza
niczego nie zapisuje ani nie naprawia; jej wynik i ostatnie wpisy dziennika
zostają w ``Diagnosis`` po stronie serwera, np. dla Zgłoszenia.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from functools import cached_property
from pathlib import Path
from typing import Final, Literal

from fastapi import APIRouter

from rozliczenia import preparation_messages, preparation_register, settlement_messages, workbook_files
from rozliczenia.centrum import contract, diagnosis_messages
from rozliczenia.centrum.cloud_files import CloudFiles
from rozliczenia.centrum.configuration import ConfigurationFiles, Template, workers_problem
from rozliczenia.centrum.log import CentrumLog, event_of
from rozliczenia.centrum.reports import Reports
from rozliczenia.centrum.runs import RunHost, StoppedRun
from rozliczenia.centrum.stops import ProblemFingerprint
from rozliczenia.centrum.tool_freshness import ToolFreshness
from rozliczenia.message import Message, StopError
from rozliczenia.period_folder import PeriodFolder, PeriodFolderLookupError, locate_period_folder
from rozliczenia.settings import Settings, SettingsStore
from rozliczenia.settlement_period import SettlementPeriod, parse_period_token

CheckState = Literal["passed", "failed", "not_checked"]

_LOG_ENTRIES: Final = 20
_UNEXPECTED_EVENT: Final = "nieoczekiwany-wyjatek"


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

    def view(self, report: contract.ReportDraft) -> contract.Diagnosis:
        """Widok Diagnozy z podglądem Zgłoszenia ``report``, które wyśle „Wyślij do Maksa”."""

        process, explanation = self.stopped.info.process, self.explanation
        # Ten sam Komunikat co Zatrzymanie to ten sam odcisk problemu: kod i trzy części.
        same = ProblemFingerprint.of(process, explanation) == ProblemFingerprint.of(process, self.stopped.stop.message)
        return contract.Diagnosis(
            explanation=contract.Message.of(explanation),
            confirms_stop=same,
            next_action="rerun" if self.fixable_by_tata else "report",
            checks=[contract.DiagnosisCheck(label=check.label, state=check.state, detail=check.detail) for check in self.checks],
            report=report,
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

    @cached_property
    def period_files(self) -> tuple[Path, ...]:
        """Pliki okresu w odszukanym Folderze okresu: oba pliki okresu i rozliczenia pracowników, bez plików blokady."""

        folder = self.period_folder
        if not isinstance(folder, PeriodFolder):
            return ()
        workers = folder.worker_settlements
        worker_files = sorted(
            path for path in (workers.iterdir() if workers.is_dir() else ()) if not path.name.startswith("~$")
        )
        return (folder.internal_settlement, folder.collective_file, *worker_files)

    @cached_property
    def templates(self) -> tuple[Template, ...]:
        """Wzorce, które czyta proces Zatrzymania."""

        return tuple(template for template in self.configuration.templates() if template.used_by == self.process)


_CheckRun = Callable[[_Computer, str], list[CheckResult]]
_NOT_CHECKED_UNEXPECTED: Final = "Nie udało się sprawdzić: nieoczekiwany błąd."


@dataclass(frozen=True)
class _Check:
    """Sprawdzenie pod stałą nazwą ``label``, którą ``run`` dostaje dla swoich wyników."""

    label: str
    run: _CheckRun

    def results(self, computer: _Computer) -> list[CheckResult]:
        """Wyniki sprawdzenia; gdy samo się nie uda, „nie sprawdzono” pod jego nazwą, bez treści wyjątku.

        Typ wyjątku trafia do dziennika Centrum od razu, więc ostatnie wpisy dziennika w Diagnozie i
        Zgłoszeniu już go mają.
        """

        try:
            return self.run(computer, self.label)
        except Exception as failure:  # noqa: BLE001 - granica sprawdzenia: typ wyjątku trafia do dziennika Centrum
            computer.log.unexpected_failure(failure, where=f"Diagnoza: {self.label}")
            return [CheckResult.not_checked(self.label, _NOT_CHECKED_UNEXPECTED)]


def _check(label: str) -> Callable[[_CheckRun], _Check]:
    """Funkcja sprawdzenia jako ``_Check`` pod nazwą ``label``."""

    def named(run: _CheckRun) -> _Check:
        return _Check(label, run)

    return named


@_check("Aktualność narzędzia")
def _tool_freshness(computer: _Computer, label: str) -> list[CheckResult]:
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


@dataclass(frozen=True)
class _Setting:
    """Ścieżka z Ustawień taty: wskazana (``chosen``), istniejąca (``existing``) i Komunikat procesu o jej braku."""

    name: str
    chosen: Path | None
    existing: Path | None
    missing: Callable[[Path], Message]


@_check("Ustawienia taty")
def _tata_settings(computer: _Computer, label: str) -> list[CheckResult]:
    settings = computer.settings
    needed = [
        _Setting(
            "folder okresów",
            settings.periods_directory,
            settings.existing_periods_directory,
            preparation_messages.periods_directory_missing,
        )
    ]
    if computer.process == "preparation":
        needed.insert(
            0,
            _Setting(
                "Rejestr zleceń", settings.register, settings.existing_register, preparation_messages.register_missing
            ),
        )
    for setting in needed:
        if setting.chosen is None:
            return [CheckResult.not_checked(label, f"Nie wskazano: {setting.name}.")]
        if setting.existing is None:
            return [CheckResult.failed(label, setting.missing(setting.chosen))]
    return [CheckResult.passed(label, " i ".join(setting.name for setting in needed).capitalize() + " są na miejscu.")]


@_check("Rejestr zleceń")
def _register(computer: _Computer, label: str) -> list[CheckResult]:
    register = computer.settings.existing_register
    if register is None:
        return [CheckResult.not_checked(label, "Rejestru zleceń nie ma na miejscu.")]
    try:
        # Przez moduł, jak proces: Diagnoza trafia na ten sam odczyt, także podmieniony hakiem awarii weryfikacji.
        preparation_register.ensure_register_available(register)
        preparation_register.read_register(register)
    except StopError as stop:
        return [CheckResult.failed(label, stop.message)]
    return [CheckResult.passed(label, "Nie jest otwarty w Excelu, otwiera się i ma wymagane nagłówki.")]


@_check("Wzorce")
def _templates(computer: _Computer, label: str) -> list[CheckResult]:
    """Każdy Wzorzec procesu jako osobne sprawdzenie pod jego etykietą.

    Wyjątek przy jednym Wzorcu nie ukrywa wyniku drugiego. ``label`` nazywa całość, tylko gdy nie da się
    nawet wyliczyć Wzorców procesu.
    """

    return [
        result
        for template in computer.templates
        for result in _Check(template.label, _template_check(template)).results(computer)
    ]


def _template_check(template: Template) -> _CheckRun:
    def check(computer: _Computer, label: str) -> list[CheckResult]:
        problem = template.problem()
        if problem is None:
            return [CheckResult.passed(label, f"{template.path.name} przechodzi Sprawdzanie.")]
        return [CheckResult.failed(label, problem)]

    return check


@_check("Konfiguracja wykonawców")
def _worker_config(computer: _Computer, label: str) -> list[CheckResult]:
    problem = workers_problem(computer.configuration.worker_config)
    return [CheckResult.passed(label, "Wczytuje się.") if problem is None else CheckResult.failed(label, problem)]


_PERIOD_FILE_LABELS: Final[Mapping[str, str]] = {
    "internal_settlement": "Rozliczenie wewnętrzne",
    "collective_file": "Plik zbiorczy",
    "worker_settlements": "Folder rozliczeń pracowników",
}


@_check("Folder okresu")
def _period_folder(computer: _Computer, label: str) -> list[CheckResult]:
    folder = computer.period_folder
    if folder is None:
        return [CheckResult.not_checked(label, "Folderu okresów nie ma na miejscu.")]
    if isinstance(folder, PeriodFolderLookupError):
        # Przebieg rozliczeń nie ma Komunikatu o odszukaniu (w Centrum start wymaga Folderu okresu),
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


@_check("Pliki okresu w Excelu")
def _period_files_in_excel(computer: _Computer, label: str) -> list[CheckResult]:
    folder = computer.period_folder
    if not isinstance(folder, PeriodFolder):
        return [CheckResult.not_checked(label, "Nie odszukano Folderu okresu.")]
    for path in computer.period_files:
        if workbook_files.is_open_in_excel(path):
            return [CheckResult.failed(label, diagnosis_messages.period_file_open(path))]
    return [CheckResult.passed(label, "Żaden plik okresu nie jest otwarty w Excelu.")]


@_check("Pliki w OneDrive")
def _files_in_onedrive(computer: _Computer, label: str) -> list[CheckResult]:
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
    files += [template.path for template in computer.templates]
    return files + list(computer.period_files)


@_check("Dziennik Centrum rozliczeń")
def _centrum_log(computer: _Computer, label: str) -> list[CheckResult]:
    entries = computer.log_entries
    # Dziennik tylko informuje: jego wpisy idą do Zgłoszenia, a wyjątek w nim nie jest przyczyną na komputerze taty.
    unexpected = ", w tym nieoczekiwany wyjątek" if any(event_of(entry) == _UNEXPECTED_EVENT for entry in entries) else ""
    return [CheckResult.passed(label, f"Ostatnie wpisy od startu Centrum: {len(entries)}{unexpected}.")]


# Sprawdzenia każdego procesu w kolejności wyjaśniania: pierwsze, które nie przeszło, jest wyjaśnieniem.
# OneDrive idzie przed sprawdzeniami, które otwierają Rejestr zleceń, wzorce i pliki okresu: plik tylko w
# chmurze może się nie otworzyć, a wtedy przyczyną jest OneDrive, nie uszkodzony plik. Dziennik idzie
# ostatni, po wpisach o sprawdzeniach, które same się nie udały.
_CHECKS: Final[Mapping[contract.ProcessKey, Sequence[_Check]]] = {
    "preparation": (
        _tool_freshness,
        _tata_settings,
        _files_in_onedrive,
        _register,
        _templates,
        _worker_config,
        _period_folder,
        _period_files_in_excel,
        _centrum_log,
    ),
    "settlement": (
        _tool_freshness,
        _tata_settings,
        _files_in_onedrive,
        _templates,
        _worker_config,
        _period_folder,
        _period_files_in_excel,
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
        checks.extend(check.results(computer))
    return Diagnosis(stopped, tuple(checks), computer.log_entries)


def diagnosis_router(
    host: RunHost,
    store: SettingsStore,
    configuration: ConfigurationFiles,
    log: CentrumLog,
    surroundings: Surroundings,
    reports: Reports,
) -> APIRouter:
    router = APIRouter(prefix="/api/runs", tags=["uruchomienia"])

    @router.post("/{run_id}/diagnosis", operation_id="diagnoseRun", responses=contract.NOT_FOUND_OR_CONFLICT)
    def run_diagnosis(run_id: str) -> contract.Diagnosis:
        stopped = host.stopped(run_id)
        diagnosis = diagnose(
            stopped, settings=store.load(), configuration=configuration, log=log, surroundings=surroundings
        )
        log.diagnosed(process=stopped.info.process, period=stopped.info.period, cause=diagnosis.explanation.code)
        draft, state = reports.draft(diagnosis)
        host.show_report(run_id, state)
        return diagnosis.view(draft)

    return router

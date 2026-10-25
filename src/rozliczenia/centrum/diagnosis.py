"""Diagnoza Zatrzymania: sprawdzenia komputera taty tylko do odczytu i wyjaśnienie w trzech częściach.

Diagnozę tata uruchamia przy Zatrzymaniu „do Maksa” albo przy powtórce
(``stops``). Każde sprawdzenie używa istniejącej reguły procesu albo
Konfiguracji (odczyt Rejestru zleceń, Sprawdzanie wzorców, wczytanie
konfiguracji wykonawców, odszukanie Folderu okresu, plik blokady Excela) i
gotowego Komunikatu z katalogu procesu; tylko przyczyny bez Komunikatu procesu
mają własny katalog (``diagnosis_messages``). Wyjaśnienie to Komunikat
pierwszego sprawdzenia, które nie przeszło, a gdy przeszły wszystkie:
„Nie znalazłem przyczyny na tym komputerze”. Rodzaj wyjaśnienia (tata usuwa
przyczynę sam albo nie) liczy ta sama reguła co rodzaj Zatrzymania. Aktualność
narzędzia sprawdza się po plikach taty: nowsza wersja jest wyjaśnieniem tylko
bez innej przyczyny, a obok innej przyczyny Diagnoza ją tylko proponuje (ADR 0009).

Nowe sprawdzenie to funkcja ``(_Computer, label) -> list[CheckResult]`` z
nazwą w ``@_check(label)``, dopisana do ``_CHECKS`` procesu w kolejności, w
jakiej ma wyjaśniać. Sprawdzenie, które samo się nie uda (nieoczekiwany
wyjątek), jest „nie sprawdzono” na swoim miejscu, a typ wyjątku trafia do
dziennika Centrum, nigdy jego treść; reszta sprawdzeń idzie dalej, więc
Diagnoza zawsze kończy się wyjaśnieniem i podglądem Zgłoszenia. Diagnoza
niczego nie zapisuje ani nie naprawia; jej wynik i ostatnie wpisy dziennika
zostają w ``Diagnosis`` po stronie serwera, dla Zgłoszenia i Logów Uruchomienia.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from functools import cached_property
from pathlib import Path
from typing import Final, Literal

from rozliczenia import input_checks, preparation_messages, settlement_messages, workbook_files
from rozliczenia.centrum import contract, diagnosis_messages
from rozliczenia.centrum.diagnosis_messages import NEWER_TOOL_VERSION
from rozliczenia.centrum.cloud_files import CloudFiles
from rozliczenia.centrum.configuration import ConfigurationFiles, Template, workers_problem
from rozliczenia.centrum.log import CentrumLog, event_of
from rozliczenia.centrum.tool_freshness import ToolFreshness, offers_update
from rozliczenia.centrum.version import short_commit
from rozliczenia.input_checks import Readers
from rozliczenia.message import Message
from rozliczenia.period_folder import (
    PeriodFolder,
    PeriodFolderInaccessible,
    PeriodFolderLookupError,
    locate_period_folder,
    reading,
)
from rozliczenia.settings import Settings
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

    checks: tuple[CheckResult, ...]
    log_entries: tuple[str, ...]

    @property
    def cause(self) -> Message | None:
        return next((check.message for check in self.checks if check.message is not None), None)

    @property
    def explanation(self) -> Message:
        return self.cause or diagnosis_messages.cause_not_found()

    @property
    def proposes_update(self) -> bool:
        """Jest nowsza wersja narzędzia, ale wyjaśnieniem jest inna przyczyna."""

        newer = any(check.message is not None and check.message.code == NEWER_TOOL_VERSION for check in self.checks)
        return newer and self.explanation.code != NEWER_TOOL_VERSION

    @property
    def next_action(self) -> contract.DiagnosisNextAction:
        """Co tata robi po wyjaśnieniu: aktualizuje narzędzie, sam usuwa przyczynę i uruchamia ponownie albo wysyła do Maksa."""

        cause = self.cause
        if cause is None or cause.reports_to_maintainer:
            return "report"
        return "update" if cause.code == NEWER_TOOL_VERSION else "rerun"

    def view(self, stop: Message, report: contract.ReportDraft) -> contract.Diagnosis:
        explanation = self.explanation
        return contract.Diagnosis(
            explanation=contract.Message.of(explanation),
            confirms_stop=explanation == stop,
            next_action=self.next_action,
            update_proposal=self.proposes_update,
            checks=[contract.DiagnosisCheck(label=check.label, state=check.state, detail=check.detail) for check in self.checks],
            report=report,
        )


@dataclass(frozen=True)
class Surroundings:
    """Granice komputera taty poza jego plikami: najnowsze Wydanie na GitHubie i atrybuty plików OneDrive."""

    tool_freshness: ToolFreshness
    cloud_files: CloudFiles


@dataclass(frozen=True)
class _ProcessFiles:
    """Pliki taty, które czyta i zapisuje proces ``process`` w okresie ``period``, wyliczone z Ustawień i Konfiguracji."""

    process: contract.ProcessKey
    period: SettlementPeriod
    settings: Settings
    configuration: ConfigurationFiles

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
    def period_files(self) -> tuple[Path, ...]:
        """Pliki okresu w odszukanym Folderze okresu: oba pliki okresu i rozliczenia pracowników, bez plików blokady."""

        folder = self.period_folder
        if not isinstance(folder, PeriodFolder):
            return ()
        workers = folder.worker_settlements
        with reading(folder.directory):
            worker_files = sorted(
                path for path in (workers.iterdir() if workers.is_dir() else ()) if not path.name.startswith("~$")
            )
        return (folder.internal_settlement, folder.collective_file, *worker_files)

    @cached_property
    def templates(self) -> tuple[Template, ...]:
        """Wzorce, które czyta proces."""

        return tuple(template for template in self.configuration.templates() if template.used_by == self.process)

    @property
    def files(self) -> list[Path]:
        """Rejestr zleceń (tylko Przygotowanie), Wzorce i pliki Folderu okresu; ścieżki mogą nie istnieć."""

        files = []
        register = self.settings.existing_register
        if self.process == "preparation" and register is not None:
            files.append(register)
        files += [template.path for template in self.templates]
        return files + list(self.period_files)


def files_of_process(
    process: contract.ProcessKey, period: str, *, settings: Settings, configuration: ConfigurationFiles
) -> list[Path]:
    """Pliki taty Uruchomienia procesu ``process`` dla tokenu okresu ``period``, ta sama lista co w sprawdzeniu OneDrive.

    Folder okresu czyta przez ``reading``: ``PeriodFolderInaccessible``, gdy się nie da.
    """

    return _ProcessFiles(process, parse_period_token(period), settings, configuration).files


@dataclass(frozen=True)
class _Computer(_ProcessFiles):
    """Komputer taty w chwili Diagnozy: pliki procesu Zatrzymania, dziennik, granice poza plikami taty i czytniki procesu."""

    log: CentrumLog
    surroundings: Surroundings
    readers: Readers

    @cached_property
    def log_entries(self) -> tuple[str, ...]:
        return tuple(self.log.recent(_LOG_ENTRIES))


_CheckRun = Callable[[_Computer, str], list[CheckResult]]
_NOT_CHECKED_UNEXPECTED: Final = "Nie udało się sprawdzić: nieoczekiwany błąd."


@dataclass(frozen=True)
class _Check:
    """Sprawdzenie pod stałą nazwą ``label``, którą ``run`` dostaje dla swoich wyników."""

    label: str
    run: _CheckRun

    def results(self, computer: _Computer) -> list[CheckResult]:
        """Wyniki sprawdzenia; gdy samo się nie uda, „nie sprawdzono” pod jego nazwą, bez treści wyjątku.

        Folder, którego nie da się odczytać, nie jest porażką sprawdzenia, tylko przyczyną: oba procesy
        wyjaśniają ją Komunikatem Przygotowania, jak odszukanie Folderu okresu.

        Typ wyjątku trafia do dziennika Centrum od razu, więc ostatnie wpisy dziennika w Diagnozie i
        Zgłoszeniu już go mają.
        """

        try:
            return self.run(computer, self.label)
        except PeriodFolderInaccessible as inaccessible:
            return [CheckResult.failed(self.label, preparation_messages.folder_inaccessible(inaccessible.folder))]
        except Exception as failure:
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
    judgement = freshness.judge()
    if offers_update(judgement):
        return [CheckResult.failed(label, diagnosis_messages.newer_tool_version())]
    if judgement == "current":
        return [CheckResult.passed(label, f"Najnowsza wersja z GitHuba, commit {short_commit(freshness.local() or '')}.")]
    return [CheckResult.not_checked(label, _NOT_CHECKED_FRESHNESS[judgement])]


_NOT_CHECKED_FRESHNESS: Final = {
    "no_commit": "Nie sprawdzono: narzędzie na tym komputerze nie ma commitu Gita.",
    "no_answer": "Nie sprawdzono: brak połączenia z GitHubem.",
    "no_release": "Nie sprawdzono: na GitHubie nie ma jeszcze żadnego Wydania.",
}


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
    problem = input_checks.register_problem(register, computer.readers)
    if problem is not None:
        return [CheckResult.failed(label, problem)]
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
        problem = template.problem(computer.readers)
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
    observed = folder.observe()
    if computer.process == "settlement" and not observed.collective_file_exists:
        return [CheckResult.failed(label, settlement_messages.collective_file_missing(folder.collective_file))]
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
    files = [path for path in computer.files if path.is_file()]
    for path in files:
        if cloud.online_only(path):
            return [CheckResult.failed(label, diagnosis_messages.file_only_in_cloud(path))]
    return [CheckResult.passed(label, f"Sprawdzone pliki są na tym komputerze: {len(files)}.")]


@_check("Dziennik Centrum rozliczeń")
def _centrum_log(computer: _Computer, label: str) -> list[CheckResult]:
    entries = computer.log_entries
    # Dziennik tylko informuje: jego wpisy idą do Zgłoszenia, a wyjątek w nim nie jest przyczyną na komputerze taty.
    unexpected = ", w tym nieoczekiwany wyjątek" if any(event_of(entry) == _UNEXPECTED_EVENT for entry in entries) else ""
    return [CheckResult.passed(label, f"Ostatnie wpisy od startu Centrum: {len(entries)}{unexpected}.")]


# Sprawdzenia każdego procesu w kolejności wyjaśniania: pierwsze, które nie przeszło, jest wyjaśnieniem.
# OneDrive idzie przed sprawdzeniami, które otwierają Rejestr zleceń, wzorce i pliki okresu: plik tylko w
# chmurze może się nie otworzyć, a wtedy przyczyną jest OneDrive, nie uszkodzony plik. Aktualność narzędzia
# idzie po plikach taty: nowsze Wydanie jest wyjaśnieniem tylko bez innej przyczyny (ADR 0009), bo przyczyny
# w plikach taty nowa wersja nie usuwa. Dziennik idzie ostatni, po wpisach o sprawdzeniach, które same się nie udały.
_CHECKS: Final[Mapping[contract.ProcessKey, Sequence[_Check]]] = {
    "preparation": (
        _tata_settings,
        _files_in_onedrive,
        _register,
        _templates,
        _worker_config,
        _period_folder,
        _period_files_in_excel,
        _tool_freshness,
        _centrum_log,
    ),
    "settlement": (
        _tata_settings,
        _files_in_onedrive,
        _templates,
        _worker_config,
        _period_folder,
        _period_files_in_excel,
        _tool_freshness,
        _centrum_log,
    ),
}


def diagnose(
    process: contract.ProcessKey,
    period: str,
    *,
    settings: Settings,
    configuration: ConfigurationFiles,
    log: CentrumLog,
    surroundings: Surroundings,
    readers: Readers,
) -> Diagnosis:
    """Wszystkie sprawdzenia procesu ``process`` dla tokenu okresu ``period``, tylko do odczytu, czytnikami procesu."""

    computer = _Computer(process, parse_period_token(period), settings, configuration, log, surroundings, readers)
    checks: list[CheckResult] = []
    for check in _CHECKS[process]:
        checks.extend(check.results(computer))
    return Diagnosis(tuple(checks), computer.log_entries)

"""Konfiguracja tylko do odczytu: trzy Wzorce, Wykonawcy z konfiguracji wykonawców i wersja narzędzia z Aktualnością.

Reguły należą do procesów: Wzorce sprawdzają te same funkcje co Sprawdzanie w
obu procesach, a Konfigurację wykonawców wczytuje moduł ``worker_config``.
Centrum tylko zamienia ich wynik na stan dla przeglądarki, z tym samym
komunikatem w trzech częściach, którym zatrzymałby się proces używający tego
pliku. Niczego w katalogu konfiguracji nie zapisuje. Te same Sprawdzania
(``ConfigurationFiles.templates``, ``workers_problem``) wykonuje Diagnoza.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path

from fastapi import APIRouter

from rozliczenia import preparation_files, preparation_messages, settlement_messages, workbook_files
from rozliczenia.centrum import contract
from rozliczenia.centrum.tool_freshness import RememberedMain, ToolFreshness
from rozliczenia.centrum.version import short_commit
from rozliczenia.collective_preparation import default_collective_template_path, default_internal_template_path
from rozliczenia.engine import default_worker_template_path
from rozliczenia.message import Message, StopError
from rozliczenia.template_settlement import WorkerTemplateValidationError, validate_worker_template
from rozliczenia.worker_config import WorkerConfigError, default_config_path, load_worker_mapping


@dataclass(frozen=True)
class ConfigurationFiles:
    """Konfiguracja wykonawców i trzy Wzorce, z których korzystają procesy."""

    worker_config: Path
    internal_template: Path
    collective_template: Path
    worker_template: Path

    @classmethod
    def default(cls) -> ConfigurationFiles:
        return cls(
            worker_config=default_config_path(),
            internal_template=default_internal_template_path(),
            collective_template=default_collective_template_path(),
            worker_template=default_worker_template_path(),
        )

    def templates(self) -> tuple[Template, Template, Template]:
        """Trzy Wzorce w kolejności Konfiguracji, każdy ze Sprawdzaniem procesu, który go używa."""

        return (
            Template("Wzorzec rozliczenia wewnętrznego", self.internal_template, "preparation", _internal_template_problem),
            Template("Wzorzec pliku zbiorczego", self.collective_template, "preparation", _collective_template_problem),
            Template("Wzorzec rozliczenia pracownika", self.worker_template, "settlement", _worker_template_problem),
        )


_Problem = tuple[contract.TemplateProblemKind, Message]
_FindProblem = Callable[[Path], _Problem | None]


@dataclass(frozen=True)
class Template:
    """Wzorzec: etykieta, plik, proces, który z niego tworzy pliki, i Sprawdzanie tego procesu."""

    label: str
    path: Path
    used_by: contract.ProcessKey
    find_problem: _FindProblem

    def problem(self) -> Message | None:
        """Komunikat, którym zatrzymałby się proces używający Wzorca; ``None``, gdy przechodzi Sprawdzanie."""

        found = self.find_problem(self.path)
        return None if found is None else found[1]
_PROBLEM_CODES: dict[str, contract.TemplateProblemKind] = {
    preparation_messages.TEMPLATE_MISSING: "missing",
    preparation_messages.TEMPLATE_OPEN_IN_EXCEL: "open_in_excel",
}


def configuration_router(
    files: ConfigurationFiles,
    freshness: ToolFreshness,
    report_key: Callable[[], contract.ReportKeyState],
    *,
    clock: Callable[[], float],
) -> APIRouter:
    """Konfiguracja; ``report_key`` mówi, czy na tym komputerze jest klucz do Zgłoszeń (bez jego wartości).

    Aktualność narzędzia porównuje commit narzędzia z `main` na GitHubie, którego odpowiedź Konfiguracja pamięta
    (``RememberedMain`` na zegarze ``clock``).
    """

    router = APIRouter(prefix="/api/configuration", tags=["konfiguracja"])
    checked = _CheckedTemplates()
    main = RememberedMain(freshness.main, clock=clock)

    @router.get("", operation_id="getConfiguration")
    def configuration() -> contract.Configuration:
        commit = freshness.local()
        return contract.Configuration(
            version=None if commit is None else contract.ToolVersion(commit=short_commit(commit), since=freshness.since()),
            freshness=_freshness(commit, main),
            templates=[checked.status(template) for template in files.templates()],
            workers=_workers(files.worker_config),
            reports=report_key(),
        )

    return router


def _freshness(commit: str | None, main: Callable[[], str | None]) -> contract.ToolFreshnessState:
    """Czy commit narzędzia to `main`; ``not_checked`` bez commitu Gita albo bez odpowiedzi GitHuba."""

    newest = None if commit is None else main()
    if commit is None or newest is None:
        return "not_checked"
    return "current" if newest == commit else "newer"


class _CheckedTemplates:
    """Wynik Sprawdzania każdego wzorca, ważny do zmiany pliku albo jego blokady.

    Prawdziwe Wzorce otwierają się sekundami, a Konfiguracja jest odczytywana
    przy każdym powrocie do karty. Brak pliku jest sprawdzany zawsze od nowa.
    """

    def __init__(self) -> None:
        self._results: dict[Path, tuple[tuple[int, int, bool], _Problem | None]] = {}

    def status(self, template: Template) -> contract.TemplateStatus:
        label, path = template.label, template.path
        found = self._problem(path, template.find_problem)
        if found is None:
            return contract.TemplateReady(state="ready", label=label, file_name=path.name)
        problem, message = found
        return contract.TemplateProblem(
            state="problem", label=label, file_name=path.name, problem=problem, message=contract.Message.of(message)
        )

    def _problem(self, path: Path, find_problem: _FindProblem) -> _Problem | None:
        try:
            stat = path.stat()
        except OSError:
            return find_problem(path)
        signature = (stat.st_mtime_ns, stat.st_size, workbook_files.is_open_in_excel(path))
        cached = self._results.get(path)
        if cached is not None and cached[0] == signature:
            return cached[1]
        found = find_problem(path)
        self._results[path] = (signature, found)
        return found


# Przez moduł, jak proces: Konfiguracja i Diagnoza trafiają na to samo Sprawdzanie wzorców.
def _internal_template_problem(path: Path) -> _Problem | None:
    return _preparation_template_problem(preparation_files.check_internal_template, path)


def _collective_template_problem(path: Path) -> _Problem | None:
    return _preparation_template_problem(preparation_files.check_collective_template, path)


def _preparation_template_problem(check: Callable[[Path], None], path: Path) -> _Problem | None:
    """Sprawdzanie wzorca z Przygotowania pliku zbiorczego z jego komunikatem."""

    try:
        check(path)
    except StopError as error:
        return _PROBLEM_CODES.get(error.message.code, "unreadable"), error.message
    return None


def _worker_template_problem(path: Path) -> _Problem | None:
    """Sprawdzanie z Przebiegu rozliczeń z jego komunikatem i rodzajem problemu ze Sprawdzania."""

    try:
        validate_worker_template(path)
    except WorkerTemplateValidationError as error:
        return error.problem, settlement_messages.worker_template_invalid(path, error.message)
    return None


def workers_problem(config_path: Path) -> Message | None:
    """Komunikat, którym zatrzymałby się Przebieg rozliczeń przy tej konfiguracji wykonawców; ``None``, gdy się wczytuje."""

    workers = _read_workers(config_path)
    return workers if isinstance(workers, Message) else None


def _workers(config_path: Path) -> contract.Workers:
    """Wykonawcy wczytani tak jak w obu procesach, w kolejności z konfiguracji wykonawców."""

    workers = _read_workers(config_path)
    if isinstance(workers, Message):
        return contract.WorkersUnreadable(state="unreadable", message=contract.Message.of(workers))
    return contract.WorkersReady(state="ready", names=list(workers.values()))


def _read_workers(config_path: Path) -> Mapping[str, str] | Message:
    try:
        return load_worker_mapping(config_path)
    except WorkerConfigError as error:
        return settlement_messages.worker_config_problem(config_path, error)

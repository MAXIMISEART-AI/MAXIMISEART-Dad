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
from typing import Final, assert_never

from fastapi import APIRouter

from rozliczenia import preparation_files, preparation_messages, settlement_messages, workbook_files
from rozliczenia.centrum import contract
from rozliczenia.centrum.tool_freshness import Judgement, RememberedRelease, ToolFreshness, offers_update
from rozliczenia.centrum.version import short_commit
from rozliczenia.collective_preparation import default_collective_template_path, default_internal_template_path
from rozliczenia.engine import check_worker_template, default_worker_template_path
from rozliczenia.message import Message
from rozliczenia.workbook_files import Problem, WorkbookError
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
            Template(
                label="Wzorzec rozliczenia wewnętrznego",
                path=self.internal_template,
                used_by="preparation",
                check=preparation_files.check_internal_template,
                explain=preparation_messages.template_unusable,
            ),
            Template(
                label="Wzorzec pliku zbiorczego",
                path=self.collective_template,
                used_by="preparation",
                check=preparation_files.check_collective_template,
                explain=preparation_messages.template_unusable,
            ),
            Template(
                label="Wzorzec rozliczenia pracownika",
                path=self.worker_template,
                used_by="settlement",
                check=check_worker_template,
                explain=settlement_messages.worker_template_unusable,
            ),
        )


_Problem = tuple[contract.TemplateProblemKind, Message]


@dataclass(frozen=True)
class Template:
    """Wzorzec: etykieta, plik, proces, który z niego tworzy pliki, Sprawdzanie tego procesu i jego katalog."""

    label: str
    path: Path
    used_by: contract.ProcessKey
    check: Callable[[Path], object]
    """Sprawdzanie procesu: ``WorkbookError``, gdy Wzorzec nie może posłużyć jako wzór."""
    explain: Callable[[Path, WorkbookError], Message]

    def find_problem(self) -> _Problem | None:
        """Rodzaj problemu i Komunikat, którym zatrzymałby się proces; ``None``, gdy Wzorzec przechodzi Sprawdzanie."""

        try:
            self.check(self.path)
        except WorkbookError as error:
            return _kind(error.problem), self.explain(self.path, error)
        return None

    def problem(self) -> Message | None:
        """Komunikat, którym zatrzymałby się proces używający Wzorca; ``None``, gdy przechodzi Sprawdzanie."""

        found = self.find_problem()
        return None if found is None else found[1]


def _kind(problem: Problem) -> contract.TemplateProblemKind:
    match problem:
        case Problem.MISSING:
            return "missing"
        case Problem.OPEN_IN_EXCEL:
            return "open_in_excel"
        case Problem.INACCESSIBLE | Problem.UNREADABLE | Problem.LAYOUT | Problem.HAS_DATA:
            return "unreadable"
        case _:
            assert_never(problem)


def configuration_router(
    files: ConfigurationFiles,
    freshness: ToolFreshness,
    report_key: Callable[[], contract.ReportKeyState],
    *,
    clock: Callable[[], float],
) -> APIRouter:
    """Konfiguracja; ``report_key`` mówi, czy na tym komputerze jest klucz do Zgłoszeń (bez jego wartości).

    Aktualność narzędzia porównuje commit narzędzia z najnowszym Wydaniem na GitHubie, którego odpowiedź
    Konfiguracja pamięta (``RememberedRelease`` na zegarze ``clock``).
    """

    router = APIRouter(prefix="/api/configuration", tags=["konfiguracja"])
    checked = _CheckedTemplates()
    release = RememberedRelease(freshness.release, clock=clock)

    @router.get("", operation_id="getConfiguration")
    def configuration() -> contract.Configuration:
        commit = freshness.local()
        judgement = freshness.judge(release)
        return contract.Configuration(
            version=None if commit is None else contract.ToolVersion(commit=short_commit(commit), since=freshness.since()),
            freshness=_STATE[judgement],
            update_offered=offers_update(judgement),
            templates=[checked.status(template) for template in files.templates()],
            workers=_workers(files.worker_config),
            reports=report_key(),
        )

    return router


# Konfiguracja nie odróżnia powodu, dla którego nie sprawdzono; Diagnoza go nazywa.
_STATE: Final[Mapping[Judgement, contract.ToolFreshnessState]] = {
    "current": "current",
    "newer": "newer",
    "no_release": "not_checked",
    "no_answer": "not_checked",
    "no_commit": "not_checked",
}


class _CheckedTemplates:
    """Wynik Sprawdzania każdego wzorca, ważny do zmiany pliku albo jego blokady.

    Prawdziwe Wzorce otwierają się sekundami, a Konfiguracja jest odczytywana
    przy każdym powrocie do karty. Brak pliku jest sprawdzany zawsze od nowa.
    """

    def __init__(self) -> None:
        self._results: dict[Path, tuple[tuple[int, int, bool], _Problem | None]] = {}

    def status(self, template: Template) -> contract.TemplateStatus:
        label, path = template.label, template.path
        found = self._problem(template)
        if found is None:
            return contract.TemplateReady(state="ready", label=label, file_name=path.name)
        problem, message = found
        return contract.TemplateProblem(
            state="problem", label=label, file_name=path.name, problem=problem, message=contract.Message.of(message)
        )

    def _problem(self, template: Template) -> _Problem | None:
        path = template.path
        try:
            stat = path.stat()
        except OSError:
            return template.find_problem()
        signature = (stat.st_mtime_ns, stat.st_size, workbook_files.is_open_in_excel(path))
        cached = self._results.get(path)
        if cached is not None and cached[0] == signature:
            return cached[1]
        found = template.find_problem()
        self._results[path] = (signature, found)
        return found


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

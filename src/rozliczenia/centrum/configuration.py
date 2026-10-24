"""Konfiguracja tylko do odczytu: trzy Wzorce, Wykonawcy z konfiguracji wykonawców i wersja narzędzia z Aktualnością.

Reguły należą do procesów: Wzorce i Konfigurację wykonawców sprawdza
Sprawdzanie obu procesów (``input_checks``) tymi samymi czytnikami co proces.
Centrum tylko zamienia jego wynik na stan dla przeglądarki, z tym samym
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

from rozliczenia import input_checks, workbook_files
from rozliczenia.centrum import contract
from rozliczenia.centrum.keyed_box import KeyJudgement
from rozliczenia.centrum.tool_freshness import Judgement, ReleaseSource, ToolFreshness, offers_update
from rozliczenia.centrum.version import short_commit
from rozliczenia.collective_preparation import default_collective_template_path, default_internal_template_path
from rozliczenia.engine import default_worker_template_path
from rozliczenia.input_checks import ProcessTemplate, Readers
from rozliczenia.message import Message
from rozliczenia.workbook_files import Problem
from rozliczenia.worker_config import default_config_path


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
            Template("Wzorzec rozliczenia wewnętrznego", "preparation", ProcessTemplate.internal(self.internal_template)),
            Template("Wzorzec pliku zbiorczego", "preparation", ProcessTemplate.collective(self.collective_template)),
            Template("Wzorzec rozliczenia pracownika", "settlement", ProcessTemplate.worker(self.worker_template)),
        )


_Problem = tuple[contract.TemplateProblemKind, Message]


@dataclass(frozen=True)
class Template:
    """Wzorzec: etykieta, proces, który z niego tworzy pliki, i Wzorzec tego procesu ze Sprawdzaniem."""

    label: str
    used_by: contract.ProcessKey
    template: ProcessTemplate

    @property
    def path(self) -> Path:
        return self.template.file.path

    def find_problem(self, readers: Readers) -> _Problem | None:
        """Rodzaj problemu i Komunikat, którym zatrzymałby się proces; ``None``, gdy Wzorzec przechodzi Sprawdzanie."""

        found = self.template.problem(readers)
        return None if found is None else (_kind(found.problem), found.message)

    def problem(self, readers: Readers) -> Message | None:
        """Komunikat, którym zatrzymałby się proces używający Wzorca; ``None``, gdy przechodzi Sprawdzanie."""

        found = self.template.problem(readers)
        return None if found is None else found.message


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
    release: ReleaseSource,
    report_key: Callable[[], KeyJudgement],
    readers: Readers,
) -> APIRouter:
    """Konfiguracja; ``report_key`` mówi, co wiadomo o kluczu do Zgłoszeń (bez jego wartości) i czeka na Skrzynkę
    najwyżej ``CONFIGURATION_WAIT_S``.

    Aktualność narzędzia porównuje commit narzędzia z najnowszym Wydaniem na GitHubie według ``release``: odpowiedzi
    GitHuba pamiętanej wspólnie z Powiadomieniami (``RememberedRelease``).
    """

    router = APIRouter(prefix="/api/configuration", tags=["konfiguracja"])
    checked = _CheckedTemplates(readers)

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
            reports=_KEY_STATE[report_key()],
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


# Konfiguracja nie odróżnia klucza przyjętego od jeszcze niesprawdzonego (np. bez sieci); Diagnoza je nazywa.
_KEY_STATE: Final[Mapping[KeyJudgement, contract.ReportKeyState]] = {
    "accepted": "ready",
    "unchecked": "ready",
    "refused": "refused_key",
    "missing": "missing_key",
}
# Tyle Konfiguracja czeka na trwające sprawdzenie klucza (zimny odczyt to ~200 ms); sprawdzenie rusza już przy starcie
# Centrum, więc zwykle jest gotowe i odczyt nie czeka wcale.
CONFIGURATION_WAIT_S: Final = 1.0


class _CheckedTemplates:
    """Wynik Sprawdzania każdego wzorca, ważny do zmiany pliku albo jego blokady.

    Prawdziwe Wzorce otwierają się sekundami, a Konfiguracja jest odczytywana
    przy każdym powrocie do karty. Brak pliku jest sprawdzany zawsze od nowa.
    """

    def __init__(self, readers: Readers) -> None:
        self._readers = readers
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
            signature = None
        else:
            signature = (stat.st_mtime_ns, stat.st_size, workbook_files.is_open_in_excel(path))
            cached = self._results.get(path)
            if cached is not None and cached[0] == signature:
                return cached[1]
        found = template.find_problem(self._readers)
        if signature is not None:
            self._results[path] = (signature, found)
        return found


def workers_problem(config_path: Path) -> Message | None:
    """Komunikat, którym zatrzymałby się Przebieg rozliczeń przy tej konfiguracji wykonawców; ``None``, gdy się wczytuje."""

    workers = input_checks.workers(config_path)
    return workers if isinstance(workers, Message) else None


def _workers(config_path: Path) -> contract.Workers:
    """Wykonawcy wczytani tak jak w obu procesach, w kolejności z konfiguracji wykonawców."""

    workers = input_checks.workers(config_path)
    if isinstance(workers, Message):
        return contract.WorkersUnreadable(state="unreadable", message=contract.Message.of(workers))
    return contract.WorkersReady(state="ready", names=list(workers.values()))

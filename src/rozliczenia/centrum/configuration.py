"""Konfiguracja tylko do odczytu: trzy Wzorce, Wykonawcy z konfiguracji wykonawców i wersja narzędzia.

Reguły należą do silnika: Wzorce sprawdzają te same funkcje co Sprawdzanie w
obu procesach, a konfigurację wykonawców wczytuje ``load_worker_mapping``.
Centrum tylko zamienia ich wynik na stan dla przeglądarki, z komunikatami w
trzech częściach z katalogu Przygotowania pliku zbiorczego. Niczego w
katalogu konfiguracji nie zapisuje.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, replace
from pathlib import Path

from fastapi import APIRouter

from rozliczenia import preparation_messages, workbook_files
from rozliczenia.centrum import contract
from rozliczenia.centrum.version import tool_version
from rozliczenia.collective_preparation import default_collective_template_path, default_internal_template_path
from rozliczenia.engine import (
    SettlementError,
    default_config_path,
    default_worker_template_path,
    load_worker_mapping,
)
from rozliczenia.preparation_files import check_collective_template, check_internal_template
from rozliczenia.preparation_messages import PreparationError, PreparationMessage
from rozliczenia.template_settlement import WorkerTemplateValidationError, validate_worker_template


@dataclass(frozen=True)
class ConfigurationFiles:
    """Konfiguracja wykonawców i trzy Wzorce, z których korzystają procesy."""

    worker_config: Path
    internal_template: Path
    collective_template: Path
    worker_template: Path

    @classmethod
    def default(cls) -> ConfigurationFiles:
        """Te same pliki w katalogu konfiguracji, których domyślnie używa CLI."""

        return cls(
            worker_config=default_config_path(),
            internal_template=default_internal_template_path(),
            collective_template=default_collective_template_path(),
            worker_template=default_worker_template_path(),
        )


_Problem = tuple[contract.TemplateProblemKind, PreparationMessage]
_FindProblem = Callable[[Path], _Problem | None]
_PROBLEM_CODES: dict[str, contract.TemplateProblemKind] = {
    "BRAK_WZORCA": "missing",
    "WZORZEC_OTWARTY": "open_in_excel",
}


def configuration_router(files: ConfigurationFiles) -> APIRouter:
    router = APIRouter(prefix="/api/configuration", tags=["konfiguracja"])
    checked = _CheckedTemplates()

    @router.get("", operation_id="getConfiguration")
    def configuration() -> contract.Configuration:
        return contract.Configuration(
            version=tool_version(),
            templates=[
                checked.status("Wzorzec rozliczenia wewnętrznego", files.internal_template, _internal_template_problem),
                checked.status("Wzorzec pliku zbiorczego", files.collective_template, _collective_template_problem),
                checked.status("Wzorzec rozliczenia pracownika", files.worker_template, _worker_template_problem),
            ],
            workers=_workers(files.worker_config),
        )

    return router


class _CheckedTemplates:
    """Wynik Sprawdzania każdego wzorca, ważny do zmiany pliku albo jego blokady.

    Prawdziwe Wzorce otwierają się sekundami, a Konfiguracja jest odczytywana
    przy każdym powrocie do karty. Brak pliku jest sprawdzany zawsze od nowa.
    """

    def __init__(self) -> None:
        self._results: dict[Path, tuple[tuple[int, int, bool], _Problem | None]] = {}

    def status(self, label: str, path: Path, find_problem: _FindProblem) -> contract.TemplateStatus:
        found = self._problem(path, find_problem)
        if found is None:
            return contract.TemplateReady(state="ready", label=label, file_name=path.name)
        problem, message = found
        return contract.TemplateProblem(
            state="problem", label=label, file_name=path.name, problem=problem, message=_message(message)
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


def _internal_template_problem(path: Path) -> _Problem | None:
    return _preparation_template_problem(check_internal_template, path)


def _collective_template_problem(path: Path) -> _Problem | None:
    return _preparation_template_problem(check_collective_template, path)


def _preparation_template_problem(check: Callable[[Path], None], path: Path) -> _Problem | None:
    """Sprawdzanie wzorca z Przygotowania pliku zbiorczego z jego komunikatem."""

    try:
        check(path)
    except PreparationError as error:
        return _PROBLEM_CODES.get(error.message.code, "unreadable"), error.message
    return None


def _worker_template_problem(path: Path) -> _Problem | None:
    """Sprawdzanie z Przebiegu rozliczeń: „Co się stało” z jego komunikatu, „Gdzie” i „Co zrobić” jak dla wzorców."""

    try:
        validate_worker_template(path)
    except WorkerTemplateValidationError as error:
        problem: contract.TemplateProblemKind
        if not path.is_file():
            problem, message = "missing", preparation_messages.template_missing(path).message
        elif workbook_files.is_open_in_excel(path):
            problem, message = "open_in_excel", preparation_messages.template_open_in_excel(path).message
        else:
            problem, message = "unreadable", preparation_messages.template_unreadable(path).message
        return problem, replace(message, what=str(error))
    return None


def _workers(config_path: Path) -> contract.Workers:
    """Wykonawcy wczytani tak jak w obu procesach, w kolejności z konfiguracji wykonawców."""

    try:
        mapping = load_worker_mapping(config_path)
    except SettlementError:
        message = preparation_messages.unreadable_worker_config(config_path).message
        return contract.WorkersUnreadable(state="unreadable", message=_message(message))
    return contract.WorkersReady(state="ready", names=list(mapping.values()))


def _message(message: PreparationMessage) -> contract.Message:
    return contract.Message(what=message.what, where=message.where, action=message.action)

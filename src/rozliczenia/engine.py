"""Deterministyczne rozdzielanie pliku zbiorczego do szablonów pracowników."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import replace
from pathlib import Path

from . import collective_file, settlement_files, settlement_messages, template_settlement, workbook_files
from .domain import Issue, ProgressObserver, SettlementSummary, WorkerResult
from .message import StopError
from .order_facts import CollectiveOrders
from .period_folder import PeriodFolder, PeriodFolderError
from .phase_runner import PhaseRunner
from .template_settlement import WorkerTemplateValidationError, validate_worker_template
from .workbook_files import DataRow, Problem, TemplateFile, WorkbookError
from .worker_config import WorkerConfigError, load_worker_mapping, normalize_text


def default_worker_template_path() -> Path:
    """Wskazuje wspólny Wzorzec rozliczenia pracownika w katalogu konfiguracji."""

    return Path(__file__).resolve().parents[2] / "config" / "Wzorzec rozliczenia pracownika.xlsx"


def _collective_file_stop(source_path: Path, error: WorkbookError) -> StopError:
    """Zatrzymanie z Komunikatem Przebiegu rozliczeń dla Pliku zbiorczego, którego nie da się użyć."""

    if error.problem is Problem.MISSING:
        return StopError(settlement_messages.collective_file_missing(source_path))
    if error.problem is Problem.OPEN_IN_EXCEL:
        return StopError(settlement_messages.collective_file_open(source_path))
    if error.problem is Problem.INACCESSIBLE:
        return StopError(settlement_messages.collective_file_inaccessible(source_path))
    if error.problem is Problem.LAYOUT:
        return StopError(settlement_messages.collective_file_without_worker_header(source_path))
    return StopError(settlement_messages.collective_file_unreadable(source_path))


def _read_source_rows(source_path: Path) -> tuple[dict[str, list[DataRow]], list[Issue], CollectiveOrders]:
    """Czyta Wiersze danych Pliku zbiorczego z ich Wyróżnieniami i grupuje je po identyfikatorze WYKONAWCA."""

    try:
        read = collective_file.read_data_rows(source_path)
    except WorkbookError as error:
        raise _collective_file_stop(source_path, error) from error
    rows_by_worker: defaultdict[str, list[DataRow]] = defaultdict(list)
    for row in read.rows:
        rows_by_worker[normalize_text(row.worker)].append(row)
    return dict(rows_by_worker), read.issues, read.orders


def _plan_rows(
    source_path: Path,
    mapping: dict[str, str],
    rows_by_worker: dict[str, list[DataRow]],
    source_issues: list[Issue],
    *,
    dry_run: bool,
) -> tuple[dict[str, list[DataRow]], list[Issue]]:
    """Przypisuje Wiersze danych do nazw z Konfiguracji wykonawców; przy zapisie każdy problem zatrzymuje."""

    rows_by_target: defaultdict[str, list[DataRow]] = defaultdict(list)
    issues: list[Issue] = []
    for source_worker, rows in rows_by_worker.items():
        target_name = mapping.get(source_worker)
        if target_name is None:
            issues.append(
                Issue(
                    "BRAK_MAPOWANIA",
                    "Nieznany identyfikator WYKONAWCA; sprawdź konfigurację pracowników.",
                )
            )
            continue
        rows_by_target[normalize_text(target_name)].extend(rows)
    if not dry_run and (source_issues or issues):
        if any(issue.code == "BRAK_MAPOWANIA" for issue in issues):
            raise StopError(settlement_messages.unmapped_worker(source_path))
        raise StopError(settlement_messages.rows_without_worker(source_path))
    return dict(rows_by_target), issues


def run_settlements(
    source_path: Path,
    config_path: Path,
    *,
    dry_run: bool = False,
    worker_template_path: Path | None = None,
    observer: ProgressObserver | None = None,
) -> SettlementSummary:
    """Uruchamia pełny proces z ochroną przed błędną lokalizacją i duplikacją.

    Ten moduł tylko sekwencjonuje cztery etapy i rozlicza Szablon pracownika
    jednego Wykonawcy; pętlę po nich ze zdarzeniami Wykonawców prowadzi
    sekwencer etapów. Konfiguracja wykonawców jest w
    ``worker_config``, a folder tymczasowy, Nienadpisywanie i publikacja
    Folderu rozliczeń pracowników w ``settlement_files``.
    """

    phases = PhaseRunner(observer)
    source_path = source_path.expanduser().resolve()
    config_path = config_path.expanduser().resolve()
    worker_template_path = (worker_template_path or default_worker_template_path()).expanduser().resolve()

    def check_inputs() -> tuple[PeriodFolder, dict[str, str], TemplateFile]:
        try:
            workbook_files.ensure_available(source_path)
        except WorkbookError as error:
            raise _collective_file_stop(source_path, error) from error
        try:
            folder = PeriodFolder.from_collective_file(source_path)
        except PeriodFolderError as exc:
            raise StopError(settlement_messages.collective_file_invalid(source_path, exc.message)) from exc
        settlement_files.ensure_worker_settlements_absent(folder.worker_settlements)
        try:
            mapping = load_worker_mapping(config_path)
        except WorkerConfigError as exc:
            raise StopError(settlement_messages.worker_config_problem(config_path, exc)) from exc
        try:
            worker_template = validate_worker_template(worker_template_path)
        except WorkerTemplateValidationError as exc:
            raise StopError(settlement_messages.worker_template_invalid(worker_template_path, exc.message)) from exc
        return folder, mapping, worker_template

    folder, mapping, worker_template = phases.check(check_inputs)
    target_directory = folder.worker_settlements
    worker_names = list(mapping.values())
    rows_by_worker, source_issues, orders = phases.read(
        lambda: _read_source_rows(source_path),
        issue_count=lambda read_rows: len(read_rows[1]),
    )
    summary = SettlementSummary(
        folder.period.token, source_path, target_directory, orders=orders, issues=list(source_issues)
    )
    rows_by_target, plan_issues = phases.plan(
        lambda: _plan_rows(source_path, mapping, rows_by_worker, source_issues, dry_run=dry_run),
        templates=lambda _planned: worker_names,
        issue_count=lambda planned: len(source_issues) + len(planned[1]),
    )
    summary.issues.extend(plan_issues)

    def settle(directory: Path, worker_name: str) -> WorkerResult:
        target_path = directory / folder.worker_settlement(worker_name).name
        rows = rows_by_target.get(normalize_text(worker_name), [])
        if dry_run:
            return WorkerResult(worker_name, target_path, len(rows), "PLAN" if rows else "PUSTY_SZABLON")
        try:
            return template_settlement.process_template(worker_name, worker_template, target_path, rows)
        except StopError:
            raise
        except WorkbookError as exc:
            raise StopError(settlement_messages.worker_files_not_copied(worker_template_path)) from exc
        except Exception as exc:
            raise StopError(settlement_messages.worker_file_failed(target_directory, worker_name)) from exc

    def save_templates(directory: Path) -> list[WorkerResult]:
        return phases.each_template(lambda worker_name: settle(directory, worker_name))

    def save_all() -> None:
        if dry_run:
            summary.results = save_templates(target_directory)
        else:
            summary.results = settlement_files.write_worker_settlements(target_directory, save_templates)

    phases.save(save_all)
    return replace(summary, phase_durations_ms=phases.durations_ms())

"""Deterministyczne rozdzielanie pliku zbiorczego do szablonów pracowników."""

from __future__ import annotations

import tempfile
import time
from collections import defaultdict
from dataclasses import replace
from pathlib import Path

from . import collective_file, settlement_messages, template_settlement, workbook_files
from .domain import (
    Issue,
    ProgressEventFactory,
    ProgressObserver,
    SettlementSummary,
    WorkerResult,
)
from .message import StopError
from .period_folder import PeriodFolder, PeriodFolderError
from .phase_runner import PhaseRunner, elapsed_ms_since
from .template_settlement import WorkerTemplateValidationError, validate_worker_template
from .workbook_files import ExcelRow, Problem, WorkbookError
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
    if error.problem is Problem.LAYOUT:
        return StopError(settlement_messages.collective_file_without_worker_header(source_path))
    return StopError(settlement_messages.collective_file_unreadable(source_path))


def _read_source_rows(source_path: Path) -> tuple[dict[str, list[ExcelRow]], list[Issue]]:
    """Czyta Wiersze danych Pliku zbiorczego i grupuje je po identyfikatorze WYKONAWCA."""

    try:
        data_rows, issues = collective_file.read_data_rows(source_path)
    except WorkbookError as error:
        raise _collective_file_stop(source_path, error) from error
    rows_by_worker: defaultdict[str, list[ExcelRow]] = defaultdict(list)
    for row in data_rows:
        rows_by_worker[normalize_text(row.worker)].append(row.values)
    return dict(rows_by_worker), issues


def run_settlements(
    source_path: Path,
    config_path: Path,
    *,
    dry_run: bool = False,
    worker_template_path: Path | None = None,
    observer: ProgressObserver | None = None,
) -> SettlementSummary:
    """Uruchamia pełny proces z ochroną przed błędną lokalizacją i duplikacją."""

    phases = PhaseRunner(observer)
    source_path = source_path.expanduser().resolve()
    config_path = config_path.expanduser().resolve()
    worker_template_path = (worker_template_path or default_worker_template_path()).expanduser().resolve()
    notify = phases.notify

    def check_inputs() -> tuple[PeriodFolder, Path, dict[str, str]]:
        try:
            workbook_files.ensure_available(source_path)
        except WorkbookError as error:
            raise _collective_file_stop(source_path, error) from error
        try:
            folder = PeriodFolder.from_collective_file(source_path)
        except PeriodFolderError as exc:
            raise StopError(settlement_messages.collective_file_invalid(source_path, exc.message)) from exc
        target_directory = folder.worker_settlements
        if target_directory.exists() or target_directory.is_symlink():
            raise StopError(settlement_messages.worker_settlements_exist(target_directory))
        try:
            mapping = load_worker_mapping(config_path)
        except WorkerConfigError as exc:
            raise StopError(settlement_messages.worker_config_invalid(config_path, exc)) from exc
        try:
            validate_worker_template(worker_template_path)
        except WorkerTemplateValidationError as exc:
            raise StopError(settlement_messages.worker_template_invalid(worker_template_path, exc.message)) from exc
        return folder, target_directory, mapping

    folder, target_directory, mapping = phases.check(check_inputs)
    rows_by_worker, source_issues = phases.read(
        lambda: _read_source_rows(source_path),
        issue_count=lambda read_rows: len(read_rows[1]),
    )
    summary = SettlementSummary(folder.period.token, source_path, target_directory, issues=list(source_issues))

    def plan_rows() -> tuple[list[tuple[str, Path]], dict[str, list[ExcelRow]], list[Issue]]:
        template_files = [(name, folder.worker_settlement(name)) for name in mapping.values()]
        rows_by_target: defaultdict[str, list[ExcelRow]] = defaultdict(list)
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
        return template_files, rows_by_target, issues

    template_files, rows_by_target, plan_issues = phases.plan(
        plan_rows,
        template_total=lambda planned: len(planned[0]),
        issue_count=lambda planned: len(source_issues) + len(planned[2]),
    )
    summary.issues.extend(plan_issues)

    def save_targets(files: list[tuple[str, Path]]) -> None:
        for template_index, (worker_name, target_path) in enumerate(files, start=1):
            target_key = normalize_text(worker_name)
            worker_started = time.perf_counter()
            notify(
                ProgressEventFactory.worker_started(
                    worker_name,
                    template_index=template_index,
                    template_total=len(template_files),
                    elapsed_ms=phases.elapsed_ms(),
                )
            )
            rows = rows_by_target.get(target_key, [])
            try:
                if dry_run:
                    result = WorkerResult(
                        worker_name,
                        target_path,
                        len(rows),
                        "PLAN" if rows else "PUSTY_SZABLON",
                    )
                else:
                    result = template_settlement.process_template(
                        worker_name,
                        worker_template_path,
                        target_path,
                        rows,
                    )
                    if result.status not in {"ZAPISANO", "PUSTY_SZABLON"}:
                        summary.issues.extend(result.issues)
                        raise StopError(settlement_messages.worker_file_failed(target_directory, worker_name))
            except Exception as exc:
                notify(
                    ProgressEventFactory.worker_failed(
                        worker_name,
                        template_index=template_index,
                        template_total=len(template_files),
                        elapsed_ms=phases.elapsed_ms(),
                        phase_elapsed_ms=phases.phase_elapsed_ms(),
                        worker_elapsed_ms=elapsed_ms_since(worker_started),
                    )
                )
                if isinstance(exc, StopError):
                    raise
                if isinstance(exc, WorkbookError):
                    raise StopError(settlement_messages.worker_files_not_copied(worker_template_path)) from exc
                raise StopError(settlement_messages.worker_file_failed(target_directory, worker_name)) from exc
            summary.issues.extend(result.issues)
            summary.results.append(result)
            notify(
                ProgressEventFactory.worker_ended(
                    worker_name,
                    template_index=template_index,
                    template_total=len(template_files),
                    status=result.status,
                    rows=result.rows,
                    elapsed_ms=phases.elapsed_ms(),
                    worker_elapsed_ms=elapsed_ms_since(worker_started),
                    issue_count=len(summary.issues),
                )
            )

    def save_all() -> None:
        if dry_run:
            save_targets(template_files)
        else:
            try:
                with tempfile.TemporaryDirectory(
                    prefix=f".{target_directory.name}.staging-",
                    dir=source_path.parent,
                ) as staging_name:
                    staging_directory = Path(staging_name)
                    save_targets(
                        [
                            (worker_name, staging_directory / target_path.name)
                            for worker_name, target_path in template_files
                        ]
                    )
                    if target_directory.exists() or target_directory.is_symlink():
                        raise StopError(settlement_messages.worker_settlements_exist(target_directory))
                    try:
                        staging_directory.rename(target_directory)
                    except OSError as exc:
                        raise StopError(settlement_messages.publish_failed(target_directory)) from exc
                    summary.results = [
                        WorkerResult(
                            result.worker_name,
                            target_directory / result.output_file.name,
                            result.rows,
                            result.status,
                            result.issues,
                        )
                        for result in summary.results
                    ]
            except OSError as exc:
                raise StopError(settlement_messages.write_failed(target_directory)) from exc

    phases.save(save_all)
    return replace(summary, phase_durations_ms=phases.durations_ms())

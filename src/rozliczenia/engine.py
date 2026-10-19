"""Deterministyczne rozdzielanie pliku zbiorczego do szablonów pracowników."""

from __future__ import annotations

import shutil
import tempfile
import time
import unicodedata
from collections import defaultdict
from dataclasses import replace
from pathlib import Path

import yaml

from . import collective_file, settlement_messages, template_settlement
from .collective_file import CollectiveFileError, ExcelRow
from .domain import (
    Issue,
    ProgressEventFactory,
    ProgressObserver,
    SettlementSummary,
    WorkerResult,
)
from .phase_runner import PhaseRunner, elapsed_ms_since
# Zatrzymanie Przebiegu rozliczeń; reszta narzędzia importuje je także stąd.
from .settlement_messages import SettlementError as SettlementError
from .template_settlement import WorkerTemplateValidationError, validate_worker_template
from .workbook_files import is_open_in_excel


_INVALID_FILENAME_CHARACTERS = frozenset('<>:"/\\|?*')
_MAX_WINDOWS_FILENAME_CODE_UNITS = 255


def _worker_filename_fits_windows(name: str) -> bool:
    filename = f"Rozliczenie 00_00_00_0000 - {name}.xlsx"
    try:
        filename_length = len(filename.encode("utf-16-le")) // 2
    except UnicodeEncodeError:
        return False
    return filename_length <= _MAX_WINDOWS_FILENAME_CODE_UNITS


def normalize_text(value: object) -> str:
    """Normalizuje identyfikator bez usuwania polskich znaków."""

    text = unicodedata.normalize("NFC", str(value or ""))
    return " ".join(text.replace("\u00a0", " ").split()).casefold()


def load_worker_mapping(config_path: Path) -> dict[str, str]:
    """Wczytuje jawne mapowanie identyfikatorów na nazwy plików."""

    try:
        config = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
    except OSError as exc:
        raise settlement_messages.worker_config_unreadable(config_path) from exc
    except yaml.YAMLError as exc:
        raise settlement_messages.worker_config_not_yaml(config_path) from exc

    if not isinstance(config, dict):
        raise settlement_messages.worker_config_invalid(config_path, "Konfiguracja musi być mapą z sekcją workers.")
    if type(config.get("schema_version")) is not int or config["schema_version"] != 1:
        raise settlement_messages.worker_config_invalid(config_path, "Nieobsługiwana wersja konfiguracji.")

    workers = config.get("workers")
    if not isinstance(workers, dict) or not workers:
        raise settlement_messages.worker_config_invalid(config_path, "Konfiguracja workers musi zawierać co najmniej jeden wpis.")

    mapping: dict[str, str] = {}
    seen_identifiers: set[str] = set()
    seen_names: dict[str, str] = {}
    for source_id, target_name in workers.items():
        if not isinstance(source_id, str) or not isinstance(target_name, str):
            raise settlement_messages.worker_config_invalid(config_path, "Konfiguracja zawiera niepoprawny identyfikator lub nazwę pracownika.")
        normalized_id = normalize_text(source_id)
        display_name = target_name.strip()
        normalized_name = normalize_text(display_name)
        if not normalized_id or not normalized_name:
            raise settlement_messages.worker_config_invalid(config_path, "Konfiguracja zawiera pusty identyfikator lub nazwę pracownika.")
        if normalized_id in seen_identifiers:
            raise settlement_messages.worker_config_invalid(config_path, "Konfiguracja zawiera powtórzony identyfikator pracownika.")
        if (
            any(character in _INVALID_FILENAME_CHARACTERS for character in display_name)
            or any(ord(character) < 32 for character in display_name)
            or display_name.endswith((".", " "))
        ):
            raise settlement_messages.worker_config_invalid(config_path, "Konfiguracja zawiera nazwę pracownika nieprawidłową dla nazwy pliku.")
        if not _worker_filename_fits_windows(display_name):
            raise settlement_messages.worker_config_invalid(config_path, "Konfiguracja zawiera nazwę pracownika zbyt długą dla nazwy pliku.")
        if normalized_name in seen_names:
            raise settlement_messages.worker_config_invalid(
                config_path,
                "Dwóch identyfikatorów wskazuje ten sam plik pracownika: "
                f"{seen_names[normalized_name]} / {display_name}",
            )
        mapping[normalized_id] = display_name
        seen_identifiers.add(normalized_id)
        seen_names[normalized_name] = display_name
    return mapping


def period_from_source(source_path: Path) -> str:
    """Waliduje nazwę i lokalizację pliku zbiorczego."""

    try:
        return collective_file.period_from_path(source_path)
    except CollectiveFileError as exc:
        raise settlement_messages.collective_file_invalid(source_path, str(exc)) from exc


def default_config_path() -> Path:
    """Wskazuje konfigurację wykonawców w katalogu konfiguracji."""

    return Path(__file__).resolve().parents[2] / "config" / "worker_mapping.yaml"


def default_worker_template_path() -> Path:
    """Wskazuje wspólny Wzorzec rozliczenia pracownika w katalogu konfiguracji."""

    return Path(__file__).resolve().parents[2] / "config" / "Wzorzec rozliczenia pracownika.xlsx"


def worker_settlements_directory(period_directory: Path, period: str) -> Path:
    """Folder rozliczeń pracowników okresu w jego Folderze okresu."""

    return period_directory / f"Rozliczenie pracowników {period}"


def _worker_settlement_filename(period: str, worker_name: str) -> str:
    return f"Rozliczenie {period} - {worker_name}.xlsx"


def count_worker_settlements(target_directory: Path, period: str) -> int:
    """Liczba Rozliczeń pracowników w folderze; pomija pliki blokady Excela, ukryte i Wzorzec bez nazwy wykonawcy."""

    prefix, suffix = _worker_settlement_filename(period, "\0").split("\0")
    return sum(
        1
        for entry in target_directory.iterdir()
        if entry.is_file()
        and entry.name.startswith(prefix)
        and entry.name.endswith(suffix)
        and len(entry.name) > len(prefix) + len(suffix)
    )


def _ensure_unlocked(source_path: Path) -> None:
    if is_open_in_excel(source_path):
        raise settlement_messages.collective_file_open(source_path)


def _read_source_rows(source_path: Path) -> tuple[dict[str, list[ExcelRow]], list[Issue]]:
    """Czyta Wiersze danych Pliku zbiorczego i grupuje je po identyfikatorze WYKONAWCA."""

    try:
        data_rows, issues = collective_file.read_data_rows(source_path)
    except CollectiveFileError as exc:
        raise settlement_messages.collective_file_invalid(source_path, str(exc)) from exc
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

    def check_inputs() -> tuple[str, Path, dict[str, str]]:
        if not source_path.is_file():
            raise settlement_messages.collective_file_missing(source_path)
        _ensure_unlocked(source_path)
        period = period_from_source(source_path)
        target_directory = worker_settlements_directory(source_path.parent, period)
        if target_directory.exists() or target_directory.is_symlink():
            raise settlement_messages.worker_settlements_exist(target_directory)
        mapping = load_worker_mapping(config_path)
        try:
            validate_worker_template(worker_template_path)
        except WorkerTemplateValidationError as exc:
            raise settlement_messages.worker_template_invalid(worker_template_path, str(exc)) from exc
        return period, target_directory, mapping

    period, target_directory, mapping = phases.check(check_inputs)
    rows_by_worker, source_issues = phases.read(
        lambda: _read_source_rows(source_path),
        issue_count=lambda read_rows: len(read_rows[1]),
    )
    summary = SettlementSummary(period, source_path, target_directory, issues=list(source_issues))

    def plan_rows() -> tuple[list[tuple[str, Path]], dict[str, list[ExcelRow]], list[Issue]]:
        template_files = [
            (name, target_directory / _worker_settlement_filename(period, name))
            for name in mapping.values()
        ]
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
                raise settlement_messages.unmapped_worker(source_path)
            raise settlement_messages.rows_without_worker(source_path)
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
                        target_path,
                        rows,
                    )
                    if result.status not in {"ZAPISANO", "PUSTY_SZABLON"}:
                        summary.issues.extend(result.issues)
                        raise settlement_messages.worker_file_failed(target_directory, worker_name)
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
                if isinstance(exc, SettlementError):
                    raise
                raise settlement_messages.worker_file_failed(target_directory, worker_name) from exc
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
                    staged_files = [
                        (worker_name, staging_directory / target_path.name)
                        for worker_name, target_path in template_files
                    ]
                    try:
                        for _, staged_path in staged_files:
                            shutil.copy2(worker_template_path, staged_path)
                    except OSError as exc:
                        raise settlement_messages.worker_files_not_copied(worker_template_path) from exc

                    save_targets(staged_files)
                    if target_directory.exists() or target_directory.is_symlink():
                        raise settlement_messages.worker_settlements_exist(target_directory)
                    try:
                        staging_directory.rename(target_directory)
                    except OSError as exc:
                        raise settlement_messages.publish_failed(target_directory) from exc
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
                raise settlement_messages.write_failed(target_directory) from exc

    phases.save(save_all)
    return replace(summary, phase_durations_ms=phases.durations_ms())

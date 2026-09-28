"""Deterministyczne rozdzielanie pliku zbiorczego do szablonów pracowników."""

from __future__ import annotations

import os
import re
import tempfile
import time
import unicodedata
import zipfile
from collections import defaultdict
from pathlib import Path
from typing import Callable, Iterable, TypeVar

import yaml
from openpyxl import load_workbook
from openpyxl.utils.exceptions import InvalidFileException

from .domain import Issue, ProgressEvent, ProgressObserver, SettlementSummary, WorkerResult


ResultT = TypeVar("ResultT")

PERIOD_PATTERN = r"\d{2}_\d{2}_\d{2}_\d{4}"
SOURCE_PATTERN = re.compile(
    rf"^Rozliczenie (?P<period>{PERIOD_PATTERN}) - zbiorcze\.xlsx$"
)
HEADER_ROW = 17
DATA_START_ROW = 18
WORKER_COLUMN = 8  # H
INPUT_CHECK_COLUMNS = range(1, 12)  # A:K
COPY_COLUMNS = range(1, 47)  # A:AT


class SettlementError(Exception):
    """Błąd uniemożliwiający bezpieczne rozpoczęcie procesu."""


def normalize_text(value: object) -> str:
    """Normalizuje identyfikator bez usuwania polskich znaków."""

    text = unicodedata.normalize("NFC", str(value or ""))
    return " ".join(text.replace("\u00a0", " ").split()).casefold()


def load_worker_mapping(config_path: Path) -> dict[str, str]:
    """Wczytuje jawne mapowanie identyfikatorów na nazwy plików."""

    try:
        config = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
    except OSError as exc:
        raise SettlementError(f"Nie można odczytać konfiguracji: {config_path}") from exc
    except yaml.YAMLError as exc:
        raise SettlementError(f"Niepoprawny YAML konfiguracji: {config_path}") from exc

    workers = config.get("workers")
    if not isinstance(workers, dict) or not workers:
        raise SettlementError("Konfiguracja workers musi zawierać co najmniej jeden wpis.")

    mapping: dict[str, str] = {}
    seen_names: dict[str, str] = {}
    for source_id, target_name in workers.items():
        normalized_id = normalize_text(source_id)
        display_name = str(target_name or "").strip()
        normalized_name = normalize_text(display_name)
        if not normalized_id or not normalized_name:
            raise SettlementError("Konfiguracja zawiera pusty identyfikator lub nazwę pracownika.")
        if normalized_name in seen_names:
            raise SettlementError(
                "Dwóch identyfikatorów wskazuje ten sam plik pracownika: "
                f"{seen_names[normalized_name]} / {display_name}"
            )
        mapping[normalized_id] = display_name
        seen_names[normalized_name] = display_name
    return mapping


def period_from_source(source_path: Path) -> str:
    """Waliduje nazwę i lokalizację pliku zbiorczego."""

    if "Rozliczenie wew." in source_path.name:
        raise SettlementError("Plik Rozliczenie wew. jest poza zakresem tego procesu.")
    match = SOURCE_PATTERN.fullmatch(source_path.name)
    if not match:
        raise SettlementError(
            "Wybierz plik nazwany dokładnie: "
            "Rozliczenie {dd}_{dd}_{mm}_{rrrr} - zbiorcze.xlsx."
        )
    period = match.group("period")
    if source_path.parent.name != period:
        raise SettlementError(
            f"Folder pliku musi nazywać się tak samo jak okres: {period}."
        )
    return period


def excel_lock_path(path: Path) -> Path:
    """Zwraca standardowy plik blokady tworzony przez desktopowy Excel."""

    return path.with_name(f"~${path.name}")


def ensure_unlocked(path: Path) -> None:
    if excel_lock_path(path).exists():
        raise SettlementError(f"Plik jest otwarty lub zablokowany: {path.name}")


def _is_real_value(cell) -> bool:
    """Pomija formuły szablonu przy wykrywaniu istniejących danych."""

    return cell.value is not None and cell.data_type != "f"


def target_has_input_data(sheet) -> bool:
    """Sprawdza dane wejściowe A:K, ignorując formuły w szablonie."""

    for row in range(DATA_START_ROW, sheet.max_row + 1):
        if any(_is_real_value(sheet.cell(row=row, column=column)) for column in INPUT_CHECK_COLUMNS):
            return True
    return False


def target_files(target_directory: Path, period: str) -> list[tuple[str, Path]]:
    """Zwraca nazwane szablony, pomijając placeholdery i pliki blokad."""

    prefix = f"Rozliczenie {period} - "
    files: list[tuple[str, Path]] = []
    for path in sorted(target_directory.glob("*.xlsx"), key=lambda item: item.name.casefold()):
        if path.name.startswith(("~$", "._")):
            continue
        if not path.name.startswith(prefix) or not path.name.endswith(".xlsx"):
            continue
        worker_name = path.stem[len(prefix) :].strip()
        if not worker_name:
            continue
        files.append((worker_name, path))
    return files


def _read_source_rows(source_path: Path) -> tuple[dict[str, list[tuple]], list[Issue]]:
    """Czyta wyłącznie dane wejściowe i grupuje je po kolumnie H."""

    workbook = load_workbook(source_path, read_only=True, data_only=False)
    try:
        sheet = workbook.active
        if sheet is None:
            raise SettlementError("Skoroszyt źródłowy nie zawiera arkusza.")
        header = next(
            sheet.iter_rows(min_row=HEADER_ROW, max_row=HEADER_ROW, max_col=WORKER_COLUMN, values_only=True),
            (),
        )
        if len(header) < WORKER_COLUMN or normalize_text(header[WORKER_COLUMN - 1]) != "wykonawca":
            raise SettlementError("W wierszu 17 nie znaleziono nagłówka WYKONAWCA w kolumnie H.")

        rows_by_worker: dict[str, list[tuple]] = defaultdict(list)
        issues: list[Issue] = []
        for row_number, values in enumerate(
            sheet.iter_rows(min_row=DATA_START_ROW, max_col=max(46, sheet.max_column), values_only=True),
            start=DATA_START_ROW,
        ):
            input_values = values[:11]
            if not any(value is not None for value in input_values):
                continue
            worker_value = values[WORKER_COLUMN - 1] if len(values) >= WORKER_COLUMN else None
            worker_id = normalize_text(worker_value)
            if not worker_id:
                issues.append(
                    Issue("BRAK_WYKONAWCY", f"Wiersz {row_number} ma dane, ale nie ma wykonawcy w kolumnie H.")
                )
                continue
            rows_by_worker[worker_id].append(tuple(values[:46]))
        return dict(rows_by_worker), issues
    finally:
        workbook.close()


def _external_link_parts(path: Path) -> dict[str, tuple[zipfile.ZipInfo, bytes]]:
    """Pobiera oryginalne relacje zewnętrzne, których openpyxl nie zapisuje 1:1."""

    with zipfile.ZipFile(path, "r") as archive:
        return {
            info.filename: (info, archive.read(info.filename))
            for info in archive.infolist()
            if info.filename.startswith("xl/externalLinks/")
        }


def _restore_external_link_parts(
    path: Path,
    parts: dict[str, tuple[zipfile.ZipInfo, bytes]],
) -> None:
    """Przywraca cały fragment externalLinks bez zmiany arkuszy i danych."""

    if not parts:
        return
    file_descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.stem}.links.", suffix=".xlsx", dir=path.parent
    )
    os.close(file_descriptor)
    temporary_path = Path(temporary_name)
    try:
        with zipfile.ZipFile(path, "r") as source, zipfile.ZipFile(temporary_path, "w") as target:
            for info in source.infolist():
                if info.filename.startswith("xl/externalLinks/"):
                    continue
                target.writestr(info, source.read(info.filename))
            for info, data in parts.values():
                target.writestr(info, data)
        os.replace(temporary_path, path)
    finally:
        temporary_path.unlink(missing_ok=True)


def _elapsed_ms(started: float) -> int:
    return max(0, round((time.perf_counter() - started) * 1000))


def _notify(observer: ProgressObserver | None, event: ProgressEvent) -> None:
    if observer is not None:
        observer(event)


def _run_phase(
    phase: str,
    observer: ProgressObserver | None,
    run_started: float,
    operation: Callable[[], ResultT],
) -> ResultT:
    phase_started = time.perf_counter()
    _notify(observer, ProgressEvent(phase, "START", elapsed_ms=_elapsed_ms(run_started)))
    try:
        return operation()
    finally:
        _notify(
            observer,
            ProgressEvent(
                phase,
                "END",
                elapsed_ms=_elapsed_ms(run_started),
                phase_elapsed_ms=_elapsed_ms(phase_started),
            ),
        )


def _save_target(path: Path, rows: Iterable[tuple]) -> None:
    """Wpisuje wartości do pustego szablonu i zapisuje atomowo."""

    external_link_parts = _external_link_parts(path)
    workbook = load_workbook(path, data_only=False, keep_links=True)
    try:
        sheet = workbook.active
        if sheet is None:
            raise SettlementError("Szablon nie zawiera arkusza.")
        for destination_row, values in enumerate(rows, start=DATA_START_ROW):
            for column, value in zip(COPY_COLUMNS, values):
                sheet.cell(row=destination_row, column=column).value = value

        calculation = getattr(workbook, "calculation", None)
        if calculation is not None:
            calculation.calcMode = "auto"
            calculation.fullCalcOnLoad = True
            calculation.forceFullCalc = True

        file_descriptor, temporary_name = tempfile.mkstemp(
            prefix=f".{path.stem}.", suffix=".xlsx", dir=path.parent
        )
        os.close(file_descriptor)
        temporary_path = Path(temporary_name)
        try:
            workbook.save(temporary_path)
            _restore_external_link_parts(temporary_path, external_link_parts)
            os.replace(temporary_path, path)
        finally:
            temporary_path.unlink(missing_ok=True)
    finally:
        workbook.close()


def run_settlements(
    source_path: Path,
    config_path: Path,
    *,
    dry_run: bool = False,
    observer: ProgressObserver | None = None,
) -> SettlementSummary:
    """Uruchamia pełny proces z ochroną przed błędną lokalizacją i duplikacją."""

    run_started = time.perf_counter()
    source_path = source_path.expanduser().resolve()
    config_path = config_path.expanduser().resolve()

    def check_inputs() -> tuple[str, Path, dict[str, str]]:
        if not source_path.is_file():
            raise SettlementError(f"Nie znaleziono pliku źródłowego: {source_path}")
        ensure_unlocked(source_path)
        period = period_from_source(source_path)
        target_directory = source_path.parent / f"Rozliczenie pracowników {period}"
        if not target_directory.is_dir():
            raise SettlementError(f"Nie znaleziono folderu szablonów: {target_directory.name}")
        return period, target_directory, load_worker_mapping(config_path)

    period, target_directory, mapping = _run_phase("Sprawdzanie", observer, run_started, check_inputs)
    rows_by_worker, source_issues = _run_phase(
        "Odczyt danych", observer, run_started, lambda: _read_source_rows(source_path)
    )
    _notify(
        observer,
        ProgressEvent(
            "Odczyt danych",
            "ISSUE_COUNT",
            elapsed_ms=_elapsed_ms(run_started),
            issue_count=len(source_issues),
        ),
    )
    summary = SettlementSummary(period, source_path, target_directory, issues=source_issues)

    def plan_rows() -> tuple[list[tuple[str, Path]], dict[str, list[tuple]], list[Issue]]:
        template_files = target_files(target_directory, period)
        target_by_name = {normalize_text(name): path for name, path in template_files}
        rows_by_target: dict[str, list[tuple]] = defaultdict(list)
        issues: list[Issue] = []
        for source_worker, rows in rows_by_worker.items():
            target_name = mapping.get(source_worker)
            if target_name is None:
                issues.append(
                    Issue("BRAK_MAPOWANIA", f"Pominięto wykonawcę bez mapowania: {source_worker}.")
                )
                continue
            target_key = normalize_text(target_name)
            if target_key not in target_by_name:
                issues.append(
                    Issue("BRAK_SZABLONU", f"Pominięto wykonawcę bez szablonu: {target_name}.")
                )
                continue
            rows_by_target[target_key].extend(rows)
        return template_files, rows_by_target, issues

    template_files, rows_by_target, plan_issues = _run_phase("Planowanie", observer, run_started, plan_rows)
    summary.issues.extend(plan_issues)
    _notify(
        observer,
        ProgressEvent(
            "Planowanie",
            "PLAN_READY",
            template_total=len(template_files),
            elapsed_ms=_elapsed_ms(run_started),
            issue_count=len(summary.issues),
        ),
    )

    def save_targets() -> None:
        for template_index, (worker_name, target_path) in enumerate(template_files, start=1):
            target_key = normalize_text(worker_name)
            worker_started = time.perf_counter()
            _notify(
                observer,
                ProgressEvent(
                    "Zapisywanie",
                    "WORKER_START",
                    template_index=template_index,
                    template_total=len(template_files),
                    worker_name=worker_name,
                    elapsed_ms=_elapsed_ms(run_started),
                ),
            )
            result: WorkerResult | None = None
            occupied = False
            writing_target = False
            try:
                ensure_unlocked(target_path)
                target_workbook = load_workbook(
                    target_path, read_only=False, data_only=False, keep_links=True
                )
                try:
                    target_sheet = target_workbook.active
                    if target_sheet is None:
                        raise ValueError("Szablon nie zawiera arkusza.")
                    header = target_sheet.cell(row=HEADER_ROW, column=WORKER_COLUMN).value
                    if normalize_text(header) != "wykonawca":
                        summary.issues.append(
                            Issue("ZLY_SZABLON", f"Szablon nie ma WYKONAWCA w H:17: {target_path.name}.")
                        )
                        result = WorkerResult(worker_name, target_path, 0, "ZLY_SZABLON")
                    else:
                        occupied = target_has_input_data(target_sheet)
                finally:
                    target_workbook.close()

                if result is None:
                    rows = rows_by_target.get(target_key, [])
                    if occupied:
                        summary.issues.append(
                            Issue(
                                "NADPISANIE_ZABLOKOWANE",
                                f"Szablon zawiera już dane: {target_path.name}.",
                            )
                        )
                        result = WorkerResult(worker_name, target_path, 0, "ZABLOKOWANY")
                    elif not rows:
                        result = WorkerResult(worker_name, target_path, 0, "PUSTY_SZABLON")
                    elif dry_run:
                        result = WorkerResult(worker_name, target_path, len(rows), "PLAN")
                    else:
                        writing_target = True
                        _save_target(target_path, rows)
                        result = WorkerResult(worker_name, target_path, len(rows), "ZAPISANO")
            except SettlementError as exc:
                if writing_target:
                    raise
                summary.issues.append(Issue("PLIK_ZABLOKOWANY", str(exc)))
                result = WorkerResult(worker_name, target_path, 0, "ZABLOKOWANY")
            except (OSError, InvalidFileException, ValueError, zipfile.BadZipFile):
                if writing_target:
                    raise
                summary.issues.append(
                    Issue("BLAD_SZABLONU", f"Nie można obsłużyć szablonu: {target_path.name}.")
                )
                result = WorkerResult(worker_name, target_path, 0, "POMINIĘTO")

            assert result is not None
            summary.results.append(result)
            _notify(
                observer,
                ProgressEvent(
                    "Zapisywanie",
                    "WORKER_END",
                    template_index=template_index,
                    template_total=len(template_files),
                    worker_name=worker_name,
                    status=result.status,
                    rows=result.rows,
                    elapsed_ms=_elapsed_ms(run_started),
                    worker_elapsed_ms=_elapsed_ms(worker_started),
                    issue_count=len(summary.issues),
                ),
            )
    save_started = time.perf_counter()
    _notify(observer, ProgressEvent("Zapisywanie", "START", elapsed_ms=_elapsed_ms(run_started)))
    try:
        save_targets()
    finally:
        _notify(
            observer,
            ProgressEvent(
                "Zapisywanie",
                "END",
                template_index=len(template_files),
                template_total=len(template_files),
                elapsed_ms=_elapsed_ms(run_started),
                phase_elapsed_ms=_elapsed_ms(save_started),
            ),
        )

    return summary

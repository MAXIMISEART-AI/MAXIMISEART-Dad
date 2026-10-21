"""Przetwarzanie pojedynczego Szablonu pracownika."""

from __future__ import annotations

from pathlib import Path
from typing import Iterable, Literal

from .domain import WorkerResult
from .workbook_files import (
    WORKER_HEADER,
    DataRow,
    Problem,
    WorkbookError,
    WorkbookSaveError,
    WorkerSettlementTemplate,
)


class TemplateWriteError(Exception):
    """Szablonu pracownika nie da się bezpiecznie zapisać; Przebieg rozliczeń się zatrzymuje."""


# Nazwa pliku sprzed zmiany nazwy Placeholdera; służy tylko podpowiedzi w komunikacie.
_LEGACY_WORKER_TEMPLATE_NAME = "placeholder.xlsx"


WorkerTemplateProblem = Literal["missing", "open_in_excel", "unreadable"]

# Wzorzec rozliczenia pracownika, który da się otworzyć, ale nie może posłużyć jako wzór: co jest z nim nie tak.
# Sprawdzanie zgłasza to jako zły Wzorzec, a Zapisywanie (Wzorzec zmieniony po Sprawdzaniu) jako błąd Szablonu.
_UNUSABLE_TEMPLATE: dict[Problem, str] = {
    Problem.LAYOUT: f"nie ma nagłówka WYKONAWCA w {WORKER_HEADER.column}:{WORKER_HEADER.row}",
    Problem.HAS_DATA: "zawiera dane i nie może być użyty jako wzór",
}


class WorkerTemplateValidationError(Exception):
    """Wzorzec rozliczenia pracownika nie może bezpiecznie posłużyć jako wzór nowych skoroszytów.

    ``message`` to bezpieczny komunikat dla taty; ``problem`` mówi, czy Wzorca
    nie ma, czy jest otwarty w Excelu, czy nie przechodzi Sprawdzania.
    """

    def __init__(self, message: str, problem: WorkerTemplateProblem = "unreadable") -> None:
        super().__init__(message)
        self.message = message
        self.problem: WorkerTemplateProblem = problem


def validate_worker_template(path: Path) -> WorkerSettlementTemplate:
    """Sprawdza Wzorzec rozliczenia pracownika bez modyfikowania jego zawartości.

    Zwraca Wzorzec wczytany przy Sprawdzaniu; Przebieg rozliczeń tworzy z niego
    Rozliczenia pracowników bez ponownego wczytywania.
    """

    template = WorkerSettlementTemplate(path)
    try:
        template.check()
    except WorkbookError as error:
        raise _validation_error(path, error) from error
    return template


def _validation_error(path: Path, error: WorkbookError) -> WorkerTemplateValidationError:
    if error.problem is Problem.MISSING:
        message = f"Nie znaleziono Wzorca rozliczenia pracownika: {path.name}."
        if path.with_name(_LEGACY_WORKER_TEMPLATE_NAME).is_file():
            message += f" Zmień nazwę pliku {_LEGACY_WORKER_TEMPLATE_NAME} w tym samym folderze na „{path.name}”."
        return WorkerTemplateValidationError(message, "missing")
    if error.problem is Problem.OPEN_IN_EXCEL:
        return WorkerTemplateValidationError("Wzorzec rozliczenia pracownika jest otwarty lub zablokowany.", "open_in_excel")
    if error.problem in _UNUSABLE_TEMPLATE:
        return WorkerTemplateValidationError(f"Wzorzec rozliczenia pracownika {_UNUSABLE_TEMPLATE[error.problem]}.")
    return WorkerTemplateValidationError("Nie można odczytać Wzorca rozliczenia pracownika.")


def process_template(
    worker_name: str,
    template: WorkerSettlementTemplate,
    target_path: Path,
    rows: Iterable[DataRow],
) -> WorkerResult:
    """Tworzy z Wzorca jeden Szablon pracownika z jego Wierszami danych i zwraca jego bezpieczny wynik.

    Wzorca, którego nie da się otworzyć, nie maskuje wynik: ``WorkbookError`` przechodzi do rozmówcy.
    Plik z Wzorca bez WYKONAWCA albo z danymi i nieudany zapis to ``TemplateWriteError``;
    Szablon pracownika wtedy nie powstaje.
    """

    rows = list(rows)
    try:
        template.create_settlement(target_path, rows)
    except WorkbookError as error:
        if error.problem in _UNUSABLE_TEMPLATE:
            raise TemplateWriteError(f"Szablon {_UNUSABLE_TEMPLATE[error.problem]}: {target_path.name}.") from error
        raise
    except WorkbookSaveError as exc:
        raise TemplateWriteError(f"Nie można zapisać szablonu: {target_path.name}") from exc
    if not rows:
        return WorkerResult(worker_name, target_path, 0, "PUSTY_SZABLON")
    return WorkerResult(worker_name, target_path, len(rows), "ZAPISANO")

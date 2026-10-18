"""Przygotowanie pliku zbiorczego: z Rejestru zleceń do Rozliczenia wewnętrznego i Pliku zbiorczego.

Jedyną operacją publiczną jest ``prepare_collective_file()``. Silnik nie pyta o
nic i nie proponuje okresu; zatrzymania zgłasza jako ``PreparationError`` z
bezpiecznym komunikatem dla taty, a wynik nie zawiera danych klientów.

Ten moduł tylko sekwencjonuje cztery etapy. Odczyt Rejestru zleceń jest w
``preparation_register``, wybór zleceń okresu i reguły zleceń w
``preparation_plan``, a wzorce i zapis plików okresu w ``preparation_files``.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field, replace
from datetime import date
from pathlib import Path
from types import MappingProxyType

from . import preparation_files, preparation_plan, preparation_register
from . import preparation_messages as messages
from .domain import ProgressObserver, ProgressPhase
from .engine import SettlementError, load_worker_mapping
from .phase_runner import PhaseRunner
from .preparation_messages import PreparationError, PreparationMessage
from .settlement_period import SettlementPeriod, parse_period_token

__all__ = [
    "PreparationError",
    "PreparationMessage",
    "PreparationSummary",
    "default_collective_template_path",
    "default_internal_template_path",
    "prepare_collective_file",
]


@dataclass
class PreparationSummary:
    """Podsumowanie Przygotowania pliku zbiorczego bez danych klientów.

    Przy ``dry_run`` to plan: ścieżki plików są docelowe, ale nic nie istnieje.
    ``orders_per_day`` ma dokładnie siedem kluczy, każdy dzień okresu od wtorku
    do poniedziałku w kolejności dat, także dni bez zleceń (wartość ``0``).
    ``skipped_empty_rows`` to całkowicie puste wiersze Rejestru od pierwszego do
    ostatniego zlecenia okresu.
    """

    period: str
    period_directory: Path
    internal_settlement_file: Path
    collective_file: Path
    period_order_count: int
    successful_order_count: int
    skipped_empty_rows: int
    orders_per_day: dict[date, int] = field(default_factory=dict)
    warnings: list[PreparationMessage] = field(default_factory=list)
    phase_durations_ms: Mapping[ProgressPhase, int] = field(default_factory=lambda: MappingProxyType({}))


def default_internal_template_path() -> Path:
    """Wzorzec rozliczenia wewnętrznego w katalogu konfiguracji obok Wzorca rozliczenia pracownika."""

    return Path(__file__).resolve().parents[2] / "config" / "Wzorzec rozliczenia wewnętrznego.xlsx"


def default_collective_template_path() -> Path:
    """Wzorzec pliku zbiorczego w katalogu konfiguracji obok Wzorca rozliczenia pracownika."""

    return Path(__file__).resolve().parents[2] / "config" / "Wzorzec pliku zbiorczego.xlsx"


def _parse_period(token: str) -> SettlementPeriod:
    try:
        return parse_period_token(token)
    except ValueError as exc:
        raise messages.invalid_period_token(token) from exc


def prepare_collective_file(
    register_path: Path,
    periods_directory: Path,
    period: str,
    config_path: Path,
    *,
    internal_template_path: Path | None = None,
    collective_template_path: Path | None = None,
    dry_run: bool = False,
    observer: ProgressObserver | None = None,
    confirm_plan: Callable[[PreparationSummary], None] | None = None,
) -> PreparationSummary:
    """Tworzy w Folderze okresu razem Rozliczenie wewnętrzne i Plik zbiorczy.

    Zgłasza ``PreparationError``, gdy nie można działać bezpiecznie; wtedy nie
    powstaje żaden plik ani nowy Folder okresu, chyba że komunikat wskazuje plik
    okresu, którego po nieudanym zapisie nie udało się usunąć. Rejestr zleceń i
    wzorce są tylko czytane.

    ``dry_run=True`` wykonuje te same sprawdzenia, odczyt i planowanie, a etap
    Zapisywanie kończy bez tworzenia czegokolwiek (także Folderu okresu). Wynik
    jest wtedy planem z tymi samymi liczbami, ostrzeżeniami i nazwami plików.

    ``confirm_plan`` dostaje plan po Planowaniu, a przed Zapisywaniem, tylko
    przy zapisie. Silnik sam o nic nie pyta: wywołujący decyduje, a żeby
    przerwać bez zapisu, zgłasza ``PreparationError``. Czas tego wywołania nie
    wlicza się do czasu uruchomienia.
    """

    phases = PhaseRunner(observer)
    register_path = register_path.expanduser().resolve()
    periods_directory = periods_directory.expanduser().resolve()
    config_path = config_path.expanduser().resolve()
    files = preparation_files.PeriodFiles(
        internal_template=(internal_template_path or default_internal_template_path()).expanduser().resolve(),
        collective_template=(collective_template_path or default_collective_template_path()).expanduser().resolve(),
        period_directory=periods_directory / period,
        period=period,
    )

    def check_inputs() -> tuple[SettlementPeriod, dict[str, str]]:
        parsed_period = _parse_period(period)
        preparation_register.ensure_register_available(register_path)
        preparation_files.check_templates(files)
        if not periods_directory.is_dir():
            raise messages.periods_directory_missing(periods_directory)
        preparation_files.ensure_period_files_absent(files)
        try:
            worker_mapping = load_worker_mapping(config_path)
        except SettlementError as exc:
            raise messages.unreadable_worker_config(config_path) from exc
        return parsed_period, worker_mapping

    parsed_period, worker_mapping = phases.check(check_inputs)
    register = phases.read(lambda: preparation_register.read_register(register_path))

    def plan_orders() -> tuple[preparation_plan.Plan, list[PreparationMessage]]:
        plan = preparation_plan.plan_period_orders(register_path, register, parsed_period, config_path, worker_mapping)
        warnings = preparation_files.plan_period_files(files, len(plan.orders), len(plan.successful_orders))
        warnings.extend(preparation_plan.period_warnings(register_path, plan))
        return plan, warnings

    plan, warnings = phases.plan(plan_orders, issue_count=lambda planned: len(planned[1]))
    summary = PreparationSummary(
        period=period,
        period_directory=files.period_directory,
        internal_settlement_file=files.internal_settlement_file,
        collective_file=files.collective_file,
        period_order_count=len(plan.orders),
        successful_order_count=len(plan.successful_orders),
        skipped_empty_rows=plan.skipped_empty_rows,
        orders_per_day=plan.orders_per_day,
        warnings=warnings,
    )
    if confirm_plan is not None and not dry_run:
        with phases.paused():
            confirm_plan(replace(summary, phase_durations_ms=phases.durations_ms()))

    def save_both() -> None:
        if not dry_run:
            preparation_files.write_period_files(files, periods_directory, plan.orders, plan.successful_orders)

    phases.save(save_both)
    return replace(summary, phase_durations_ms=phases.durations_ms())

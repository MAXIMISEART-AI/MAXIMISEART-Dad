"""CLI Przygotowania pliku zbiorczego (osobne wejście, uruchamiane przez ``run_preparation.py``)."""

from __future__ import annotations

import argparse
from collections.abc import Mapping
from datetime import date, datetime, timedelta, timezone
import sys
import time
from pathlib import Path
from typing import Any, TextIO

from .cli import Dashboard, ask_in_dialog, default_config_path, record_metrics
from .collective_preparation import (
    PreparationError,
    PreparationSummary,
    default_collective_template_path,
    default_internal_template_path,
    prepare_collective_file,
)
from .domain import PHASES, ProgressPhase
from .phase_runner import elapsed_ms_since
from . import preparation_messages as messages
from .preparation_messages import PreparationMessage, unexpected_failure
from .settlement_period import SettlementPeriod, last_complete_period, parse_period_token
from .telemetry import METRICS_SCHEMA_VERSION, PERIOD_PATTERN, UNKNOWN_PERIOD, MetricsStore

_TITLE = "Przygotowanie pliku zbiorczego"
# Liczniki historii metryk Przygotowania pliku zbiorczego (inne niż Przebiegu rozliczeń).
_COUNTERS = ("period_orders", "successful_orders", "skipped_empty_rows", "warnings")
_WEEKDAY_LABELS = ("pon", "wt", "śr", "czw", "pt", "sob", "niedz")
_YES_ANSWERS = ("t", "tak")
# Status końcowy, gdy nie powstał żaden plik: zatrzymanie z komunikatem albo błąd nieprzewidziany.
_STOPPED = "ZATRZYMANO"
_FAILED = "BŁĄD"


def default_metrics_path() -> Path:
    """Osobna lokalna historia metryk, obok historii Przebiegu rozliczeń."""

    return Path(__file__).resolve().parents[2] / ".przygotowanie-pliku-zbiorczego-metrics.jsonl"


def choose_register_file() -> Path:
    """Okno wyboru pliku Rejestru zleceń, gdy nie podano ``--register``."""

    selected = ask_in_dialog(
        lambda dialog: dialog.askopenfilename(
            title="Wybierz plik Rejestru zleceń",
            filetypes=[("Rejestr zleceń Excel", "ZLECENIA*.xlsx"), ("Excel", "*.xlsx")],
        )
    )
    if not selected:
        raise messages.register_not_selected()
    return Path(selected)


def choose_periods_directory() -> Path:
    """Okno wyboru folderu okresów, gdy nie podano ``--periods-directory``."""

    selected = ask_in_dialog(
        lambda dialog: dialog.askdirectory(title="Wybierz folder okresów (np. INEA)", mustexist=True)
    )
    if not selected:
        raise messages.periods_directory_not_selected()
    return Path(selected)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Tworzy Rozliczenie wewnętrzne i Plik zbiorczy okresu z Rejestru zleceń."
    )
    parser.add_argument("--register", type=Path, help="Plik Rejestru zleceń; bez niego okno wyboru pliku.")
    parser.add_argument(
        "--periods-directory",
        type=Path,
        help="Folder okresów, w którym powstaje Folder okresu; bez niego okno wyboru folderu.",
    )
    parser.add_argument(
        "--period",
        help="Token okresu, np. 08_14_09_2026; bez niego pytanie z propozycją ostatniego pełnego okresu.",
    )
    parser.add_argument("--config", type=Path, default=default_config_path(), help="Konfiguracja wykonawców.")
    parser.add_argument(
        "--internal-template",
        type=Path,
        default=default_internal_template_path(),
        help="Wzorzec rozliczenia wewnętrznego.",
    )
    parser.add_argument(
        "--collective-template",
        type=Path,
        default=default_collective_template_path(),
        help="Wzorzec pliku zbiorczego.",
    )
    parser.add_argument(
        "--metrics",
        type=Path,
        default=default_metrics_path(),
        help="Lokalny plik historii metryk JSONL Przygotowania pliku zbiorczego.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Sprawdź wszystko i pokaż plan bez tworzenia plików ani folderów.",
    )
    return parser


def _orders_per_day_lines(orders_per_day: dict[date, int]) -> list[str]:
    """Linie ``- wt 08.09.2026: 1`` dla każdego dnia okresu, w kolejności dat."""

    return [
        f"- {_WEEKDAY_LABELS[day.weekday()]} {day:%d.%m.%Y}: {count}"
        for day, count in orders_per_day.items()
    ]


def _message_lines(message: PreparationMessage) -> list[str]:
    first, *rest = message.text.splitlines()
    return [f"- {first}", *(f"  {line}" for line in rest)]


def _summary_lines(summary: PreparationSummary, *, dry_run: bool) -> list[str]:
    lines = [
        f"Okres: {summary.period}",
        f"Zlecenia okresu: {summary.period_order_count}",
        f"Zlecenia skuteczne: {summary.successful_order_count}",
        f"Pominięte puste wiersze: {summary.skipped_empty_rows}",
        "Zlecenia na dzień:",
        *_orders_per_day_lines(summary.orders_per_day),
        f"Ostrzeżenia: {len(summary.warnings)}",
    ]
    for warning in summary.warnings:
        lines.extend(_message_lines(warning))
    lines.append(f"Rozliczenie wewnętrzne: {summary.internal_settlement_file.name}")
    lines.append(f"Plik zbiorczy: {summary.collective_file.name}")
    if dry_run:
        lines.append("DRY-RUN: Nic nie zapisano")
    return lines


def _say(output: TextIO, text: str, *, end: str = "\n") -> None:
    """Linia dla taty przed dashboardem; błąd terminala nie przerywa procesu."""

    try:
        output.write(text + end)
        output.flush()
    except (OSError, ValueError):
        pass


def _say_message(output: TextIO, message: PreparationMessage) -> None:
    for line in message.text.splitlines():
        _say(output, line)


def _is_interactive(stream: TextIO) -> bool:
    try:
        return bool(stream.isatty())
    except (AttributeError, OSError, ValueError):
        return False


def _ask(output: TextIO, input_stream: TextIO, prompt: str) -> str | None:
    """Odpowiedź bez otaczających spacji; ``None``, gdy wejście się skończyło.

    Gdy odpowiedź nie pochodzi z terminala (który sam wyświetla Enter), dopisuje
    koniec linii, żeby kolejny komunikat nie trafił do linii pytania.
    """

    _say(output, prompt, end="")
    answer = input_stream.readline()
    if not _is_interactive(input_stream):
        _say(output, "")
    return None if answer == "" else answer.strip()


def _period_label(period: SettlementPeriod) -> str:
    return f"{period.token} (wtorek {period.tuesday:%d.%m.%Y} – poniedziałek {period.monday:%d.%m.%Y})"


def _ask_period(today: date, output: TextIO, input_stream: TextIO) -> str:
    """Proponuje ostatni pełny okres; Enter go potwierdza, inny poprawny token go zastępuje."""

    proposed = last_complete_period(today)
    previous = SettlementPeriod(proposed.tuesday - timedelta(days=7))
    _say(output, f"Proponowany okres: {_period_label(proposed)}")
    _say(output, f"Enter potwierdza ten okres. Inny okres wpisz jak w nazwie folderu, np. {previous.token}.")
    while True:
        answer = _ask(output, input_stream, "Okres: ")
        if answer is None:
            raise messages.period_not_entered()
        if not answer:
            return proposed.token
        try:
            return parse_period_token(answer).token
        except ValueError:
            _say_message(output, messages.invalid_period_token(answer).message)


class _IncompletePeriodQuestion:
    """Decyzja CLI po Planowaniu: przy niepełnym okresie pyta tatę o kontynuację.

    Silnik wywołuje ją z planem między Planowaniem a Zapisywaniem. Dashboard jest
    na czas pytania zatrzymany, a czas oczekiwania na odpowiedź jest odejmowany
    od czasu uruchomienia. Odmowa to ``PreparationError``.
    """

    def __init__(self, dashboard: Dashboard, output: TextIO, input_stream: TextIO) -> None:
        self._dashboard = dashboard
        self._output = output
        self._input_stream = input_stream
        self.waited_ms = 0

    def __call__(self, plan: PreparationSummary) -> None:
        warning = next((item for item in plan.warnings if item.code == messages.INCOMPLETE_PERIOD), None)
        if warning is None:
            return
        asked = time.perf_counter()
        self._dashboard.stop()
        try:
            _say(self._output, "Ostrzeżenie: niepełny okres")
            for line in [*warning.text.splitlines(), "Zlecenia na dzień:", *_orders_per_day_lines(plan.orders_per_day)]:
                _say(self._output, line)
            answer = _ask(
                self._output,
                self._input_stream,
                "Kontynuować mimo niepełnego okresu? Wpisz t (tak) albo n (nie): ",
            )
        finally:
            self.waited_ms += elapsed_ms_since(asked)
        if answer is None or answer.casefold() not in _YES_ANSWERS:
            raise messages.incomplete_period_refused(plan.period)
        self._dashboard.resume()


def _metrics_period(period: str) -> str:
    return period if PERIOD_PATTERN.fullmatch(period) else UNKNOWN_PERIOD


def _metric_record(
    *,
    mode: str,
    period: str,
    summary: PreparationSummary | None,
    phase_durations_ms: Mapping[ProgressPhase, int],
    total_elapsed_ms: int,
    started_at: str,
) -> dict[str, Any]:
    counters = dict.fromkeys(_COUNTERS, 0)
    phase_durations = dict(phase_durations_ms)
    if summary is not None:
        counters.update(
            {
                "period_orders": summary.period_order_count,
                "successful_orders": summary.successful_order_count,
                "skipped_empty_rows": summary.skipped_empty_rows,
                "warnings": len(summary.warnings),
            }
        )
        phase_durations.update(summary.phase_durations_ms)
    return {
        "schema_version": METRICS_SCHEMA_VERSION,
        "started_at": started_at,
        "mode": mode,
        "period": _metrics_period(period),
        "completed": summary is not None,
        "result": "OK" if summary is not None else "BLAD_KRYTYCZNY",
        "total_duration_ms": total_elapsed_ms,
        "phase_durations_ms": {phase: phase_durations.get(ProgressPhase(phase), 0) for phase in PHASES},
        "counters": counters,
    }


def main(
    argv: list[str] | None = None,
    *,
    output: TextIO | None = None,
    input_stream: TextIO | None = None,
    metrics_path: Path | None = None,
    today: date | None = None,
) -> int:
    """Uruchamia Przygotowanie pliku zbiorczego; ``0`` sukces, ``1`` zatrzymanie, błąd albo odmowa."""

    output = output or sys.stdout
    input_stream = input_stream or sys.stdin
    args = build_parser().parse_args(argv)
    mode = "DRY-RUN" if args.dry_run else "RUN"
    metrics_store = MetricsStore(metrics_path or args.metrics, frozenset(_COUNTERS))

    summary: PreparationSummary | None = None
    stop: tuple[str, PreparationMessage] | None = None
    period: str = args.period or UNKNOWN_PERIOD
    try:
        register_path: Path = args.register or choose_register_file()
        periods_directory: Path = args.periods_directory or choose_periods_directory()
        period = args.period or _ask_period(today or date.today(), output, input_stream)
    except PreparationError as error:
        stop = (_STOPPED, error.message)

    # Czas liczony od uruchomienia silnika, bez czasu wyboru plików i odpowiedzi taty.
    started_at = datetime.now(timezone.utc).isoformat()
    started = time.perf_counter()
    dashboard = Dashboard(output, mode, period, title=_TITLE, shows_templates=False)
    dashboard.start()
    question = _IncompletePeriodQuestion(dashboard, output, input_stream)
    if stop is None:
        try:
            summary = prepare_collective_file(
                register_path,
                periods_directory,
                period,
                args.config,
                internal_template_path=args.internal_template,
                collective_template_path=args.collective_template,
                dry_run=args.dry_run,
                observer=dashboard,
                confirm_plan=question,
            )
        except PreparationError as error:
            stop = (_STOPPED, error.message)
        except Exception:
            stop = (_FAILED, unexpected_failure())

    total_elapsed_ms = max(0, elapsed_ms_since(started) - question.waited_ms)
    dashboard.stop()
    if stop is not None:
        status, message = stop
        dashboard.print_line(f"Status końcowy: {status}")
        for line in message.text.splitlines():
            dashboard.print_line(line)
        dashboard.print_line(f"Czas uruchomienia: {total_elapsed_ms} ms")
    else:
        assert summary is not None
        dashboard.print_line("Status końcowy: OK")
        dashboard.print_line(f"Czas uruchomienia: {total_elapsed_ms} ms")
        for line in _summary_lines(summary, dry_run=args.dry_run):
            dashboard.print_line(line)

    record = _metric_record(
        mode=mode,
        period=period,
        summary=summary,
        phase_durations_ms=dashboard.phase_durations_ms,
        total_elapsed_ms=total_elapsed_ms,
        started_at=started_at,
    )
    record_metrics(
        dashboard,
        metrics_store,
        record,
        failure_warning="Nie zapisano metryk; Przygotowanie pliku zbiorczego zakończyło się niezależnie.",
    )
    return 0 if summary is not None else 1


if __name__ == "__main__":
    raise SystemExit(main())

"""CLI Przygotowania pliku zbiorczego (osobne wejście, uruchamiane przez ``run_preparation.py``)."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import TextIO

from .cli import default_config_path
from .collective_preparation import (
    PreparationError,
    PreparationSummary,
    default_collective_template_path,
    default_internal_template_path,
    prepare_collective_file,
)
from .preparation_messages import PreparationMessage, unexpected_failure


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Tworzy Rozliczenie wewnętrzne i Plik zbiorczy okresu z Rejestru zleceń."
    )
    parser.add_argument("--register", type=Path, required=True, help="Plik Rejestru zleceń.")
    parser.add_argument(
        "--periods-directory",
        type=Path,
        required=True,
        help="Folder okresów, w którym powstaje Folder okresu.",
    )
    parser.add_argument("--period", required=True, help="Token okresu, np. 08_14_09_2026.")
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
    return parser


def _print_summary(output: TextIO, summary: PreparationSummary) -> None:
    print("Status końcowy: OK", file=output)
    print(f"Zlecenia okresu: {summary.period_order_count}", file=output)
    print(f"Zlecenia skuteczne: {summary.successful_order_count}", file=output)
    print(f"Pominięte puste wiersze: {summary.skipped_empty_rows}", file=output)
    print(f"Rozliczenie wewnętrzne: {summary.internal_settlement_file.name}", file=output)
    print(f"Plik zbiorczy: {summary.collective_file.name}", file=output)


def _print_stop(output: TextIO, status: str, message: PreparationMessage) -> None:
    print(f"Status końcowy: {status}", file=output)
    print(message.text, file=output)


def main(argv: list[str] | None = None, *, output: TextIO | None = None) -> int:
    """Uruchamia Przygotowanie pliku zbiorczego; ``0`` sukces, ``1`` zatrzymanie albo błąd."""

    output = output or sys.stdout
    args = build_parser().parse_args(argv)
    print(f"Przygotowanie pliku zbiorczego | okres: {args.period}", file=output)
    try:
        summary = prepare_collective_file(
            args.register,
            args.periods_directory,
            args.period,
            args.config,
            internal_template_path=args.internal_template,
            collective_template_path=args.collective_template,
        )
    except PreparationError as error:
        _print_stop(output, "ZATRZYMANO", error.message)
        return 1
    except Exception:
        _print_stop(output, "BŁĄD", unexpected_failure())
        return 1
    _print_summary(output, summary)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

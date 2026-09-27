"""Interfejs tekstowy i wybór lokalnego pliku źródłowego."""

from __future__ import annotations

import argparse
from pathlib import Path

from .engine import SettlementError, run_settlements


def default_config_path() -> Path:
    return Path(__file__).resolve().parents[2] / "config" / "worker_mapping.yaml"


def choose_source_file() -> Path:
    """Pokazuje lokalny wybór pliku, gdy launcher nie podał argumentu."""

    try:
        import tkinter as tk
        from tkinter import filedialog

        root = tk.Tk()
        root.withdraw()
        selected = filedialog.askopenfilename(
            title="Wybierz plik zbiorczy rozliczenia",
            filetypes=[("Plik zbiorczy Excel", "Rozliczenie * - zbiorcze.xlsx"), ("Excel", "*.xlsx")],
        )
        root.destroy()
        if selected:
            return Path(selected)
    except Exception:
        pass
    raise SettlementError("Nie wybrano pliku zbiorczego.")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Rozdziela plik zbiorczy na szablony pracowników.")
    parser.add_argument("--source", type=Path, help="Ścieżka do pliku ... - zbiorcze.xlsx")
    parser.add_argument("--config", type=Path, default=default_config_path())
    parser.add_argument("--dry-run", action="store_true", help="Sprawdź plan bez zapisywania plików.")
    return parser


def print_summary(summary) -> None:
    action = "Plan" if summary.planned_count else "Zakończono"
    print(f"{action}: {summary.period}")
    print(f"Pliki zapisane: {summary.written_count}")
    if summary.planned_count:
        print(f"Pliki planowane: {summary.planned_count}")
    print(f"Puste szablony: {summary.empty_count}")
    print(f"Wiersze danych: {summary.total_rows}")
    if summary.issues:
        print("Wymaga sprawdzenia:")
        for issue in summary.issues:
            print(f"- {issue.message}")
    else:
        print("Status: OK")


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        source = args.source or choose_source_file()
        summary = run_settlements(source, args.config, dry_run=args.dry_run)
        print_summary(summary)
        return 0 if summary.ok else 2
    except SettlementError as exc:
        print(f"Nie wykonano: {exc}")
        return 1
    except OSError as exc:
        print(f"Nie wykonano z powodu pliku lub dostępu: {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

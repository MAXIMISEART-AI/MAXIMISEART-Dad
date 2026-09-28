"""Shared display labels and formatting for settlement progress adapters."""

from __future__ import annotations

from collections.abc import Mapping

from .progress import ProgressSnapshot


OPERATION_STATUS_PRESENTATION: dict[str, tuple[str, str]] = {
    "ZAPISANO": ("OK", "green"),
    "PUSTY_SZABLON": ("OK", "green"),
    "PLAN": ("OK", "green"),
    "ZABLOKOWANY": ("OSTRZEŻENIE", "yellow"),
    "ZLY_SZABLON": ("BŁĄD", "red"),
    "POMINIĘTO": ("BŁĄD", "red"),
}


def operation_status_presentation(status: str | None) -> tuple[str, str]:
    """Return the same semantic label and optional style for every adapter."""

    return OPERATION_STATUS_PRESENTATION.get(status or "", ("OSTRZEŻENIE", "yellow"))


def progress_line(snapshot: ProgressSnapshot) -> str:
    if not snapshot.template_total:
        return "oczekuje na liczbę szablonów"
    percentage = round(snapshot.templates_completed / snapshot.template_total * 100)
    return f"{snapshot.templates_completed}/{snapshot.template_total} ({percentage}%)"


def counter_line(snapshot: ProgressSnapshot) -> str:
    return format_counter_line(snapshot.metric_counters())


def format_counter_line(counters: Mapping[str, int]) -> str:
    return (
        f"zapisano: {counters['written']} | "
        f"puste: {counters['empty']} | "
        f"planowane: {counters['planned']} | "
        f"pominięte: {counters['skipped']}"
    )

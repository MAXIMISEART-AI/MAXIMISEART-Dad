"""Skoroszyty na dysku: blokada Excela i bezpieczny zapis."""

from __future__ import annotations

from pathlib import Path


def is_open_in_excel(path: Path) -> bool:
    """Rozpoznaje skoroszyt otwarty w desktopowym Excelu po pliku blokady ``~$…``."""

    return path.with_name(f"~${path.name}").exists()

"""Lokalne rozdzielanie tygodniowych rozliczeń pracowników."""

from pathlib import Path
from typing import Final

__all__ = ["TOOL_ROOT", "engine"]

# Katalog narzędzia (klon Gita z ``pyproject.toml``), w którym leży pakiet ``src/rozliczenia``.
TOOL_ROOT: Final = Path(__file__).resolve().parents[2]

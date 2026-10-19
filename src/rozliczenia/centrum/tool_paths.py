"""Pliki narzędzia wspólne z CLI: konfiguracja wykonawców, wzorce i pliki metryk.

Centrum rozliczeń używa tych samych domyślnych ścieżek co launchery `.cmd`, więc
Uruchomienia z obu wejść czytają te same wzorce i dopisują do tych samych
plików metryk. Testy i skill weryfikacji podają własne ścieżki.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from rozliczenia import preparation_cli
from rozliczenia.collective_preparation import default_collective_template_path, default_internal_template_path
from rozliczenia.engine import default_config_path


@dataclass(frozen=True)
class ToolPaths:
    worker_config: Path = field(default_factory=default_config_path)
    internal_template: Path = field(default_factory=default_internal_template_path)
    collective_template: Path = field(default_factory=default_collective_template_path)
    preparation_metrics: Path = field(default_factory=preparation_cli.default_metrics_path)

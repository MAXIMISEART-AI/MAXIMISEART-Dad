"""Konfiguracja wykonawców: który identyfikator Wykonawcy z kolumny H to która nazwa w Rozliczeniu pracownika.

Wspólna dla Przebiegu rozliczeń, Przygotowania pliku zbiorczego i ekranu
Konfiguracji w Centrum rozliczeń. Złamaną regułę zgłasza jako
``WorkerConfigError`` z powodem i bezpiecznym szczegółem; Komunikat dla taty
wybiera proces ze swojego katalogu.
"""

from __future__ import annotations

import stat
import unicodedata
from pathlib import Path
from typing import Literal

import yaml

from . import TOOL_ROOT
from .period_folder import check_worker_name

__all__ = [
    "WorkerConfigError",
    "default_config_path",
    "load_worker_mapping",
    "normalize_text",
]

WorkerConfigProblem = Literal["missing", "inaccessible", "not_utf8", "not_yaml", "invalid"]


class WorkerConfigError(Exception):
    """Konfiguracji wykonawców nie da się użyć.

    ``reason``: brak pliku (``missing``, także folder w jego miejscu), plik, którego
    system nie oddał (``inaccessible``, np. zajęty przez inny program albo bez
    dostępu; to nie zła treść), zapisany w innym kodowaniu niż UTF-8 (``not_utf8``,
    np. ANSI ze starego Notatnika albo UTF-16 z PowerShella 5.1), zły YAML
    (``not_yaml``) albo złamana reguła (``invalid``). ``detail`` to bezpieczne
    zdanie dla taty bez ścieżki pliku.
    """

    def __init__(self, reason: WorkerConfigProblem, detail: str) -> None:
        super().__init__(detail)
        self.reason: WorkerConfigProblem = reason
        self.detail = detail


def normalize_text(value: object) -> str:
    """Normalizuje identyfikator bez usuwania polskich znaków."""

    text = unicodedata.normalize("NFC", str(value or ""))
    return " ".join(text.replace("\u00a0", " ").split()).casefold()


def default_config_path() -> Path:
    """Wskazuje Konfigurację wykonawców w katalogu konfiguracji."""

    return TOOL_ROOT / "config" / "worker_mapping.yaml"


def load_worker_mapping(config_path: Path) -> dict[str, str]:
    """Wczytuje mapowanie znormalizowanych identyfikatorów na nazwy, w kolejności z pliku."""

    try:
        config = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
    except OSError as exc:
        raise _unread(config_path) from exc
    except UnicodeDecodeError as exc:
        raise WorkerConfigError("not_utf8", "Plik nie jest zapisany w kodowaniu UTF-8.") from exc
    except yaml.YAMLError as exc:
        raise WorkerConfigError("not_yaml", "Plik nie jest poprawnym YAML.") from exc

    if not isinstance(config, dict):
        raise _invalid("Konfiguracja musi być mapą z sekcją workers.")
    if type(config.get("schema_version")) is not int or config["schema_version"] != 1:
        raise _invalid("Nieobsługiwana wersja konfiguracji.")

    workers = config.get("workers")
    if not isinstance(workers, dict) or not workers:
        raise _invalid("Konfiguracja workers musi zawierać co najmniej jeden wpis.")

    mapping: dict[str, str] = {}
    seen_names: dict[str, str] = {}
    for source_id, target_name in workers.items():
        if not isinstance(source_id, str) or not isinstance(target_name, str):
            raise _invalid("Konfiguracja zawiera niepoprawny identyfikator lub nazwę pracownika.")
        normalized_id = normalize_text(source_id)
        display_name = target_name.strip()
        normalized_name = normalize_text(display_name)
        if not normalized_id or not normalized_name:
            raise _invalid("Konfiguracja zawiera pusty identyfikator lub nazwę pracownika.")
        if normalized_id in mapping:
            raise _invalid("Konfiguracja zawiera powtórzony identyfikator pracownika.")
        name_check = check_worker_name(display_name)
        if name_check == "invalid":
            raise _invalid("Konfiguracja zawiera nazwę pracownika nieprawidłową dla nazwy pliku.")
        if name_check == "too_long":
            raise _invalid("Konfiguracja zawiera nazwę pracownika zbyt długą dla nazwy pliku.")
        if normalized_name in seen_names:
            raise _invalid(
                f"Dwóch identyfikatorów wskazuje ten sam plik pracownika: {seen_names[normalized_name]} / {display_name}"
            )
        mapping[normalized_id] = display_name
        seen_names[normalized_name] = display_name
    return mapping


def _unread(config_path: Path) -> WorkerConfigError:
    """Plik, którego nie udało się przeczytać: brak pliku albo plik niedostępny, rozpoznane po ``stat`` jak skoroszyt.

    Folder bez dostępu daje ``OSError`` także w ``stat``, więc plik w nim jest niedostępny, a nie brakujący.
    """

    try:
        missing = not stat.S_ISREG(config_path.stat().st_mode)
    except (FileNotFoundError, NotADirectoryError):
        missing = True
    except OSError:
        missing = False
    if missing:
        return WorkerConfigError("missing", "Nie można odczytać pliku konfiguracji.")
    return WorkerConfigError(
        "inaccessible", "Nie można teraz odczytać pliku konfiguracji. Plik może być zajęty przez inny program."
    )


def _invalid(detail: str) -> WorkerConfigError:
    return WorkerConfigError("invalid", detail)

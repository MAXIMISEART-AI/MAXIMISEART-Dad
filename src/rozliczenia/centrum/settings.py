"""Ustawienia taty w lokalnym pliku YAML poza gitem: Rejestr zleceń, folder okresów i motyw.

Brak albo uszkodzenie pliku znaczy „nie ustawiono”, nigdy błąd startu. Zapis
podmienia plik atomowo, więc przerwany zapis zostawia poprzednie ustawienia.
"""

from __future__ import annotations

import os
import tempfile
import threading
from collections.abc import Callable
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Literal

import yaml
from fastapi import APIRouter

from rozliczenia.centrum import contract
from rozliczenia.centrum.platform import Platform

Theme = Literal["dark", "light"]
_THEMES: tuple[Theme, ...] = ("dark", "light")
_SCHEMA_VERSION = 1


def default_settings_path() -> Path:
    return Path(__file__).resolve().parents[3] / "config" / "centrum-ustawienia.yaml"


@dataclass(frozen=True)
class CentrumSettings:
    register: Path | None = None
    periods_directory: Path | None = None
    theme: Theme = "dark"


class SettingsStore:
    def __init__(self, path: Path) -> None:
        self._path = path
        self._lock = threading.Lock()

    def load(self) -> CentrumSettings:
        try:
            document = yaml.safe_load(self._path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, yaml.YAMLError):
            return CentrumSettings()
        if not isinstance(document, dict) or document.get("schema_version") != _SCHEMA_VERSION:
            return CentrumSettings()
        theme = document.get("motyw")
        return CentrumSettings(
            register=_path_or_none(document.get("rejestr_zlecen")),
            periods_directory=_path_or_none(document.get("folder_okresow")),
            theme=theme if theme in _THEMES else "dark",
        )

    def update(
        self,
        *,
        register: Path | None = None,
        periods_directory: Path | None = None,
        theme: Theme | None = None,
    ) -> CentrumSettings:
        with self._lock:
            current = self.load()
            updated = replace(
                current,
                register=register or current.register,
                periods_directory=periods_directory or current.periods_directory,
                theme=theme or current.theme,
            )
            self._write(updated)
            return updated

    def _write(self, settings: CentrumSettings) -> None:
        document = {
            "schema_version": _SCHEMA_VERSION,
            "rejestr_zlecen": None if settings.register is None else str(settings.register),
            "folder_okresow": None if settings.periods_directory is None else str(settings.periods_directory),
            "motyw": settings.theme,
        }
        self._path.parent.mkdir(parents=True, exist_ok=True)
        descriptor, temporary = tempfile.mkstemp(prefix=f".{self._path.name}.", dir=self._path.parent)
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8") as file:
                yaml.safe_dump(document, file, allow_unicode=True, sort_keys=False, width=1_000_000)
            os.replace(temporary, self._path)
        except BaseException:
            Path(temporary).unlink(missing_ok=True)
            raise


def _path_or_none(value: object) -> Path | None:
    return Path(value) if isinstance(value, str) and value else None


_REGISTER_DIALOG = "Wybierz plik Rejestru zleceń"
_REGISTER_FILETYPES = (("Rejestr zleceń Excel", "ZLECENIA*.xlsx"), ("Excel", "*.xlsx"))
_PERIODS_DIALOG = "Wybierz folder okresów (np. INEA)"


def settings_router(store: SettingsStore, platform: Platform) -> APIRouter:
    router = APIRouter(prefix="/api/settings", tags=["ustawienia"])

    @router.get("", operation_id="getSettings")
    def read() -> contract.Settings:
        return describe(store.load())

    @router.post("/register/choose", operation_id="chooseRegister")
    def choose_register() -> contract.Choice:
        chosen = platform.choose_file(_REGISTER_DIALOG, _REGISTER_FILETYPES)
        if chosen is None:
            return contract.Choice(settings=describe(store.load()))
        return contract.Choice(settings=describe(store.update(register=chosen)))

    @router.post("/periods-directory/choose", operation_id="choosePeriodsDirectory")
    def choose_periods_directory() -> contract.Choice:
        chosen = platform.choose_folder(_PERIODS_DIALOG)
        if chosen is None:
            return contract.Choice(settings=describe(store.load()))
        return contract.Choice(settings=describe(store.update(periods_directory=chosen)))

    @router.put("/theme", operation_id="changeTheme")
    def change_theme(change: contract.ThemeChange) -> contract.Settings:
        return describe(store.update(theme=change.theme))

    return router


def describe(settings: CentrumSettings) -> contract.Settings:
    return contract.Settings(
        order_register=_describe_path(settings.register, exists=Path.is_file),
        periods_directory=_describe_path(settings.periods_directory, exists=Path.is_dir),
        theme=settings.theme,
    )


def _describe_path(path: Path | None, *, exists: Callable[[Path], bool]) -> contract.PathSetting:
    if path is None:
        return contract.NotSetPath(state="not_set")
    if exists(path):
        return contract.ReadyPath(state="ready", path=str(path), name=path.name)
    return contract.MissingPath(state="missing", path=str(path), name=path.name)

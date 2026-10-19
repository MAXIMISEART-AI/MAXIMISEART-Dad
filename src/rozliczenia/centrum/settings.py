"""Ustawienia taty w Centrum rozliczeń: odczyt, wskazanie Rejestru zleceń i folderu okresów oknem wyboru, motyw.

Plik ustawień i jego zapis należą do ``rozliczenia.settings``, wspólnego z launcherami ``.cmd``.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from fastapi import APIRouter

from rozliczenia.centrum import contract
from rozliczenia.centrum.platform import Platform
from rozliczenia.settings import Settings, SettingsStore

_REGISTER_DIALOG = "Wybierz plik Rejestru zleceń"
_REGISTER_FILETYPES = (("Rejestr zleceń Excel", "ZLECENIA*.xlsx"), ("Excel", "*.xlsx"))
_PERIODS_DIALOG = "Wybierz folder okresów (np. Załączniki albo INEA)"


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


def describe(settings: Settings) -> contract.Settings:
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

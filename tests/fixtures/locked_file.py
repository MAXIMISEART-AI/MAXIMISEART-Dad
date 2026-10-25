"""Plik stanu Centrum zablokowany jak na Windows, gdy antywirus albo indeksowanie trzyma go otwartym."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
import os
from pathlib import Path

import pytest

Replace = Callable[[str | os.PathLike[str], str | os.PathLike[str]], None]


@dataclass
class LockedFile:
    """``os.replace``, które na plik ``name`` rzuca ``PermissionError`` jak Windows przy pliku otwartym gdzie indziej.

    ``failures`` to tyle pierwszych zamian, które padają (``None``: każda, dopóki test nie zawoła ``release``);
    ``attempts`` liczy zamiany na ten plik. Zamianę innych plików robi ``inner``.
    """

    name: str
    failures: int | None
    inner: Replace
    attempts: int = 0

    def __call__(self, source: str | os.PathLike[str], target: str | os.PathLike[str]) -> None:
        if Path(target).name == self.name:
            self.attempts += 1
            if self.failures is None or self.attempts <= self.failures:
                raise PermissionError(13, "Odmowa dostępu", str(target))
        self.inner(source, target)

    def release(self) -> None:
        self.failures = 0


def lock_file(monkeypatch: pytest.MonkeyPatch, name: str, failures: int | None = None) -> LockedFile:
    """Blokuje zamianę pliku ``name`` (``Path.replace`` woła ``os.replace``) do końca testu albo ``release``.

    Kolejne wywołanie blokuje następny plik obok poprzednich.
    """

    locked = LockedFile(name, failures, os.replace)
    monkeypatch.setattr(os, "replace", locked)
    return locked

"""Kontrakt wywołania skryptów skilli ``verify-*``: katalog runu, katalog przebiegu i warianty.

Skrypt skilla bierze te argumenty tylko z ``Parser`` (pilnuje tego ``tests/test_wywolanie_skryptow_skilli.py``):

- ``--root``: katalog jednego runu. Może leżeć gdziekolwiek, także poza repozytorium; względny liczy się od
  bieżącego katalogu w chwili wywołania, a dalej skrypt widzi już tylko ścieżkę bezwzględną.
- ``--run-dir``: katalog przebiegu runnera, z runami w ``runs/<id>`` i dowodami w ``evidence/<id>``.
  Domyślnie ``.verification`` checkoutu, w którym leży skrypt.
- ``--variant``: lista wariantów, także jako jeden argument ``"existing locked"`` albo ``"--variant existing"``.

Katalog runu zakłada ``create_run_root`` ze znacznikiem ``.katalog-runu``. Sprzątanie i kroki, które piszą do runu,
wymagają znacznika, więc literówka w ``--root`` nie skasuje ani nie zmieni cudzego katalogu.
"""

from __future__ import annotations

import argparse
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path
import shutil
import sys
from typing import Any

VERIFICATION = Path(__file__).resolve().parents[1] / ".verification"
MARKER = ".katalog-runu"
EVERY = "all"


class RunRootError(ValueError):
    """Katalog runu jest zajęty albo nie założyła go fixture skilla."""


def absolute_path(value: str) -> Path:
    if not value.strip():
        raise argparse.ArgumentTypeError("pusta ścieżka")
    return Path(value).expanduser().resolve()


@dataclass(frozen=True)
class _Variants:
    known: tuple[str, ...]
    default: str
    every: tuple[str, ...]

    def resolve(self, given: Sequence[str] | None, parser: argparse.ArgumentParser) -> tuple[str, ...]:
        names = [name for value in given or (self.default,) for name in value.replace(",", " ").split()]
        unknown = [name for name in names if name not in (*self.known, EVERY)]
        if unknown or not names:
            known = ", ".join((*self.known, EVERY))
            parser.error(f"--variant: nieznany wariant {', '.join(unknown) or '(pusty)'}; znane: {known}")
        expanded = (variant for name in names for variant in (self.every if name == EVERY else (name,)))
        return tuple(dict.fromkeys(expanded))


class Parser(argparse.ArgumentParser):
    """``ArgumentParser`` skryptu skilla; argumenty kontraktu dodają tylko jego metody."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._variants: _Variants | None = None

    def add_root(self, help: str) -> None:
        self.add_argument("--root", type=absolute_path, required=True, help=help)

    def add_run_dir(self) -> None:
        self.add_argument(
            "--run-dir",
            type=absolute_path,
            default=VERIFICATION,
            help="katalog przebiegu: runy w runs/<id>, dowody w evidence/<id> (domyślnie .verification checkoutu)",
        )

    def add_variants(self, known: Iterable[str], *, default: str, every: Iterable[str]) -> None:
        """``args.variant`` to krotka wariantów w podanej kolejności; ``all`` to ``every``."""

        variants = self._variants = _Variants(tuple(known), default, tuple(every))
        self.add_argument(
            "--variant",
            nargs="+",
            action="extend",
            metavar="WARIANT",
            help=f"jeden albo kilka z: {', '.join((*variants.known, EVERY))} "
            f"(domyślnie {default}; {EVERY}: {', '.join(variants.every)})",
        )

    def parse_known_args(  # type: ignore[override]
        self, args: Sequence[str] | None = None, namespace: argparse.Namespace | None = None
    ) -> tuple[argparse.Namespace, list[str]]:
        given = sys.argv[1:] if args is None else list(args)
        parsed, rest = super().parse_known_args(list(self._split_joined(given)), namespace)
        if self._variants is not None:
            parsed.variant = self._variants.resolve(parsed.variant, self)
        return parsed, rest

    def _split_joined(self, arguments: Iterable[str]) -> Iterable[str]:
        """``"--variant existing"`` jako jeden argument (zsh nie dzieli ``$a``) to ``--variant=existing``."""

        for argument in arguments:
            option, *value = argument.split(None, 1) or [argument]
            if value and argument.startswith("--") and option in self._option_string_actions:
                yield f"{option}={value[0]}"
            else:
                yield argument


@dataclass(frozen=True)
class Run:
    """Jeden run runnera: ``root`` zakłada fixture i usuwa sprzątanie, ``evidence`` zostaje."""

    root: Path
    evidence: Path


def new_run(run_dir: Path, name: str) -> Run:
    evidence = run_dir / "evidence" / name
    evidence.mkdir(parents=True)
    return Run(run_dir / "runs" / name, evidence)


def create_run_root(root: Path) -> Path:
    if root.exists() and (not root.is_dir() or any(root.iterdir())):
        raise RunRootError(f"katalog runu nie jest pusty: {root}")
    root.mkdir(parents=True, exist_ok=True)
    (root / MARKER).write_text("Katalog runu skilla verify-*; sprzątanie skilla go usuwa.\n", encoding="utf-8")
    return root


def require_run_root(root: Path) -> Path:
    if not (root / MARKER).is_file():
        raise RunRootError(f"{root} nie ma znacznika {MARKER}: nie założyła go fixture skilla")
    return root


def remove_run_root(root: Path) -> None:
    if root.exists():
        shutil.rmtree(require_run_root(root))

"""Przesuwa gałąź `stabilna` na commit `main`, którego CI przeszło (ADR 0014): tylko do przodu, bez force.

Uruchamia go workflow ``.github/workflows/stabilna.yml`` po zielonym runie CI na pushu do `main`.
Każde uruchomienie wylicza wynik ze stanu ``origin``, więc powtórzone albo spóźnione (run CI starszego
commitu kończy się po nowszym) niczego nie cofa:

- `stabilna` już zawiera commit: nic się nie zmienia;
- `stabilna` nie istnieje albo jest przodkiem commitu: push bez force; gdy ktoś przesunie ją w
  międzyczasie, Git odrzuca push, a skrypt liczy od nowa;
- commit albo `stabilna` spoza `main`, albo `stabilna`, która nie jest przodkiem commitu: kod 1, `stabilna` bez
  zmian.

    python3 tools/promuj_stabilna.py <commit> [--remote origin]
"""

from __future__ import annotations

import argparse
from collections.abc import Sequence
from pathlib import Path
import subprocess
import sys

import potomne

MAIN = "main"
STABLE = "stabilna"
ATTEMPTS = 3
TIMEOUT_S = 120
# Własna przestrzeń refów: skrypt nie rusza gałęzi checkoutu, w którym biegnie.
_FETCHED_MAIN = "refs/promuj-stabilna/main"
_FETCHED_STABLE = "refs/promuj-stabilna/stabilna"


class Refused(Exception):
    """`stabilna` zostaje bez zmian, bo przesunięcie nie byłoby do przodu po `main`; ``str()`` mówi czemu."""


def promote(repo: Path, commit: str, remote: str = "origin") -> str:
    """Przesuwa `stabilna` w ``remote`` na ``commit`` z `main`; zwraca linię wyniku, ``Refused`` przy odmowie."""

    rejected = ""
    for _ in range(ATTEMPTS):
        stable = _fetch(repo, remote)
        if not _is_ancestor(repo, commit, _FETCHED_MAIN):
            raise Refused(f"{commit} nie jest na {MAIN}")
        if stable is not None and not _is_ancestor(repo, stable, _FETCHED_MAIN):
            raise Refused(f"{STABLE} {stable} nie jest na {MAIN}")
        if stable is not None and _is_ancestor(repo, commit, stable):
            return f"STABILNA JUŻ ZAWIERA {commit} ({STABLE} = {stable})"
        if stable is not None and not _is_ancestor(repo, stable, commit):
            raise Refused(f"{STABLE} {stable} nie jest przodkiem {commit}")
        pushed = _git(repo, "push", "--quiet", remote, f"{commit}:refs/heads/{STABLE}")
        if pushed.returncode == 0:
            return f"STABILNA PRZESUNIĘTA {stable or '-'} -> {commit}"
        rejected = pushed.stderr.strip()
    raise Refused(f"push na {STABLE} odrzucony {ATTEMPTS} razy: {rejected}")


def _fetch(repo: Path, remote: str) -> str | None:
    """Pobiera `main` i `stabilna` z ``remote``; commit `stabilna` albo ``None``, gdy jej tam nie ma."""

    listed = _git(repo, "ls-remote", "--exit-code", remote, f"refs/heads/{STABLE}")
    if listed.returncode not in (0, 2):
        raise RuntimeError(f"git ls-remote: {listed.stderr.strip()}")
    exists = listed.returncode == 0
    refspecs = [f"+refs/heads/{MAIN}:{_FETCHED_MAIN}"]
    if exists:
        refspecs.append(f"+refs/heads/{STABLE}:{_FETCHED_STABLE}")
    _checked(repo, "fetch", "--quiet", "--no-tags", remote, *refspecs)
    return _checked(repo, "rev-parse", _FETCHED_STABLE).strip() if exists else None


def _is_ancestor(repo: Path, ancestor: str, descendant: str) -> bool:
    result = _git(repo, "merge-base", "--is-ancestor", ancestor, descendant)
    if result.returncode not in (0, 1):
        raise RuntimeError(f"git merge-base: {result.stderr.strip()}")
    return result.returncode == 0


def _checked(repo: Path, *args: str) -> str:
    result = _git(repo, *args)
    if result.returncode != 0:
        raise RuntimeError(f"git {args[0]}: {result.stderr.strip()}")
    return result.stdout


def _git(repo: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return potomne.run(["git", "-C", str(repo), *args], cwd=repo, timeout=TIMEOUT_S)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("commit", help="pełny SHA commitu `main`, którego CI przeszło")
    parser.add_argument("--remote", default="origin")
    args = parser.parse_args(argv)
    try:
        print(promote(Path.cwd(), args.commit, args.remote))
    except Refused as refused:
        print(f"STABILNA BEZ ZMIAN: {refused}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

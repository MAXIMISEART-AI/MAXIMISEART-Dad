"""Pokazuje, że test albo sprawdzenie pada na zepsutej wersji kodu (mutacji).

Każda mutacja dostaje własną kopię checkoutu: odłączony ``git worktree`` z HEAD w katalogu
tymczasowym z naniesionymi niezacommitowanymi zmianami (także dodanymi do indeksu), więc ``git``
działa w niej jak w checkoucie. Checkout zostaje nietknięty, więc nie ma czego przywracać ani
nieaktualnych ``.pyc``. Polecenie biegnie Pythonem, który uruchomił narzędzie, w korzeniu kopii,
z ``PYTHONPATH`` na ``src`` kopii: edytowalna instalacja ``.venv`` wskazuje ``src`` checkoutu.

Mutacja zmienia jedną albo kilka kotwic, każdą obecną w swoim pliku dokładnie raz; inaczej jest
NIEAKTUALNA. Zanim narzędzie zepsuje kod, polecenie musi przejść na kopii bez mutacji. Mutacja
jest WYKRYTA, gdy polecenie pada; PRZEKROCZONY CZAS (``--limit-s``) nie jest wykryciem. Mutacje
biegną po kolei, bo równoległe testy przekraczają swoje limity czasu; ``--rownolegle`` je zrównolegla.
Polecenia i kopie biegną przez ``tools/potomne.py``: procesy potomne polecenia giną z jego końcem, a
przekroczony czas, przerwanie (Ctrl-C) i zabicie narzędzia kończą polecenie i usuwają kopie.

    .venv/bin/python tools/mutacje.py --zmiana src/rozliczenia/x.py 'stary kod' 'nowy kod' \\
        -- -m pytest -q tests/test_x.py -k nazwa_testu
    .venv/bin/python tools/mutacje.py --plik mutacje.json -- -m pytest -q tests/test_x.py

Plik JSON to lista ``{"nazwa", "zmiany": [[plik, kotwica, zamiana], ...]}`` z opcjonalnym
``"polecenie"`` (argumenty Pythona), które zastępuje polecenie po ``--``. Skrypty
``check_<co>_mutations.py`` skilli ``verify-*`` używają tego samego silnika przez ``check_all``.
"""

from __future__ import annotations

import argparse
from collections.abc import Iterator, Sequence
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from dataclasses import dataclass
from functools import partial
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import threading

import potomne

ROOT = Path(__file__).resolve().parents[1]
TIMEOUT = 600


@dataclass(frozen=True)
class Edit:
    file: Path  # względem korzenia repozytorium
    anchor: str
    replacement: str

    def __post_init__(self) -> None:
        if self.file.anchor or ".." in self.file.parts:
            raise ValueError(f"plik mutacji musi leżeć w repozytorium, względem jego korzenia: {self.file}")


@dataclass(frozen=True)
class Mutation:
    name: str
    edits: tuple[Edit, ...]
    command: tuple[str, ...]  # argumenty Pythona, uruchamiane w korzeniu kopii
    harm: str = ""
    expected: str | None = None  # początek ostatniej linii wyjścia; None: polecenie kończy się błędem


def environment(copy: Path) -> dict[str, str]:
    return {
        **os.environ,
        "PYTHONPATH": os.pathsep.join([str(copy / "src"), os.environ.get("PYTHONPATH", "")]).rstrip(os.pathsep),
        "PYTHONDONTWRITEBYTECODE": "1",
        "PYTHONUTF8": "1",
    }


def _git(*arguments: str) -> bytes:
    return subprocess.run(["git", *arguments], cwd=ROOT, capture_output=True, check=True).stdout


@contextmanager
def checkout_copy() -> Iterator[Path]:
    changed = (
        _git("diff", "--name-only", "-z", "--no-renames", "HEAD") + _git("ls-files", "-z", "--others", "--exclude-standard")
    ).decode("utf-8")
    with potomne.commit_copy(ROOT, "HEAD") as copy:
        names = sorted(set(filter(None, changed.split("\0"))))
        present = [name for name in names if (ROOT / name).is_symlink() or (ROOT / name).is_file()]
        # Najpierw usunięcia: ścieżka, która zmieniła typ, zwalnia miejsce na plik albo katalog o tej nazwie.
        for name in sorted(set(names) - set(present)):
            _remove(copy, copy / name)
        for name in present:
            (copy / name).parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(ROOT / name, copy / name, follow_symlinks=False)
        imported = subprocess.run(
            [sys.executable, "-c", "import rozliczenia; print(rozliczenia.__file__)"],
            cwd=copy,
            env=environment(copy),
            capture_output=True,
            text=True,
            encoding="utf-8",
            check=True,
        ).stdout.strip()
        if not Path(imported).resolve().is_relative_to(copy.resolve()):
            raise RuntimeError(f"kopia importuje rozliczenia z {imported}, nie ze swojego src")
        yield copy


def _remove(copy: Path, path: Path) -> None:
    """Usuwa plik kopii i katalogi, które przez to zostały puste, jak ``git rm``."""

    path.unlink(missing_ok=True)
    for parent in path.parents:
        if parent == copy or any(parent.iterdir()):
            break
        parent.rmdir()


def _apply(copy: Path, edits: Sequence[Edit]) -> str | None:
    """Zmienia kod kopii; zwraca opis kotwicy, której nie ma dokładnie raz."""

    for edit in edits:
        path = copy / edit.file
        code = path.read_text(encoding="utf-8") if path.is_file() else ""
        if code.count(edit.anchor) != 1:
            return f"kotwicy nie ma dokładnie raz w {edit.file.as_posix()}: {edit.anchor.strip()[:60]!r}"
        path.write_text(code.replace(edit.anchor, edit.replacement), encoding="utf-8")
    return None


def _run(copy: Path, command: Sequence[str], limit_s: float, stop: threading.Event | None = None) -> tuple[int | None, str]:
    """Uruchamia polecenie w kopii; zwraca kod wyjścia (None po przekroczeniu czasu) i ostatnią linię."""

    try:
        done = potomne.run([sys.executable, *command], cwd=copy, env=environment(copy), timeout=limit_s, stop=stop)
    except subprocess.TimeoutExpired:
        return None, f"brak wyniku po {limit_s:g} s"
    lines = (done.stdout.strip() or done.stderr.strip()).splitlines()
    return done.returncode, lines[-1] if lines else f"kod wyjścia {done.returncode}"


def _verdict(mutation: Mutation, *, limit_s: float, stop: threading.Event) -> tuple[str, str]:
    with checkout_copy() as copy:
        stale = _apply(copy, mutation.edits)
        if stale:
            return "NIEAKTUALNA", stale
        code, last = _run(copy, mutation.command, limit_s, stop)
    if code is None:
        return "PRZEKROCZONY CZAS", last
    caught = last.startswith(mutation.expected) if mutation.expected is not None else code != 0
    return ("WYKRYTA" if caught else "NIEWYKRYTA"), last


def _baseline(baseline: set[tuple[str, ...]], limit_s: float) -> list[str]:
    """Polecenia, które padają już bez mutacji, z ostatnią linią wyjścia."""

    red = []
    with checkout_copy() as copy:
        for command in sorted(baseline):
            code, last = _run(copy, command, limit_s)
            if code != 0:
                red.append(f"{' '.join(command)} → {last}")
    return red


def check_all(mutations: Sequence[Mutation], *, parallel: bool = True, baseline: bool = False, limit_s: float = TIMEOUT) -> int:
    if baseline:
        red = _baseline({mutation.command for mutation in mutations if mutation.expected is None}, limit_s)
        for line in red:
            print(f"PODSTAWA CZERWONA: {line}", flush=True)
        if red:
            print("MUTACJE: polecenie pada bez mutacji, więc porażka po mutacji niczego nie dowodzi")
            return 2
    stop = threading.Event()
    pool = ThreadPoolExecutor(max_workers=None if parallel else 1)
    try:
        verdicts = list(pool.map(partial(_verdict, limit_s=limit_s, stop=stop), mutations))
    except BaseException:
        # Przerwanie w głównym wątku nie dociera do wątków, które czekają na swoje polecenia.
        stop.set()
        raise
    finally:
        pool.shutdown(cancel_futures=True)
    failures = 0
    for mutation, (verdict, last) in zip(mutations, verdicts, strict=True):
        failures += verdict != "WYKRYTA"
        harm = f" ({mutation.harm})" if mutation.harm else ""
        print(f"{verdict}: {mutation.name}{harm} → {last}", flush=True)
    print("MUTACJE OK" if not failures else f"MUTACJE: {failures} bez oczekiwanego wyniku")
    return 1 if failures else 0


def _from_file(path: Path, command: tuple[str, ...]) -> list[Mutation]:
    entries = json.loads(path.read_text(encoding="utf-8"))
    return [
        Mutation(
            name=entry["nazwa"],
            edits=tuple(Edit(Path(file), anchor, replacement) for file, anchor, replacement in entry["zmiany"]),
            command=tuple(entry.get("polecenie", command)),
        )
        for entry in entries
    ]


def main(argv: list[str] | None = None) -> int:
    arguments = sys.argv[1:] if argv is None else argv
    split = arguments.index("--") if "--" in arguments else len(arguments)
    command = tuple(arguments[split + 1 :])
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument(
        "--zmiana",
        nargs=3,
        action="append",
        default=[],
        metavar=("PLIK", "KOTWICA", "ZAMIANA"),
        help="Jedna zmiana mutacji; powtórz dla mutacji w kilku miejscach.",
    )
    parser.add_argument("--nazwa", default="mutacja", help="Nazwa mutacji z --zmiana w raporcie.")
    parser.add_argument("--plik", type=Path, help="Plik JSON z listą mutacji.")
    parser.add_argument("--rownolegle", action="store_true", help="Mutacje naraz, każda w swojej kopii.")
    parser.add_argument("--limit-s", type=float, default=TIMEOUT, help="Limit czasu jednego polecenia w sekundach.")
    args = parser.parse_args(arguments[:split])
    try:
        mutations = _from_file(args.plik, command) if args.plik else []
        if args.zmiana:
            edits = tuple(Edit(Path(file), anchor, replacement) for file, anchor, replacement in args.zmiana)
            mutations.append(Mutation(args.nazwa, edits, command))
    except ValueError as error:
        parser.error(str(error))
    if not mutations or not all(mutation.command for mutation in mutations):
        parser.error("podaj mutację (--zmiana albo --plik) i polecenie po --, np. -- -m pytest -q tests/test_x.py")
    return check_all(mutations, parallel=args.rownolegle, baseline=True, limit_s=args.limit_s)


if __name__ == "__main__":
    raise SystemExit(main())

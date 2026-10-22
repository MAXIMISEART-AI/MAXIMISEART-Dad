"""Pokazuje, że test albo sprawdzenie pada na zepsutej wersji kodu (mutacji).

Każda mutacja dostaje własną kopię checkoutu: odłączony ``git worktree`` z HEAD w katalogu
tymczasowym z naniesionymi niezacommitowanymi zmianami (także dodanymi do indeksu), więc ``git``
działa w niej jak w checkoucie. Checkout zostaje nietknięty, więc nie ma czego przywracać ani
nieaktualnych ``.pyc``. Polecenie biegnie Pythonem, który uruchomił narzędzie, w korzeniu kopii,
z ``PYTHONPATH`` na ``src`` kopii: edytowalna instalacja ``.venv`` wskazuje ``src`` checkoutu.

Mutacja zmienia jedną albo kilka kotwic, każdą obecną w swoim pliku dokładnie raz; inaczej jest
NIEAKTUALNA. Zanim narzędzie zepsuje kod, polecenie musi przejść na kopii bez mutacji. Mutacja
jest WYKRYTA, gdy polecenie pada; PRZEKROCZONY CZAS nie jest wykryciem. Mutacje biegną po kolei,
bo równoległe testy przekraczają swoje limity czasu; ``--rownolegle`` je zrównolegla. Przekroczony
czas i przerwanie (Ctrl-C albo SIGINT do samego narzędzia) zabijają polecenie razem z jego procesami
potomnymi, a kopie są usuwane. Po zabiciu samego narzędzia (SIGKILL) robi to za nie sprzątacz.

    .venv/bin/python tools/mutacje.py --zmiana src/rozliczenia/x.py 'stary kod' 'nowy kod' \\
        -- -m pytest -q tests/test_x.py -k nazwa_testu
    .venv/bin/python tools/mutacje.py --plik mutacje.json -- -m pytest -q tests/test_x.py

Plik JSON to lista ``{"nazwa", "zmiany": [[plik, kotwica, zamiana], ...]}`` z opcjonalnym
``"polecenie"`` (argumenty Pythona), które zastępuje polecenie po ``--``. Skrypty
``check_<co>_mutations.py`` skilli ``verify-*`` używają tego samego silnika przez ``check_all``.
"""

from __future__ import annotations

import argparse
from collections.abc import Callable, Iterator, Sequence
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from dataclasses import dataclass
from functools import partial
import json
import os
from pathlib import Path
import shutil
import signal
import subprocess
import sys
import tempfile
import threading

ROOT = Path(__file__).resolve().parents[1]
TIMEOUT = 600
# Sprzątacz w osobnej sesji przeżywa narzędzie zabite bez sprzątania, np. SIGKILL od tools/mutacje_skilli.py, którego
# zabiła brama pre-push. Polecenia mutacji biegną we własnych sesjach, więc zabicie grupy narzędzia ich nie sięga.
# Gdy potok od narzędzia zamknie się bez linii ``koniec``, sprzątacz zabija zgłoszone polecenia i usuwa zgłoszone kopie.
JANITOR = r"""import os, shutil, signal, subprocess, sys
live = set()
for line in sys.stdin:
    if line == "koniec\n":
        sys.exit()
    (live.add if line[0] == "+" else live.discard)(tuple(line[1:].rstrip("\n").split(" ", 1)))
for kind, value in live:
    if kind == "polecenie" and sys.platform == "win32":
        subprocess.run(["taskkill", "/F", "/T", "/PID", value], capture_output=True)
    elif kind == "polecenie":
        try:
            os.killpg(int(value), signal.SIGKILL)
        except OSError:
            pass
for kind, value in live:
    if kind == "kopia":
        subprocess.run(["git", "worktree", "remove", "--force", os.path.join(value, "kopia")], cwd=sys.argv[1], capture_output=True)
        shutil.rmtree(value, ignore_errors=True)
subprocess.run(["git", "worktree", "prune"], cwd=sys.argv[1], capture_output=True)
"""


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
def checkout_copy(report: Callable[[str], None]) -> Iterator[Path]:
    changed = (
        _git("diff", "--name-only", "-z", "--no-renames", "HEAD") + _git("ls-files", "-z", "--others", "--exclude-standard")
    ).decode("utf-8")
    with tempfile.TemporaryDirectory(prefix="mutacja-", ignore_cleanup_errors=True) as scratch:
        report(f"+kopia {scratch}")
        copy = Path(scratch) / "kopia"
        _git("worktree", "add", "--quiet", "--detach", str(copy), "HEAD")
        try:
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
        finally:
            # Bez check: proces, który przeżył polecenie, może trzymać pliki kopii, a wynik mutacji już jest.
            subprocess.run(["git", "worktree", "remove", "--force", str(copy)], cwd=ROOT, capture_output=True, check=False)
    _git("worktree", "prune")
    report(f"-kopia {scratch}")


def _remove(copy: Path, path: Path) -> None:
    """Usuwa plik kopii i katalogi, które przez to zostały puste, jak ``git rm``."""

    path.unlink(missing_ok=True)
    for parent in path.parents:
        if parent == copy or any(parent.iterdir()):
            break
        parent.rmdir()


class _Commands:
    """Trwające polecenia mutacji; ``stop`` zabija je razem z ich procesami potomnymi i nie wpuszcza nowych.

    Polecenia i kopie zgłasza sprzątaczowi ``JANITOR``; koniec bloku ``with`` po własnym sprzątaniu go zwalnia.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._running: set[subprocess.Popen[str]] = set()
        self._stopped = False
        self._reporting = threading.Lock()
        self._janitor = subprocess.Popen(
            [sys.executable, "-c", JANITOR, str(ROOT)],
            env={**os.environ, "PYTHONUTF8": "1"},
            stdin=subprocess.PIPE,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            text=True,
            encoding="utf-8",
            start_new_session=sys.platform != "win32",
        )

    def report(self, line: str) -> None:
        assert self._janitor.stdin is not None
        with self._reporting:
            self._janitor.stdin.write(f"{line}\n")
            self._janitor.stdin.flush()

    def __enter__(self) -> _Commands:
        return self

    def __exit__(self, *_: object) -> None:
        self.report("koniec")
        assert self._janitor.stdin is not None
        self._janitor.stdin.close()
        self._janitor.wait()

    @contextmanager
    def run(self, command: Sequence[str], copy: Path) -> Iterator[subprocess.Popen[str]]:
        """Polecenie w kopii; nie przeżywa bloku ``with``, także po przekroczeniu czasu i przerwaniu."""

        with self._lock:
            if self._stopped:
                raise _Stopped
            process = subprocess.Popen(
                command,
                cwd=copy,
                env=environment(copy),
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding="utf-8",
                errors="replace",
                start_new_session=sys.platform != "win32",
            )
            self._running.add(process)
            self.report(f"+polecenie {process.pid}")
        with process:
            try:
                yield process
            finally:
                _kill_tree(process)
                self.report(f"-polecenie {process.pid}")
                process.wait()
                with self._lock:
                    self._running.discard(process)

    def stop(self) -> None:
        with self._lock:
            self._stopped = True
            running = list(self._running)
        for process in running:
            _kill_tree(process)


class _Stopped(Exception):
    """Mutacja nie uruchomiła polecenia, bo przebieg został przerwany."""


def _kill_tree(process: subprocess.Popen[str]) -> None:
    """Zabija trwające polecenie z jego potomkami: w Windows ``taskkill /T``, gdzie indziej całą jego sesję."""

    if process.poll() is not None:
        return
    if sys.platform == "win32":
        subprocess.run(["taskkill", "/F", "/T", "/PID", str(process.pid)], capture_output=True, timeout=30, check=False)
    else:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except OSError:
            pass  # sesja już się skończyła
    process.kill()


def _apply(copy: Path, edits: Sequence[Edit]) -> str | None:
    """Zmienia kod kopii; zwraca opis kotwicy, której nie ma dokładnie raz."""

    for edit in edits:
        path = copy / edit.file
        code = path.read_text(encoding="utf-8") if path.is_file() else ""
        if code.count(edit.anchor) != 1:
            return f"kotwicy nie ma dokładnie raz w {edit.file.as_posix()}: {edit.anchor.strip()[:60]!r}"
        path.write_text(code.replace(edit.anchor, edit.replacement), encoding="utf-8")
    return None


def _run(commands: _Commands, copy: Path, command: Sequence[str]) -> tuple[int | None, str]:
    """Uruchamia polecenie w kopii; zwraca kod wyjścia (None po przekroczeniu czasu) i ostatnią linię."""

    with commands.run([sys.executable, *command], copy) as process:
        try:
            stdout, stderr = process.communicate(timeout=TIMEOUT)
        except subprocess.TimeoutExpired:
            return None, f"brak wyniku po {TIMEOUT} s"
    lines = (stdout.strip() or stderr.strip()).splitlines()
    return process.returncode, lines[-1] if lines else f"kod wyjścia {process.returncode}"


def _verdict(commands: _Commands, mutation: Mutation) -> tuple[str, str]:
    with checkout_copy(commands.report) as copy:
        stale = _apply(copy, mutation.edits)
        if stale:
            return "NIEAKTUALNA", stale
        code, last = _run(commands, copy, mutation.command)
    if code is None:
        return "PRZEKROCZONY CZAS", last
    caught = last.startswith(mutation.expected) if mutation.expected is not None else code != 0
    return ("WYKRYTA" if caught else "NIEWYKRYTA"), last


def _baseline(commands: _Commands, baseline: set[tuple[str, ...]]) -> list[str]:
    """Polecenia, które padają już bez mutacji, z ostatnią linią wyjścia."""

    red = []
    with checkout_copy(commands.report) as copy:
        for command in sorted(baseline):
            code, last = _run(commands, copy, command)
            if code != 0:
                red.append(f"{' '.join(command)} → {last}")
    return red


def check_all(mutations: Sequence[Mutation], *, parallel: bool = True, baseline: bool = False) -> int:
    with _Commands() as commands:
        if baseline:
            red = _baseline(commands, {mutation.command for mutation in mutations if mutation.expected is None})
            for line in red:
                print(f"PODSTAWA CZERWONA: {line}", flush=True)
            if red:
                print("MUTACJE: polecenie pada bez mutacji, więc porażka po mutacji niczego nie dowodzi")
                return 2
        pool = ThreadPoolExecutor(max_workers=None if parallel else 1)
        try:
            verdicts = list(pool.map(partial(_verdict, commands), mutations))
        except BaseException:
            # Przerwanie (np. SIGINT tylko do tego procesu) nie czeka, aż trwające mutacje dobiegną końca.
            commands.stop()
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
    return check_all(mutations, parallel=args.rownolegle, baseline=True)


if __name__ == "__main__":
    raise SystemExit(main())

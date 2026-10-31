"""Dowodzi, że test albo sprawdzenie pada na zepsutym kodzie (mutacji); użyj raz dla każdego testu dodanego albo zmienionego w zmianie.

Każda mutacja dostaje własną kopię checkoutu: odłączony ``git worktree`` z HEAD w katalogu
tymczasowym z naniesionymi niezacommitowanymi zmianami (także dodanymi do indeksu), więc ``git``
działa w niej jak w checkoucie. Checkout zostaje nietknięty, więc nie ma czego przywracać ani
nieaktualnych ``.pyc``. Polecenie biegnie Pythonem, który uruchomił narzędzie, w korzeniu kopii,
z ``PYTHONPATH`` na ``src`` kopii: edytowalna instalacja ``.venv`` wskazuje ``src`` checkoutu.

Mutacja zmienia jedną albo kilka kotwic, każdą obecną w swoim pliku dokładnie raz; inaczej jest
NIEAKTUALNA. Pusta kotwica w pliku, którego nie ma, tworzy go razem z katalogami. Zanim narzędzie
zepsuje kod, polecenie musi przejść na kopii bez mutacji, a jeśli mutacja oczekuje ostatniej
linii wyjścia, polecenie bez mutacji nie może się nią kończyć. Mutacja jest WYKRYTA, gdy polecenie
pada albo kończy się oczekiwaną linią; PRZEKROCZONY CZAS (``--limit-s``) nie jest wykryciem. Mutacja, która nie
zdąży zacząć się albo skończyć przed końcem czasu wywołującego (``deadline`` w ``verdicts``), dostaje BEZ WERDYKTU.
Mutacje biegną po kolei, bo równoległe testy przekraczają swoje limity czasu; ``--rownolegle`` puszcza
naraz najwyżej ``PARALLEL``, a ich polecenia dostają ``PYTEST_XDIST_AUTO_NUM_WORKERS=1`` (chyba że wywołujący je
ustawił), bo gołe ``pytest -n auto`` w teście każdej z nich bierze wszystkie rdzenie komputera.
Polecenia i kopie biegną przez ``tools/lib/potomne.py``: procesy potomne polecenia giną z jego końcem, a
przekroczony czas, przerwanie (Ctrl-C) i zabicie narzędzia kończą polecenie i usuwają kopie.

    .venv/bin/python tools/mutacje.py --zmiana src/rozliczenia/x.py 'stary kod' 'nowy kod' \\
        -- -m pytest -q tests/test_x.py -k nazwa_testu
    .venv/bin/python tools/mutacje.py --plik mutacje.json -- -m pytest -q tests/test_x.py

Plik JSON to lista ``{"nazwa", "zmiany": [[plik, kotwica, zamiana], ...]}`` z opcjonalnym
``"polecenie"`` (argumenty Pythona), które zastępuje polecenie po ``--``, i opcjonalnym
``"oczekiwane"``, początkiem ostatniej linii wyjścia, który wykrywa mutację zamiast kodu wyjścia.
Lista dłuższa niż ``ciezkie_ci.TARGETED`` mutacji to ręczne ``change-mutations``: poza CI narzędzie odmawia
jej startu (kod 2 i linia ``CIĘŻKIE CI ODMOWA``) na zasadach ``tools/lib/ciezkie_ci.py``. Skrypty
``check_<co>_mutations.py`` skilli ``verify-*`` używają tego samego silnika przez ``check_all``, który
takiego limitu nie ma.

Z ``MUTACJE_CZESC=K/N`` w środowisku ``check_all`` sprawdza tylko K-tą z N części tabeli: mutacje w kolejności nazw,
co N-tą od K-tej, więc część nie zależy od kolejności tabeli, a N części sprawdza każdą mutację dokładnie raz. Podstawa
części to tylko polecenia jej mutacji, a część bez mutacji kończy się ``MUTACJE OK``. Tak plan CI
(``tools/plan_ci.py``) dzieli długi skrypt mutacji skilla na zadania bez zmiany skryptu.
"""

from __future__ import annotations

import argparse
from collections import defaultdict
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
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools/lib"))

import ciezkie_ci
import potomne

ROOT = Path(__file__).resolve().parents[1]
TIMEOUT = 600
# Tyle mutacji naraz dawał ThreadPoolExecutor (rdzenie + 4) na 4 vCPU runnera CI; na 16 rdzeniach Maca dawał 20.
PARALLEL = 8
PART = "MUTACJE_CZESC"
NO_VERDICT = "BEZ WERDYKTU"


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


def environment(copy: Path, *, concurrent: bool = False) -> dict[str, str]:
    nested = {"PYTEST_XDIST_AUTO_NUM_WORKERS": "1"} if concurrent else {}
    # Część dzieli tabelę tego skryptu, nie tabele, które sprawdzane polecenie samo uruchamia.
    inherited = {name: value for name, value in os.environ.items() if name != PART}
    return {
        **nested,
        **inherited,
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
        found = potomne.run(
            [sys.executable, "-c", "import rozliczenia; print(rozliczenia.__file__)"], cwd=copy, env=environment(copy)
        )
        found.check_returncode()
        imported = found.stdout.strip()
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
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(code.replace(edit.anchor, edit.replacement), encoding="utf-8")
    return None


def _run(
    copy: Path, command: Sequence[str], limit_s: float, stop: threading.Event | None = None, *, concurrent: bool = False
) -> tuple[int | None, str]:
    """Uruchamia polecenie w kopii; zwraca kod wyjścia (None po przekroczeniu czasu) i ostatnią linię."""

    try:
        env = environment(copy, concurrent=concurrent)
        done = potomne.run([sys.executable, *command], cwd=copy, env=env, timeout=limit_s, stop=stop)
    except subprocess.TimeoutExpired:
        return None, f"brak wyniku po {limit_s:g} s"
    lines = (done.stdout.strip() or done.stderr.strip()).splitlines()
    return done.returncode, lines[-1] if lines else f"kod wyjścia {done.returncode}"


def _verdict(mutation: Mutation, *, limit_s: float, stop: threading.Event, concurrent: bool, deadline: float | None) -> tuple[str, str]:
    left = limit_s if deadline is None else deadline - time.monotonic()
    if left <= 0:
        return NO_VERDICT, "czas minął, zanim się zaczęła"
    with checkout_copy() as copy:
        stale = _apply(copy, mutation.edits)
        if stale:
            return "NIEAKTUALNA", stale
        code, last = _run(copy, mutation.command, min(limit_s, left), stop, concurrent=concurrent)
    if code is None:
        # Polecenie przerwał koniec czasu wywołującego, a nie jego własny limit, więc nie wiadomo, czy mutacja je zawiesza.
        return ("PRZEKROCZONY CZAS" if left >= limit_s else NO_VERDICT), last
    caught = last.startswith(mutation.expected) if mutation.expected is not None else code != 0
    return ("WYKRYTA" if caught else "NIEWYKRYTA"), last


def _baseline(mutations: Sequence[Mutation], limit_s: float) -> list[str]:
    """Polecenia, które bez mutacji padają albo kończą się linią oczekiwaną po mutacji, z ostatnią linią wyjścia."""

    expected: dict[tuple[str, ...], set[str]] = defaultdict(set)
    for mutation in mutations:
        expected[mutation.command] |= set() if mutation.expected is None else {mutation.expected}
    red = []
    with checkout_copy() as copy:
        for command in sorted(expected):
            code, last = _run(copy, command, limit_s)
            if code != 0 or any(last.startswith(line) for line in expected[command]):
                red.append(f"{' '.join(command)} → {last}")
    return red


def verdicts(
    mutations: Sequence[Mutation], *, workers: int, limit_s: float = TIMEOUT, deadline: float | None = None
) -> Iterator[tuple[str, str]]:
    """Werdykt i ostatnia linia wyjścia każdej mutacji po kolei, bez sprawdzenia podstawy; ``workers`` mutacji naraz.

    Z ``deadline`` (chwila ``time.monotonic()``) żadne polecenie nie biegnie dłużej niż do niej.
    """

    stop = threading.Event()
    pool = ThreadPoolExecutor(max_workers=workers)
    try:
        yield from pool.map(partial(_verdict, limit_s=limit_s, stop=stop, concurrent=workers > 1, deadline=deadline), mutations)
    except BaseException:
        # Przerwanie w głównym wątku nie dociera do wątków, które czekają na swoje polecenia.
        stop.set()
        raise
    finally:
        pool.shutdown(cancel_futures=True)


def _part(mutations: Sequence[Mutation], part: str) -> list[Mutation]:
    """Mutacje części ``K/N`` w kolejności tabeli; zła postać to ``ValueError`` z nazwą zmiennej."""

    number, _, count = part.partition("/")
    if not (number.isdigit() and count.isdigit() and 1 <= int(number) <= int(count)):
        raise ValueError(f"{PART} to K/N z 1 <= K <= N, nie {part!r}")
    by_name = sorted(range(len(mutations)), key=lambda index: (mutations[index].name, repr(mutations[index])))
    chosen = set(by_name[int(number) - 1 :: int(count)])
    return [mutation for index, mutation in enumerate(mutations) if index in chosen]


def check_all(mutations: Sequence[Mutation], *, parallel: bool = True, limit_s: float = TIMEOUT) -> int:
    if not mutations:
        print("MUTACJE: brak mutacji, więc nie ma czego dowieść")
        return 1
    if part := os.environ.get(PART):
        total = len(mutations)
        mutations = _part(mutations, part)
        print(f"MUTACJE CZĘŚĆ {part}: {len(mutations)} z {total} mutacji", flush=True)
        if not mutations:
            print("MUTACJE OK")
            return 0
    red = _baseline(mutations, limit_s)
    for line in red:
        print(f"PODSTAWA CZERWONA: {line}", flush=True)
    if red:
        print("MUTACJE: polecenie bez mutacji pada albo daje wynik mutacji, więc wynik po mutacji niczego nie dowodzi")
        return 2
    failures = 0
    found = list(verdicts(mutations, workers=PARALLEL if parallel else 1, limit_s=limit_s))
    for mutation, (verdict, last) in zip(mutations, found, strict=True):
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
            expected=entry.get("oczekiwane"),
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
    ciezkie_ci.argument(parser)
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
    if refused := ciezkie_ci.mutations_refusal(len(mutations), args.odtwarzam, root=ROOT):
        print(refused)
        return 2
    return check_all(mutations, parallel=args.rownolegle, limit_s=args.limit_s)


if __name__ == "__main__":
    raise SystemExit(main())

"""Dowodzi, że test albo sprawdzenie pada na zepsutym kodzie (mutacji); użyj raz dla każdego testu dodanego albo zmienionego w zmianie.

Każda mutacja dostaje własną kopię checkoutu: odłączony ``git worktree`` z HEAD w katalogu
tymczasowym z naniesionymi niezacommitowanymi zmianami (także dodanymi do indeksu), więc ``git``
działa w niej jak w checkoucie. Checkout zostaje nietknięty, więc nie ma czego przywracać ani
nieaktualnych ``.pyc``. Polecenie biegnie Pythonem, który uruchomił narzędzie, w korzeniu kopii,
z ``PYTHONPATH`` na ``src`` kopii: edytowalna instalacja ``.venv`` wskazuje ``src`` checkoutu.

Mutacja zmienia jedną albo kilka kotwic, każdą obecną w swoim pliku dokładnie raz; inaczej jest
NIEAKTUALNA. Pusta kotwica w pliku, którego nie ma, tworzy go razem z katalogami. Zanim narzędzie
zepsuje kod, polecenie musi przejść na kopii bez mutacji, a jeśli mutacja oczekuje ostatniej
linii wyjścia, polecenie bez mutacji nie może się nią kończyć. Werdykty to ``Verdict``, a dowodem jest tylko
WYKRYTA: polecenie pada albo kończy się oczekiwaną linią. ZAWIESZENIE to polecenie bez wyniku w ``--limit-s`` albo
test, który pytest-timeout skończył po swoim limicie (linia ``Failed: Timeout (>…s) from pytest-timeout.`` metody ``signal``
albo linia ``+++ Timeout +++`` metody ``thread`` bez xdist); worker xdist, którego zabiła metoda ``thread`` (Windows),
nie zostawia takiej linii, więc tam ZAWIESZENIE widać tylko po ``--limit-s``. Mutacja, która nie zdąży zacząć się
albo skończyć przed końcem czasu wywołującego (``deadline`` w ``verdicts``), dostaje BEZ WERDYKTU.

Narzędzie z wiersza poleceń uruchamia każdą mutację NIEWYKRYTA na HEAD także na merge-base HEAD z ``--baza`` (bez
niezacommitowanych zmian), z podstawą jej polecenia na merge-base. Gdy tam jest WYKRYTA, dostaje REGRES: zmiana
osłabiła test, który ją łapał. Z ``--jak-ci`` polecenie każdej mutacji to ``pytest -n 1`` z plikami zadań pytest, w
których plan CI pull requestu (``tools/plan_ci.py plan --baza``) stawia pliki testów zmienione od merge-base, na torze
systemu, na którym biegnie narzędzie. Jeden worker dzieli proces z sąsiadami z zadania, jak w CI, a plik, który plan
dzieli na udziały, biegnie cały.
Mutacje biegną po kolei, bo równoległe testy przekraczają swoje limity czasu; ``--rownolegle`` puszcza
naraz najwyżej ``PARALLEL``, a ich polecenia dostają ``PYTEST_XDIST_AUTO_NUM_WORKERS=1`` (chyba że wywołujący je
ustawił), bo gołe ``pytest -n auto`` w teście każdej z nich bierze wszystkie rdzenie komputera.
Polecenia i kopie biegną przez ``tools/lib/potomne.py``: procesy potomne polecenia giną z jego końcem, a
przekroczony czas, przerwanie (Ctrl-C) i zabicie narzędzia kończą polecenie i usuwają kopie.

    .venv/bin/python tools/mutacje.py --zmiana src/rozliczenia/x.py 'stary kod' 'nowy kod' \\
        -- -m pytest -q tests/test_x.py -k nazwa_testu
    .venv/bin/python tools/mutacje.py --plik mutacje.json -- -m pytest -q tests/test_x.py
    .venv/bin/python tools/mutacje.py --jak-ci --zmiana src/rozliczenia/x.py 'stary kod' 'nowy kod'

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
from collections.abc import Collection, Iterable, Iterator, Sequence
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from dataclasses import dataclass, replace
from enum import StrEnum
from functools import partial
import importlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools/lib"))
# plan_ci i szybko importuje dopiero --jak-ci: plan_ci sam importuje ten moduł.
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))

import ciezkie_ci
import potomne

ROOT = Path(__file__).resolve().parents[1]
TIMEOUT = 600
# Tyle mutacji naraz dawał ThreadPoolExecutor (rdzenie + 4) na 4 vCPU runnera CI; na 16 rdzeniach Maca dawał 20.
PARALLEL = 8
PART = "MUTACJE_CZESC"
BASE = "origin/main"
# Linie, którymi pytest-timeout kończy test po limicie, w pytest_timeout.py 2.4: ``PYTEST_FAILURE_MESSAGE`` metody
# ``signal`` jako błąd testu (``E   Failed: …``) albo w krótkim podsumowaniu (``FAILED <test> - Failed: …``) i nagłówek
# zrzutu stosów metody ``thread`` (``terminal.sep("+", title="Timeout")``). Cała linia, bo ten sam tekst w cudzysłowie
# drukuje też asercja testu, który go sprawdza.
PYTEST_TIMEOUT = re.compile(r"(?:E\s+|FAILED \S+ - )?(?P<hang>Failed: Timeout \(>[0-9.]+s\) from pytest-timeout\.)|(?P<thread>\++ Timeout \++)")


class Verdict(StrEnum):
    """Werdykt mutacji; tylko WYKRYTA dowodzi, że polecenie łapie zepsuty kod."""

    CAUGHT = "WYKRYTA"  # polecenie pada albo kończy się oczekiwaną linią
    SURVIVED = "NIEWYKRYTA"  # polecenie przechodzi po mutacji
    REGRESSION = "REGRES"  # NIEWYKRYTA na HEAD, a WYKRYTA na merge-base: zmiana osłabiła test
    HANG = "ZAWIESZENIE"  # polecenie bez wyniku w swoim limicie albo test po limicie pytest-timeout
    STALE = "NIEAKTUALNA"  # kotwica nie występuje dokładnie raz
    NO_VERDICT = "BEZ WERDYKTU"  # koniec czasu wywołującego przed wynikiem


NO_VERDICT = Verdict.NO_VERDICT


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
def checkout_copy(commit: str | None = None) -> Iterator[Path]:
    """Kopia HEAD z niezacommitowanymi zmianami checkoutu albo, z ``commit``, kopia samego commitu."""

    changed = (
        b""
        if commit is not None
        else _git("diff", "--name-only", "-z", "--no-renames", "HEAD") + _git("ls-files", "-z", "--others", "--exclude-standard")
    ).decode("utf-8")
    with potomne.commit_copy(ROOT, commit or "HEAD") as copy:
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


@dataclass(frozen=True)
class _Ran:
    code: int | None  # None: polecenie przekroczyło limit
    last: str  # ostatnia linia wyjścia
    hang: str | None  # linia zawieszenia: własny limit albo pytest-timeout


def _run(
    copy: Path, command: Sequence[str], limit_s: float, stop: threading.Event | None = None, *, concurrent: bool = False
) -> _Ran:
    """Uruchamia polecenie w kopii; zwraca kod wyjścia, ostatnią linię i linię zawieszenia, jeśli było."""

    try:
        env = environment(copy, concurrent=concurrent)
        done = potomne.run([sys.executable, *command], cwd=copy, env=env, timeout=limit_s, stop=stop)
    except subprocess.TimeoutExpired:
        late = f"brak wyniku po {limit_s:g} s"
        return _Ran(None, late, late)
    lines = (done.stdout.strip() or done.stderr.strip()).splitlines()
    hangs = (PYTEST_TIMEOUT.fullmatch(line.strip()) for line in f"{done.stdout}\n{done.stderr}".splitlines())
    hang = next((found["hang"] or found["thread"] for found in hangs if found), None)
    return _Ran(done.returncode, lines[-1] if lines else f"kod wyjścia {done.returncode}", hang)


def _verdict(
    mutation: Mutation, *, limit_s: float, stop: threading.Event, concurrent: bool, deadline: float | None, commit: str | None
) -> tuple[Verdict, str]:
    left = limit_s if deadline is None else deadline - time.monotonic()
    if left <= 0:
        return Verdict.NO_VERDICT, "czas minął, zanim się zaczęła"
    with checkout_copy(commit) as copy:
        stale = _apply(copy, mutation.edits)
        if stale:
            return Verdict.STALE, stale
        ran = _run(copy, mutation.command, min(limit_s, left), stop, concurrent=concurrent)
    if ran.code is None and left < limit_s:
        # Polecenie przerwał koniec czasu wywołującego, a nie jego własny limit, więc nie wiadomo, czy mutacja je zawiesza.
        return Verdict.NO_VERDICT, ran.last
    if ran.hang is not None:
        return Verdict.HANG, ran.hang
    caught = ran.last.startswith(mutation.expected) if mutation.expected is not None else ran.code != 0
    return (Verdict.CAUGHT if caught else Verdict.SURVIVED), ran.last


def _baseline(mutations: Sequence[Mutation], limit_s: float, commit: str | None = None) -> dict[tuple[str, ...], str]:
    """Polecenia, które bez mutacji padają albo kończą się linią oczekiwaną po mutacji, z ostatnią linią wyjścia."""

    expected: dict[tuple[str, ...], set[str]] = defaultdict(set)
    for mutation in mutations:
        expected[mutation.command] |= set() if mutation.expected is None else {mutation.expected}
    red = {}
    with checkout_copy(commit) as copy:
        for command in sorted(expected):
            ran = _run(copy, command, limit_s)
            if ran.code != 0 or any(ran.last.startswith(line) for line in expected[command]):
                red[command] = ran.last
    return red


def verdicts(
    mutations: Sequence[Mutation],
    *,
    workers: int,
    limit_s: float = TIMEOUT,
    deadline: float | None = None,
    commit: str | None = None,
) -> Iterator[tuple[Verdict, str]]:
    """Werdykt i ostatnia linia wyjścia każdej mutacji po kolei, bez sprawdzenia podstawy; ``workers`` mutacji naraz.

    Z ``deadline`` (chwila ``time.monotonic()``) żadne polecenie nie biegnie dłużej niż do niej. Z ``commit`` mutacje
    biegną na kopii tego commitu bez niezacommitowanych zmian checkoutu.
    """

    stop = threading.Event()
    pool = ThreadPoolExecutor(max_workers=workers)
    try:
        run = partial(_verdict, limit_s=limit_s, stop=stop, concurrent=workers > 1, deadline=deadline, commit=commit)
        yield from pool.map(run, mutations)
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


def _against_base(
    mutations: Sequence[Mutation], found: Sequence[tuple[Verdict, str]], base: str, *, workers: int, limit_s: float
) -> list[tuple[Verdict, str]]:
    """Mutacje NIEWYKRYTA na HEAD, które na merge-base HEAD z ``base`` są WYKRYTA, jako REGRES.

    Mutacja, której merge-base nie rozstrzyga (podstawa czerwona, inny werdykt niż NIEWYKRYTA), zostaje NIEWYKRYTA z
    dopiskiem, co dał merge-base; ta, która tam też jest NIEWYKRYTA, zostaje bez zmian.
    """

    survived = [index for index, (verdict, _) in enumerate(found) if verdict is Verdict.SURVIVED]
    if not survived:
        return list(found)
    fork = subprocess.run(["git", "merge-base", "HEAD", base], cwd=ROOT, capture_output=True, text=True, encoding="utf-8", check=False)
    if fork.returncode:
        print(f"MERGE-BASE: brak merge-base HEAD z {base}, więc NIEWYKRYTA bez porównania ({fork.stderr.strip()})", flush=True)
        return list(found)
    commit = fork.stdout.strip()
    red = _baseline([mutations[index] for index in survived], limit_s, commit)
    compared = [index for index in survived if mutations[index].command not in red]
    there = verdicts([mutations[index] for index in compared], workers=workers, limit_s=limit_s, commit=commit)
    on_base = dict(zip(compared, there, strict=True))
    result = list(found)
    for index in survived:
        last, command = found[index][1], mutations[index].command
        if command in red:
            result[index] = (Verdict.SURVIVED, f"{last} (na merge-base {commit[:8]} podstawa czerwona: {red[command]})")
            continue
        verdict, base_last = on_base[index]
        if verdict is Verdict.CAUGHT:
            result[index] = (Verdict.REGRESSION, f"{last} ({verdict} na merge-base {commit[:8]}: {base_last})")
        elif verdict is not Verdict.SURVIVED:
            result[index] = (Verdict.SURVIVED, f"{last} (na merge-base {commit[:8]} {verdict}: {base_last})")
    return result


def check_all(mutations: Sequence[Mutation], *, parallel: bool = True, limit_s: float = TIMEOUT, base: str | None = None) -> int:
    """Podstawa i werdykt każdej mutacji; z ``base`` mutacja NIEWYKRYTA biegnie też na merge-base (REGRES)."""

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
    for command, last in red.items():
        print(f"PODSTAWA CZERWONA: {' '.join(command)} → {last}", flush=True)
    if red:
        print("MUTACJE: polecenie bez mutacji pada albo daje wynik mutacji, więc wynik po mutacji niczego nie dowodzi")
        return 2
    failures = 0
    workers = PARALLEL if parallel else 1
    found = list(verdicts(mutations, workers=workers, limit_s=limit_s))
    if base is not None:
        found = _against_base(mutations, found, base, workers=workers, limit_s=limit_s)
    for mutation, (verdict, last) in zip(mutations, found, strict=True):
        failures += verdict is not Verdict.CAUGHT
        harm = f" ({mutation.harm})" if mutation.harm else ""
        print(f"{verdict}: {mutation.name}{harm} → {last}", flush=True)
    print("MUTACJE OK" if not failures else f"MUTACJE: {failures} bez oczekiwanego wyniku")
    return 1 if failures else 0


def _from_file(path: Path, command: tuple[str, ...], *, own_command: bool = True) -> list[Mutation]:
    entries = json.loads(path.read_text(encoding="utf-8"))
    if not own_command and (named := [entry["nazwa"] for entry in entries if "polecenie" in entry]):
        raise ValueError(f"--jak-ci składa polecenie samo, a wpisy {', '.join(named)} mają własne")
    return [
        Mutation(
            name=entry["nazwa"],
            edits=tuple(Edit(Path(file), anchor, replacement) for file, anchor, replacement in entry["zmiany"]),
            command=tuple(entry.get("polecenie", command)),
            expected=entry.get("oczekiwane"),
        )
        for entry in entries
    ]


def ci_files(jobs: Iterable[tuple[str, Sequence[str]]], tracks: Collection[str], tested: Collection[str]) -> list[str]:
    """Pliki testów (i węzły ``plik::test``) zadań pytest (tor, jednostki) z ``tracks``, w których stoi plik z ``tested``.

    Kolejność jak w planie, bez powtórzeń; udział pliku ``#k/n`` to cały plik.
    """

    units = [[unit.removeprefix("pytest:").partition("#")[0] for unit in units if unit.startswith("pytest:")] for track, units in jobs if track in tracks]
    return list(dict.fromkeys(name for job in units if any(name.partition("::")[0] in tested for name in job) for name in job))


def _ci_command(base: str) -> tuple[str, ...]:
    """``pytest -n 1`` z plikami zadań pytest planu CI pull requestu, w których stoją testy zmienione od ``base``."""

    # Przez import_module: plan_ci importuje ten moduł, a kopie narzędzi w repozytoriach testów nie mają ani jego, ani szybko.
    plan_ci = importlib.import_module("plan_ci")
    szybko = importlib.import_module("szybko")
    with tempfile.TemporaryDirectory(prefix="plan-ci-") as folder:
        path = Path(folder) / "plan.json"
        # Bez GITHUB_OUTPUT: plan z narzędzia nie jest macierzą zadań runu.
        env = {name: value for name, value in os.environ.items() if name != "GITHUB_OUTPUT"}
        done = potomne.run([sys.executable, str(ROOT / "tools/plan_ci.py"), "plan", "--baza", base, "--wyjscie", str(path)], cwd=ROOT, env=env)
        if done.returncode:
            raise ValueError(f"tools/plan_ci.py plan --baza {base} padł: {(done.stderr.strip() or done.stdout.strip())[-300:]}")
        plan = plan_ci.Plan.z_json(path.read_text(encoding="utf-8"))
    jobs: list[tuple[str, tuple[str, ...]]] = [(job.tor, tuple(job.jednostki)) for job in plan.zadania]
    tracks: set[str] = {track.nazwa for track in plan_ci.TORY if track.os.startswith("windows") == (sys.platform == "win32")}
    tested: frozenset[str] = szybko.changed_since(base) & set(plan_ci.pliki_testow(ROOT))
    files = ci_files(jobs, tracks, tested)
    if not files:
        raise ValueError(f"zmiana od {base} nie zmienia pliku testów, który plan CI stawia w zadaniu pytest")
    return ("-m", "pytest", "-q", "-n", "1", "-p", "no:cacheprovider", *files)


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
    parser.add_argument("--baza", default=BASE, help=f"Gałąź, z której merge-base z HEAD daje REGRES i plan --jak-ci (domyślnie {BASE}).")
    parser.add_argument("--jak-ci", action="store_true", help="Polecenie z plików zadań pytest planu CI, w których stoją zmienione testy, bez polecenia po --.")
    ciezkie_ci.argument(parser)
    args = parser.parse_args(arguments[:split])
    if args.jak_ci and command:
        parser.error("--jak-ci składa polecenie samo, więc nie podawaj go po --")
    try:
        mutations = _from_file(args.plik, command, own_command=not args.jak_ci) if args.plik else []
        if args.zmiana:
            edits = tuple(Edit(Path(file), anchor, replacement) for file, anchor, replacement in args.zmiana)
            mutations.append(Mutation(args.nazwa, edits, command))
    except ValueError as error:
        parser.error(str(error))
    if not mutations or not (args.jak_ci or all(mutation.command for mutation in mutations)):
        parser.error("podaj mutację (--zmiana albo --plik) i polecenie po --, np. -- -m pytest -q tests/test_x.py, albo --jak-ci")
    if refused := ciezkie_ci.mutations_refusal(len(mutations), args.odtwarzam, root=ROOT):
        print(refused)
        return 2
    if args.jak_ci:
        try:
            ci = _ci_command(args.baza)
        except ValueError as error:
            parser.error(str(error))
        print(f"JAK CI: {' '.join(ci)}", flush=True)
        mutations = [replace(mutation, command=ci) for mutation in mutations]
    return check_all(mutations, parallel=args.rownolegle, limit_s=args.limit_s, base=args.baza)


if __name__ == "__main__":
    raise SystemExit(main())

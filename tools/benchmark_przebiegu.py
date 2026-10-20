"""Benchmark Przebiegu rozliczeń na lustrze folderów taty, bez danych klientów.

Użycie (z katalogu repozytorium):

    python tools/benchmark_przebiegu.py measure --scenario typowy-tydzien --machine mac-m4max
    python tools/benchmark_przebiegu.py comment [--before SHA] [--after SHA]
    python tools/benchmark_przebiegu.py guard --budget-ms MS [--summary PLIK]

Z syntetycznymi Wzorcami (bez Wzorców taty, jak w CI):

    python tools/syntetyczne_wzorce.py .benchmark/syntetyczne-wzorce
    python tools/benchmark_przebiegu.py measure --templates-dir .benchmark/syntetyczne-wzorce \\
        --config .benchmark/syntetyczne-wzorce/worker_mapping.yaml --machine mac-m4max-syntetyczne

``measure`` buduje lustro folderów taty (albo używa istniejącego), uruchamia na nim
Przebieg rozliczeń 3 razy jako osobny proces Pythona (``run.py --source``) i dopisuje
rekord pomiaru do dziennika JSONL w ``.benchmark/`` (poza gitem). ``comment`` drukuje
z dziennika komentarz Markdown do issue-dziennika wspinaczki (spec #141). ``guard`` to straż
czasu w CI: opisuje ostatni pomiar dziennika w Markdown i kończy się kodem 1 tylko wtedy, gdy
mediana czasu ściany przekracza budżet.

Lustro to ``Załączniki/Rozliczenia 2026/10_Październik_2026/INEA/06_12_10_2026`` z
Plikiem zbiorczym, który Przygotowanie pliku zbiorczego (``run_preparation.py``)
tworzy z deterministycznego, syntetycznego Rejestru zleceń. Wykonawcy pochodzą z
Konfiguracji wykonawców; adresy i numery są fikcyjne. Wzorce są brane z folderu
``--templates-dir`` pod nazwami, pod którymi leżą w ``config``; domyślnie z ``config``
tego checkoutu, a gdy ich tam nie ma (świeży worktree), z ``config`` głównego checkoutu.

Benchmark nie czyta ani nie zmienia Ustawień taty i nie dopisuje rekordów do historii
metryk w repozytorium. Na wyjście, do dziennika i do komentarza trafiają tylko liczby,
nazwy scenariuszy, commit i maszyna: nigdy Wykonawcy, adresy, numery zleceń ani wiersze.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import platform
import random
import shutil
import statistics
import subprocess
import sys
import tempfile
import time
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from openpyxl import Workbook

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from rozliczenia.period_folder import PeriodFolder, collective_file_name  # noqa: E402
from rozliczenia.settlement_period import parse_period_token  # noqa: E402
from rozliczenia.worker_config import WorkerConfigError, load_worker_mapping  # noqa: E402

RUNS = 3
DEFAULT_DIRECTORY = ROOT / ".benchmark"
WORKER_TEMPLATE = "Wzorzec rozliczenia pracownika.xlsx"
INTERNAL_TEMPLATE = "Wzorzec rozliczenia wewnętrznego.xlsx"
COLLECTIVE_TEMPLATE = "Wzorzec pliku zbiorczego.xlsx"
TEMPLATE_NAMES = (WORKER_TEMPLATE, INTERNAL_TEMPLATE, COLLECTIVE_TEMPLATE)

PERIOD = parse_period_token("06_12_10_2026")
MONTH_FOLDER = "10_Październik_2026"
REGISTER_NAME = "ZLECENIA INTERMAX OD 08_11_2021.xlsx"
# Zmiana sposobu generowania lustra zmienia jego odcisk, więc stare lustro nie zostanie użyte.
GENERATOR_VERSION = 1
SEED = 141
REGISTER_HEADERS = (
    "DATA GODZ. POCZ.",
    "MIASTO",
    "adres",
    "UMOWA",
    "URZĄDZENIA",
    "CZYNNOŚCI",
    "NUMER ZL.",
    "WYKONAWCA",
    "NUMER UMOWY",
    "SKUTECZNE",
    "CZYNNOŚCI ZREALIZOWANE",
)
CITIES = ("Miasto Syntetyczne", "Wieś Syntetyczna", "Osada Syntetyczna")
DEVICES = ("dekoder", "router", "terminal ONT")
ACTIVITIES = ("instalacja", "serwis", "demontaż")

# Cele wspinaczki na Macu (spec #141): mediana czasu ściany typowego tygodnia.
HARD_GOAL_MS = 18_000
AMBITIOUS_GOAL_MS = 6_000
TO_FILL = "_Do uzupełnienia._"


class BenchmarkError(Exception):
    """Pomiar nie może się odbyć; komunikat nie zawiera danych z lustra."""


@dataclass(frozen=True)
class Scenario:
    """Tydzień lustra: Zlecenia skuteczne, nieskuteczne i Wykonawcy z Konfiguracji bez wierszy."""

    successful_orders: int
    unsuccessful_orders: int
    workers_without_rows: int


SCENARIOS = {
    "typowy-tydzien": Scenario(successful_orders=500, unsuccessful_orders=50, workers_without_rows=2),
    # 2× najcięższego tygodnia w Rejestrze zleceń (592 zlecenia).
    "ciezki-tydzien": Scenario(successful_orders=1200, unsuccessful_orders=120, workers_without_rows=0),
    # Test dymny benchmarku: kilka zleceń, sekunda na uruchomienie.
    "maly-tydzien": Scenario(successful_orders=6, unsuccessful_orders=1, workers_without_rows=1),
}


# --- lustro -----------------------------------------------------------------------------------


def _main_checkout_config() -> Path | None:
    """``config/`` głównego checkoutu: worktree dzieli z nim katalog gita, ale nie Wzorce spoza gita."""

    try:
        common = subprocess.run(
            ["git", "rev-parse", "--git-common-dir"], cwd=ROOT, capture_output=True, text=True, check=True, timeout=10
        ).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return None
    return (ROOT / common).resolve().parent / "config"


def default_templates_directory() -> Path:
    """``config/`` tego checkoutu, gdy ma Wzorce, inaczej ``config/`` głównego checkoutu."""

    local = ROOT / "config"
    if (local / WORKER_TEMPLATE).is_file():
        return local
    main_config = _main_checkout_config()
    return main_config if main_config is not None and (main_config / WORKER_TEMPLATE).is_file() else local


def _templates(directory: Path) -> dict[str, Path]:
    paths = {name: directory / name for name in TEMPLATE_NAMES}
    missing = [name for name, path in paths.items() if not path.is_file()]
    if missing:
        raise BenchmarkError(f"Brak Wzorców w {directory}: {', '.join(missing)}. Wskaż folder przez --templates-dir.")
    return paths


def _worker_ids(config: Path) -> list[str]:
    try:
        return list(load_worker_mapping(config))
    except WorkerConfigError as error:
        raise BenchmarkError(f"Konfiguracja wykonawców {config} jest niepoprawna: {error.detail}") from None


def _fingerprint(scenario_name: str, config: Path, templates: Mapping[str, Path]) -> str:
    """Odcisk wejść lustra: inne Wzorce, Konfiguracja albo scenariusz dają inne lustro."""

    digest = hashlib.sha256(f"{GENERATOR_VERSION}|{SEED}|{scenario_name}|{SCENARIOS[scenario_name]}".encode())
    for path in (config, templates[INTERNAL_TEMPLATE], templates[COLLECTIVE_TEMPLATE]):
        digest.update(path.read_bytes())
    return digest.hexdigest()[:12]


def _period_directory(mirror: Path) -> Path:
    return mirror / "Załączniki" / f"Rozliczenia {PERIOD.monday.year}" / MONTH_FOLDER / "INEA" / PERIOD.token


def _register_rows(scenario: Scenario, worker_ids: Sequence[str]) -> list[dict[str, object]]:
    """Deterministyczne, fikcyjne zlecenia okresu; jest wśród nich zlecenie z poniedziałku."""

    active = list(worker_ids[: len(worker_ids) - scenario.workers_without_rows])
    if not active:
        raise BenchmarkError("Scenariusz nie zostawia żadnego Wykonawcy z wierszami.")
    rng = random.Random(SEED)
    total = scenario.successful_orders + scenario.unsuccessful_orders
    successful = [True] * scenario.successful_orders + [False] * scenario.unsuccessful_orders
    rng.shuffle(successful)
    workers = active + [rng.choice(active) for _ in range(scenario.successful_orders - len(active))]
    rng.shuffle(workers)
    successful_workers = iter(workers)
    rows: list[dict[str, object]] = []
    for number in range(1, total + 1):
        started = PERIOD.start + timedelta(days=number % 7, hours=rng.randint(7, 19), minutes=rng.randrange(60))
        activity = rng.choice(ACTIVITIES)
        is_successful = successful[number - 1]
        rows.append(
            {
                "DATA GODZ. POCZ.": started,
                "MIASTO": rng.choice(CITIES),
                "adres": f"ul. Syntetyczna {number:05d}",
                "UMOWA": f"BENCH-UM-{number:05d}",
                "URZĄDZENIA": rng.choice(DEVICES),
                "CZYNNOŚCI": activity,
                "NUMER ZL.": f"BENCH-ZL-{number:05d}",
                "WYKONAWCA": next(successful_workers) if is_successful else rng.choice(active),
                "NUMER UMOWY": f"BENCH-OR-{number:05d}",
                "SKUTECZNE": "tak" if is_successful else "nie",
                "CZYNNOŚCI ZREALIZOWANE": activity if is_successful else "",
            }
        )
    rows.sort(key=lambda row: str(row["DATA GODZ. POCZ."]))
    return rows


def _write_register(path: Path, rows: Iterable[Mapping[str, object]]) -> None:
    workbook = Workbook(write_only=True)
    sheet = workbook.create_sheet("ZLECENIA")
    sheet.append(list(REGISTER_HEADERS))
    for row in rows:
        sheet.append([row[header] for header in REGISTER_HEADERS])
    workbook.save(path)


def _run_quietly(arguments: Sequence[str | Path], failure_log: Path) -> int:
    """Uruchamia skrypt tego checkoutu bez stdin.

    Wyjście procesu zawiera nazwy Wykonawców, więc nie trafia na ekran, tylko do lokalnego logu przy błędzie.
    """

    completed = subprocess.run(
        [sys.executable, *map(str, arguments)],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
    )
    if completed.returncode != 0:
        failure_log.parent.mkdir(parents=True, exist_ok=True)
        failure_log.write_bytes(completed.stdout)
    return completed.returncode


def ensure_mirror(
    mirrors: Path, scenario_name: str, config: Path, templates: Mapping[str, Path]
) -> tuple[Path, bool]:
    """Lustro scenariusza i to, czy zostało właśnie zbudowane; budowa jest atomowa (folder roboczy + rename)."""

    mirror = mirrors / f"{scenario_name}-{_fingerprint(scenario_name, config, templates)}"
    if mirror.is_dir():
        return mirror, False
    mirrors.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=f".{mirror.name}.staging-", dir=mirrors))
    try:
        _period_directory(staging).mkdir(parents=True)
        register = staging / REGISTER_NAME
        _write_register(register, _register_rows(SCENARIOS[scenario_name], _worker_ids(config)))
        with tempfile.TemporaryDirectory(prefix="benchmark-przygotowanie-") as scratch:
            exit_code = _run_quietly(
                [
                    ROOT / "run_preparation.py",
                    "--register",
                    register,
                    "--periods-directory",
                    staging / "Załączniki",
                    "--period",
                    PERIOD.token,
                    "--config",
                    config,
                    "--internal-template",
                    templates[INTERNAL_TEMPLATE],
                    "--collective-template",
                    templates[COLLECTIVE_TEMPLATE],
                    "--metrics",
                    Path(scratch) / "metrics.jsonl",
                ],
                mirrors / "ostatni-blad-przygotowania.txt",
            )
        if exit_code != 0:
            raise BenchmarkError(
                f"Przygotowanie pliku zbiorczego lustra zakończyło się kodem {exit_code}; "
                f"wyjście w {mirrors / 'ostatni-blad-przygotowania.txt'}."
            )
        staging.rename(mirror)
    finally:
        shutil.rmtree(staging, ignore_errors=True)
    return mirror, True


# --- pomiar -----------------------------------------------------------------------------------


def _spread(values: Sequence[int]) -> dict[str, int]:
    return {"mediana": round(statistics.median(values)), "min": min(values), "max": max(values)}


def _remove_worker_settlements(folder: Path) -> None:
    """Każde uruchomienie startuje bez Folderu rozliczeń pracowników i bez folderów roboczych publikacji."""

    for path in (folder, *folder.parent.glob(f".{folder.name}.staging-*")):
        if path.is_dir():
            shutil.rmtree(path)


def _process_metrics(path: Path) -> dict[str, Any]:
    lines = path.read_text(encoding="utf-8").splitlines() if path.is_file() else []
    if len(lines) != 1:
        raise BenchmarkError("Przebieg rozliczeń nie zapisał jednego rekordu metryk procesu.")
    record: dict[str, Any] = json.loads(lines[0])
    if not record.get("completed") or record.get("mode") != "RUN":
        raise BenchmarkError(f"Przebieg rozliczeń nie zakończył się w trybie RUN: {record.get('result')}.")
    return record


def _git(*arguments: str) -> str | None:
    try:
        return subprocess.run(
            ["git", *arguments], cwd=ROOT, capture_output=True, text=True, check=True, timeout=30
        ).stdout
    except (OSError, subprocess.SubprocessError):
        return None


def measure(mirror: Path, scenario_name: str, config: Path, worker_template: Path, machine: str) -> dict[str, Any]:
    """Rekord dziennika z ``RUNS`` uruchomień Przebiegu rozliczeń na lustrze."""

    started_at = datetime.now(UTC).isoformat(timespec="seconds")
    sha = _git("rev-parse", "HEAD")
    status = _git("status", "--porcelain")
    source = _period_directory(mirror) / collective_file_name(PERIOD)
    worker_settlements = PeriodFolder.from_collective_file(source).worker_settlements
    walls: list[int] = []
    metrics: list[dict[str, Any]] = []
    with tempfile.TemporaryDirectory(prefix="benchmark-przebiegu-") as scratch:
        for run in range(1, RUNS + 1):
            _remove_worker_settlements(worker_settlements)
            metrics_path = Path(scratch) / f"uruchomienie-{run}.jsonl"
            failure_log = mirror.parent / "ostatni-blad-przebiegu.txt"
            started = time.perf_counter()
            exit_code = _run_quietly(
                [
                    ROOT / "run.py",
                    "--source",
                    source,
                    "--config",
                    config,
                    "--worker-template",
                    worker_template,
                    "--metrics",
                    metrics_path,
                ],
                failure_log,
            )
            wall_ms = round((time.perf_counter() - started) * 1000)
            if exit_code != 0:
                raise BenchmarkError(
                    f"Przebieg rozliczeń {run}/{RUNS} zakończył się kodem {exit_code}; wyjście w {failure_log}."
                )
            walls.append(wall_ms)
            metrics.append(_process_metrics(metrics_path))
            print(f"Uruchomienie {run}/{RUNS}: {wall_ms} ms", flush=True)
    counters = metrics[0]["counters"]
    if any(record["counters"] != counters for record in metrics):
        raise BenchmarkError("Liczniki Przebiegu rozliczeń różnią się między uruchomieniami tego samego lustra.")
    phases = list(metrics[0]["phase_durations_ms"])
    return {
        "started_at": started_at,
        "git_sha": sha.strip() if sha is not None else None,
        "dirty": bool(status.strip()) if status is not None else None,
        "machine": machine,
        "scenario": scenario_name,
        "runs": RUNS,
        "wall_ms": _spread(walls),
        "czas_uruchomienia_ms": _spread([record["total_duration_ms"] for record in metrics]),
        "phase_durations_ms": {
            phase: _spread([record["phase_durations_ms"][phase] for record in metrics]) for phase in phases
        },
        "counters": counters,
        # Bramka poprawności (#144) jeszcze nie istnieje.
        "oracle": None,
    }


def append_record(journal: Path, record: Mapping[str, Any]) -> None:
    journal.parent.mkdir(parents=True, exist_ok=True)
    with journal.open("a", encoding="utf-8") as stream:
        stream.write(json.dumps(record, ensure_ascii=False) + "\n")


# --- komentarz --------------------------------------------------------------------------------


def _read_journal(journal: Path) -> list[dict[str, Any]]:
    if not journal.is_file():
        raise BenchmarkError(f"Brak dziennika {journal}; najpierw uruchom measure.")
    return [json.loads(line) for line in journal.read_text(encoding="utf-8").splitlines() if line.strip()]


def _matches(record: Mapping[str, Any], reference: str | None) -> bool:
    return reference is None or str(record.get("git_sha") or "").startswith(reference)


def _pairs(
    records: Sequence[Mapping[str, Any]], before: str | None, after: str | None
) -> list[tuple[Mapping[str, Any] | None, Mapping[str, Any]]]:
    """Dla każdego scenariusza: ostatni rekord ``after`` i rekord przed nim (albo ostatni ``before``)."""

    names = [*SCENARIOS, *(record["scenario"] for record in records)]
    pairs: list[tuple[Mapping[str, Any] | None, Mapping[str, Any]]] = []
    for name in dict.fromkeys(names):
        history = [record for record in records if record["scenario"] == name]
        after_indices = [index for index, record in enumerate(history) if _matches(record, after)]
        if not after_indices:
            continue
        after_index = after_indices[-1]
        if before is None:
            earlier = history[after_index - 1] if after_index > 0 else None
        else:
            candidates = [
                record for index, record in enumerate(history) if index != after_index and _matches(record, before)
            ]
            earlier = candidates[-1] if candidates else None
        pairs.append((earlier, history[after_index]))
    return pairs


def _spread_text(spread: Mapping[str, int] | None) -> str:
    return "—" if spread is None else f"{spread['mediana']} ({spread['min']}–{spread['max']})"


def _commit_text(record: Mapping[str, Any] | None) -> str:
    if record is None:
        return "brak pomiaru"
    sha = str(record.get("git_sha") or "nieznany")[:7]
    return f"`{sha}`" + (" + niezacommitowane zmiany" if record.get("dirty") else "")


def _oracle_text(oracle: object) -> str:
    if oracle is None or oracle == "nie sprawdzono":
        return "nie sprawdzono"
    if isinstance(oracle, Mapping):
        return ", ".join(f"{key}: {value}" for key, value in oracle.items())
    return str(oracle)


def _improvement(before: Mapping[str, Any], after: Mapping[str, Any]) -> str:
    """Poprawa liczy się tylko wtedy, gdy mediana jest szybsza o więcej niż rozrzut min–max (spec #141)."""

    gain = before["wall_ms"]["mediana"] - after["wall_ms"]["mediana"]
    noise = max(spread["max"] - spread["min"] for spread in (before["wall_ms"], after["wall_ms"]))
    direction = f"krótsza o {gain} ms" if gain >= 0 else f"dłuższa o {-gain} ms"
    verdict = "tak" if gain > noise else "nie"
    return f"Poprawa czasu ściany: **{verdict}** (mediana {direction}, największy rozrzut min–max {noise} ms)."


def _measurement_table(before: Mapping[str, Any] | None, after: Mapping[str, Any]) -> list[str]:
    def row(label: str, value: Any) -> str:
        return f"| {label} | {value(before) if before is not None else '—'} | {value(after)} |"

    def text(key: str) -> Any:
        return lambda record: record.get(key)

    lines = [
        "| | Przed | Po |",
        "|---|---:|---:|",
        row("Rozpoczęto", text("started_at")),
        row("Commit", lambda record: f"`{record.get('git_sha') or 'nieznany'}`"),
        row("Niezacommitowane zmiany", lambda record: {True: "tak", False: "nie"}.get(record.get("dirty"), "?")),
        row("Maszyna", text("machine")),
        row("Uruchomienia", text("runs")),
        row("Czas ściany [ms]", lambda record: _spread_text(record["wall_ms"])),
        row("Czas uruchomienia [ms]", lambda record: _spread_text(record["czas_uruchomienia_ms"])),
    ]
    phases = dict.fromkeys([*(before or {}).get("phase_durations_ms", {}), *after["phase_durations_ms"]])
    for phase in phases:
        lines.append(
            row(f"{phase} [ms]", lambda record, phase=phase: _spread_text(record["phase_durations_ms"].get(phase)))
        )
    counters = dict.fromkeys([*(before or {}).get("counters", {}), *after["counters"]])
    for counter in counters:
        lines.append(row(f"`{counter}`", lambda record, counter=counter: record["counters"].get(counter, "—")))
    lines.append(row("Bramka poprawności", lambda record: _oracle_text(record.get("oracle"))))
    return lines


def _next_step(pairs: Sequence[tuple[Mapping[str, Any] | None, Mapping[str, Any]]]) -> str:
    typical = next((after for _, after in pairs if after["scenario"] == "typowy-tydzien"), None)
    goals = (
        f"Cel twardy: mediana czasu ściany typowego tygodnia ≤ {HARD_GOAL_MS} ms na Macu; "
        f"cel ambitny ≤ {AMBITIOUS_GOAL_MS} ms."
    )
    if typical is None:
        return f"{goals} Brak pomiaru typowego tygodnia."
    median = typical["wall_ms"]["mediana"]
    if median <= AMBITIOUS_GOAL_MS:
        status = "cel ambitny osiągnięty"
    elif median <= HARD_GOAL_MS:
        status = f"cel twardy osiągnięty, do ambitnego brakuje {median - AMBITIOUS_GOAL_MS} ms"
    else:
        status = f"do celu twardego brakuje {median - HARD_GOAL_MS} ms"
    return f"{goals} Teraz {median} ms na maszynie `{typical['machine']}`: {status}."


def render_comment(records: Sequence[Mapping[str, Any]], before: str | None = None, after: str | None = None) -> str:
    """Komentarz do issue-dziennika w stałym układzie; Hipotezę i Decyzję dopisuje człowiek albo agent."""

    pairs = _pairs(records, before, after)
    if not pairs:
        raise BenchmarkError("W dzienniku nie ma rekordu pasującego do --after.")
    lines = ["## Hipoteza", "", TO_FILL, "", "## Zmiana", ""]
    lines += [f"- {after['scenario']}: {_commit_text(before)} → {_commit_text(after)}" for before, after in pairs]
    lines += ["", "## Pomiar", ""]
    for earlier, later in pairs:
        lines += [f"### {later['scenario']}", "", *_measurement_table(earlier, later), ""]
        if earlier is not None:
            lines += [_improvement(earlier, later), ""]
    lines += ["## Bramka poprawności", ""]
    lines += [f"- {after['scenario']}: {_oracle_text(after.get('oracle'))}" for _, after in pairs]
    lines += ["", "## Decyzja", "", TO_FILL, "", "## Następny krok", "", _next_step(pairs), ""]
    return "\n".join(lines)


# --- straż czasu w CI -------------------------------------------------------------------------


def guard_summary(record: Mapping[str, Any], budget_ms: int) -> tuple[str, bool]:
    """Podsumowanie ostatniego pomiaru do joba CI i to, czy mediana czasu ściany mieści się w budżecie."""

    median = record["wall_ms"]["mediana"]
    within = median <= budget_ms
    verdict = "w budżecie" if within else f"ponad budżetem o {median - budget_ms} ms"
    lines = [
        f"### Czas Przebiegu rozliczeń: {record['scenario']}",
        "",
        "| | mediana (min–max) [ms] |",
        "|---|---:|",
        f"| Czas ściany | {_spread_text(record['wall_ms'])} |",
        f"| Czas uruchomienia | {_spread_text(record['czas_uruchomienia_ms'])} |",
        *(f"| {phase} | {_spread_text(spread)} |" for phase, spread in record["phase_durations_ms"].items()),
        "",
        f"{_commit_text(record)}, maszyna `{record['machine']}`, uruchomienia: {record['runs']}.",
        "",
        f"Budżet mediany czasu ściany: {budget_ms} ms. Wynik: **{verdict}**.",
        "",
    ]
    return "\n".join(lines), within


# --- CLI --------------------------------------------------------------------------------------


def _default_machine() -> str:
    return f"{platform.system()}-{platform.machine()}".lower()


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    commands = parser.add_subparsers(dest="command", required=True)
    measure_parser = commands.add_parser("measure", help="Zbuduj lustro (jeśli go brak) i zmierz scenariusz.")
    measure_parser.add_argument("--scenario", choices=list(SCENARIOS), default="typowy-tydzien")
    measure_parser.add_argument("--templates-dir", type=Path, help="Folder z trzema Wzorcami (nazwy jak w config).")
    measure_parser.add_argument("--config", type=Path, default=ROOT / "config" / "worker_mapping.yaml")
    measure_parser.add_argument("--mirror-dir", type=Path, default=DEFAULT_DIRECTORY / "lustro")
    measure_parser.add_argument("--journal", type=Path, default=DEFAULT_DIRECTORY / "przebieg.jsonl")
    measure_parser.add_argument("--machine", default=_default_machine(), help="Np. mac-m4max albo tata-i7.")
    comment_parser = commands.add_parser("comment", help="Wydrukuj komentarz Markdown z dziennika.")
    comment_parser.add_argument("--journal", type=Path, default=DEFAULT_DIRECTORY / "przebieg.jsonl")
    comment_parser.add_argument("--before", help="Commit (prefiks) pomiaru „przed”; domyślnie poprzedni rekord.")
    comment_parser.add_argument("--after", help="Commit (prefiks) pomiaru „po”; domyślnie ostatni rekord.")
    guard_parser = commands.add_parser(
        "guard", help="Opisz ostatni pomiar dziennika i zakończ kodem 1, gdy mediana czasu ściany przekracza budżet."
    )
    guard_parser.add_argument("--journal", type=Path, default=DEFAULT_DIRECTORY / "przebieg.jsonl")
    guard_parser.add_argument("--budget-ms", type=int, required=True)
    guard_parser.add_argument("--summary", type=Path, help="Plik, do którego dopisać podsumowanie (np. job CI).")
    return parser


def _guard(journal: Path, budget_ms: int, summary_path: Path | None) -> int:
    records = _read_journal(journal)
    if not records:
        raise BenchmarkError(f"Dziennik {journal} jest pusty; najpierw uruchom measure.")
    summary, within = guard_summary(records[-1], budget_ms)
    print(summary, end="")
    if summary_path is not None:
        with summary_path.open("a", encoding="utf-8") as stream:
            stream.write(summary)
    return 0 if within else 1


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        if args.command == "comment":
            print(render_comment(_read_journal(args.journal), args.before, args.after), end="")
            return 0
        if args.command == "guard":
            return _guard(args.journal, args.budget_ms, args.summary)
        templates = _templates((args.templates_dir or default_templates_directory()).expanduser().resolve())
        config = args.config.expanduser().resolve()
        mirror, built = ensure_mirror(args.mirror_dir.expanduser().resolve(), args.scenario, config, templates)
        print(f"Lustro {'zbudowane' if built else 'istniejące'}: {mirror}", flush=True)
        record = measure(mirror, args.scenario, config, templates[WORKER_TEMPLATE], args.machine)
        append_record(args.journal, record)
    except BenchmarkError as error:
        print(f"Benchmark przerwany: {error}", file=sys.stderr)
        return 1
    wall, startup = record["wall_ms"], record["czas_uruchomienia_ms"]
    print(
        f"{args.scenario}: czas ściany {_spread_text(wall)} ms, Czas uruchomienia {_spread_text(startup)} ms "
        f"(mediana (min–max) z {RUNS} uruchomień). Rekord w {args.journal}."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

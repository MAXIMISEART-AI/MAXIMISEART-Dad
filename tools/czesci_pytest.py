"""Dzieli pliki testów na N części o podobnym czasie w CI i wypisuje pliki części K, najdłuższe najpierw.

Czas pliku to suma czasów jego testów w raporcie junit części pytest, a z raportów obu Pythonów
średnia. Tabela Windowsa to ``tools/czasy_testow_ci.json``, a Linuksa (``--linux``)
``tools/czasy_testow_ci_linux.json``: na Linuksie biegną testy, które Windows pomija, i te same pliki
trwają inaczej. Plik spoza tabeli waży tyle, co mediana tabeli, więc nowy test trafia do którejś
części bez zmiany tabeli; nieaktualna tabela psuje tylko równowagę części, nie ich sumę.
Najdłuższe pliki idą pierwsze, bo xdist rozdaje testy po kolei: długi test z końca kolejki startuje
dopiero wtedy, gdy reszta workerów już kończy.

    py -3 tools/czesci_pytest.py 1/3                                # pliki części 1 z 3, po jednym w linii
    python tools/czesci_pytest.py --linux 1/2                       # część 1 z 2 według tabeli Linuksa
    .venv/bin/python tools/czesci_pytest.py --czasy-z junit-*/junit.xml   # tabela Windowsa z raportów junit części
"""

from __future__ import annotations

import argparse
from collections import defaultdict
import json
from pathlib import Path
import statistics
from xml.etree import ElementTree

ROOT = Path(__file__).resolve().parents[1]
TIMES = ROOT / "tools" / "czasy_testow_ci.json"
TIMES_LINUX = ROOT / "tools" / "czasy_testow_ci_linux.json"
# Domyślne python_files pytest: pyproject.toml go nie zmienia.
PYTEST_FILES = ("test_*.py", "*_test.py")


def _part(text: str) -> tuple[int, int]:
    number, _, count = text.partition("/")
    if not (number.isdigit() and count.isdigit() and 1 <= int(number) <= int(count)):
        raise argparse.ArgumentTypeError(f"część K/N z 1 <= K <= N, nie {text!r}")
    return int(number), int(count)


def parts(files: list[str], times: dict[str, float], count: int) -> list[list[str]]:
    """Pliki w ``count`` częściach: każdy następny najdłuższy plik do części o najmniejszej sumie."""

    default = statistics.median(times.values()) if times else 1.0
    weight = {name: times.get(name, default) for name in files}
    chosen: list[list[str]] = [[] for _ in range(count)]
    sums = [0.0] * count
    for name in sorted(files, key=lambda name: (-weight[name], name)):
        lightest = sums.index(min(sums))
        chosen[lightest].append(name)
        sums[lightest] += weight[name]
    return chosen


def _times_from(reports: list[Path]) -> dict[str, float]:
    per_report: dict[str, list[float]] = defaultdict(list)
    for junit in reports:
        times: dict[str, float] = defaultdict(float)
        for case in ElementTree.parse(junit).getroot().iter("testcase"):
            module = case.get("classname", "").split(".")
            while module and not module[-1].startswith("test_"):
                module.pop()
            if module:
                times["/".join(module) + ".py"] += float(case.get("time", 0))
        for name, seconds in times.items():
            per_report[name].append(seconds)
    return {name: round(statistics.mean(seconds), 1) for name, seconds in sorted(per_report.items())}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("czesc", nargs="?", type=_part, metavar="K/N", help="Część K z N.")
    group.add_argument("--czasy-z", type=Path, nargs="+", metavar="JUNIT", help="Zapisz tabelę czasów z raportów junit części.")
    parser.add_argument("--linux", action="store_true", help=f"Tabela Linuksa {TIMES_LINUX.name} zamiast {TIMES.name}.")
    args = parser.parse_args(argv)
    table = TIMES_LINUX if args.linux else TIMES
    if args.czasy_z is not None:
        table.write_text(json.dumps(_times_from(args.czasy_z), indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
        return 0
    number, count = args.czesc
    files = sorted({path.relative_to(ROOT).as_posix() for pattern in PYTEST_FILES for path in (ROOT / "tests").rglob(pattern)})
    times = json.loads(table.read_text(encoding="utf-8")) if table.is_file() else {}
    print("\n".join(parts(files, times, count)[number - 1]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

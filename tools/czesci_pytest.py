"""Dzieli pliki testów na N części o podobnym czasie w CI i wypisuje pliki części K, najdłuższe najpierw.

Czas pliku to suma czasów jego testów z raportu junit zadania pytest na Windowsie, zapisana w
``tools/czasy_testow_ci.json``. Plik spoza tabeli waży tyle, co mediana tabeli, więc nowy test trafia
do którejś części bez zmiany tabeli; nieaktualna tabela psuje tylko równowagę części, nie ich sumę.
Najdłuższe pliki idą pierwsze, bo xdist rozdaje testy po kolei: długi test z końca kolejki startuje
dopiero wtedy, gdy reszta workerów już kończy.

    py -3 tools/czesci_pytest.py 1/2                              # pliki części 1 z 2, po jednym w linii
    .venv/bin/python tools/czesci_pytest.py --czasy-z junit.xml   # tabela czasów z raportu junit
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


def _times_from(junit: Path) -> dict[str, float]:
    times: dict[str, float] = defaultdict(float)
    for case in ElementTree.parse(junit).getroot().iter("testcase"):
        module = case.get("classname", "").split(".")
        while module and not module[-1].startswith("test_"):
            module.pop()
        if module:
            times["/".join(module) + ".py"] += float(case.get("time", 0))
    return {name: round(seconds, 1) for name, seconds in sorted(times.items())}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("czesc", nargs="?", type=_part, metavar="K/N", help="Część K z N.")
    group.add_argument("--czasy-z", type=Path, metavar="JUNIT", help=f"Zapisz {TIMES.name} z raportu junit.")
    args = parser.parse_args(argv)
    if args.czasy_z is not None:
        TIMES.write_text(json.dumps(_times_from(args.czasy_z), indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
        return 0
    number, count = args.czesc
    files = sorted({path.relative_to(ROOT).as_posix() for pattern in PYTEST_FILES for path in (ROOT / "tests").rglob(pattern)})
    times = json.loads(TIMES.read_text(encoding="utf-8")) if TIMES.is_file() else {}
    print("\n".join(parts(files, times, count)[number - 1]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

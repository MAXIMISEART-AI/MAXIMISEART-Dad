"""``tools/czesci_pytest.py`` dzieli pliki testów na części CI bez zgubionego i bez powtórzonego pliku."""

from __future__ import annotations

from collections import Counter
import importlib.util
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys
from typing import Any

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
TOOL = ROOT / "tools" / "czesci_pytest.py"
WORKFLOW = ROOT / ".github" / "workflows" / "ci.yml"


def _part(root: Path, text: str) -> list[str]:
    tool = root / "tools" / TOOL.name
    done = subprocess.run([sys.executable, str(tool), text], capture_output=True, text=True, encoding="utf-8", check=True)
    return done.stdout.split()


@pytest.mark.parametrize("count", [1, 2, 3])
def test_kazdy_plik_testow_jest_w_dokladnie_jednej_czesci(tmp_path: Path, count: int) -> None:
    tests = ["tests/test_a.py", "tests/b_test.py", "tests/podfolder/test_c.py", "tests/podfolder/d_test.py"]
    for name in [*tests, "tests/fixtures/pomocnik.py", "tests/conftest.py"]:
        (tmp_path / name).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / name).write_text("", encoding="utf-8")
    (tmp_path / "tools").mkdir()
    shutil.copy(TOOL, tmp_path / "tools" / TOOL.name)

    files = [name for number in range(1, count + 1) for name in _part(tmp_path, f"{number}/{count}")]

    assert sorted(files) == sorted(tests)


@pytest.mark.parametrize("count", [2, 3])
def test_czesci_repozytorium_obejmuja_kazdy_plik_testow(count: int) -> None:
    files = [name for number in range(1, count + 1) for name in _part(ROOT, f"{number}/{count}")]

    assert len(files) == len(set(files))
    assert set(files) == {path.relative_to(ROOT).as_posix() for path in (ROOT / "tests").rglob("test_*.py")}


def test_czesc_zaczyna_sie_od_najdluzszego_pliku_a_plik_spoza_tabeli_wazy_mediane() -> None:
    spec = importlib.util.spec_from_file_location("czesci_pytest", TOOL)
    assert spec is not None and spec.loader is not None
    tool = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(tool)

    chosen = tool.parts(["a", "b", "c", "d", "nowy"], {"a": 10.0, "b": 1.0, "c": 6.0, "d": 4.0}, 2)

    assert chosen == [["a", "d"], ["c", "nowy", "b"]]


@pytest.mark.parametrize("part", ["0/2", "3/2", "2"])
def test_czesc_spoza_zakresu_jest_bledem_wywolania(part: str) -> None:
    done = subprocess.run([sys.executable, str(TOOL), part], capture_output=True, text=True, encoding="utf-8", check=False)

    assert (done.returncode, done.stdout) == (2, "")


def test_tabela_czasow_sumuje_testy_pliku_w_raporcie_i_usrednia_raporty_obu_pythonow(tmp_path: Path) -> None:
    (tmp_path / "tools").mkdir()
    shutil.copy(TOOL, tmp_path / "tools" / TOOL.name)
    reports = []
    python_311 = [[("tests.test_a", 1.5), ("tests.test_a.TestKlasa", 2.0)], [("tests.podfolder.test_b", 4.0)]]
    python_314 = [[("tests.test_a", 2.5)], [("tests.podfolder.test_b", 2.0)]]
    for number, cases in enumerate([*python_311, *python_314]):
        report = tmp_path / f"junit-{number}.xml"
        report.write_text(
            "<testsuites><testsuite>"
            + "".join(f'<testcase classname="{name}" name="t" time="{seconds}"/>' for name, seconds in cases)
            + "</testsuite></testsuites>",
            encoding="utf-8",
        )
        reports.append(str(report))

    subprocess.run([sys.executable, str(tmp_path / "tools" / TOOL.name), "--czasy-z", *reports], check=True)

    table = json.loads((tmp_path / "tools" / "czasy_testow_ci.json").read_text(encoding="utf-8"))
    assert table == {"tests/podfolder/test_b.py": 3.0, "tests/test_a.py": 3.0}


def test_linux_dzieli_pliki_wedlug_wlasnej_tabeli_a_windows_wedlug_swojej(tmp_path: Path) -> None:
    for name in ("tests/test_a.py", "tests/test_b.py"):
        (tmp_path / name).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / name).write_text("", encoding="utf-8")
    (tmp_path / "tools").mkdir()
    shutil.copy(TOOL, tmp_path / "tools" / TOOL.name)
    (tmp_path / "tools" / "czasy_testow_ci.json").write_text('{"tests/test_a.py": 9.0, "tests/test_b.py": 1.0}', encoding="utf-8")
    report = tmp_path / "junit.xml"
    report.write_text(
        '<testsuite><testcase classname="tests.test_a" name="t" time="1.0"/><testcase classname="tests.test_b" name="t" time="9.0"/></testsuite>',
        encoding="utf-8",
    )
    tool = [sys.executable, str(tmp_path / "tools" / TOOL.name)]

    subprocess.run([*tool, "--linux", "--czasy-z", str(report)], check=True)

    first = {flag: subprocess.run([*tool, *flag, "1/2"], capture_output=True, text=True, check=True).stdout.split() for flag in ((), ("--linux",))}
    assert first == {(): ["tests/test_a.py"], ("--linux",): ["tests/test_b.py"]}
    assert json.loads((tmp_path / "tools" / "czasy_testow_ci.json").read_text(encoding="utf-8")) == {"tests/test_a.py": 9.0, "tests/test_b.py": 1.0}


def _combinations(matrix: dict[str, Any]) -> list[dict[str, Any]]:
    """Kombinacje macierzy GitHub Actions: iloczyn list, bez ``exclude``, z ``include``."""

    axes = {key: values for key, values in matrix.items() if key not in ("include", "exclude")}
    combinations: list[dict[str, Any]] = [{}]
    for key, values in axes.items():
        combinations = [{**combination, key: value} for combination in combinations for value in values]
    for excluded in matrix.get("exclude", []):
        combinations = [c for c in combinations if any(c.get(key) != value for key, value in excluded.items())]
    for extra in matrix.get("include", []):
        matching = [c for c in combinations if all(c[key] == value for key, value in extra.items() if key in axes)]
        for combination in matching:
            combination.update({key: value for key, value in extra.items() if key not in axes})
        if not matching:
            combinations.append(dict(extra))
    return combinations


def _jobs_with_parts() -> dict[str, dict[str, Any]]:
    jobs = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))["jobs"]
    return {name: job for name, job in jobs.items() if any("part" in c for c in _combinations(job.get("strategy", {}).get("matrix", {})))}


def test_macierz_kazdego_zadania_z_czesciami_obejmuje_dokladnie_czesci_od_1_do_n() -> None:
    jobs = _jobs_with_parts()
    missing = {}
    for name, job in jobs.items():
        steps = " ".join(step.get("run", "") for step in job["steps"])
        count_in_steps = ",".join(sorted(set(re.findall(r"matrix\.part }}/(\d+)", steps))))
        groups: dict[tuple[tuple[str, Any], ...], list[str]] = {}
        for combination in _combinations(job["strategy"]["matrix"]):
            part = str(combination.pop("part"))
            groups.setdefault(tuple(sorted(combination.items())), []).append(part if "/" in part else f"{part}/{count_in_steps}")
        for group, found in groups.items():
            count = found[0].partition("/")[2]
            expected = [f"{number}/{count}" for number in range(1, int(count) + 1)] if count.isdigit() else []
            if Counter(found) != Counter(expected):
                missing[f"{name} {dict(group)}"] = sorted(found)

    assert {"pytest", "mutations"} <= set(jobs)
    assert missing == {}


def test_linux_dzieli_pliki_wedlug_tabeli_linuksa_a_windows_wedlug_tabeli_windowsa() -> None:
    steps = [step for step in _jobs_with_parts()["pytest"]["steps"] if TOOL.name in step.get("run", "")]
    flags = {step["if"]: "--linux" in step["run"] for step in steps}

    assert flags == {"${{ runner.os == 'Windows' }}": False, "${{ runner.os == 'Linux' }}": True}

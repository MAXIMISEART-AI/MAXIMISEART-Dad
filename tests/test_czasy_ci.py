"""Czasy CI: zadanie zapisuje czas każdej jednostki swojej pracy, a Required na main scala zapisy runu w ``czasy-ci``.

Zapis zadania bierze testy z junit pytest, kroki skilli z wyjścia ``tools/mutacje_skilli.py`` i kroki CI z API zadań
runu. Wejście, którego brakuje albo którego nie da się odczytać, jest zgłoszone linią ``CZASY CI FAIL``, a reszta
pomiaru zostaje.
"""

from __future__ import annotations

import json
from pathlib import Path
import sys
import tomllib

import pytest

from tests.fixtures.ci_workflow import jobs

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

from czasy_ci import KROKI, main  # noqa: E402

RUNNER = "GitHub Actions 1000012606"
ENV = {
    "GITHUB_JOB": "pytest",
    "RUNNER_NAME": RUNNER,
    "GITHUB_RUN_ID": "40259456807",
    "GITHUB_RUN_ATTEMPT": "2",
    "GITHUB_EVENT_NAME": "push",
    "GITHUB_SHA": "31bb76513d0bce91cdba28d09f61d07431ee4028",
}
# junit pytest -n 4 z junit_family = xunit1: na Windows ścieżka z ukośnikami wstecznymi, test w klasie, porażka
# testu, błąd fixture, pominięty test i plik, którego nie dało się zaimportować.
JUNIT = """<?xml version="1.0" encoding="utf-8"?><testsuites><testsuite name="pytest" tests="7">
<testcase classname="tests.test_b" name="test_ok" file="tests\\test_b.py" line="3" time="0.100" />
<testcase classname="tests.test_b.TestK" name="test_w_klasie" file="tests\\test_b.py" line="9" time="0.200" />
<testcase classname="tests.test_a" name="test_zly" file="tests/test_a.py" line="7" time="1.500"><failure message="assert False">E</failure></testcase>
<testcase classname="tests.test_c" name="test_fixture" file="tests/test_c.py" line="26" time="0.250"><error message="failed on setup">E</error></testcase>
<testcase classname="tests.test_d" name="test_pominiety" file="tests/test_d.py" line="11" time="0.000"><skipped message="skip">s</skipped></testcase>
<testcase classname="tests.test_d" name="test_ok" file="tests/test_d.py" line="15" time="2.000" />
<testcase classname="" name="tests.test_e" file="tests/test_e.py" time="0.000"><error message="collection failure">E</error></testcase>
</testsuite></testsuites>
"""
# Wyjście Mutation checks z końcami linii Windows: echo skryptów, pominięty skrypt i zły klucz ci bez czasu.
MUTATIONS_LOG = (
    "== .agents/skills/verify-a/scripts/check_a_mutations.py\r\n"
    "WYKRYTA: próg 18:00 → OK   PODSTAWA nie-ta-linia (1 s)\r\n"
    "OK   .agents/skills/verify-a/scripts/check_a_mutations.py (101 s)\r\n"
    "== PODSTAWA verify-b: .agents/skills/verify-b/scripts/explore.py\r\n"
    "OK   PODSTAWA verify-b (23 s)\r\n"
    "FAIL .agents/skills/verify-c/scripts/check_c_mutations.py (7 s): kod wyjścia 1\r\n"
    "FAIL PODSTAWA verify-d (300 s): przekroczył limit 300 s\r\n"
    "FAIL PODSTAWA verify-e: ci: brak skryptu\r\n"
    "POMINIĘTY .agents/skills/verify-f/scripts/check_f_mutations.py: brak zmian\r\n"
    "MUTACJE SKILLI FAIL | .agents/skills/verify-c/scripts/check_c_mutations.py, PODSTAWA verify-d\r\n"
)
MUTATION_UNITS = [
    {"klucz": "skill:verify-a/check_a_mutations.py", "s": 101.0, "status": "ok"},
    {"klucz": "skill:verify-b/ci", "s": 23.0, "status": "ok"},
    {"klucz": "skill:verify-c/check_c_mutations.py", "s": 7.0, "status": "fail"},
    {"klucz": "skill:verify-d/ci", "s": 300.0, "status": "fail"},
]


def _step(name: str, conclusion: str, started: str, completed: str) -> dict[str, str]:
    return {"name": name, "conclusion": conclusion, "started_at": f"2026-10-26T{started}Z", "completed_at": f"2026-10-26T{completed}Z"}


def _api(steps: list[dict[str, str]]) -> dict[str, object]:
    """Odpowiedź API zadań runu: to zadanie i zadanie na innym runnerze z tymi samymi krokami."""

    job = {"name": "pytest (Python 3.14, 1/2)", "runner_name": RUNNER, "started_at": "2026-10-26T02:30:51Z", "steps": steps}
    return {"total_count": 2, "jobs": [{**job, "name": "inne", "runner_name": "GitHub Actions 7", "started_at": "2026-10-26T01:00:00Z"}, job]}


PYTEST_STEPS = [
    _step("Set up job", "success", "02:30:51", "02:30:54"),
    _step("Run tests", "failure", "02:31:08", "02:37:31"),
    _step("Run tests (Linux)", "skipped", "02:37:31", "02:37:31"),
    _step("E2E (verify-rozliczenia --variant all)", "success", "02:37:31", "02:38:32"),
    _step("Timing guard: generate synthetic Wzorce", "success", "02:38:32", "02:38:42"),
    _step("Timing guard: measure Przebieg rozliczeń (typowy tydzień)", "success", "02:38:42", "02:39:02"),
    _step("Timing guard: report timings and enforce the budget", "cancelled", "02:39:02", "02:39:07"),
    _step("Upload benchmark failure output", "success", "02:39:07", "02:39:09"),
]
PYTEST_UNITS = [
    {"klucz": "krok:e2e", "s": 61.0, "status": "ok"},
    {"klucz": "krok:pytest", "s": 383.0, "status": "fail"},
    {"klucz": "krok:timing", "s": 30.0, "status": "ok"},
    {"klucz": "pytest:tests/test_a.py", "s": 1.5, "status": "fail"},
    {"klucz": "pytest:tests/test_b.py", "s": 0.3, "status": "ok"},
    {"klucz": "pytest:tests/test_c.py", "s": 0.25, "status": "fail"},
    {"klucz": "pytest:tests/test_d.py", "s": 2.0, "status": "ok"},
    {"klucz": "pytest:tests/test_e.py", "s": 0.0, "status": "fail"},
]


@pytest.fixture(autouse=True)
def _github_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for name, value in ENV.items():
        monkeypatch.setenv(name, value)


def _inputs(folder: Path, steps: list[dict[str, str]] = PYTEST_STEPS) -> dict[str, Path]:
    folder.mkdir(parents=True, exist_ok=True)
    paths = {"junit": folder / "junit.xml", "mutacje": folder / "mutacje.log", "kroki": folder / "zadania.json"}
    paths["junit"].write_text(JUNIT, encoding="utf-8")
    paths["mutacje"].write_bytes(MUTATIONS_LOG.encode("utf-8"))
    paths["kroki"].write_text(json.dumps(_api(steps)), encoding="utf-8")
    return paths


def _record(tmp_path: Path, paths: dict[str, Path], *sources: str, tor: str = "Windows-3.14.0") -> tuple[int, dict[str, object]]:
    record = tmp_path / "czasy" / "zapis" / "pytest-0-2.json"
    arguments = [part for source in sources for part in (f"--{source}", str(paths[source]))]
    code = main(["zadanie", "--tor", tor, *arguments, "--wyjscie", str(record)])
    return code, json.loads(record.read_text(encoding="utf-8"))


def test_zadanie_pytest_zapisuje_czas_kazdego_pliku_testow_i_kazdego_kroku_z_narzutem(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    code, record = _record(tmp_path, _inputs(tmp_path / "wejscie"), "kroki", "junit")

    assert code == 0
    assert record == {
        "wersja": 1,
        "run": 40259456807,
        "proba": 2,
        "szablon": "pytest",
        "zadanie": "pytest (Python 3.14, 1/2)",
        "tor": "windows-3.14",
        "zdarzenie": "push",
        "sha": ENV["GITHUB_SHA"],
        "narzut_s": 17.0,
        "jednostki": PYTEST_UNITS,
        "bledy": [],
    }
    assert capsys.readouterr().out.splitlines() == ["CZASY CI | pytest (Python 3.14, 1/2) | windows-3.14 | 8 jednostek | narzut 17 s | pytest-0-2.json"]


def test_zadanie_mutation_checks_zapisuje_czas_kazdego_kroku_skilla_takze_nieudanego(tmp_path: Path) -> None:
    steps = [
        _step("Run each verify skill's baseline check and prove it fails on broken variants", "failure", "02:32:00", "02:42:00"),
        _step("Upload baseline evidence on failure", "success", "02:42:00", "02:42:03"),
    ]
    code, record = _record(tmp_path, _inputs(tmp_path / "wejscie", steps), "kroki", "mutacje", tor="Windows-3.14.2")

    assert code == 0
    assert (record["tor"], record["narzut_s"], record["bledy"]) == ("windows-3.14", 69.0, [])
    assert record["jednostki"] == [{"klucz": "krok:mutacje", "s": 600.0, "status": "fail"}, *MUTATION_UNITS]


def test_zadanie_bez_kroku_jednostki_nie_ma_narzutu(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    steps = [_step("Set up job", "success", "02:30:51", "02:30:54"), _step("Run tests (Linux)", "skipped", "02:31:00", "02:31:00")]
    code, record = _record(tmp_path, _inputs(tmp_path / "wejscie", steps), "kroki", tor="Linux-3.14.0")

    assert code == 0
    assert (record["tor"], record["narzut_s"], record["jednostki"]) == ("linux-3.14", None, [])
    assert "| 0 jednostek | narzut ? s |" in capsys.readouterr().out


def _replace(path: Path, content: str | None) -> None:
    if content is None:
        path.unlink()
    else:
        path.write_text(content, encoding="utf-8")


@pytest.mark.parametrize(
    ("source", "content", "error"),
    [
        ("junit", None, "junit.xml: FileNotFoundError("),
        ("junit", "<testsuites><testsuite>", "junit.xml: ValueError('to nie jest XML ("),
        ("junit", '<testsuite><testcase name="test_x" time="1.0" /></testsuite>', "junit.xml: ValueError('test test_x bez atrybutu file"),
        ("junit", '<testsuite name="pytest" tests="0"></testsuite>', "junit.xml: ValueError('brak testów')"),
        ("mutacje", None, "mutacje.log: FileNotFoundError("),
        ("mutacje", "OK   PODSTAWA verify-b (23 s)\n", "mutacje.log: ValueError('brak linii MUTACJE SKILLI OK/FAIL"),
        ("kroki", None, "zadania.json: FileNotFoundError("),
        ("kroki", "", "zadania.json: JSONDecodeError("),
        ("kroki", '{"message": "Bad credentials"}', "zadania.json: KeyError('jobs')"),
        ("kroki", '{"jobs": null}', "zadania.json: TypeError("),
        ("kroki", json.dumps({"jobs": []}), "zadania.json: ValueError(\"0 zadań na runnerze 'GitHub Actions 1000012606' zamiast jednego\")"),
    ],
)
def test_brakujace_albo_zepsute_wejscie_jest_zgloszone_a_reszta_pomiaru_zostaje(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], source: str, content: str | None, error: str
) -> None:
    paths = _inputs(tmp_path / "wejscie")
    _replace(paths[source], content)
    sources = ("kroki", "junit", "mutacje")

    code, record = _record(tmp_path, paths, *sources)
    errors = record["bledy"]
    out = capsys.readouterr().out.splitlines()

    assert code == 1
    assert isinstance(errors, list) and len(errors) == 1 and errors[0].startswith(error), errors
    assert out[0] == f"CZASY CI FAIL | {errors[0]}"
    kept = {"kroki": PYTEST_UNITS[:3], "junit": PYTEST_UNITS[3:], "mutacje": MUTATION_UNITS}
    assert record["jednostki"] == [unit for other in sources if other != source for unit in kept[other]]
    assert record["zadanie"] == ("pytest" if source == "kroki" else "pytest (Python 3.14, 1/2)")


def _merge(folder: Path, output: Path) -> int:
    return main(["scal", "--katalog", str(folder), "--wyjscie", str(output)])


def _saved(folder: Path, name: str, *, run: int, attempt: int, job: str, tor: str = "windows-3.14", seconds: float = 1.0) -> None:
    record = {
        "wersja": 1,
        "run": run,
        "proba": attempt,
        "szablon": "pytest",
        "zadanie": job,
        "tor": tor,
        "zdarzenie": "push",
        "sha": f"sha{run}",
        "narzut_s": None,
        "jednostki": [{"klucz": "krok:pytest", "s": seconds, "status": "ok"}],
        "bledy": [],
    }
    folder.mkdir(parents=True, exist_ok=True)
    (folder / name).write_text(json.dumps(record), encoding="utf-8")


def test_scalenie_zapisow_runu_daje_obserwacje_kazdego_klucza_na_torze(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    for lane, (python, steps) in {"windows": ("Windows-3.14.0", PYTEST_STEPS), "linux": ("Linux-3.14.0", PYTEST_STEPS[1:2])}.items():
        paths = _inputs(tmp_path / lane, steps)
        main(["zadanie", "--tor", python, "--kroki", str(paths["kroki"]), "--junit", str(paths["junit"]), "--wyjscie", str(tmp_path / "zapisy" / f"{lane}.json")])
    capsys.readouterr()

    code = _merge(tmp_path / "zapisy", tmp_path / "czasy-ci.json")
    merged = json.loads((tmp_path / "czasy-ci.json").read_text(encoding="utf-8"))

    def observed(unit: dict[str, object]) -> list[dict[str, object]]:
        return [{"run": 40259456807, "proba": 2, "zadanie": "pytest (Python 3.14, 1/2)", "s": unit["s"], "status": unit["status"]}]

    assert code == 0
    assert merged["runy"] == [{"run": 40259456807, "proba": 2, "sha": ENV["GITHUB_SHA"], "zdarzenie": "push"}]
    assert merged["tory"] == {
        "linux-3.14": {
            "krok:pytest": observed(PYTEST_UNITS[1]),
            "narzut:pytest": observed({"s": 17.0, "status": "ok"}),
            **{str(unit["klucz"]): observed(unit) for unit in PYTEST_UNITS[3:]},
        },
        "windows-3.14": {
            **{str(unit["klucz"]): observed(unit) for unit in PYTEST_UNITS},
            "narzut:pytest": observed({"s": 17.0, "status": "ok"}),
        },
    }
    assert list(merged["tory"]["windows-3.14"]) == sorted(merged["tory"]["windows-3.14"])
    assert capsys.readouterr().out.splitlines() == [
        "CZASY CI | linux-3.14 | 7 kluczy, w tym 5 plików testów",
        "CZASY CI | windows-3.14 | 9 kluczy, w tym 5 plików testów",
        "CZASY CI SCALONE | 2 zapisów zadań | czasy-ci.json",
    ]


def test_scalenie_tych_samych_zapisow_daje_ten_sam_plik_niezaleznie_od_nazw_plikow(tmp_path: Path) -> None:
    records = [(2, 1, "A"), (1, 2, "A"), (1, 1, "B"), (1, 1, "A")]
    for index, (run, attempt, job) in enumerate(records):
        _saved(tmp_path / "po-kolei", f"{index}.json", run=run, attempt=attempt, job=job, seconds=index)
        _saved(tmp_path / "odwrotnie", f"{len(records) - index}.json", run=run, attempt=attempt, job=job, seconds=index)

    assert _merge(tmp_path / "po-kolei", tmp_path / "1.json") == 0
    assert _merge(tmp_path / "odwrotnie", tmp_path / "2.json") == 0
    merged = (tmp_path / "1.json").read_bytes()

    assert merged == (tmp_path / "2.json").read_bytes()
    observations = json.loads(merged)["tory"]["windows-3.14"]["krok:pytest"]
    assert [(o["run"], o["proba"], o["zadanie"], o["s"]) for o in observations] == [(1, 1, "A", 3), (1, 1, "B", 2), (1, 2, "A", 1), (2, 1, "A", 0)]
    assert [(run["run"], run["proba"]) for run in json.loads(merged)["runy"]] == [(1, 1), (1, 2), (2, 1)]


@pytest.mark.parametrize(
    ("broken", "error"),
    [
        ("katalog", "0-zly.json: IsADirectoryError(" if sys.platform != "win32" else "0-zly.json: PermissionError("),
        ("{", "0-zly.json: JSONDecodeError("),
        ('{"wersja": 2}', "0-zly.json: ValueError('wersja zapisu inna niż 1')"),
        ("{}", "0-zly.json: KeyError('wersja')"),
        ('{"wersja": 1, "jednostki": [], "nieznane": 1}', "0-zly.json: TypeError("),
    ],
)
def test_zepsuty_zapis_zadania_jest_zgloszony_a_scalenie_bierze_pozostale(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], broken: str, error: str
) -> None:
    _saved(tmp_path / "zapisy", "1-dobry.json", run=1, attempt=1, job="A")
    if broken == "katalog":
        (tmp_path / "zapisy" / "0-zly.json").mkdir()
    else:
        (tmp_path / "zapisy" / "0-zly.json").write_text(broken, encoding="utf-8")

    code = _merge(tmp_path / "zapisy", tmp_path / "czasy-ci.json")
    out = capsys.readouterr().out.splitlines()

    assert code == 1
    assert out[0].startswith(f"CZASY CI FAIL | {error}"), out
    assert out[-1] == "CZASY CI SCALONE | 1 zapisów zadań | czasy-ci.json"
    assert list(json.loads((tmp_path / "czasy-ci.json").read_text(encoding="utf-8"))["tory"]["windows-3.14"]) == ["krok:pytest"]


@pytest.mark.parametrize("records", [(), ("{",)])
def test_bez_zadnego_dobrego_zapisu_scalenie_nie_tworzy_czasow_ci(tmp_path: Path, capsys: pytest.CaptureFixture[str], records: tuple[str, ...]) -> None:
    (tmp_path / "zapisy").mkdir()
    for index, content in enumerate(records):
        (tmp_path / "zapisy" / f"{index}.json").write_text(content, encoding="utf-8")

    code = _merge(tmp_path / "zapisy", tmp_path / "czasy-ci.json")
    out = capsys.readouterr().out.splitlines()

    assert code == 1
    assert not (tmp_path / "czasy-ci.json").exists()
    assert len(out) == 1 and out[0].startswith("CZASY CI FAIL | "), out
    assert ("brak zapisów zadań w" in out[0]) == (not records)


def test_kazdy_krok_jednostki_jest_krokiem_ci_a_pytest_w_ci_zapisuje_junit_z_plikiem_testu() -> None:
    workflow = jobs()
    names = {step.get("name") for job in ("pytest", "mutations") for step in workflow[job]["steps"]}
    pytest_runs = [line for step in workflow["pytest"]["steps"] for line in step.get("run", "").splitlines() if "-m pytest" in line]

    assert set(KROKI) - names == set()
    assert len(pytest_runs) == 2
    assert tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["tool"]["pytest"]["ini_options"]["junit_family"] == "xunit1"
    assert all(line.endswith(" --junitxml .ci-czasy/junit.xml") for line in pytest_runs), pytest_runs
    for job in ("pytest", "mutations"):
        recorded = [step["run"] for step in workflow[job]["steps"] if "tools/czasy_ci.py zadanie" in step.get("run", "")]
        assert len(recorded) == 1 and "--kroki .ci-czasy/zadania.json" in recorded[0], job



@pytest.mark.parametrize(
    ("arguments", "missing"),
    [
        ([], "polecenie"),
        (["zadanie", "--kroki", "k.json", "--wyjscie", "z.json"], "--tor"),
        (["zadanie", "--tor", "Linux-3.14", "--wyjscie", "z.json"], "--kroki"),
        (["zadanie", "--tor", "Linux-3.14", "--kroki", "k.json"], "--wyjscie"),
        (["scal", "--wyjscie", "c.json"], "--katalog"),
        (["scal", "--katalog", "zapisy"], "--wyjscie"),
    ],
)
def test_wywolanie_bez_wymaganego_argumentu_konczy_sie_kodem_2_z_jego_nazwa(
    capsys: pytest.CaptureFixture[str], arguments: list[str], missing: str
) -> None:
    with pytest.raises(SystemExit) as stopped:
        main(arguments)

    assert stopped.value.code == 2
    assert capsys.readouterr().err.splitlines()[-1].endswith(f"the following arguments are required: {missing}")

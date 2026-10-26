"""Plan CI dzieli pytest trzech torów na zadania bez zgubionego i bez powtórzonego testu, mieści run w limicie zadań
konta, a Required przyjmuje tylko zapisy tego samego planu, w których każde zadanie zgłosiło każdą swoją jednostkę."""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterator
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys
import zlib

import pytest

from tests.fixtures.git_repo import commit, git, repository

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

import czasy_ci  # noqa: E402
import mutacje_zmiany  # noqa: E402
import plan_ci  # noqa: E402

FILES = [f"tests/test_{index:02}.py" for index in range(40)]
# Plik dłuższy niż zadanie, jak test_uszkodzone_wejscia: 1100 s testów na Windows.
LONG = "tests/test_dlugi.py"


def _times(per_file_s: float = 60.0) -> czasy_ci.Czasy:
    """Czasy jednego runu main: każdy plik ``per_file_s`` na każdym torze, ``LONG`` 1100 s, i dwa zadania pytest toru."""

    lanes: dict[str, dict[str, tuple[czasy_ci.Obserwacja, ...]]] = {}
    for lane in plan_ci.TORY:
        keys: dict[str, tuple[czasy_ci.Obserwacja, ...]] = {f"pytest:{name}": (czasy_ci.Obserwacja(1, "A", per_file_s),) for name in FILES}
        keys[f"pytest:{LONG}"] = (czasy_ci.Obserwacja(1, "B", 1100.0),)
        keys["narzut:pytest"] = (czasy_ci.Obserwacja(1, "A", 14.0), czasy_ci.Obserwacja(1, "B", 16.0))
        keys["krok:pytest"] = (czasy_ci.Obserwacja(1, "A", 20.0 * per_file_s / 4 + 30), czasy_ci.Obserwacja(1, "B", 1100.0 / 4 + 30))
        keys["krok:e2e"] = (czasy_ci.Obserwacja(1, "A", 61.0),)
        lanes[lane.nazwa] = keys
    return czasy_ci.Czasy((1,), lanes)


def _plan(czasy: czasy_ci.Czasy, files: list[str], mutations: int = 0) -> plan_ci.Plan:
    return plan_ci.rozplanuj([plan_ci.wycen(lane, files, czasy) for lane in plan_ci.TORY], "pull_request", mutations, czasy.runy)


def _run_jobs(plan: plan_ci.Plan) -> int:
    return plan_ci.STALE_ZADANIA + len(plan.zadania) + (plan_ci.ZADANIA_ZMIANY if plan.mutacje_zmiany else 0)


@pytest.mark.parametrize("mutations", [0, 12])
def test_kazdy_plik_testow_biegnie_raz_na_kazdym_torze_a_udzialy_dlugiego_pliku_pokrywaja_go_raz(mutations: int) -> None:
    plan = _plan(_times(), [*FILES, LONG], mutations)

    for lane in plan_ci.TORY:
        units = Counter(unit for job in plan.zadania if job.tor == lane.nazwa for unit in job.jednostki)
        shares = sorted(unit for unit in units if unit.startswith(f"pytest:{LONG}#"))
        count = len(shares)
        longest = max(job.sciana_s for job in plan.zadania if job.tor == lane.nazwa)

        assert set(units.values()) == {1}, lane
        assert {unit for unit in units if "#" not in unit} - {f"pytest:{LONG}"} == {*(f"pytest:{name}" for name in FILES), *(f"krok:{step}" for step in lane.kroki)}
        assert shares == [f"pytest:{LONG}#{share}/{count}" for share in range(1, count + 1)], shares
        # Cały plik albo jego udziały, a cały tylko wtedy, gdy zmieścił się w celu ściany.
        assert (f"pytest:{LONG}" in units) == (count == 0) == (1100 / plan_ci.WORKERY < longest <= plan.cel_s), (lane, plan.cel_s)
    assert [job.id for job in plan.zadania if "krok:timing" in job.jednostki] != [] == [job for job in plan.zadania if "krok:timing" in job.jednostki and job.tor != "windows-3.14"]


@pytest.mark.parametrize("mutations", [0, 12])
def test_run_miesci_sie_w_limicie_zadan_konta_bo_cel_sciany_rosnie_co_5_s(mutations: int, monkeypatch: pytest.MonkeyPatch) -> None:
    czasy = _times(per_file_s=150.0)
    plan = _plan(czasy, [*FILES, LONG], mutations)
    monkeypatch.setattr(plan_ci, "ZADANIA_RUNU", 100)
    unlimited = _plan(czasy, [*FILES, LONG], mutations)

    assert _run_jobs(plan) <= plan_ci.ZADANIA_RUNU == 100
    assert _run_jobs(plan) <= 19 < _run_jobs(unlimited)
    assert unlimited.cel_s == plan_ci.CEL_S < plan.cel_s
    assert (plan.cel_s - plan_ci.CEL_S) % plan_ci.KROK_CELU_S == 0
    assert max(job.sciana_s for job in plan.zadania) <= plan.cel_s
    assert max(job.sciana_s for job in unlimited.zadania) <= plan_ci.CEL_S


def test_ten_sam_stan_daje_ten_sam_plan_a_zadania_maja_rozne_nazwy() -> None:
    first, again = _plan(_times(), [*FILES, LONG]), _plan(_times(), [*FILES, LONG])

    assert first.digest == again.digest
    assert len({job.nazwa for job in first.zadania}) == len({job.id for job in first.zadania}) == len(first.zadania)


def test_tor_bez_pracy_nie_ma_zadan_a_bez_zadnej_pracy_macierz_jest_pusta(monkeypatch: pytest.MonkeyPatch) -> None:
    with_steps = _plan(czasy_ci.Czasy((), {}), [])
    monkeypatch.setattr(plan_ci, "TORY", tuple(plan_ci.Tor(lane.nazwa, lane.os, lane.python, (), lane.etykieta) for lane in plan_ci.TORY))
    empty = _plan(czasy_ci.Czasy((), {}), [])

    assert {job.tor for job in with_steps.zadania} == {"windows-3.11", "windows-3.14"}
    assert empty.macierz() == []
    assert plan_ci.werdykt(empty, {"plan": "success", "pytest": "skipped", "change-mutations": "skipped"}, []) == []
    assert plan_ci.werdykt(with_steps, {"plan": "success", "pytest": "skipped", "change-mutations": "skipped"}, []) == [
        "pytest=skipped",
        *(f"{job.nazwa}: brak zapisu czasów z tego planu, więc nic nie dowodzi, że jego jednostki biegły" for job in with_steps.zadania),
    ]


def _record(plan: plan_ci.Plan, job: plan_ci.Zadanie, units: list[str], *, attempt: int = 1, digest: str | None = None) -> czasy_ci.Zapis:
    reported = tuple(czasy_ci.Jednostka(unit, 1.0, "ok") for unit in units)
    return czasy_ci.Zapis(1, attempt, "pytest", job.nazwa, job.tor, "pull_request", "0" * 40, 9.0, reported, (), digest or plan.digest, job.id)


def test_required_czerwienieje_gdy_zaplanowana_jednostka_nie_zglosila_wyniku_w_ostatniej_probie_zadania() -> None:
    plan = _plan(_times(), [*FILES, LONG])
    results = {"plan": "success", "pytest": "success", "change-mutations": "skipped"}
    complete = [_record(plan, job, [unit.partition("#")[0] for unit in job.jednostki]) for job in plan.zadania]
    split = next(job for job in plan.zadania if any("#" in unit for unit in job.jednostki))
    missing = f"pytest:{LONG}"
    partial = _record(plan, split, [unit.partition("#")[0] for unit in split.jednostki if not unit.startswith(missing)], attempt=2)

    assert plan_ci.werdykt(plan, results, complete) == []
    assert plan_ci.werdykt(plan, results, [*complete, partial]) == [f"{split.nazwa}: jednostki bez wyniku: {missing}"]
    assert plan_ci.werdykt(plan, results, [partial, *(record for record in complete if record.zadanie_planu != split.id)]) == [
        f"{split.nazwa}: jednostki bez wyniku: {missing}"
    ]


def test_plan_zmieniony_po_digest_nie_wykonuje_sie_a_required_nie_bierze_zapisow_innego_planu(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    plan = _plan(_times(), [*FILES, LONG])
    tampered = json.loads(plan.do_json())
    tampered["zadania"][0]["jednostki"] = tampered["zadania"][0]["jednostki"][1:]
    (tmp_path / "plan.json").write_text(json.dumps(tampered), encoding="utf-8")
    other = [_record(plan, job, [unit.partition("#")[0] for unit in job.jednostki], digest="inny") for job in plan.zadania]

    code = plan_ci.main(["wykonaj", "--plan", str(tmp_path / "plan.json"), "--zadanie", plan.zadania[0].id])

    assert code == 1
    assert capsys.readouterr().out.startswith(f"WYKONANIE FAIL | plan {(tmp_path / 'plan.json').as_posix()}: treść planu nie zgadza się z jego digest {plan.digest[:12]}")
    assert len(plan_ci.werdykt(plan, {"plan": "success"}, other)) == len(plan.zadania)


def test_bez_czasow_z_main_plan_wazy_prace_domyslnie_mowi_to_i_daje_macierz(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    def offline(*arguments: str) -> str:
        raise subprocess.CalledProcessError(1, ["gh", *arguments], stderr="gh: not logged in")

    monkeypatch.setattr(czasy_ci, "_gh", offline)
    monkeypatch.setenv("GITHUB_OUTPUT", str(tmp_path / "output"))

    code = plan_ci.main(["plan", "--zdarzenie", "push", "--czasy", str(tmp_path / "czasy"), "--wyjscie", str(tmp_path / "plan.json")])
    out = capsys.readouterr().out.splitlines()
    plan = plan_ci.Plan.z_json((tmp_path / "plan.json").read_text(encoding="utf-8"))
    output = dict(line.split("=", 1) for line in (tmp_path / "output").read_text(encoding="utf-8").splitlines())

    assert code == 0
    assert out[0] == "CZASY CI | pobranie czasy-ci z GitHuba: gh: not logged in; plan waży pracę bez pomiaru domyślnie"
    assert out[1].startswith("PLAN CI | push | cel 225 s | ") and out[1].endswith("| mutacje zmiany 0 | czasy z runów main: brak (wagi domyślne)")
    assert out[-1] == f"PLAN CI DIGEST | {plan.digest}"
    assert {unit for job in plan.zadania if job.tor == "linux-3.14" for unit in job.jednostki} == {f"pytest:{name}" for name in plan_ci.pliki_testow()}
    assert (json.loads(output["pytest"]), output["mutacje-zmiany"]) == (plan.macierz(), "0")


def test_kroki_planu_uruchamiaja_skrypty_repozytorium_kazde_polecenie_z_limitem_czasu() -> None:
    for step in plan_ci.KROKI.values():
        assert len(step.polecenia) == len(step.limity_s) and all(limit > 0 for limit in step.limity_s), step.nazwa
        for command in step.polecenia:
            python, script, *_ = command.split()
            assert python == "{python}" and (ROOT / script).is_file(), command


@pytest.fixture
def mini_repo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Path]:
    """Repozytorium z plikiem 30 testów, z których 3 padają, i pluginem udziałów; w nim biegnie ``wykonaj``."""

    (tmp_path / "tools").mkdir()
    shutil.copy2(ROOT / "tools" / "pytest_czesc.py", tmp_path / "tools" / "pytest_czesc.py")
    (tmp_path / "tests").mkdir()
    cases = "\n".join(f"def test_{index:02}() -> None:\n    assert {index % 10 != 7}\n" for index in range(30))
    (tmp_path / "tests" / "test_mini.py").write_text(cases, encoding="utf-8")
    (tmp_path / "pytest.ini").write_text("[pytest]\njunit_family = xunit1\n", encoding="utf-8")
    monkeypatch.setattr(plan_ci, "ROOT", tmp_path)
    monkeypatch.chdir(tmp_path)
    # ``wykonaj`` uruchamia pytest z ``-n auto``: tu jeden worker, bo test sam biegnie w workerze xdist.
    monkeypatch.setenv("PYTEST_XDIST_AUTO_NUM_WORKERS", "1")
    yield tmp_path


def _junit_tests() -> set[str]:
    return set(re.findall(r'name="(test_\d+)"', plan_ci.JUNIT.read_text(encoding="utf-8")))


def test_udzialy_pliku_dziela_go_miedzy_zadania_bez_luk_i_powtorzen_niezaleznie_od_pythonhashseed(mini_repo: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    jobs = tuple(plan_ci.Zadanie(f"linux-3.14-{share}", "linux-3.14", f"pytest (Python 3.14, Linux, {share}/3)", (f"pytest:tests/test_mini.py#{share}/3",), 1.0) for share in (1, 2, 3))
    plan = plan_ci.Plan("push", plan_ci.CEL_S, (), 0, jobs)
    ran = []
    for share, seed in zip((1, 2, 3), ("0", "1", "random"), strict=True):
        monkeypatch.setenv("PYTHONHASHSEED", seed)
        plan_ci.wykonaj(plan, f"linux-3.14-{share}")
        ran.append(_junit_tests())

    assert Counter(test for tests in ran for test in tests) == Counter(f"test_{index:02}" for index in range(30))
    assert all(ran) and ran == [{f"test_{i:02}" for i in range(30) if zlib.crc32(f"tests/test_mini.py::test_{i:02}".encode()) % 3 == share} for share in range(3)]


def test_zadanie_wykonuje_kroki_po_czerwonym_pytest_przerywa_krok_po_limicie_i_zapisuje_wynik_z_planem(
    mini_repo: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    (mini_repo / "wisi.py").write_text("import time\n\ntime.sleep(60)\n", encoding="utf-8")
    (mini_repo / "zapisuje.py").write_text("import pathlib, sys\n\npathlib.Path(sys.argv[1]).touch()\n", encoding="utf-8")
    quick = plan_ci.Krok("szybki", ("{python} zapisuje.py biegl",), (60.0,), 1.0)
    hung = plan_ci.Krok("wiszacy", ("{python} wisi.py", "{python} zapisuje.py nie-biegnie"), (1.0, 60.0), 1.0)
    monkeypatch.setattr(plan_ci, "KROKI", {step.nazwa: step for step in (quick, hung)})
    job = plan_ci.Zadanie("windows-3.14-1", "windows-3.14", "pytest (Python 3.14, 1/1)", ("pytest:tests/test_mini.py", "krok:wiszacy", "krok:szybki"), 1.0)
    plan = plan_ci.Plan("push", plan_ci.CEL_S, (), 0, (job,))

    code = plan_ci.wykonaj(plan, job.id)
    result = json.loads(plan_ci.WYKONANIE.read_text(encoding="utf-8"))

    assert code == 1
    assert len(_junit_tests()) == 30
    assert (result["plan"], result["zadanie"]) == (plan.digest, job.id)
    assert [(unit["klucz"], unit["status"]) for unit in result["jednostki"]] == [("krok:pytest", "fail"), ("krok:wiszacy", "fail"), ("krok:szybki", "ok")]
    assert ((mini_repo / "nie-biegnie").exists(), (mini_repo / "biegl").exists()) == (False, True)
    assert capsys.readouterr().out.splitlines()[-1] == "WYKONANIE FAIL | krok:pytest, krok:wiszacy"


@pytest.mark.parametrize(("changed", "mutated"), [("src/pakiet/a.py", True), ("tests/test_a.py", False)])
def test_change_mutations_startuja_tylko_gdy_zmiana_ma_mutacje(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, changed: str, mutated: bool) -> None:
    repo = repository(tmp_path / "repo", {"src/pakiet/a.py": "def a(x: int) -> bool:\n    return x > 1\n", "tests/test_a.py": "def test_a() -> None:\n    pass\n"})
    commit(repo, "baza")
    git(repo, "branch", "baza")
    with (repo / changed).open("a", encoding="utf-8") as file:
        file.write("\n\ndef b(x: int) -> bool:\n    return x < 3\n")
    commit(repo, "zmiana")
    for module in (plan_ci, mutacje_zmiany):
        monkeypatch.setattr(module, "ROOT", repo)

    assert (plan_ci.liczba_mutacji_zmiany("baza") > 0) == mutated

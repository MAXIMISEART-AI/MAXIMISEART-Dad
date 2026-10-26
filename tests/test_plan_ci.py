"""Plan CI dzieli pytest trzech torów i wybrane kroki skilli na zadania bez zgubionego i bez powtórzonego testu, kroku
albo mutacji, mieści run w limicie zadań konta, a Required przyjmuje tylko zapisy tego samego planu, w których każde
zadanie zgłosiło każdą swoją jednostkę."""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterator
import dataclasses
import json
import math
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
import mutacje_skilli  # noqa: E402
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


# Kroki skilli: czas w CI, liczba mutacji skryptu (podstawa: 0) i czy skill używa Chromium.
SKILL_STEPS = {
    "verify-a/ci": (300.0, 0, True),
    "verify-a/check_a_mutations.py": (900.0, 12, True),
    "verify-b/check_b_mutations.py": (1100.0, 2, False),
    "verify-c/ci": (30.0, 0, False),
    "verify-c/check_c_mutations.py": (60.0, 5, False),
    "verify-d/check_d_mutations.py": (80.0, 3, False),
}


def _skill_steps(keys: list[str]) -> list[mutacje_skilli.Step]:
    skills = ROOT / ".agents" / "skills"
    return [
        mutacje_skilli.Step(skills / key.split("/")[0], key, key, (key,), None if key.endswith("/ci") else mutacje_skilli.VERDICT, SKILL_STEPS[key][1], SKILL_STEPS[key][2])
        for key in keys
    ]


def _with_skill_times(czasy: czasy_ci.Czasy) -> czasy_ci.Czasy:
    """Czasy z pomiarem każdego kroku ``SKILL_STEPS`` i narzutem dwóch zadań Mutation checks z runu 1."""

    lane = plan_ci.MUTACJE.pomiary
    keys: dict[str, tuple[czasy_ci.Obserwacja, ...]] = {f"skill:{key}": (czasy_ci.Obserwacja(1, "M", s),) for key, (s, _, _) in SKILL_STEPS.items()}
    keys["narzut:mutations"] = (czasy_ci.Obserwacja(1, "M", 40.0), czasy_ci.Obserwacja(1, "N", 46.0))
    return czasy_ci.Czasy(czasy.runy, {**czasy.tory, lane: {**czasy.tory.get(lane, {}), **keys}})


def _plan(czasy: czasy_ci.Czasy, files: list[str], mutations: int = 0, steps: list[mutacje_skilli.Step] | None = None) -> plan_ci.Plan:
    lanes = [plan_ci.wycen(lane, files, czasy) for lane in plan_ci.TORY]
    skills = [] if steps is None else [plan_ci.wycen_mutacje(steps, czasy)]
    return plan_ci.rozplanuj([*lanes, *skills], "pull_request", mutations, czasy.runy)


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


@pytest.mark.parametrize(("mutations", "skills"), [(0, False), (12, False), (0, True), (12, True)])
def test_run_miesci_sie_w_limicie_zadan_konta_bo_cel_sciany_rosnie_co_5_s(mutations: int, skills: bool, monkeypatch: pytest.MonkeyPatch) -> None:
    czasy = _with_skill_times(_times(per_file_s=150.0))
    steps = _skill_steps(list(SKILL_STEPS)) if skills else None
    plan = _plan(czasy, [*FILES, LONG], mutations, steps)
    monkeypatch.setattr(plan_ci, "ZADANIA_RUNU", 100)
    unlimited = _plan(czasy, [*FILES, LONG], mutations, steps)

    assert _run_jobs(plan) <= plan_ci.ZADANIA_RUNU == 100
    assert _run_jobs(plan) <= 19 < _run_jobs(unlimited)
    assert unlimited.cel_s == plan_ci.CEL_S < plan.cel_s
    assert (plan.cel_s - plan_ci.CEL_S) % plan_ci.KROK_CELU_S == 0
    # Jeden cel dla wszystkich torów: Mutation checks dzielą limit zadań z pytest, a nie biorą go przed nimi. Dłużej
    # trwa tylko zadanie z jedną jednostką, której nie da się podzielić (podstawa, skrypt z dwiema mutacjami).
    assert all(job.sciana_s <= plan.cel_s or len(job.jednostki) == 1 for job in plan.zadania)
    assert all(job.sciana_s <= plan_ci.CEL_S or len(job.jednostki) == 1 for job in unlimited.zadania)
    assert bool(plan.macierz("mutations")) == skills


def test_kazdy_wybrany_krok_skilla_biegnie_raz_a_skrypt_dluzszy_od_zadania_w_czesciach_najwyzej_po_jednej_na_mutacje() -> None:
    chosen = [key for key in SKILL_STEPS if key != "verify-d/check_d_mutations.py"]
    plan = _plan(_with_skill_times(_times()), [*FILES, LONG], steps=_skill_steps(chosen))
    jobs = [job for job in plan.zadania if job.tor == plan_ci.MUTACJE.nazwa]
    units = Counter(unit for job in jobs for unit in job.jednostki)
    parts = {key: sorted(unit for unit in units if unit.partition("#")[0] == f"skill:{key}") for key in SKILL_STEPS}

    assert set(units.values()) == {1}
    assert parts["verify-d/check_d_mutations.py"] == []
    for key in chosen:
        count = len(parts[key]) if "#" in parts[key][0] else 0
        assert parts[key] == ([f"skill:{key}#{part}/{count}" for part in range(1, count + 1)] or [f"skill:{key}"]), parts[key]
        assert count <= SKILL_STEPS[key][1], key
    # Podstawy się nie dzieli; skrypt dłuższy od zadania tak, ale nie na więcej części, niż ma mutacji.
    capacity = plan.cel_s - 43.0 - plan_ci.DOMYSLNIE.koniec_s
    assert parts["verify-a/ci"] == ["skill:verify-a/ci"]
    assert len(parts["verify-a/check_a_mutations.py"]) == math.ceil(900.0 / capacity) > 1
    assert len(parts["verify-b/check_b_mutations.py"]) == 2 < 1100.0 / capacity
    # Części jednego skryptu biegną w różnych zadaniach, bo każda waży tyle, że dwie przekroczyłyby cel.
    assert all(len({unit.partition("#")[0] for unit in job.jednostki}) == len(job.jednostki) for job in jobs)
    assert [job.przegladarka for job in jobs] == [any(unit.startswith("skill:verify-a/") for unit in job.jednostki) for job in jobs]
    assert [entry["przegladarka"] for entry in plan.macierz("mutations")] == [job.przegladarka for job in jobs]
    assert all(job.sciana_s <= plan.cel_s or len(job.jednostki) == 1 for job in jobs)


def test_w_zadaniu_podstawa_skilla_biegnie_przed_jego_skryptami_mutacji() -> None:
    plan = _plan(_with_skill_times(_times()), FILES, steps=_skill_steps(["verify-c/check_c_mutations.py", "verify-c/ci"]))

    assert [job.jednostki for job in plan.zadania if job.tor == plan_ci.MUTACJE.nazwa] == [("skill:verify-c/ci", "skill:verify-c/check_c_mutations.py")]


def test_ten_sam_stan_daje_ten_sam_plan_a_zadania_maja_rozne_nazwy() -> None:
    first, again = _plan(_times(), [*FILES, LONG]), _plan(_times(), [*FILES, LONG])

    assert first.digest == again.digest
    assert len({job.nazwa for job in first.zadania}) == len({job.id for job in first.zadania}) == len(first.zadania)


def test_tor_bez_pracy_nie_ma_zadan_a_bez_zadnej_pracy_macierz_jest_pusta(monkeypatch: pytest.MonkeyPatch) -> None:
    with_steps = _plan(czasy_ci.Czasy((), {}), [], steps=[])
    monkeypatch.setattr(plan_ci, "TORY", tuple(dataclasses.replace(lane, kroki=()) for lane in plan_ci.TORY))
    empty = _plan(czasy_ci.Czasy((), {}), [], steps=[])
    skipped = {"plan": "success", "pytest": "skipped", "mutations": "skipped", "change-mutations": "skipped"}

    assert {job.tor for job in with_steps.zadania} == {"windows-3.11", "windows-3.14"}
    assert (empty.macierz("pytest"), empty.macierz("mutations"), with_steps.macierz("mutations")) == ([], [], [])
    assert plan_ci.werdykt(empty, skipped, []) == []
    assert plan_ci.werdykt(with_steps, skipped, []) == [
        "pytest=skipped",
        *(f"{job.nazwa}: brak zapisu czasów z tego planu, więc nic nie dowodzi, że jego jednostki biegły" for job in with_steps.zadania),
    ]


def _record(
    plan: plan_ci.Plan, job: plan_ci.Zadanie, units: list[str], *, attempt: int = 1, digest: str | None = None, failed: frozenset[str] = frozenset()
) -> czasy_ci.Zapis:
    reported = tuple(czasy_ci.Jednostka(unit, 1.0, "fail" if unit in failed else "ok") for unit in units)
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


def test_required_czerwienieje_gdy_jednostka_zadania_padla_w_ostatniej_probie_a_przechodzi_po_ponowieniu_zadania() -> None:
    plan = _plan(_times(), [*FILES, LONG])
    results = {"plan": "success", "pytest": "success", "change-mutations": "skipped"}
    complete = [_record(plan, job, [unit.partition("#")[0] for unit in job.jednostki]) for job in plan.zadania]
    job = next(job for job in plan.zadania if "krok:e2e" in job.jednostki)
    units = [unit.partition("#")[0] for unit in job.jednostki]
    failed = _record(plan, job, units, failed=frozenset({units[0], "krok:e2e"}))
    others = [record for record in complete if record.zadanie_planu != job.id]

    assert plan_ci.werdykt(plan, results, [*others, failed]) == [f"{job.nazwa}: jednostki z porażką: {', '.join(sorted({units[0], 'krok:e2e'}))}"]
    assert plan_ci.werdykt(plan, results, [*others, failed, _record(plan, job, units, attempt=2)]) == []


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

    # Baza HEAD nie ma zmian, więc tylko push, który bazę pomija, wybiera każdy krok (ADR 0014).
    code = plan_ci.main(["plan", "--zdarzenie", "push", "--baza", "HEAD", "--czasy", str(tmp_path / "czasy"), "--wyjscie", str(tmp_path / "plan.json")])
    out = capsys.readouterr().out.splitlines()
    plan = plan_ci.Plan.z_json((tmp_path / "plan.json").read_text(encoding="utf-8"))
    output = dict(line.split("=", 1) for line in (tmp_path / "output").read_text(encoding="utf-8").splitlines())

    every_step = {f"skill:{step.key}" for step in mutacje_skilli.steps({})}
    planned_steps = {unit.partition("#")[0] for job in plan.zadania if job.tor == plan_ci.MUTACJE.nazwa for unit in job.jednostki}

    assert code == 0
    assert out[0] == "CZASY CI | pobranie czasy-ci z GitHuba: gh: not logged in; plan waży pracę bez pomiaru domyślnie"
    assert re.fullmatch(r"PLAN CI \| push \| cel \d+ s \| (\d+) zadań runu \(limit 19\) \| mutacje zmiany 0 \| czasy z runów main: brak \(wagi domyślne\)", out[1]), out[1]
    assert out[-1] == f"PLAN CI DIGEST | {plan.digest}"
    assert {unit for job in plan.zadania if job.tor == "linux-3.14" for unit in job.jednostki} == {f"pytest:{name}" for name in plan_ci.pliki_testow()}
    # Push biegnie każdy krok każdego skilla repozytorium.
    assert planned_steps == every_step != set()
    assert (json.loads(output["pytest"]), json.loads(output["mutations"]), output["mutacje-zmiany"]) == (plan.macierz("pytest"), plan.macierz("mutations"), "0")


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
    (mini_repo / "plan.json").write_text(plan.do_json(), encoding="utf-8")

    code = plan_ci.main(["wykonaj", "--plan", str(mini_repo / "plan.json"), "--zadanie", job.id])
    result = json.loads(plan_ci.WYKONANIE.read_text(encoding="utf-8"))

    assert code == 1
    assert len(_junit_tests()) == 30
    assert (result["plan"], result["zadanie"]) == (plan.digest, job.id)
    assert [(unit["klucz"], unit["status"]) for unit in result["jednostki"]] == [("krok:pytest", "fail"), ("krok:wiszacy", "fail"), ("krok:szybki", "ok")]
    assert ((mini_repo / "nie-biegnie").exists(), (mini_repo / "biegl").exists()) == (False, True)
    assert capsys.readouterr().out.splitlines()[-1] == "WYKONANIE FAIL | krok:pytest, krok:wiszacy"


def test_zadanie_mutation_checks_uruchamia_po_kolei_swoje_kroki_skilli_a_czesc_skryptu_z_jej_numerem(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    log = tmp_path / "uruchomienia"
    records = f"import os, sys\nopen({str(log)!r}, 'a').write(os.path.basename(sys.argv[0]) + ' ' + os.environ.get('MUTACJE_CZESC', 'bez-czesci') + chr(10))\n"
    files = {
        "verify-a/SKILL.md": "---\nname: verify-a\nci: .agents/skills/verify-a/scripts/sprawdz.py\n---\n",
        "verify-a/scripts/sprawdz.py": records,
        "verify-a/scripts/check_a_mutations.py": f"MUTATIONS = ()\nif __name__ == '__main__':\n    {records.replace(chr(10), chr(10) + '    ').rstrip()}\n    print('MUTACJE OK')\n",
        "verify-b/SKILL.md": "",
        "verify-b/scripts/check_b_mutations.py": "MUTATIONS = ()\nif __name__ == '__main__':\n    raise SystemExit(1)\n",
    }
    for name, text in files.items():
        (tmp_path / ".agents" / "skills" / name).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / ".agents" / "skills" / name).write_text(text, encoding="utf-8")
    monkeypatch.setattr(mutacje_skilli, "ROOT", tmp_path)
    monkeypatch.setattr(mutacje_skilli, "SKILLS", tmp_path / ".agents" / "skills")
    monkeypatch.chdir(tmp_path)
    script = "skill:verify-a/check_a_mutations.py"
    # Krok z planu, którego zadanie nie znajduje wśród kroków skilli (plan i zadanie policzyły je inaczej), nie biegł.
    lost = "skill:verify-c/check_c_mutations.py"
    jobs = (
        plan_ci.Zadanie(
            "mutacje-1", "mutacje", "Mutation checks (1/2)", ("skill:verify-a/ci", f"{script}#1/2", "skill:verify-b/check_b_mutations.py", lost), 1.0
        ),
        plan_ci.Zadanie("mutacje-2", "mutacje", "Mutation checks (2/2)", (f"{script}#2/2",), 1.0),
    )
    plan = plan_ci.Plan("push", plan_ci.CEL_S, (), 0, jobs)
    results = []
    for job in jobs:
        code = plan_ci.wykonaj(plan, job.id)
        units = json.loads(plan_ci.WYKONANIE.read_text(encoding="utf-8"))["jednostki"]
        results.append((code, [(unit["klucz"], unit["status"]) for unit in units], capsys.readouterr().out.splitlines()[-1]))

    assert results == [
        (
            1,
            [("skill:verify-a/ci", "ok"), (script, "ok"), ("skill:verify-b/check_b_mutations.py", "fail"), (lost, "fail")],
            f"WYKONANIE FAIL | skill:verify-b/check_b_mutations.py, {lost}",
        ),
        (0, [(script, "ok")], "WYKONANIE OK | Mutation checks (2/2)"),
    ]
    # Podstawa biegnie cała, a każda część skryptu mutacji dostaje swój numer.
    assert log.read_text(encoding="utf-8").splitlines() == ["sprawdz.py bez-czesci", "check_a_mutations.py 1/2", "check_a_mutations.py 2/2"]


MALFORMED = "src/pakiet/a.py:4: wyjątek musi mieć postać `# mutacje-zmiany: <powód> | do RRRR-MM-DD | zgoda <kto>`"


SKILL = {
    ".agents/skills/verify-a/SKILL.md": "---\nname: verify-a\npilnuje:\n  - src/pakiet/*.py\n---\n",
    ".agents/skills/verify-a/scripts/check_a_mutations.py": "MUTATIONS = ()\n",
}
SKILL_SCRIPT = ".agents/skills/verify-a/scripts/check_a_mutations.py"


@pytest.mark.parametrize(
    ("changed", "appended", "started", "reported"),
    [
        ("src/pakiet/a.py", "\n\ndef b(x: int) -> bool:\n    return x < 3\n", True, [f"WYBRANY {SKILL_SCRIPT} (zmienione: src/pakiet/a.py)"]),
        ("tests/test_a.py", "\n\ndef b(x: int) -> bool:\n    return x < 3\n", False, [f"POMINIĘTY {SKILL_SCRIPT}: "]),
        # Sam komentarz nie ma mutacji, ale zadanie Change mutations zgłasza zły wyjątek jako MUTACJE ZMIANY FAIL.
        (
            "src/pakiet/a.py",
            "\n# mutacje-zmiany: bez terminu\n",
            True,
            [f"MUTACJE ZMIANY | {MALFORMED}; Change mutations startują, żeby to zgłosić", f"WYBRANY {SKILL_SCRIPT} (zmienione: src/pakiet/a.py)"],
        ),
    ],
    ids=["zmiana src", "zmiana testów", "sam komentarz src ze złym wyjątkiem"],
)
def test_plan_pull_requestu_startuje_change_mutations_i_mutation_checks_tylko_z_praca_od_zmiany(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], changed: str, appended: str, started: bool, reported: list[str]
) -> None:
    def offline(*arguments: str) -> str:
        raise subprocess.CalledProcessError(1, ["gh", *arguments], stderr="gh: not logged in")

    repo = repository(tmp_path / "repo", {"src/pakiet/a.py": "def a(x: int) -> bool:\n    return x > 1\n", "tests/test_a.py": "def test_a() -> None:\n    pass\n", **SKILL})
    commit(repo, "baza")
    git(repo, "branch", "baza")
    with (repo / changed).open("a", encoding="utf-8") as file:
        file.write(appended)
    commit(repo, "zmiana")
    for module in (plan_ci, mutacje_zmiany, mutacje_skilli):
        monkeypatch.setattr(module, "ROOT", repo)
    monkeypatch.setattr(mutacje_skilli, "SKILLS", repo / ".agents" / "skills")
    monkeypatch.setattr(czasy_ci, "_gh", offline)
    monkeypatch.setenv("GITHUB_OUTPUT", str(tmp_path / "output"))

    code = plan_ci.main(["plan", "--zdarzenie", "pull_request", "--baza", "baza", "--czasy", str(tmp_path / "czasy"), "--wyjscie", str(tmp_path / "plan.json")])
    out = capsys.readouterr().out
    planned = plan_ci.Plan.z_json((tmp_path / "plan.json").read_text(encoding="utf-8")).mutacje_zmiany
    output = dict(line.split("=", 1) for line in (tmp_path / "output").read_text(encoding="utf-8").splitlines())

    mutation_checks = [entry["nazwa"] for entry in json.loads(output["mutations"])]

    assert (code, planned > 0, output["mutacje-zmiany"]) == (0, started, str(planned)), out
    assert f"| mutacje zmiany {planned} |" in out, out
    # Zmiana spoza pilnuje i plików skilla nie daje Mutation checks żadnego zadania.
    assert mutation_checks == (["Mutation checks (1/1)"] if started else [])
    shown = [line for line in out.splitlines() if line.startswith(("MUTACJE ZMIANY", "WYBRANY", "POMINIĘTY"))]
    assert len(shown) == len(reported) and all(line.startswith(start) for line, start in zip(shown, reported, strict=True)), out


@pytest.mark.parametrize(
    ("files", "failure"),
    [
        (
            {".agents/skills/verify-a/scripts/check_mutation_proba.py": "MUTATIONS = ()\n"},
            ".agents/skills/verify-a/scripts/check_mutation_proba.py: nazwa spoza wzorca scripts/check_*_mutations.py",
        ),
        (
            {".agents/skills/verify-b/SKILL.md": "---\nname: verify-b\nci: brak.py\n---\n"},
            "PODSTAWA verify-b: ci w .agents/skills/verify-b/SKILL.md nie zaczyna się skryptem .py z repozytorium",
        ),
    ],
    ids=["skrypt mutacji spoza wzorca", "zły klucz ci"],
)
def test_zgubiony_skrypt_mutacji_albo_zly_klucz_ci_trafia_z_wyboru_do_planu_i_czerwieni_required(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], files: dict[str, str], failure: str
) -> None:
    def offline(*arguments: str) -> str:
        raise subprocess.CalledProcessError(1, ["gh", *arguments], stderr="gh: not logged in")

    repo = repository(tmp_path / "repo", {"src/pakiet/a.py": "def a(x: int) -> bool:\n    return x > 1\n", **SKILL})
    commit(repo, "baza")
    git(repo, "branch", "baza")
    for name, text in files.items():
        (repo / name).parent.mkdir(parents=True, exist_ok=True)
        (repo / name).write_text(text, encoding="utf-8")
    commit(repo, "zmiana")
    for module in (plan_ci, mutacje_zmiany, mutacje_skilli):
        monkeypatch.setattr(module, "ROOT", repo)
    monkeypatch.setattr(mutacje_skilli, "SKILLS", repo / ".agents" / "skills")
    monkeypatch.setattr(czasy_ci, "_gh", offline)

    code = plan_ci.main(["plan", "--zdarzenie", "pull_request", "--baza", "baza", "--czasy", str(tmp_path / "czasy"), "--wyjscie", str(tmp_path / "plan.json")])
    plan = plan_ci.Plan.z_json((tmp_path / "plan.json").read_text(encoding="utf-8"))
    every_job_green = {"plan": "success", "pytest": "success", "mutations": "success", "change-mutations": "success"}
    complete = [_record(plan, job, [unit.partition("#")[0] for unit in job.jednostki]) for job in plan.zadania]

    assert code == 0
    assert f"FAIL {failure}" in capsys.readouterr().out.splitlines()
    assert plan.bledy == (failure,)
    assert plan_ci.werdykt(plan, every_job_green, complete) == [f"mutacje skilli: {failure}"]

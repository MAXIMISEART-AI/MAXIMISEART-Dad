"""``tools/mutacje_skilli.py`` nie przepuszcza skryptu mutacji, który zgubił się albo nie dał werdyktu.

Każdy test buduje własne ``.agents/skills`` obok kopii narzędzia, więc narzędzie widzi tylko te skille.
"""

from __future__ import annotations

import contextlib
import fnmatch
import importlib.util
import json
from pathlib import Path
import os
import shutil
import signal
import subprocess
import sys
import time
from types import ModuleType

import pytest

from tests.fixtures.git_repo import commit, git
from tests.fixtures.potomne import beating, wait_for

ROOT = Path(__file__).resolve().parents[1]
TOOLS = ROOT / "tools"
TOOL = TOOLS / "mutacje_skilli.py"
PASSING = 'print("WYKRYTA: proba")\nprint("MUTACJE OK")\n'
CHECKED = "src/pakiet/sprawdzany.py"
GUARDED = "---\nname: verify-x\npilnuje:\n  - src/pakiet/rout*.py\n---\n"
ANCHORS = "src/pakiet/kotwice.txt"
WITH_TABLE = f"""from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[4] / "tools"))
from mutacje import Edit, Mutation  # noqa: E402

MUTATIONS = (
    Mutation("m", (Edit(Path("{CHECKED}"), "X", "Y"), Edit(Path("{ANCHORS}"), "X", "Y")), (".agents/skills/verify-a/scripts/sprawdz_a.py",)),
)

if __name__ == "__main__":
    {PASSING.replace(chr(10), chr(10) + "    ").rstrip()}
"""
REPO = {
    "src/pakiet/__init__.py": "",
    CHECKED: "def run() -> int:\n    from pakiet import pomocnik\n\n    return pomocnik.X\n",
    "src/pakiet/pomocnik.py": "X = 1\n",
    "src/pakiet/obcy.py": "Y = 2\n",
    "src/pakiet/routing.py": "Z = 3\n",
    ANCHORS: "X\n",
    ".agents/skills/verify-a/scripts/sprawdz_a.py": "from pakiet import sprawdzany\n",
    "requirements.txt": "pytest\n",
    "docs/opis.md": "opis\n",
}


def _skill(root: Path, name: str, scripts: dict[str, str], skill_md: str = "") -> None:
    skill = root / ".agents" / "skills" / name
    for script, body in scripts.items():
        (skill / "scripts" / script).parent.mkdir(parents=True, exist_ok=True)
        (skill / "scripts" / script).write_text(body, encoding="utf-8")
    skill.mkdir(parents=True, exist_ok=True)
    (skill / "SKILL.md").write_text(skill_md, encoding="utf-8")


def _tool(root: Path) -> list[str]:
    (root / "tools").mkdir(exist_ok=True)
    for name in (TOOL.name, "potomne.py", "ciezkie_ci.py", "mutacje.py", "sciezki_w_kodzie.py"):
        shutil.copy(TOOLS / name, root / "tools" / name)
    return [sys.executable, str(root / "tools" / TOOL.name)]


def _run(root: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [*_tool(root), *args],
        cwd=root,
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=120,
        check=False,
    )


def _start(root: Path) -> subprocess.Popen[str]:
    return subprocess.Popen(
        _tool(root),
        cwd=root,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        text=True,
        encoding="utf-8",
    )


def test_skrypty_z_werdyktem_przechodza(tmp_path: Path) -> None:
    _skill(tmp_path, "verify-a", {"check_a_mutations.py": PASSING}, "py -3 scripts\\check_a_mutations.py")

    result = _run(tmp_path)

    assert result.returncode == 0, result.stdout
    assert result.stdout.splitlines()[-1] == "MUTACJE SKILLI OK"


def test_skrypt_mutacji_o_zlej_nazwie_albo_w_podfolderze_daje_fail(tmp_path: Path) -> None:
    _skill(tmp_path, "verify-a", {"check_a_mutations.py": PASSING})
    _skill(tmp_path, "verify-b", {"check_mutation_proba.py": PASSING, "sub/check_sub_mutations.py": PASSING})

    result = _run(tmp_path)

    assert result.returncode == 1
    final = result.stdout.splitlines()[-1]
    assert ".agents/skills/verify-b/scripts/check_mutation_proba.py" in final
    assert ".agents/skills/verify-b/scripts/sub/check_sub_mutations.py" in final


def test_skrypt_wskazany_w_skill_md_a_usuniety_daje_fail(tmp_path: Path) -> None:
    _skill(tmp_path, "verify-a", {"check_a_mutations.py": PASSING})
    _skill(tmp_path, "verify-b", {}, "py -3 .agents\\skills\\verify-b\\scripts\\check_b_mutations.py")

    result = _run(tmp_path)

    assert result.returncode == 1
    assert ".agents/skills/verify-b/scripts/check_b_mutations.py" in result.stdout.splitlines()[-1]


@pytest.mark.parametrize(
    "mention",
    [
        "Nazwij skrypt `scripts/check_<co>_mutations.py`.",
        "Zobacz też `check_b_mutations.py` w verify-b.",
        "py -3 .agents\\skills\\verify-b\\scripts\\check_b_mutations.py",
        "Testy runnera są w `tests/test_mutations.py`.",
    ],
)
def test_wzmianka_w_prozie_nie_daje_fail(tmp_path: Path, mention: str) -> None:
    _skill(tmp_path, "verify-a", {"check_a_mutations.py": PASSING}, f"py -3 scripts\\check_a_mutations.py\n{mention}\n")
    _skill(tmp_path, "verify-b", {"check_b_mutations.py": PASSING})

    result = _run(tmp_path)

    assert result.returncode == 0, result.stdout
    assert result.stdout.splitlines()[-1] == "MUTACJE SKILLI OK"


def test_skrypt_bez_werdyktu_daje_fail(tmp_path: Path) -> None:
    _skill(tmp_path, "verify-a", {"check_a_mutations.py": "def main() -> int:\n    return 0\n"})

    result = _run(tmp_path)

    assert result.returncode == 1
    assert ".agents/skills/verify-a/scripts/check_a_mutations.py" in result.stdout.splitlines()[-1]


def test_skrypt_po_limicie_czasu_daje_fail_a_kolejne_dalej_ruszaja(tmp_path: Path) -> None:
    _skill(tmp_path, "verify-a", {"check_a_mutations.py": "import time\ntime.sleep(60)\n"})
    _skill(tmp_path, "verify-b", {"check_b_mutations.py": PASSING})

    result = _run(tmp_path, "--limit-s", "1")

    assert result.returncode == 1
    assert "OK   .agents/skills/verify-b/scripts/check_b_mutations.py" in result.stdout
    final = result.stdout.splitlines()[-1]
    assert ".agents/skills/verify-a/scripts/check_a_mutations.py" in final
    assert "verify-b" not in final


def test_wyjscie_skryptu_mutacji_widac_w_trakcie_jego_pracy(tmp_path: Path) -> None:
    seen = tmp_path / "linia-widziana"
    script = (
        "import pathlib, sys, time\n"
        "print('WYKRYTA: pierwsza', flush=True)\n"
        "deadline = time.monotonic() + 20\n"
        f"while not pathlib.Path({str(seen)!r}).exists():\n"
        "    if time.monotonic() > deadline:\n"
        "        sys.exit(3)\n"
        "    time.sleep(0.05)\n" + PASSING
    )
    _skill(tmp_path, "verify-a", {"check_a_mutations.py": script})

    runner = _start(tmp_path)
    assert runner.stdout is not None
    lines = []
    for line in runner.stdout:
        lines.append(line.rstrip("\n"))
        if line.startswith("WYKRYTA: pierwsza"):
            seen.touch()
    runner.wait(timeout=30)

    assert (runner.returncode, lines[-1]) == (0, "MUTACJE SKILLI OK"), lines


@pytest.mark.parametrize(
    "mention",
    [
        "py -3 ./.agents/skills/verify-a/scripts/check_a_mutations.py",
        "py -3 .\\.agents\\skills\\verify-a\\scripts\\check_a_mutations.py",
        "py -3 {root}/.agents/skills/verify-a/scripts/check_a_mutations.py",
    ],
)
def test_sciezka_z_kropka_albo_bezwzgledna_do_skryptu_w_repo_przechodzi(tmp_path: Path, mention: str) -> None:
    _skill(tmp_path, "verify-a", {"check_a_mutations.py": PASSING}, mention.format(root=tmp_path))

    result = _run(tmp_path)

    assert result.returncode == 0, result.stdout + result.stderr
    assert result.stdout.splitlines()[-1] == "MUTACJE SKILLI OK"


def test_sciezka_bezwzgledna_spoza_repo_daje_nazwany_fail(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    outside = tmp_path / "gdzie-indziej" / "scripts" / "check_x_mutations.py"
    _skill(root, "verify-a", {"check_a_mutations.py": PASSING}, f"py -3 scripts/check_a_mutations.py\npy -3 {outside}\n")

    result = _run(root)

    assert result.returncode == 1, result.stdout + result.stderr
    assert "Traceback" not in result.stderr
    assert outside.as_posix() in result.stdout.splitlines()[-1]


def test_zabity_runner_nie_zostawia_skryptu_mutacji(tmp_path: Path) -> None:
    ready, beats = tmp_path / "skrypt-gotowy", tmp_path / "skrypt-zyje"
    beat = f"open({str(beats)!r}, 'a').write('.')"
    script = (
        f"import os, pathlib, time\n{beat}\npathlib.Path({str(ready)!r}).write_text(str(os.getpid()))\n"
        f"while True:\n    {beat}\n    time.sleep(0.1)\n"
    )
    _skill(tmp_path, "verify-a", {"check_a_mutations.py": script})
    runner = subprocess.Popen(_tool(tmp_path), cwd=tmp_path, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL)
    try:
        deadline = time.monotonic() + 60
        while not ready.exists() and time.monotonic() < deadline:
            time.sleep(0.05)
        assert ready.exists(), "skrypt mutacji nie ruszył"
        runner.kill()
        runner.wait(timeout=30)

        assert wait_for(lambda: not beating(beats), 5), "skrypt mutacji przeżył runner"
    finally:
        runner.kill()
        runner.wait()
        if ready.exists():
            with contextlib.suppress(OSError):
                os.kill(int(ready.read_text()), signal.SIGTERM)


def _selection_repo(root: Path) -> str:
    """Skill a z ``pilnuje`` i tabelą, b z tabelą bez ``pilnuje``, c z ``pilnuje`` bez tabeli; zwraca commit bazy."""

    for name, text in REPO.items():
        (root / name).parent.mkdir(parents=True, exist_ok=True)
        (root / name).write_text(text, encoding="utf-8")
    checker = {"sprawdz_a.py": REPO[".agents/skills/verify-a/scripts/sprawdz_a.py"]}
    _skill(root, "verify-a", {"check_a_mutations.py": WITH_TABLE, **checker}, GUARDED)
    _skill(root, "verify-b", {"check_b_mutations.py": WITH_TABLE})
    _skill(root, "verify-c", {"check_c_mutations.py": PASSING}, GUARDED)
    _tool(root)
    git(root, "init", "--quiet")
    return commit(root, "baza")


def _ran(result: subprocess.CompletedProcess[str], skill: str) -> bool:
    script = f".agents/skills/{skill}/scripts/check_{skill[-1]}_mutations.py"
    ran, skipped = f"OK   {script}" in result.stdout, f"POMINIĘTY {script}" in result.stdout
    assert ran != skipped, result.stdout
    return ran


@pytest.mark.parametrize(
    ("changed", "runs"),
    [
        ("docs/opis.md", False),
        ("src/pakiet/obcy.py", False),
        ("src/pakiet/routing.py", True),
        (".agents/skills/verify-b/SKILL.md", False),
        (CHECKED, True),
        (ANCHORS, True),
        ("src/pakiet/pomocnik.py", True),
        ("src/pakiet/__init__.py", True),
        (".agents/skills/verify-a/scripts/sprawdz_a.py", True),
        (".agents/skills/verify-a/SKILL.md", True),
        ("requirements.txt", True),
        ("tools/potomne.py", True),
        ("tools/mutacje_skilli.py", True),
    ],
)
def test_ze_zmianami_od_bazy_biegnie_skrypt_ktorego_pliki_sie_zmienily(tmp_path: Path, changed: str, runs: bool) -> None:
    base = _selection_repo(tmp_path)
    with (tmp_path / changed).open("a", encoding="utf-8") as file:
        file.write("\n")
    commit(tmp_path, "zmiana")

    result = _run(tmp_path, "--zmiany-od", base)

    assert result.returncode == 0, result.stdout + result.stderr
    assert result.stdout.splitlines()[-1] == "MUTACJE SKILLI OK"
    assert (_ran(result, "verify-a"), _ran(result, "verify-b"), _ran(result, "verify-c")) == (runs, True, True)


def test_usuniety_plik_importowany_przez_sprawdzenie_uruchamia_skrypt(tmp_path: Path) -> None:
    base = _selection_repo(tmp_path)
    (tmp_path / "src/pakiet/pomocnik.py").unlink()
    commit(tmp_path, "bez pomocnika")

    assert _ran(_run(tmp_path, "--zmiany-od", base), "verify-a")


def test_niezacommitowana_zmiana_uruchamia_skrypt(tmp_path: Path) -> None:
    base = _selection_repo(tmp_path)
    (tmp_path / "src/pakiet/pomocnik.py").write_text("X = 2\n", encoding="utf-8")

    assert _ran(_run(tmp_path, "--zmiany-od", base), "verify-a")


def test_bez_zmian_od_bazy_pomija_tylko_skill_z_pilnuje_i_tabela(tmp_path: Path) -> None:
    base = _selection_repo(tmp_path)

    selected, everything = _run(tmp_path, "--zmiany-od", base), _run(tmp_path)

    assert [_ran(selected, skill) for skill in ("verify-a", "verify-b", "verify-c")] == [False, True, True]
    assert [_ran(everything, skill) for skill in ("verify-a", "verify-b", "verify-c")] == [True, True, True]


def test_pilnuje_nie_bedace_lista_globow_uruchamia_skrypt(tmp_path: Path) -> None:
    _selection_repo(tmp_path)
    (tmp_path / ".agents/skills/verify-a/SKILL.md").write_text("---\npilnuje: src/pakiet/routing.py\n---\n", encoding="utf-8")
    base = commit(tmp_path, "pilnuje jako tekst")

    assert _ran(_run(tmp_path, "--zmiany-od", base), "verify-a")


def _load_tool(monkeypatch: pytest.MonkeyPatch) -> ModuleType:
    monkeypatch.syspath_prepend(str(TOOLS))
    spec = importlib.util.spec_from_file_location("mutacje_skilli", TOOL)
    assert spec is not None and spec.loader is not None
    tool = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(tool)
    return tool


def test_kazdy_glob_pilnuje_trafia_w_plik_repozytorium(monkeypatch: pytest.MonkeyPatch) -> None:
    tool = _load_tool(monkeypatch)
    tracked = git(ROOT, "ls-files").splitlines()

    guarded = {md.parent.name: tool.guarded(md) for md in sorted((ROOT / ".agents" / "skills").glob("*/SKILL.md"))}
    dead = [f"{skill}: {glob}" for skill, globs in guarded.items() for glob in globs or () if not any(fnmatch.fnmatchcase(name, glob) for name in tracked)]

    assert any(guarded.values())
    assert dead == []


def test_skrypt_mutacji_czyta_kazdy_plik_repozytorium_ladowany_przez_jego_sprawdzenia(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    tool = _load_tool(monkeypatch)
    # Moduły z chwili startu interpretera nie są ładowane przez sprawdzenia. W przebiegu bez mutacji zadania Change
    # mutations ``sitecustomize`` z ``PYTHONPATH`` ładuje przy starcie ``tools/pokrycie_procesu.py``, więc test robi to
    # samo; gdy ``PYTHONPATH`` ma już ``sitecustomize`` zadania, wygrywa tamten.
    (tmp_path / "sitecustomize.py").write_text(
        f"import sys\nsys.path.insert(0, {str(TOOLS)!r})\nimport pokrycie_procesu\nsys.path.remove({str(TOOLS)!r})\n", encoding="utf-8"
    )
    python_path = os.pathsep.join(path for path in (os.environ.get("PYTHONPATH", ""), str(tmp_path)) if path)
    loader = (
        "import sys\n"
        "started = set(sys.modules)\n"
        "import json, os, runpy\n"
        "script = runpy.run_path(sys.argv[1], run_name='_mutacje')\n"
        "for checker in {mutation.command[0] for mutation in script['MUTATIONS']}:\n"
        "    sys.path.insert(0, os.path.dirname(os.path.abspath(checker)))  # jak `python <sprawdzenie>`\n"
        "    runpy.run_path(checker, run_name='_sprawdzenie')\n"
        "files = [getattr(module, '__file__', None) for name, module in list(sys.modules.items()) if name not in started]\n"
        "print(json.dumps({'start': 'pokrycie_procesu' in started, 'pliki': files}))\n"
    )
    scripts = sorted((ROOT / ".agents" / "skills").glob("*/scripts/check_*_mutations.py"))
    unread, nothing_loaded, not_preloaded = {}, [], []
    for script in scripts:
        out = subprocess.run(
            [sys.executable, "-c", loader, str(script)],
            cwd=ROOT,
            env={**os.environ, "PYTHONPATH": python_path},
            capture_output=True,
            text=True,
            encoding="utf-8",
            check=True,
        ).stdout
        measured = json.loads(out.splitlines()[-1])
        loaded = {Path(name).resolve() for name in measured["pliki"] if name}
        in_repo = {path.relative_to(ROOT).as_posix() for path in loaded if path.is_relative_to(ROOT) and ".venv" not in path.parts}
        unread[script.relative_to(ROOT).as_posix()] = sorted(in_repo - tool.reads(script))
        if not in_repo:
            nothing_loaded.append(script.name)
        if not measured["start"]:
            not_preloaded.append(script.name)

    assert scripts
    assert not_preloaded == []  # bez modułu ze startu filtr ``started`` niczego nie sprawdza
    assert nothing_loaded == []  # skrypt mutacji ładuje co najmniej ``tools/mutacje.py``, więc pusty pomiar jest zepsuty
    assert unread == {script.relative_to(ROOT).as_posix(): [] for script in scripts}


def test_polecenie_ci_kazdego_skilla_to_skrypt_z_repozytorium(monkeypatch: pytest.MonkeyPatch) -> None:
    tool = _load_tool(monkeypatch)

    commands = {md.parent.name: tool.ci_command(md) for md in sorted((ROOT / ".agents" / "skills").glob("*/SKILL.md"))}

    assert {"verify-centrum-rozliczen", "verify-aktualizacja-narzedzia"} <= {skill for skill, command in commands.items() if command}


def test_nazwy_mutacji_w_tabeli_kazdego_skryptu_skilla_sa_rozne(monkeypatch: pytest.MonkeyPatch) -> None:
    """Część ``MUTACJE_CZESC`` układa mutacje po nazwie; przy dwóch równych nazwach decydowałoby ``repr`` ścieżek."""

    tool = _load_tool(monkeypatch)
    scripts = sorted((ROOT / ".agents" / "skills").glob(f"*/scripts/{tool.PATTERN}"))
    names = {script.name: [mutation.name for mutation in tool._mutations(script)] for script in scripts}

    assert scripts
    assert {script: sorted(set(found)) for script, found in names.items()} == {script: sorted(found) for script, found in names.items()}


def test_wybor_oznacza_kroki_skilla_ktorego_skrypty_importuja_playwright_i_liczy_mutacje_skryptu(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    table = (
        "from pathlib import Path\nimport sys\n\nsys.path.insert(0, str(Path(__file__).resolve().parents[4] / 'tools'))\n"
        "from mutacje import Edit, Mutation  # noqa: E402\n\n"
        "MUTATIONS = tuple(Mutation(f'm{numer}', (Edit(Path('a.txt'), 'X', 'Y'),), ('a.py',)) for numer in range({count}))\n"
    )
    drive = ".agents/skills/verify-a/scripts/drive/przegladarka.py"
    _skill(tmp_path, "verify-a", {"check_a_mutations.py": table.replace("{count}", "3"), "drive/przegladarka.py": "from playwright.sync_api import sync_playwright\n"}, _with_ci("verify-a", drive))
    _skill(tmp_path, "verify-b", {"check_b_mutations.py": table.replace("{count}", "0"), "opis.py": "TEKST = 'import playwright'\n"})
    _tool(tmp_path)
    monkeypatch.syspath_prepend(str(tmp_path / "tools"))
    spec = importlib.util.spec_from_file_location("mutacje_skilli_w_kopii", tmp_path / "tools" / TOOL.name)
    assert spec is not None and spec.loader is not None
    tool = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(tool)

    selection = tool.wybor(None)

    assert [(step.key, step.mutations, step.browser) for step, _ in selection.chosen] == [
        ("verify-a/ci", 0, True),
        ("verify-a/check_a_mutations.py", 3, True),
        ("verify-b/check_b_mutations.py", 1, False),
    ]
    assert (selection.skipped, selection.failed) == ([], {})


CHECKED_IN_CI = (
    "import sys\n"
    "def _uzywa():\n"
    "    from pakiet import pomocnik\n"
    "print('sprawdzone', *sys.argv[1:])\n"
    "sys.exit({code})\n"
)


def _with_ci(name: str, command: str, globs: str = "src/pakiet/rout*.py") -> str:
    return f"---\nname: {name}\npilnuje:\n  - {globs}\nci: {command}\n---\n"


def test_podstawa_ci_biegnie_z_argumentami_przed_mutacjami_skilla(tmp_path: Path) -> None:
    command = ".agents/skills/verify-d/scripts/sprawdz_d.py --feature all"
    _skill(tmp_path, "verify-d", {"check_d_mutations.py": PASSING, "sprawdz_d.py": CHECKED_IN_CI.format(code=0)}, _with_ci("verify-d", command))

    result = _run(tmp_path)

    assert result.returncode == 0, result.stdout + result.stderr
    lines = result.stdout.splitlines()
    assert lines.index(f"== PODSTAWA verify-d: {command}") < lines.index("sprawdzone --feature all") < lines.index("== .agents/skills/verify-d/scripts/check_d_mutations.py")
    assert lines[-1] == "MUTACJE SKILLI OK"


def test_czerwona_podstawa_ci_daje_fail_takze_w_skillu_bez_skryptu_mutacji(tmp_path: Path) -> None:
    _skill(tmp_path, "verify-a", {"check_a_mutations.py": PASSING})
    _skill(tmp_path, "verify-d", {"sprawdz_d.py": CHECKED_IN_CI.format(code=1)}, _with_ci("verify-d", ".agents/skills/verify-d/scripts/sprawdz_d.py"))

    result = _run(tmp_path)

    assert result.returncode == 1
    assert "FAIL PODSTAWA verify-d" in result.stdout
    assert result.stdout.splitlines()[-1] == "MUTACJE SKILLI FAIL | PODSTAWA verify-d"


@pytest.mark.parametrize("command", ["docs/opis.md", "", ".agents/skills/verify-d/scripts/nie_ma.py"])
def test_klucz_ci_bez_skryptu_z_repozytorium_daje_fail(tmp_path: Path, command: str) -> None:
    _skill(tmp_path, "verify-a", {"check_a_mutations.py": PASSING})
    _skill(tmp_path, "verify-d", {}, _with_ci("verify-d", command))
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs/opis.md").write_text("opis\n", encoding="utf-8")

    result = _run(tmp_path)

    assert result.returncode == 1
    assert "FAIL PODSTAWA verify-d: ci w .agents/skills/verify-d/SKILL.md nie zaczyna się skryptem .py z repozytorium" in result.stdout
    assert result.stdout.splitlines()[-1] == "MUTACJE SKILLI FAIL | PODSTAWA verify-d"


@pytest.mark.parametrize(("arguments", "separately"), [("", False), (" --pelny", True)])
def test_podstawa_ci_ktora_uruchamia_skrypt_mutacji_nie_biegnie_drugi_raz(tmp_path: Path, arguments: str, separately: bool) -> None:
    _selection_repo(tmp_path)
    command = ".agents/skills/verify-a/scripts/sprawdz_a.py" + arguments
    (tmp_path / ".agents/skills/verify-a/SKILL.md").write_text(_with_ci("verify-a", command), encoding="utf-8")
    (tmp_path / ".agents/skills/verify-a/scripts/sprawdz_a.py").write_text(CHECKED_IN_CI.format(code=0), encoding="utf-8")

    result = _run(tmp_path)

    assert result.stdout.splitlines()[-1] == "MUTACJE SKILLI OK", result.stdout + result.stderr
    assert (f"== PODSTAWA verify-a: {command}" in result.stdout.splitlines()) == separately
    assert _ran(result, "verify-a")


@pytest.mark.parametrize(
    ("changed", "runs"),
    [
        ("docs/opis.md", False),
        ("src/pakiet/obcy.py", False),
        ("src/pakiet/routing.py", True),
        ("src/pakiet/pomocnik.py", True),
        (".agents/skills/verify-d/SKILL.md", True),
        ("requirements.txt", True),
        ("tools/mutacje_skilli.py", True),
    ],
)
def test_ze_zmianami_od_bazy_podstawa_ci_biegnie_gdy_zmiana_dotyka_skilla(tmp_path: Path, changed: str, runs: bool) -> None:
    _selection_repo(tmp_path)
    _skill(tmp_path, "verify-d", {"sprawdz_d.py": CHECKED_IN_CI.format(code=0)}, _with_ci("verify-d", ".agents/skills/verify-d/scripts/sprawdz_d.py"))
    base = commit(tmp_path, "skill z podstawa")
    with (tmp_path / changed).open("a", encoding="utf-8") as file:
        file.write("\n")
    commit(tmp_path, "zmiana")

    result = _run(tmp_path, "--zmiany-od", base)

    assert result.stdout.splitlines()[-1] == "MUTACJE SKILLI OK", result.stdout + result.stderr
    ran, skipped = "OK   PODSTAWA verify-d" in result.stdout, "POMINIĘTY PODSTAWA verify-d" in result.stdout
    assert (ran, skipped) == (runs, not runs), result.stdout

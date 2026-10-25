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
    for name in (TOOL.name, "potomne.py", "mutacje.py"):
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

        assert wait_for(lambda: not beating(beats), 7), "skrypt mutacji przeżył runner"
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


def test_skrypt_mutacji_czyta_kazdy_plik_repozytorium_ladowany_przez_jego_sprawdzenia(monkeypatch: pytest.MonkeyPatch) -> None:
    tool = _load_tool(monkeypatch)
    loader = (
        "import json, os, runpy, sys\n"
        "script = runpy.run_path(sys.argv[1], run_name='_mutacje')\n"
        "for checker in {mutation.command[0] for mutation in script['MUTATIONS']}:\n"
        "    sys.path.insert(0, os.path.dirname(os.path.abspath(checker)))  # jak `python <sprawdzenie>`\n"
        "    runpy.run_path(checker, run_name='_sprawdzenie')\n"
        "print(json.dumps([getattr(module, '__file__', None) for module in list(sys.modules.values())]))\n"
    )
    scripts = sorted((ROOT / ".agents" / "skills").glob("*/scripts/check_*_mutations.py"))
    unread = {}
    for script in scripts:
        out = subprocess.run(
            [sys.executable, "-c", loader, str(script)], cwd=ROOT, capture_output=True, text=True, encoding="utf-8", check=True
        ).stdout
        loaded = {Path(name).resolve() for name in json.loads(out.splitlines()[-1]) if name}
        in_repo = {path.relative_to(ROOT).as_posix() for path in loaded if path.is_relative_to(ROOT) and ".venv" not in path.parts}
        unread[script.parents[1].name] = sorted(in_repo - tool.reads(script))

    assert scripts
    assert unread == {script.parents[1].name: [] for script in scripts}


def test_czesci_uruchamiaja_kazdy_skrypt_dokladnie_raz(tmp_path: Path) -> None:
    for skill in ("verify-a", "verify-b", "verify-c"):
        _skill(tmp_path, skill, {f"check_{skill[-1]}_mutations.py": PASSING})

    parts = [_run(tmp_path, "--czesc", f"{number}/2") for number in (1, 2)]

    ran = [line.split()[1] for part in parts for line in part.stdout.splitlines() if line.startswith("OK   ")]
    assert [part.stdout.splitlines()[-1] for part in parts] == ["MUTACJE SKILLI OK"] * 2
    assert sorted(ran) == [f".agents/skills/verify-{name}/scripts/check_{name}_mutations.py" for name in "abc"]


def test_kazdy_nastepny_najdluzszy_skrypt_idzie_do_najlzejszej_czesci(monkeypatch: pytest.MonkeyPatch) -> None:
    tool = _load_tool(monkeypatch)
    scripts = [ROOT / ".agents" / "skills" / f"verify-{name}" / "scripts" / f"check_{name}_mutations.py" for name in "abcd"]

    chosen = tool.parts(scripts, 3, {"verify-a": 60, "verify-b": 300, "verify-c": 90, "verify-d": 60})

    assert [[script.parents[1].name for script in part] for part in chosen] == [["verify-b"], ["verify-c"], ["verify-a", "verify-d"]]


def test_skrypt_spoza_tabeli_czasow_wazy_mediane_tabeli(monkeypatch: pytest.MonkeyPatch) -> None:
    tool = _load_tool(monkeypatch)
    scripts = [ROOT / ".agents" / "skills" / f"verify-{name}" / "scripts" / f"check_{name}_mutations.py" for name in ("a", "b", "c", "nowy")]

    chosen = tool.parts(scripts, 3, {"verify-a": 100, "verify-b": 60, "verify-c": 50})

    assert [[script.parents[1].name for script in part] for part in chosen] == [["verify-a"], ["verify-b", "verify-c"], ["verify-nowy"]]


def test_najdluzszy_skrypt_z_tabeli_czasow_ma_czesc_dla_siebie(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    times = _load_tool(monkeypatch).CI_TIMES_S
    for skill in times:
        _skill(tmp_path, skill, {"check_x_mutations.py": PASSING})

    parts = [_run(tmp_path, "--czesc", f"{number}/{len(times) - 1}") for number in range(1, len(times))]

    ran = [{line.split()[1].split("/")[2] for line in part.stdout.splitlines() if line.startswith("OK   ")} for part in parts]
    assert {max(times, key=times.__getitem__)} in ran
    assert sorted(skill for part in ran for skill in part) == sorted(times)


def test_tabela_czasow_mutacji_wymienia_tylko_skille_ze_skryptem_mutacji(monkeypatch: pytest.MonkeyPatch) -> None:
    tool = _load_tool(monkeypatch)
    skills = {script.parents[1].name for script in (ROOT / ".agents" / "skills").glob(f"*/scripts/{tool.PATTERN}")}

    assert set(tool.CI_TIMES_S) <= skills


@pytest.mark.parametrize("part", ["0/2", "3/2", "1", "a/b"])
def test_czesc_spoza_zakresu_jest_bledem_wywolania(tmp_path: Path, part: str) -> None:
    _skill(tmp_path, "verify-a", {"check_a_mutations.py": PASSING})

    result = _run(tmp_path, "--czesc", part)

    assert result.returncode == 2
    assert "OK   " not in result.stdout

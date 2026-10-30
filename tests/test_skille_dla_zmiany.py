"""``tools/skille_dla_zmiany.py`` wskazuje skille ``verify-*`` dla zmiany z ``pilnuje:`` w ich ``SKILL.md``.

Testy zachowania budują własne repozytorium z kopią narzędzia. Testy struktury sprawdzają skille, ``AGENTS.md`` i
``docs/agents/skille.md`` tego checkoutu: routing skilli żyje we frontmatterach, a te pliki tylko odsyłają do narzędzia.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path
import re
import subprocess
import sys
from types import ModuleType

import pytest
import yaml

from tests.fixtures.git_repo import commit, copy_files, git

ROOT = Path(__file__).resolve().parents[1]
TOOLS = ROOT / "tools"
SKILLS = ROOT / ".agents" / "skills"
VERDICT = "SKILLE VERIFY: "
REPO = {
    ".agents/skills/verify-a/SKILL.md": "---\nname: verify-a\ndescription: a\npilnuje:\n  - src/a/*\n  - tools/narzedzie.py\n---\n",
    ".agents/skills/verify-b/SKILL.md": "---\nname: verify-b\ndescription: b\npilnuje:\n  - docs/b.md\n---\n",
    ".agents/skills/verify-b/scripts/run_b.py": "import pomocnik\nprint('b')\n",
    ".agents/skills/inny/SKILL.md": "---\nname: inny\ndescription: nie verify\npilnuje:\n  - docs/b.md\n---\n",
    "src/a/b/gleboki.py": "X = 1\n",
    "src/ab.py": "Y = 1\n",
    "tools/narzedzie.py": "Z = 1\n",
    "tools/pomocnik.py": "P = 1\n",
    "docs/b.md": "b\n",
    "docs/inny.md": "inny\n",
}


TOOLS_FOR_CHANGE = (
    "tools/skille_dla_zmiany.py", "tools/ci/mutacje_skilli.py", "tools/ci/plan_ci.py", "tools/lib/niestabilne_testy.py",
    "tools/ci/mutacje_zmiany.py", "tools/ci/pokrycie_procesu.py", "tools/lib/potomne.py", "tools/szybko.py", "tools/ci_lokalnie.py",
    "tools/ci/czasy_ci.py", "tools/lib/ciezkie_ci.py", "tools/mutacje.py", "tools/lib/sciezki_w_kodzie.py",
)


def _repo(root: Path, files: dict[str, str] = REPO) -> str:
    for name, text in files.items():
        (root / name).parent.mkdir(parents=True, exist_ok=True)
        (root / name).write_text(text, encoding="utf-8")
    copy_files(root, TOOLS_FOR_CHANGE)
    git(root, "init", "--quiet")
    return commit(root, "baza")


def _run(root: Path, *arguments: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(root / "tools" / "skille_dla_zmiany.py"), *arguments],
        cwd=root,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )


def _skills(result: subprocess.CompletedProcess[str]) -> list[str]:
    assert result.returncode == 0, result.stdout + result.stderr
    last = result.stdout.splitlines()[-1]
    assert last.startswith(VERDICT), result.stdout
    named = last.removeprefix(VERDICT)
    return [] if named == "brak" else named.split(", ")


def _append(root: Path, name: str) -> None:
    with (root / name).open("a", encoding="utf-8") as file:
        file.write("zmiana\n")


@pytest.mark.parametrize(
    ("changed", "skills", "reason"),
    [
        ("src/a/b/gleboki.py", ["verify-a"], "verify-a: src/a/b/gleboki.py (src/a/*)"),
        ("tools/narzedzie.py", ["verify-a"], "verify-a: tools/narzedzie.py"),
        ("docs/b.md", ["verify-b"], "verify-b: docs/b.md"),
        (".agents/skills/verify-b/scripts/run_b.py", ["verify-b"], "verify-b: .agents/skills/verify-b/scripts/run_b.py (folder skilla)"),
        ("src/ab.py", [], None),
        # Import skryptu skilla spoza pilnuje: skill pilnuje swojego zachowania globami, a importów nie liczy (ADR 0020).
        ("tools/pomocnik.py", [], None),
        ("docs/inny.md", [], None),
        (".agents/skills/inny/SKILL.md", [], None),
    ],
)
def test_zmiana_wskazuje_skille_ktorych_glob_albo_folder_obejmuje_zmieniony_plik(
    tmp_path: Path, changed: str, skills: list[str], reason: str | None
) -> None:
    base = _repo(tmp_path)
    _append(tmp_path, changed)
    commit(tmp_path, "zmiana")

    result = _run(tmp_path, base)

    assert _skills(result) == skills
    assert result.stdout.splitlines()[:-1] == ([reason] if reason else [])


def test_zmiana_bez_commitu_nowy_plik_i_przeniesienie_poza_glob_wskazuja_skill(tmp_path: Path) -> None:
    base = _repo(tmp_path)

    _append(tmp_path, "docs/b.md")
    assert _skills(_run(tmp_path, base)) == ["verify-b"]
    git(tmp_path, "checkout", "--", "docs/b.md")

    (tmp_path / "src/a/nowy.py").write_text("N = 1\n", encoding="utf-8")
    assert _skills(_run(tmp_path, base)) == ["verify-a"]
    (tmp_path / "src/a/nowy.py").unlink()

    git(tmp_path, "mv", "docs/b.md", "docs/przeniesiony.md")
    commit(tmp_path, "przeniesienie")
    assert _skills(_run(tmp_path, base)) == ["verify-b"]


def test_zmiana_tylko_w_bazie_po_rozgalezieniu_nie_wskazuje_skilla(tmp_path: Path) -> None:
    _repo(tmp_path)
    trunk = git(tmp_path, "rev-parse", "--abbrev-ref", "HEAD")
    git(tmp_path, "checkout", "--quiet", "-b", "praca")
    _append(tmp_path, "tools/narzedzie.py")
    commit(tmp_path, "praca")
    git(tmp_path, "checkout", "--quiet", trunk)
    _append(tmp_path, "docs/b.md")
    moved = commit(tmp_path, "baza poszła dalej")
    git(tmp_path, "checkout", "--quiet", "praca")

    assert _skills(_run(tmp_path, moved)) == ["verify-a"]


def test_skill_bez_pilnuje_albo_z_nieczytelnym_pilnuje_obowiazuje_zawsze(tmp_path: Path) -> None:
    base = _repo(
        tmp_path,
        {
            **REPO,
            ".agents/skills/verify-bez/SKILL.md": "---\nname: verify-bez\ndescription: bez klucza\n---\n",
            ".agents/skills/verify-zly/SKILL.md": "---\nname: verify-zly\npilnuje: docs/b.md\n---\n",
        },
    )

    result = _run(tmp_path, base)

    assert _skills(result) == ["verify-bez", "verify-zly"]
    assert result.stdout.splitlines()[0] == "verify-bez: .agents/skills/verify-bez/SKILL.md nie ma klucza pilnuje"


def test_wiele_plikow_jednego_skilla_skraca_powod(tmp_path: Path) -> None:
    base = _repo(tmp_path)
    for number in range(5):
        (tmp_path / f"src/a/plik{number}.py").write_text("P = 1\n", encoding="utf-8")

    result = _run(tmp_path, base)

    assert result.stdout.splitlines() == [
        "verify-a: src/a/plik0.py (src/a/*), src/a/plik1.py (src/a/*), src/a/plik2.py (src/a/*) i 2 innych",
        f"{VERDICT}verify-a",
    ]


def test_skill_z_poleceniami_w_ci_zostaje_w_skillach_verify_a_liczy_ci_wymienia_jego_polecenia(tmp_path: Path) -> None:
    base = _repo(
        tmp_path,
        {
            **REPO,
            ".agents/skills/verify-a/SKILL.md": "---\nname: verify-a\npilnuje:\n  - src/a/*\nci: tools/narzedzie.py --wszystko\n---\n",
            ".agents/skills/verify-a/scripts/check_a_mutations.py": MUTATION_SCRIPT,
            ".agents/skills/verify-mac/SKILL.md": "---\nname: verify-mac\npilnuje:\n  - src/a/*\n---\n",
            ".agents/skills/verify-zly/SKILL.md": "---\nname: verify-zly\npilnuje:\n  - src/a/*\nci: docs/b.md\n---\n",
            ".agents/skills/verify-e2e/SKILL.md": "---\nname: verify-e2e\npilnuje:\n  - src/a/*\n---\n",
            ".agents/skills/verify-e2e/scripts/run_e2e.py": "print('e2e')\n",
            ".github/workflows/ci.yml": "      - run: py -3 .agents/skills/verify-e2e/scripts/run_e2e.py --variant all\n",
        },
    )
    _append(tmp_path, "src/a/b/gleboki.py")

    result = _run(tmp_path, base)

    assert _skills(result) == ["verify-a", "verify-e2e", "verify-mac", "verify-zly"]
    assert result.stdout.splitlines()[-2] == "LICZY CI: verify-a (narzedzie.py --wszystko); verify-e2e (run_e2e.py --variant all)"


MUTATION_SCRIPT = "MUTATIONS = ()\nif __name__ == '__main__':\n    print('MUTACJE OK')\n"
AGREEING = {
    **REPO,
    # Wczytanie tabel mutacji zostawia __pycache__ w folderze skilla, a repozytorium go ignoruje.
    ".gitignore": "__pycache__/\n",
    ".agents/skills/verify-a/SKILL.md": "---\nname: verify-a\npilnuje:\n  - src/a/*\nci: .agents/skills/verify-a/scripts/sprawdz_a.py --wszystko\n---\n",
    ".agents/skills/verify-a/scripts/sprawdz_a.py": "print('sprawdzone')\n",
    ".agents/skills/verify-a/scripts/check_a_mutations.py": MUTATION_SCRIPT,
}


def _in_mutation_checks(root: Path, base: str, *, night: bool = False) -> list[str]:
    """Polecenia kroków, które uruchomił ``tools/ci/mutacje_skilli.py --zmiany-od`` (z ``night``: ``--noc``), w postaci linii
    ``LICZY CI`` albo ``LICZY NOC``."""

    out = subprocess.run(
        [sys.executable, str(root / "tools" / "ci" / "mutacje_skilli.py"), "--zmiany-od", base, *(["--noc"] * night)],
        cwd=root,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=True,
    ).stdout
    found = []
    for line in out.splitlines():
        if line.startswith("== "):
            command = line.removeprefix("== ").split(" (")[0].split(": ", 1)[-1].split()
            found.append(" ".join([Path(command[0]).name, *command[1:]]))
    return found


@pytest.mark.parametrize(
    ("changed", "at_night"),
    [("src/a/b/gleboki.py", []), (".agents/skills/verify-a/SKILL.md", ["check_a_mutations.py"])],
    ids=["pilnuje", "folder skilla"],
)
def test_liczy_ci_i_liczy_noc_wymieniaja_dokladnie_kroki_skilla_ktore_uruchamia_plan_pull_requestu_i_nocy(
    tmp_path: Path, changed: str, at_night: list[str]
) -> None:
    base = _repo(tmp_path, AGREEING)
    _append(tmp_path, changed)
    commit(tmp_path, "zmiana")

    result = _run(tmp_path, base)

    assert _skills(result) == ["verify-a"]
    lines = result.stdout.splitlines()
    assert [line for line in lines if line.startswith(("LICZY CI", "LICZY NOC"))] == [
        "LICZY CI: verify-a (sprawdz_a.py --wszystko)",
        *([f"LICZY NOC: verify-a ({', '.join(at_night)})"] * bool(at_night)),
    ]
    assert (_in_mutation_checks(tmp_path, base), _in_mutation_checks(tmp_path, base, night=True)) == (["sprawdz_a.py --wszystko"], at_night)


def test_zmiana_runnera_mutacji_nie_wskazuje_skilla_choc_noc_uruchamia_jego_skrypt_mutacji(tmp_path: Path) -> None:
    base = _repo(tmp_path, AGREEING)
    with (tmp_path / "tools" / "mutacje.py").open("a", encoding="utf-8") as file:
        file.write("# zmiana\n")
    commit(tmp_path, "zmiana runnera")

    assert _skills(_run(tmp_path, base)) == []
    assert (_in_mutation_checks(tmp_path, base), _in_mutation_checks(tmp_path, base, night=True)) == ([], ["check_a_mutations.py"])


@pytest.mark.parametrize(
    ("changed", "in_ci"),
    [("src/a/b/gleboki.py", ["LICZY CI: verify-rozliczenia (run_verification.py --variant all)"]), (".agents/skills/verify-rozliczenia/SKILL.md", [])],
    ids=["src", "tylko folder skilla"],
)
def test_liczy_ci_wymienia_e2e_tylko_gdy_plan_pull_requestu_go_uruchamia(tmp_path: Path, changed: str, in_ci: list[str]) -> None:
    base = _repo(
        tmp_path,
        {
            **REPO,
            ".agents/skills/verify-rozliczenia/SKILL.md": "---\nname: verify-rozliczenia\npilnuje:\n  - src/a/*\n---\n",
            ".agents/skills/verify-rozliczenia/scripts/run_verification.py": "print('e2e')\n",
        },
    )
    _append(tmp_path, changed)
    commit(tmp_path, "zmiana")

    result = _run(tmp_path, base)

    assert "verify-rozliczenia" in _skills(result)
    assert [line for line in result.stdout.splitlines() if line.startswith("LICZY CI")] == in_ci


def test_baza_ktorej_nie_ma_daje_nieznane_skille_i_kod_bledu(tmp_path: Path) -> None:
    _repo(tmp_path)

    result = _run(tmp_path, "nie-ma-takiej-bazy")

    assert result.returncode == 1
    assert result.stdout.splitlines()[-1].startswith(f"{VERDICT}nieznane (git merge-base: ")
    assert "nie-ma-takiej-bazy" in result.stdout


def _load_tool(monkeypatch: pytest.MonkeyPatch) -> ModuleType:
    monkeypatch.syspath_prepend(str(TOOLS))
    spec = importlib.util.spec_from_file_location("skille_dla_zmiany", TOOLS / "skille_dla_zmiany.py")
    assert spec is not None and spec.loader is not None
    tool = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(tool)
    return tool


def test_kazdy_skill_verify_deklaruje_pilnuje(monkeypatch: pytest.MonkeyPatch) -> None:
    _load_tool(monkeypatch)
    ci = importlib.import_module("mutacje_skilli")
    skills = sorted(SKILLS.glob("verify-*/SKILL.md"))

    without = [md.parent.name for md in skills if ci.guarded(md) is None]

    assert skills
    assert without == [], "dopisz do frontmattera SKILL.md klucz pilnuje: z globami ścieżek, przy których zmianie skill obowiązuje"



def test_frontmatter_kazdego_skilla_jest_poprawnym_yaml() -> None:
    broken = {}
    for md in sorted(SKILLS.glob("*/SKILL.md")):
        front = md.read_text(encoding="utf-8").split("\n---\n", 1)[0].removeprefix("---\n")
        try:
            yaml.safe_load(front)
        except yaml.YAMLError as error:
            broken[md.parent.name] = str(error).splitlines()[0]

    assert broken == {}, "harness czyta frontmatter jako YAML: wartość bez cudzysłowu nie może mieć „: ”"


def test_workflow_skilla_windows_biegnie_dla_tych_samych_sciezek_co_jego_pilnuje(monkeypatch: pytest.MonkeyPatch) -> None:
    _load_tool(monkeypatch)
    ci = importlib.import_module("mutacje_skilli")
    skill = SKILLS / "verify-centrum-na-windowsie"
    workflow = yaml.safe_load((ROOT / ".github" / "workflows" / f"{skill.name}.yml").read_text(encoding="utf-8"))
    triggers = workflow[True]  # YAML 1.1 czyta klucz „on” jako True

    expected = sorted([*ci.guarded(skill / "SKILL.md"), f"{skill.relative_to(ROOT).as_posix()}/**"])

    assert {event: sorted(triggers[event]["paths"]) for event in ("pull_request", "push")} == {
        "pull_request": expected,
        "push": expected,
    }, "paths workflow skilla Windows to jego pilnuje: i folder skilla: dopisz ścieżkę w obu miejscach"

# Zdanie, które każe uruchomić coś przed oddaniem pracy albo pushem.
BEFORE_PUSH = re.compile(r"before (handing|you hand|pushing|you push|opening|you open)|przed (pushem|oddaniem)", re.IGNORECASE)
# Argumenty kontraktu skryptu skilla (``tools/lib/skrypt_skilla.py``), które mówią, gdzie biec, a nie co sprawdzić.
PLACE = ("--run-dir", "--root")
CI_AND_LOCAL = "## What CI runs and what stays local"


def _ci_commands(tool: ModuleType) -> set[tuple[str, ...]]:
    """Polecenia skilli, które liczy CI (``ci_runs`` narzędzia); skrypt mutacji bez argumentów obejmuje każde swoje wywołanie."""

    steps = importlib.import_module("mutacje_skilli").steps({})
    every = importlib.import_module("plan_ci").KROKI.values()
    return {run for md in SKILLS.glob("*/SKILL.md") for run in tool.ci_runs(md.parent, steps, every)}


def _selecting(arguments: str) -> tuple[str, ...]:
    """Argumenty wywołania bez ``PLACE`` i ich wartości."""

    words = arguments.split()
    return tuple(word for number, word in enumerate(words) if word not in PLACE and (number == 0 or words[number - 1] not in PLACE))


def _paragraphs(text: str) -> list[str]:
    """Akapity prozy, każdy z blokiem kodu, który stoi zaraz pod nim."""

    found: list[str] = []
    for chunk in re.split(r"\n\s*\n", text):
        if chunk.lstrip().startswith("```") and found:
            found[-1] += "\n" + chunk
        else:
            found.append(chunk)
    return found


def _mandates(tool: ModuleType, text: str, commands: set[tuple[str, ...]]) -> list[str]:
    """Akapity, które każą przed pushem uruchomić lokalnie polecenie liczone przez CI."""

    found = []
    for paragraph in _paragraphs(text):
        if not BEFORE_PUSH.search(paragraph):
            continue
        named = {(Path(script).name, *_selecting(arguments)) for _, script, arguments in tool.SKILL_COMMAND.findall(paragraph.replace("\\", "/"))}
        # Wywołanie bez części argumentów polecenia CI to zwykle jego domyślny przebieg (``all``), więc też się liczy.
        if any(command[: len(ci)] == ci or ci[: len(command)] == command for command in named for ci in commands):
            found.append(paragraph.splitlines()[0])
    return found


def test_skill_nie_kaze_uruchamiac_przed_pushem_tego_co_liczy_ci(monkeypatch: pytest.MonkeyPatch) -> None:
    """Akapit ze zdaniem „before handing/pushing…” albo „przed pushem” nie wymienia polecenia, które liczy CI.

    Polecenie liczy się także w bloku kodu pod akapitem, z ``--run-dir``/``--root`` albo bez części argumentów.
    Granica: nakaz innymi słowami („after every change”, „always run”, „it must end with”) łapie tylko przegląd.
    """

    tool = _load_tool(monkeypatch)
    commands = _ci_commands(tool)

    found = {md.parent.name: _mandates(tool, md.read_text(encoding="utf-8"), commands) for md in sorted(SKILLS.glob("*/SKILL.md"))}

    assert {("run_verification.py", "--variant", "all"), ("run_centrum_verification.py", "--feature", "all")} <= commands
    assert {skill: lines for skill, lines in found.items() if lines} == {}, (
        "polecenie, które liczy CI, skill uruchamia lokalnie tylko do odtworzenia czerwonego kroku CI albo przy pracy nad jedną funkcją"
    )


def test_skill_z_poleceniami_w_ci_mowi_co_liczy_ci_a_co_zostaje_lokalnie(monkeypatch: pytest.MonkeyPatch) -> None:
    """Granica: czy sekcja trafnie nazywa osąd, który zostaje lokalnie, łapie tylko przegląd."""

    tool = _load_tool(monkeypatch)
    steps = importlib.import_module("mutacje_skilli").steps({})
    every = importlib.import_module("plan_ci").KROKI.values()
    skills = [md for md in sorted(SKILLS.glob("verify-*/SKILL.md")) if tool.ci_runs(md.parent, steps, every)]

    without = [md.parent.name for md in skills if CI_AND_LOCAL not in md.read_text(encoding="utf-8").splitlines()]

    assert {"verify-centrum-rozliczen", "verify-aktualizacja-narzedzia"} <= {md.parent.name for md in skills}
    assert without == [], f"dopisz sekcję {CI_AND_LOCAL!r}: które polecenia liczy CI, a co z workflow zostaje lokalnie (osąd, Mac)"


def test_agents_md_nie_wymienia_skilli_verify() -> None:
    """``AGENTS.md`` i pliki ``docs/agents/``, do których odsyła przed pushem, nie wymieniają skilli ``verify-*``."""

    documents = (ROOT / "AGENTS.md", ROOT / "docs" / "agents" / "pr-i-ci.md", ROOT / "docs" / "agents" / "skille.md")
    agents = "\n".join(path.read_text(encoding="utf-8") for path in documents)

    named = [md.parent.name for md in sorted(SKILLS.glob("verify-*/SKILL.md")) if md.parent.name in agents]

    assert named == [], "routing skilli verify-* żyje w ich pilnuje:, a AGENTS.md odsyła do tools/skille_dla_zmiany.py"

"""``tools/skille_dla_zmiany.py`` wskazuje skille ``verify-*`` dla zmiany z ``pilnuje:`` w ich ``SKILL.md``.

Testy zachowania budują własne repozytorium z kopią narzędzia. Testy struktury sprawdzają skille, ``AGENTS.md`` i
``docs/agents/skille.md`` tego checkoutu: routing skilli żyje we frontmatterach, a te pliki tylko odsyłają do narzędzia.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path
import re
import shutil
import subprocess
import sys
from types import ModuleType

import pytest
import yaml

from tests.fixtures.git_repo import commit, git

ROOT = Path(__file__).resolve().parents[1]
TOOLS = ROOT / "tools"
SKILLS = ROOT / ".agents" / "skills"
VERDICT = "SKILLE VERIFY: "
REPO = {
    ".agents/skills/verify-a/SKILL.md": "---\nname: verify-a\ndescription: a\npilnuje:\n  - src/a/*\n  - tools/narzedzie.py\n---\n",
    ".agents/skills/verify-b/SKILL.md": "---\nname: verify-b\ndescription: b\npilnuje:\n  - docs/b.md\n---\n",
    ".agents/skills/verify-b/scripts/run_b.py": "print('b')\n",
    ".agents/skills/inny/SKILL.md": "---\nname: inny\ndescription: nie verify\npilnuje:\n  - docs/b.md\n---\n",
    "src/a/b/gleboki.py": "X = 1\n",
    "src/ab.py": "Y = 1\n",
    "tools/narzedzie.py": "Z = 1\n",
    "docs/b.md": "b\n",
    "docs/inny.md": "inny\n",
}


def _repo(root: Path, files: dict[str, str] = REPO) -> str:
    for name, text in files.items():
        (root / name).parent.mkdir(parents=True, exist_ok=True)
        (root / name).write_text(text, encoding="utf-8")
    (root / "tools").mkdir(exist_ok=True)
    for name in ("skille_dla_zmiany.py", "mutacje_skilli.py", "potomne.py", "szybko.py", "ci_lokalnie.py", "ciezkie_ci.py", "mutacje.py", "sciezki_w_kodzie.py"):
        shutil.copy(TOOLS / name, root / "tools" / name)
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


EXECUTED = {
    **REPO,
    ".agents/skills/verify-c/SKILL.md": "---\nname: verify-c\ndescription: c\npilnuje:\n  - docs/c.md\n---\n",
    ".agents/skills/verify-c/scripts/run_c.py": (
        "from pathlib import Path\nimport pomocnik\nimport produkt\n\n"
        'ROOT = Path(__file__).resolve().parents[4]\nSCRIPT = ROOT / "tools" / "uruchamiany.py"\n'
    ),
    ".agents/skills/verify-c/scripts/check_c_mutations.py": "import tylko_mutacje\n",
    "tools/pomocnik.py": "import glebszy\n",
    "tools/glebszy.py": 'G = 1\nSKRYPT = "tools/z_importu.py"\n',
    "tools/z_importu.py": "Z = 1\n",
    "tools/uruchamiany.py": 'import od_uruchamianego\n\nDALEJ = "tools/dalej.py"\n',
    "tools/dalej.py": "D = 1\n",
    "tools/od_uruchamianego.py": "U = 1\n",
    "tools/tylko_mutacje.py": "M = 1\n",
    "src/produkt.py": 'P = 1\nSKRYPT = "tools/z_produktu.py"\n',
    "tools/z_produktu.py": "R = 1\n",
    "docs/c.md": "c\n",
}


@pytest.mark.parametrize(
    ("changed", "skills"),
    [
        ("tools/pomocnik.py", ["verify-c"]),
        ("tools/glebszy.py", ["verify-c"]),
        ("tools/uruchamiany.py", ["verify-c"]),
        ("tools/od_uruchamianego.py", ["verify-c"]),
        ("tools/dalej.py", ["verify-c"]),
        ("tools/z_importu.py", ["verify-c"]),
        ("tools/z_produktu.py", []),
        ("tools/tylko_mutacje.py", []),
        ("src/produkt.py", []),
    ],
)
def test_plik_spoza_src_ktory_wykonuja_skrypty_skilla_wskazuje_skill(tmp_path: Path, changed: str, skills: list[str]) -> None:
    base = _repo(tmp_path, EXECUTED)
    _append(tmp_path, changed)
    commit(tmp_path, "zmiana")

    result = _run(tmp_path, base)

    assert _skills(result) == skills
    assert result.stdout.splitlines()[:-1] == [f"verify-c: {changed} (wykonują go skrypty skilla)" for _ in skills] + [
        "LICZY CI: verify-c (check_c_mutations.py)" for _ in skills
    ]


def test_skill_ktorego_skryptu_nie_da_sie_sparsowac_obowiazuje_zawsze(tmp_path: Path) -> None:
    base = _repo(tmp_path, {**EXECUTED, ".agents/skills/verify-c/scripts/run_c.py": "def zepsuty(:\n"})

    result = _run(tmp_path, base)

    assert _skills(result) == ["verify-c"]
    assert result.stdout.splitlines()[0].startswith("verify-c: .agents/skills/verify-c/scripts/run_c.py się nie parsuje, więc skill obowiązuje zawsze")


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
            ".agents/skills/verify-a/scripts/check_a_mutations.py": "print('MUTACJE OK')\n",
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
    assert result.stdout.splitlines()[-2] == "LICZY CI: verify-a (narzedzie.py --wszystko, check_a_mutations.py); verify-e2e (run_e2e.py --variant all)"


def test_baza_ktorej_nie_ma_daje_nieznane_skille_i_kod_bledu(tmp_path: Path) -> None:
    _repo(tmp_path)

    result = _run(tmp_path, "nie-ma-takiej-bazy")

    assert result.returncode == 1
    assert result.stdout.splitlines()[-1].startswith(f"{VERDICT}nieznane (git diff: ")
    assert "nie-ma-takiej-bazy" in result.stdout


def _load_tool(monkeypatch: pytest.MonkeyPatch) -> ModuleType:
    monkeypatch.syspath_prepend(str(TOOLS))
    spec = importlib.util.spec_from_file_location("skille_dla_zmiany", TOOLS / "skille_dla_zmiany.py")
    assert spec is not None and spec.loader is not None
    tool = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(tool)
    return tool


def test_kazdy_skill_verify_deklaruje_pilnuje(monkeypatch: pytest.MonkeyPatch) -> None:
    tool = _load_tool(monkeypatch)
    skills = sorted(SKILLS.glob("verify-*/SKILL.md"))

    without = [md.parent.name for md in skills if tool.guarded(md) is None]

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


def _spelled(names: set[str]) -> set[str]:
    """Nazwy plików tak, jak je rozróżnia system: ścieżka Windows nie rozróżnia wielkości liter, więc zbiór kandydatów
    importu (``openpyxl/Workbook.py`` i ``openpyxl/workbook.py``) zostawia po jednej z pisowni, różnej w każdym zbiorze."""

    return {name.casefold() for name in names} if sys.platform == "win32" else names


def test_wybor_w_ci_liczy_dla_polecenia_ci_kazdego_skilla_te_same_pliki_co_skille_dla_zmiany(monkeypatch: pytest.MonkeyPatch) -> None:
    tool = _load_tool(monkeypatch)
    ci = importlib.import_module("mutacje_skilli")
    # Folder bez SKILL.md nie ma polecenia ci, więc czyta tylko runner mutacji i INFRASTRUCTURE, wspólne dla wszystkich skilli.
    runner = ci.read_in_ci(SKILLS / "nie-ma-takiego-skilla", [])
    differences = {}
    for md in sorted(SKILLS.glob("verify-*/SKILL.md")):
        if ci.ci_command(md) is None:
            continue
        in_ci = {name for name in ci.read_in_ci(md.parent, []) if not name.startswith("src/")}
        for_change = {path.relative_to(ROOT).as_posix() for path in tool._executed(md.parent) if path.is_relative_to(ROOT)}
        differences[md.parent.name] = sorted(_spelled(in_ci - runner) ^ _spelled(for_change - runner))

    assert len(differences) >= 2
    assert differences == dict.fromkeys(differences, [])


# Skrypt dla maszyn uruchamia ścieżką polecenie ci Centrum (``drive/metryki.py``) i sprawdzenie mutacji Excela
# (``run_excel_verification.py``), a żaden z nich go nie importuje.
@pytest.mark.parametrize("skill", ["verify-centrum-rozliczen", "verify-skoroszyty-w-excelu"])
def test_zmiana_samego_skryptu_dla_maszyn_uruchamia_w_ci_polecenia_skilla_ktory_go_uruchamia(monkeypatch: pytest.MonkeyPatch, skill: str) -> None:
    _load_tool(monkeypatch)
    ci = importlib.import_module("mutacje_skilli")
    folder = SKILLS / skill

    runs, why = ci._why_run(folder, sorted(folder.glob(f"scripts/{ci.PATTERN}")), {"tools/uruchom_proces.py"})

    assert runs, why


def test_workflow_skilla_windows_biegnie_dla_tych_samych_sciezek_co_jego_pilnuje(monkeypatch: pytest.MonkeyPatch) -> None:
    tool = _load_tool(monkeypatch)
    skill = SKILLS / "verify-centrum-na-windowsie"
    workflow = yaml.safe_load((ROOT / ".github" / "workflows" / f"{skill.name}.yml").read_text(encoding="utf-8"))
    triggers = workflow[True]  # YAML 1.1 czyta klucz „on” jako True

    expected = sorted([*tool.guarded(skill / "SKILL.md"), f"{skill.relative_to(ROOT).as_posix()}/**"])

    assert {event: sorted(triggers[event]["paths"]) for event in ("pull_request", "push")} == {
        "pull_request": expected,
        "push": expected,
    }, "paths workflow skilla Windows to jego pilnuje: i folder skilla: dopisz ścieżkę w obu miejscach"

# Zdanie, które każe uruchomić coś przed oddaniem pracy albo pushem.
BEFORE_PUSH = re.compile(r"before (handing|you hand|pushing|you push|opening|you open)|przed (pushem|oddaniem)", re.IGNORECASE)
# Argumenty kontraktu skryptu skilla (``tools/skrypt_skilla.py``), które mówią, gdzie biec, a nie co sprawdzić.
PLACE = ("--run-dir", "--root")
CI_AND_LOCAL = "## What CI runs and what stays local"


def _ci_commands(tool: ModuleType) -> set[tuple[str, ...]]:
    """Polecenia skilli, które liczy CI (``ci_runs`` narzędzia); skrypt mutacji bez argumentów obejmuje każde swoje wywołanie."""

    return {run for md in SKILLS.glob("*/SKILL.md") for run in tool.ci_runs(md.parent)}


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
    skills = [md for md in sorted(SKILLS.glob("verify-*/SKILL.md")) if tool.ci_runs(md.parent)]

    without = [md.parent.name for md in skills if CI_AND_LOCAL not in md.read_text(encoding="utf-8").splitlines()]

    assert {"verify-centrum-rozliczen", "verify-aktualizacja-narzedzia"} <= {md.parent.name for md in skills}
    assert without == [], f"dopisz sekcję {CI_AND_LOCAL!r}: które polecenia liczy CI, a co z workflow zostaje lokalnie (osąd, Mac)"


def test_agents_md_nie_wymienia_skilli_verify() -> None:
    """``AGENTS.md`` i pliki ``docs/agents/``, do których odsyła przed pushem, nie wymieniają skilli ``verify-*``."""

    documents = (ROOT / "AGENTS.md", ROOT / "docs" / "agents" / "pr-i-ci.md", ROOT / "docs" / "agents" / "skille.md")
    agents = "\n".join(path.read_text(encoding="utf-8") for path in documents)

    named = [md.parent.name for md in sorted(SKILLS.glob("verify-*/SKILL.md")) if md.parent.name in agents]

    assert named == [], "routing skilli verify-* żyje w ich pilnuje:, a AGENTS.md odsyła do tools/skille_dla_zmiany.py"

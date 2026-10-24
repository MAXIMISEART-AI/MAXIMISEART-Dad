"""Skrypty narzędzi i skilli startują osobnym procesem bez zainstalowanego pakietu ``rozliczenia``.

CI na Windows instaluje tylko ``requirements.txt``, więc skrypt widzi ``src`` tylko wtedy, gdy sam dopisze go do
``sys.path`` (jak ``tools/uruchom_proces.py``). Na Macu ``.venv`` ma instalację edytowalną, która to chowa, więc
test usuwa z ``sys.path`` każdy katalog z pakietem ``rozliczenia`` i uruchamia ``--help`` każdego skryptu z parserem
argumentów, tak jak ``python skrypt.py``. Skrypty bez parsera pomija, bo ``--help`` nie zatrzymałoby ich pracy.

Skrypt dopisuje katalogi jedną linią w jednej postaci (``BOOTSTRAP``), więc ruff nie potrzebuje tłumienia E402 przy
importach pod nią (``per-file-ignores`` w ``pyproject.toml``), a kopia w innej postaci albo z liczbą ``parents``,
która nie trafia w korzeń repozytorium, czerwieni ``test_skrypt_dopisuje_katalogi_do_sys_path_jedna_linia``.
"""

from __future__ import annotations

import ast
from collections.abc import Iterator
from pathlib import Path
import re
import subprocess
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = sorted([*(ROOT / "tools").glob("**/*.py"), *(ROOT / ".agents" / "skills").glob("*/scripts/**/*.py")])
WITHOUT_INSTALL = (
    "import runpy, sys\n"
    "from pathlib import Path\n"
    "script = sys.argv[1]\n"
    "sys.path[:] = [entry for entry in sys.path if not (Path(entry or '.') / 'rozliczenia').is_dir()]\n"
    "sys.path.insert(0, str(Path(script).parent))\n"
    "sys.argv = [script, '--help']\n"
    "runpy.run_path(script, run_name='__main__')\n"
)
BOOTSTRAP = 'sys.path[:0] = [str(Path(__file__).resolve().parents[{parents}] / folder) for folder in ("src", "tools")]'
BOOTSTRAP_SHAPE = re.compile(
    r"sys\.path\[:0\] = \[str\(Path\(__file__\)\.resolve\(\)\.parents\[(\d+)\] / folder\) for folder in (\(.*\))\]"
)
READING = frozenset({"copy", "count", "index"})


def _runs_with_parser(path: Path) -> bool:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    entry = any(isinstance(node, ast.If) and "__main__" in ast.unparse(node.test) for node in tree.body)
    parser = any(
        isinstance(node, ast.Call) and ast.unparse(node.func).rsplit(".", 1)[-1] in ("ArgumentParser", "Parser")
        for node in ast.walk(tree)
    )
    return entry and parser


def _path_changes(tree: ast.Module) -> Iterator[ast.Call | ast.Assign | ast.AugAssign | ast.AnnAssign]:
    """Każde wyrażenie, które zmienia ``sys.path``: wywołanie jego metody albo przypisanie do niego lub jego wycinka."""

    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            if ast.unparse(node.func.value) == "sys.path" and node.func.attr not in READING:
                yield node
        elif isinstance(node, (ast.Assign, ast.AugAssign, ast.AnnAssign)):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            if any(ast.unparse(target).startswith("sys.path") for target in targets):
                yield node


def _bootstrap_problem(path: Path, tree: ast.Module, change: ast.expr | ast.stmt) -> str | None:
    """Co nie zgadza się z ``BOOTSTRAP`` w zmianie ``sys.path``; ``None``, gdy to jedna linia w tej postaci."""

    shape = BOOTSTRAP_SHAPE.fullmatch(ast.unparse(change))
    if change not in tree.body or shape is None:
        return "dopisz katalogi jedną linią na poziomie modułu"
    parents = len(path.relative_to(ROOT).parts) - 1
    if int(shape.group(1)) != parents:
        return f"parents[{shape.group(1)}] nie trafia w korzeń repozytorium, z tego pliku to parents[{parents}]"
    folders = ast.literal_eval(shape.group(2))
    missing = [folder for folder in folders if not (ROOT / folder).is_dir()]
    return f"brak katalogu {', '.join(missing)} w repozytorium" if missing else None


def test_skrypt_dopisuje_katalogi_do_sys_path_jedna_linia() -> None:
    problems = []
    for path in SCRIPTS:
        tree = ast.parse(path.read_text(encoding="utf-8"))
        changes = list(_path_changes(tree))
        if len(changes) > 1:
            problems.append(f"{path.relative_to(ROOT).as_posix()}: {len(changes)} zmiany sys.path, połącz je w jedną")
        for change in changes:
            problem = _bootstrap_problem(path, tree, change)
            if problem is not None:
                example = BOOTSTRAP.format(parents=len(path.relative_to(ROOT).parts) - 1)
                problems.append(f"{path.relative_to(ROOT).as_posix()}:{change.lineno}: {problem}: {example}")

    assert problems == [], "\n".join(problems)


@pytest.mark.skipif(sys.platform == "win32", reason="CI na Windows i tak uruchamia skrypty bez instalacji pakietu")
@pytest.mark.parametrize(
    "script", [path for path in SCRIPTS if _runs_with_parser(path)], ids=lambda path: path.relative_to(ROOT).as_posix()
)
def test_skrypt_odpowiada_na_help_bez_zainstalowanego_pakietu(tmp_path: Path, script: Path) -> None:
    answered = subprocess.run(
        [sys.executable, "-c", WITHOUT_INSTALL, str(script)],
        cwd=tmp_path,
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=60,
        check=False,
    )

    assert answered.returncode == 0, answered.stderr
